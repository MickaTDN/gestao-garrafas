import copy
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, close_old_connections, connection, transaction
from django.db.migrations.exceptions import IrreversibleError
from django.test import Client, TestCase, TransactionTestCase, skipUnlessDBFeature
from django.urls import reverse
from django.utils import timezone

from consultation.models import SheetAction
from consultation.review import confirm_sheet, correct_sheet, reject_sheet, review_sheet
from consultation.sheets import receive_sheet
from consultation.test_sheets import SheetFixtures
from inventory.documents import verified_bytes
from inventory.models import (
    AuditEvent,
    Document,
    Movement,
    Person,
    Reference,
    ReportNumber,
    ReportSequence,
)
from tests.document_fixtures import confirmed_operation, signature_png


class ReviewFixtures(SheetFixtures):
    def received(self, kind="entry", **changes):
        payload = {**self.payload, "sheet_id": str(uuid.uuid4()), "kind": kind, **changes}
        return receive_sheet(self.packet(payload), actor=self.admin).sheet

    def confer(self, sheet, sequence=0, **kwargs):
        return review_sheet(sheet.pk, actor=self.admin, sequence=sequence, **kwargs)[0]

    def confirm(self, sheet, review, **kwargs):
        return confirm_sheet(
            sheet.pk,
            actor=self.admin,
            sequence=review.sequence,
            token=review.data["token"],
            confirmed=True,
            report_requested=False,
            **kwargs,
        )

    def values(self, sheet, **changes):
        return {
            **{
                k: copy.deepcopy(sheet.payload[k])
                for k in ("person", "physical_date", "notes", "lines")
            },
            **changes,
        }


class PendingReviewTests(ReviewFixtures, TestCase):
    def setUp(self):
        self.prepare()

    def test_review_and_correction_never_create_official_records_or_rewrite_original(self):
        sheet = self.received()
        raw = bytes(sheet.receipts.get().original)
        with self.assertRaises(ValidationError):
            correct_sheet(
                sheet.pk, actor=self.admin, sequence=0, values=self.values(sheet), reason=""
            )
        correction = correct_sheet(
            sheet.pk,
            actor=self.admin,
            sequence=0,
            values=self.values(
                sheet, person="Pessoa corrigida sintética", notes="Observações conferidas"
            ),
            reason="Correção administrativa identificada",
        )
        review = self.confer(sheet, correction.sequence)
        self.assertEqual(review.kind, "reviewed")
        sheet.refresh_from_db()
        self.assertEqual(sheet.payload["person"], "Pessoa fictícia")
        self.assertEqual(bytes(sheet.receipts.get().original), raw)
        self.assertEqual(Movement.objects.count(), 0)
        self.assertEqual(Person.objects.count(), 0)
        self.assertEqual(Document.objects.count(), 0)
        self.ref.refresh_from_db()
        self.assertEqual(self.ref.current_stock, 12)

    def test_entry_optional_pdf_and_annual_number_even_without_pdf(self):
        first = self.received()
        movement = self.confirm(first, self.confer(first))
        self.assertEqual(movement.report_number.number, 1)
        self.assertIsNone(movement.report_number.document_id)
        second = self.received()
        review = self.confer(second)
        result = confirm_sheet(
            second.pk,
            actor=self.admin,
            sequence=review.sequence,
            token=review.data["token"],
            confirmed=True,
            report_requested=True,
        )
        self.assertEqual(result.report_number.number, 2)
        self.assertTrue(verified_bytes(result.report_number.document).startswith(b"%PDF"))
        self.ref.refresh_from_db()
        self.assertEqual(self.ref.current_stock, 28)

    def test_exit_requires_pdf_preserves_packaging_and_signature(self):
        sheet = self.received("exit")
        review = self.confer(sheet)
        with self.assertRaises(ValidationError):
            self.confirm(
                sheet, review, validation="signed", signature_data="data:image/png;base64,AAAA"
            )
        movement = self.confirm(sheet, review, validation="signed", signature_data=signature_png())
        self.assertTrue(movement.report_requested)
        self.assertEqual(movement.documents.filter(kind="signature").count(), 1)
        document = movement.report_number.document
        self.assertTrue(verified_bytes(document).startswith(b"%PDF"))
        self.assertEqual(document.metadata["validation"], "signed")
        self.assertEqual(
            (document.metadata["lines"][0]["boxes"], document.metadata["lines"][0]["units"]), (1, 2)
        )
        self.ref.refresh_from_db()
        self.assertEqual(self.ref.current_stock, 4)

    def test_rejection_requires_reason_is_terminal_and_preserves_history(self):
        sheet = self.received()
        with self.assertRaises(ValidationError):
            reject_sheet(sheet.pk, actor=self.admin, sequence=0, reason=" ")
        event = reject_sheet(
            sheet.pk, actor=self.admin, sequence=0, reason="Folha enviada por engano"
        )
        with self.assertRaises(ValidationError):
            self.confer(sheet, event.sequence)
        self.assertEqual(Movement.objects.count(), 0)
        self.assertEqual(sheet.receipts.count(), 1)
        self.assertEqual(sheet.actions.count(), 1)

    def test_permissions_are_enforced_by_all_services(self):
        sheet = self.received()
        for operation in [
            lambda: correct_sheet(
                sheet.pk, actor=self.viewer, sequence=0, values=self.values(sheet), reason="Motivo"
            ),
            lambda: reject_sheet(sheet.pk, actor=self.viewer, sequence=0, reason="Motivo"),
            lambda: review_sheet(sheet.pk, actor=self.viewer, sequence=0),
            lambda: confirm_sheet(
                sheet.pk, actor=self.viewer, sequence=0, token=uuid.uuid4(), confirmed=True
            ),
        ]:
            with self.assertRaises(PermissionDenied):
                operation()
        self.assertFalse(SheetAction.objects.exists())

    def test_unknown_inactive_capacity_and_location_require_explicit_resolution(self):
        for changes in [{"reference_id": "unknown-id"}, {"box_capacity": 12}]:
            line = {**self.payload["lines"][0], **changes}
            sheet = self.received(lines=[line])
            with self.assertRaises(ValidationError):
                self.confer(sheet)
        self.assertEqual(Reference.objects.count(), 1)
        sheet = self.received()
        self.ref.active = False
        self.ref.save(update_fields=["active"])
        with self.assertRaises(ValidationError):
            self.confer(sheet)
        self.ref.active = True
        self.ref.save(update_fields=["active"])
        location = self.ref.location
        location.active = False
        location.save(update_fields=["active"])
        with self.assertRaises(ValidationError):
            self.confer(sheet)
        self.assertEqual(Movement.objects.count(), 0)

    def test_unknown_reference_can_be_corrected_to_existing_with_reason(self):
        sheet = self.received(lines=[{**self.payload["lines"][0], "reference_id": "unknown-id"}])
        correction = correct_sheet(
            sheet.pk,
            actor=self.admin,
            sequence=0,
            values=self.values(sheet, lines=self.payload["lines"]),
            reason="Associação explicitamente conferida à referência existente",
        )
        self.confirm(sheet, self.confer(sheet, correction.sequence))
        sheet.refresh_from_db()
        self.assertEqual(sheet.payload["lines"][0]["reference_id"], "unknown-id")
        self.assertEqual(Reference.objects.count(), 1)

    def test_multiple_references_and_unknown_box_capacity_confirm_in_one_transaction(self):
        second = Reference.objects.create(
            code="SHEET-UNKNOWN-CAP",
            name="Capacidade desconhecida",
            location=self.ref.location,
            current_stock=0,
        )
        sheet = self.received(
            lines=self.payload["lines"]
            + [{"reference_id": str(second.pk), "boxes": None, "units": 4, "box_capacity": None}]
        )
        movement = self.confirm(sheet, self.confer(sheet))
        self.assertEqual(movement.lines.count(), 2)
        self.assertIsNone(movement.lines.get(reference=second).box_capacity)
        self.ref.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual((self.ref.current_stock, second.current_stock), (20, 4))

    def test_conflict_receipts_require_explicit_acknowledgement_and_new_conflict_invalidates_review(
        self,
    ):
        sheet = self.received()
        receive_sheet(
            self.packet({**sheet.payload, "notes": "Primeiro ficheiro divergente"}),
            actor=self.admin,
        )
        with self.assertRaises(ValidationError):
            self.confer(sheet)
        with self.assertRaises(ValidationError):
            self.confer(sheet, acknowledge_conflicts=True)
        review = self.confer(
            sheet,
            acknowledge_conflicts=True,
            reason="Originais comparados; versão de trabalho conferida",
        )
        receive_sheet(
            self.packet({**sheet.payload, "notes": "Segundo ficheiro divergente"}), actor=self.admin
        )
        with self.assertRaises(ValidationError):
            self.confirm(sheet, review)
        self.assertFalse(Movement.objects.exists())

    def test_duplicate_delivery_after_review_or_confirmation_does_not_duplicate_movement(self):
        sheet = self.received()
        review = self.confer(sheet)
        self.assertEqual(
            receive_sheet(self.packet(sheet.payload), actor=self.admin).outcome, "duplicate"
        )
        movement = self.confirm(sheet, review)
        self.assertEqual(self.confirm(sheet, review).pk, movement.pk)
        receive_sheet(self.packet(sheet.payload), actor=self.admin)
        self.assertEqual(self.confirm(sheet, review).pk, movement.pk)
        self.assertEqual(Movement.objects.count(), 1)
        self.assertEqual(ReportNumber.objects.count(), 1)
        self.assertEqual(sheet.actions.filter(kind="confirmed").count(), 1)

    def test_pdf_failure_rolls_back_stock_people_number_documents_and_link_then_retry_succeeds(
        self,
    ):
        sheet = self.received("exit")
        review = self.confer(sheet)
        with patch(
            "inventory.documents.render_pdf", side_effect=RuntimeError("synthetic PDF error")
        ):
            with self.assertRaises(RuntimeError):
                self.confirm(sheet, review)
        self.ref.refresh_from_db()
        self.assertEqual(self.ref.current_stock, 12)
        for model in (Movement, Person, Document, ReportNumber, ReportSequence):
            self.assertEqual(model.objects.count(), 0)
        self.assertEqual(sheet.actions.count(), 1)
        self.assertTrue(AuditEvent.objects.filter(action="sheets.confirmation_failed").exists())
        result = self.confirm(sheet, review)
        self.assertEqual(result.report_number.number, 1)

    def test_failure_recording_final_decision_rolls_back_already_rendered_pdf_and_stock(self):
        sheet = self.received("exit")
        review = self.confer(sheet)
        with patch(
            "consultation.review._record", side_effect=RuntimeError("synthetic decision failure")
        ):
            with self.assertRaises(RuntimeError):
                self.confirm(sheet, review)
        self.assertFalse(Movement.objects.exists())
        self.assertFalse(Document.objects.exists())
        self.ref.refresh_from_db()
        self.assertEqual(self.ref.current_stock, 12)

    def test_stock_change_and_aba_require_fresh_review(self):
        sheet = self.received()
        review = self.confer(sheet)
        confirmed_operation(self.admin, self.ref, kind="entry", report=False)
        confirmed_operation(self.admin, self.ref, kind="exit", report=True)
        self.ref.refresh_from_db()
        self.assertEqual(self.ref.current_stock, 12)
        with self.assertRaises(ValidationError):
            self.confirm(sheet, review)
        new_review = self.confer(sheet, review.sequence)
        self.confirm(sheet, new_review)
        self.ref.refresh_from_db()
        self.assertEqual(self.ref.current_stock, 20)

    def test_all_lines_are_atomic_when_an_exit_loses_available_stock(self):
        second = Reference.objects.create(
            code="SHEET-2",
            name="Segunda sintética",
            location=self.ref.location,
            current_stock=12,
            box_capacity=6,
        )
        sheet = self.received(
            "exit",
            lines=self.payload["lines"]
            + [{"reference_id": str(second.pk), "boxes": 1, "units": 2, "box_capacity": 6}],
        )
        review = self.confer(sheet)
        confirmed_operation(self.admin, second, kind="exit", report=True)  # 12 -> 10 still enough
        confirmed_operation(self.admin, second, kind="exit", report=True)
        confirmed_operation(self.admin, second, kind="exit", report=True)  # 6 < 8
        with self.assertRaises(ValidationError):
            self.confirm(sheet, review)
        self.ref.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual((self.ref.current_stock, second.current_stock), (12, 6))
        self.assertFalse(sheet.actions.filter(kind="confirmed").exists())

    def test_official_date_is_today_and_yesterdays_review_cannot_bypass_it(self):
        sheet = self.received()
        yesterday = timezone.localdate() - timedelta(days=1)
        with patch("consultation.review.timezone.localdate", return_value=yesterday):
            review = self.confer(sheet)
        with self.assertRaises(ValidationError):
            self.confirm(sheet, review)
        result = self.confirm(sheet, self.confer(sheet, review.sequence))
        self.assertEqual(result.date, timezone.localdate())
        self.assertEqual(result.source_metadata["physical_date"], "2026-01-02")

    def test_explicit_confirmation_token_revision_and_positive_quantities_are_required(self):
        sheet = self.received()
        with self.assertRaises(ValidationError):
            confirm_sheet(
                sheet.pk, actor=self.admin, sequence=0, token=uuid.uuid4(), confirmed=True
            )
        review = self.confer(sheet)
        for changes in [{"confirmed": False}, {"token": str(uuid.uuid4())}, {"sequence": 0}]:
            values = dict(
                actor=self.admin,
                sequence=review.sequence,
                token=review.data["token"],
                confirmed=True,
                report_requested=False,
            )
            with self.assertRaises(ValidationError):
                confirm_sheet(sheet.pk, **{**values, **changes})
        corrected = correct_sheet(
            sheet.pk,
            actor=self.admin,
            sequence=review.sequence,
            values=self.values(
                sheet, lines=[{**sheet.payload["lines"][0], "boxes": 0, "units": 0}]
            ),
            reason="Contagem comunicada a esclarecer",
        )
        with self.assertRaises(ValidationError):
            self.confer(sheet, corrected.sequence)
        self.assertFalse(Movement.objects.exists())

    def test_immutable_decisions_and_postgresql_terminal_guard(self):
        sheet = self.received()
        rejected = reject_sheet(sheet.pk, actor=self.admin, sequence=0, reason="Ensaio rejeitado")
        with self.assertRaises(ValidationError):
            rejected.save()
        if connection.vendor == "postgresql":
            for query in [
                "DELETE FROM consultation_sheetaction",
                "UPDATE consultation_sheetaction SET reason='changed'",
            ]:
                with self.assertRaises(DatabaseError), transaction.atomic():
                    connection.cursor().execute(query)
            with self.assertRaises(DatabaseError), transaction.atomic():
                SheetAction.objects.create(
                    sheet=sheet,
                    sequence=2,
                    kind="reviewed",
                    actor=self.admin,
                    data={"payload": sheet.payload},
                )

    def test_schema_reverse_refuses_erasing_decisions(self):
        import importlib

        from django.apps import apps

        sheet = self.received()
        self.confer(sheet)
        reverse_guard = importlib.import_module(
            "consultation.migrations.0006_sheet_action_guards"
        ).reverse
        with self.assertRaises(IrreversibleError):
            reverse_guard(apps, None)

    def test_administrative_pages_csrf_forged_dates_and_closed_post_are_safe(self):
        sheet = self.received()
        url = reverse("web:sheet-process", args=[sheet.pk])
        self.client.force_login(self.admin)
        self.assertEqual(
            self.client.post(url, {"action": "forged-action", "sequence": 0}).status_code, 400
        )
        self.assertContains(self.client.get(reverse("web:pending-entries")), "Daniel")
        self.assertContains(self.client.get(url), "Caixas: 1")
        secure = Client(enforce_csrf_checks=True)
        secure.force_login(self.admin)
        self.assertEqual(secure.post(url, {"action": "review", "sequence": 0}).status_code, 403)
        response = self.client.post(url, {"action": "review", "sequence": 0})
        self.assertEqual(response.status_code, 302)
        event = sheet.actions.get()
        data = {
            "action": "confirm",
            "sequence": event.sequence,
            "token": event.data["token"],
            "confirm": "on",
            "report_requested": "no",
            "date": "2020-01-01",
            "workflow_version": "0",
        }
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(self.client.post(url, data).status_code, 302)
        movement = sheet.actions.get(kind="confirmed").movement
        self.assertEqual(movement.date, timezone.localdate())
        self.assertEqual(Movement.objects.count(), 1)
        self.assertContains(self.client.get(url), movement.display_number)
        self.assertNotContains(self.client.get(reverse("web:pending-entries")), str(sheet.sheet_id))
        self.client.force_login(self.viewer)
        for page in [url, reverse("web:pending-entries"), reverse("web:pending-exits")]:
            self.assertEqual(self.client.get(page).status_code, 403)
        self.assertEqual(self.client.post(url, data).status_code, 403)

    def test_structured_correction_can_add_and_remove_lines_without_rewriting_original(self):
        sheet = self.received()
        second = Reference.objects.create(
            code="SHEET-NEW-LINE",
            name="Linha acrescentada sintética",
            location=self.ref.location,
            current_stock=0,
        )
        self.client.force_login(self.admin)
        data = {
            "action": "correct",
            "correction-sequence": 0,
            "correction-person": sheet.payload["person"],
            "correction-physical_date": sheet.payload["physical_date"],
            "correction-notes": "Conferência sintética",
            "correction-reason": "Retirada e associação de linha explicitamente conferidas",
            "lines-TOTAL_FORMS": 2,
            "lines-INITIAL_FORMS": 1,
            "lines-0-reference_id": str(self.ref.pk),
            "lines-0-boxes": 1,
            "lines-0-units": 2,
            "lines-0-box_capacity": 6,
            "lines-0-DELETE": "on",
            "lines-1-reference_id": str(second.pk),
            "lines-1-units": 3,
            "lines-1-boxes": "",
            "lines-1-box_capacity": "",
        }
        response = self.client.post(reverse("web:sheet-process", args=[sheet.pk]), data)
        self.assertEqual(response.status_code, 302)
        correction = sheet.actions.get()
        self.assertEqual(correction.data["payload"]["lines"][0]["reference_id"], str(second.pk))
        self.confirm(sheet, self.confer(sheet, correction.sequence))
        self.ref.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual((self.ref.current_stock, second.current_stock), (12, 3))
        sheet.refresh_from_db()
        self.assertEqual(sheet.payload["lines"][0]["reference_id"], str(self.ref.pk))

    def test_500_line_sheet_can_be_corrected_pagewise_without_field_limit_bypass(self):
        original = [
            {"reference_id": f"unknown-{i}", "boxes": None, "units": 1, "box_capacity": 6}
            for i in range(500)
        ]
        sheet = self.received(lines=original)
        self.client.force_login(self.admin)
        data = {
            "action": "correct",
            "correction-sequence": 0,
            "correction-person": sheet.payload["person"],
            "correction-physical_date": sheet.payload["physical_date"],
            "correction-notes": "",
            "correction-reason": "Associação explícita na segunda página",
            "lines-TOTAL_FORMS": 30,
            "lines-INITIAL_FORMS": 30,
        }
        for index, line in enumerate(original[30:60]):
            for key, value in line.items():
                data[f"lines-{index}-{key}"] = "" if value is None else value
        data["lines-0-reference_id"] = str(self.ref.pk)
        response = self.client.post(
            reverse("web:sheet-process", args=[sheet.pk]) + "?lines_page=2", data
        )
        self.assertEqual(response.status_code, 302)
        working = sheet.actions.get().data["payload"]["lines"]
        self.assertEqual(len(working), 500)
        self.assertEqual(working[:30], original[:30])
        self.assertEqual(working[30]["reference_id"], str(self.ref.pk))
        self.assertEqual(working[60:], original[60:])
        self.assertFalse(Movement.objects.exists())


@skipUnlessDBFeature("has_select_for_update")
class PendingReviewConcurrencyTests(ReviewFixtures, TransactionTestCase):
    def setUp(self):
        self.prepare()

    def parallel(self, jobs):
        barrier = Barrier(len(jobs))

        def run(job):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:
                    return job()
                except ValidationError:
                    return "rejected"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
            return list(pool.map(run, jobs))

    def test_same_sheet_two_connections_confirm_one_movement(self):
        sheet = self.received("exit")
        review = self.confer(sheet)
        ids = self.parallel(
            [lambda: self.confirm(sheet, review).pk, lambda: self.confirm(sheet, review).pk]
        )
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(Movement.objects.count(), 1)
        self.assertEqual(ReportNumber.objects.count(), 1)
        self.ref.refresh_from_db()
        self.assertEqual(self.ref.current_stock, 4)

    def test_two_sheets_compete_for_same_stock_without_negative_balance(self):
        first, second = self.received("exit"), self.received("exit")
        a, b = self.confer(first), self.confer(second)
        results = self.parallel(
            [lambda: self.confirm(first, a).pk, lambda: self.confirm(second, b).pk]
        )
        self.assertEqual(results.count("rejected"), 1)
        self.assertEqual(Movement.objects.count(), 1)
        self.ref.refresh_from_db()
        self.assertEqual(self.ref.current_stock, 4)

    def test_confirmation_and_rejection_are_mutually_exclusive(self):
        sheet = self.received()
        review = self.confer(sheet)
        self.parallel(
            [
                lambda: self.confirm(sheet, review).pk,
                lambda: (
                    reject_sheet(
                        sheet.pk,
                        actor=self.admin,
                        sequence=review.sequence,
                        reason="Concorrência sintética",
                    ).pk
                ),
            ]
        )
        self.assertEqual(sheet.actions.filter(kind__in=["confirmed", "rejected"]).count(), 1)
        self.ref.refresh_from_db()
        self.assertEqual(self.ref.current_stock, 20 if Movement.objects.exists() else 12)
