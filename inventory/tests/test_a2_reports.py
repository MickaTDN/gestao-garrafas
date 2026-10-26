import hashlib
import io
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time, timedelta
from datetime import timezone as dt_timezone
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection, connections, transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from pypdf import PdfReader

from inventory import operations
from inventory.documents import store_document, verified_bytes
from inventory.models import (
    AuditEvent,
    Document,
    Location,
    Movement,
    Reference,
    ReportFile,
    ReportNumber,
    ReportSequence,
    ReportTemplate,
)
from inventory.reporting import delete_pdf, regenerate_pdf, reproduce
from inventory.services import confirm_movement
from tests.document_fixtures import confirmed_operation


class ReportLifecycleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_user(username="a2-doc-admin", role="admin")
        cls.viewer = get_user_model().objects.create_user(username="a2-doc-viewer")
        cls.location = Location.objects.create(name="Local A2 fictício")
        cls.reference = Reference.objects.create(
            code="A2-SYN",
            name="Garrafa A2 fictícia",
            location=cls.location,
            current_stock=50,
            box_capacity=6,
        )

    def confirmed(self, kind="exit", **kwargs):
        return confirmed_operation(self.admin, self.reference, kind=kind, **kwargs)

    def test_number_allocated_on_confirmation_independently_of_pdf(self):
        draft = operations.create_draft(actor=self.admin, kind="entry", references=[self.reference])
        self.assertFalse(ReportNumber.objects.exists())
        self.assertFalse(ReportSequence.objects.exists())
        without = self.confirmed(kind="entry", report=False)
        self.assertIsNone(without.report_number.document_id)
        first = self.confirmed(kind="entry", report=True)
        self.reference.refresh_from_db()
        second = self.confirmed()
        self.assertEqual(
            (str(first.report_number), str(second.report_number)),
            (f"Mov-2/{first.date.year % 100:02}", f"Mov-3/{second.date.year % 100:02}"),
        )
        self.assertEqual(first.report_number.year, first.date.year)
        self.assertEqual(ReportSequence.objects.get(year=first.date.year).last_number, 3)
        self.assertEqual(draft.lines.get().quantity, None)

    def test_year_reset_uses_official_movement_date_and_four_digit_year(self):
        result = []
        for year in (2026, 2026, 2027, 2027):
            now = datetime(year, 6, 15, 12, tzinfo=dt_timezone.utc)
            with patch("django.utils.timezone.now", return_value=now):
                movement = self.confirmed(kind="entry", report=True)
                result.append((movement.report_number.year, str(movement.report_number)))
        self.assertEqual(
            result, [(2026, "Mov-1/26"), (2026, "Mov-2/26"), (2027, "Mov-1/27"), (2027, "Mov-2/27")]
        )

    def test_previous_day_draft_cannot_be_confirmed_even_after_forging_today_date(self):
        yesterday = timezone.make_aware(
            datetime.combine(timezone.localdate() - timedelta(days=1), time(12))
        )
        with patch("django.utils.timezone.now", return_value=yesterday):
            draft = operations.create_draft(
                actor=self.admin, kind="entry", references=[self.reference]
            )
        draft = operations.save_draft(
            draft.pk,
            actor=self.admin,
            revision=0,
            header={"person_name": "Cliente fictício", "date": timezone.localdate()},
            rows=[{"id": draft.lines.get().pk, "units": 2}],
        )
        reviewed, _ = operations.review_draft(draft.pk, actor=self.admin, revision=draft.revision)
        with self.assertRaisesMessage(ValidationError, "outro dia"):
            confirm_movement(
                draft.pk,
                actor=self.admin,
                review_token=reviewed.review_token,
                report_requested=True,
            )
        self.reference.refresh_from_db()
        self.assertEqual(self.reference.current_stock, 50)
        self.assertFalse(ReportNumber.objects.exists())
        operations.cancel_draft(draft.pk, actor=self.admin, revision=reviewed.revision)
        self.assertEqual(Movement.objects.get(pk=draft.pk).status, "cancelled")

    def test_future_or_backdated_official_date_rejected(self):
        for difference in (-1, 1):
            draft = operations.create_draft(
                actor=self.admin, kind="entry", references=[self.reference]
            )
            draft = operations.save_draft(
                draft.pk,
                actor=self.admin,
                revision=0,
                header={
                    "person_name": "Cliente fictício",
                    "date": timezone.localdate() + timedelta(days=difference),
                },
                rows=[{"id": draft.lines.get().pk, "units": 1}],
            )
            reviewed, _ = operations.review_draft(
                draft.pk, actor=self.admin, revision=draft.revision
            )
            with self.assertRaises(ValidationError):
                confirm_movement(
                    draft.pk,
                    actor=self.admin,
                    review_token=reviewed.review_token,
                    report_requested=True,
                )
        self.assertFalse(ReportNumber.objects.exists())

    def test_pdf_header_client_table_and_signature_presentation(self):
        movement = self.confirmed(signed=True)
        document = movement.documents.get(kind="pdf")
        text = "\n".join(
            page.extract_text() for page in PdfReader(io.BytesIO(verified_bytes(document))).pages
        )
        for label in (
            "Vertente Aveludada",
            "Cliente: Pessoa documental sintética",
            "Quantidade movimentada",
            "Stock final",
            "Validação com assinatura.",
            str(movement.report_number),
        ):
            self.assertIn(label, text)
        for label in (
            "Confirmado:",
            "Confirmado em",
            "Pessoa:",
            "Stock antes",
            "Variação",
            "Capacidade",
            "Total de garrafas:",
            "— identifica informação",
            "não constitui assinatura digital qualificada",
            "A2-SYN",
        ):
            self.assertNotIn(label, text)
        self.assertEqual(movement.validation, "signed")
        self.assertEqual(document.metadata["validation"], "signed")

    def test_delete_and_regenerate_preserve_every_original_byte_and_number(self):
        movement = self.confirmed(signed=True)
        document = movement.documents.get(kind="pdf")
        original = verified_bytes(document)
        self.assertEqual(reproduce(document), original)
        original_number = str(movement.report_number)
        snapshot = document.metadata
        delete_pdf(actor=self.admin, document_id=document.pk)
        self.assertIsNone(ReportFile.objects.get(document=document).payload)
        self.assertTrue(Document.objects.filter(pk=document.pk).exists())
        self.assertTrue(movement.documents.filter(kind="signature", payload__isnull=False).exists())
        # Live catalogue, stock and people change; reproduction uses only frozen evidence.
        Reference.objects.filter(pk=self.reference.pk).update(
            name="Nome fictício posterior", box_capacity=12, current_stock=500
        )
        movement.person.name = "Cliente fictício posterior"
        movement.person.save()
        document = regenerate_pdf(actor=self.admin, document_id=document.pk)
        self.assertEqual(verified_bytes(document), original)
        self.assertEqual(document.metadata, snapshot)
        self.assertEqual(str(ReportNumber.objects.get(movement=movement)), original_number)
        self.assertEqual(ReportSequence.objects.get(year=movement.date.year).last_number, 1)
        self.assertEqual(Reference.objects.get(pk=self.reference.pk).current_stock, 500)
        self.assertEqual(
            AuditEvent.objects.filter(action="document.file_deleted", movement=movement).count(), 1
        )
        self.assertEqual(
            AuditEvent.objects.filter(
                action="document.file_regenerated", movement=movement
            ).count(),
            1,
        )

    def test_repeated_regeneration_is_idempotent_and_never_allocates_another_number(self):
        movement = self.confirmed()
        document = movement.documents.get(kind="pdf")
        delete_pdf(actor=self.admin, document_id=document.pk)
        delete_pdf(actor=self.admin, document_id=document.pk)
        regenerate_pdf(actor=self.admin, document_id=document.pk)
        regenerate_pdf(actor=self.admin, document_id=document.pk)
        self.assertEqual(ReportFile.objects.get(document=document).reproductions, 1)
        self.assertEqual(ReportNumber.objects.count(), 1)
        self.assertEqual(AuditEvent.objects.filter(action="document.file_regenerated").count(), 1)

    def test_legacy_only_copy_cannot_be_deleted_or_renumbered(self):
        movement = Movement.objects.create(kind="entry", created_by=self.admin)
        document = store_document(
            movement,
            kind="pdf",
            payload=b"%PDF-synthetic-legacy-unique",
            metadata={"presentation": 2},
        )
        movement.status = "confirmed"
        movement.save()
        with self.assertRaises(ValidationError):
            delete_pdf(actor=self.admin, document_id=document.pk)
        self.assertEqual(verified_bytes(document), b"%PDF-synthetic-legacy-unique")
        self.assertEqual(document.number, f"MOV-{movement.pk}")
        self.assertFalse(ReportNumber.objects.exists())

    def test_unreproducible_pdf_keeps_the_only_file(self):
        movement = self.confirmed()
        document = movement.documents.get(kind="pdf")
        original = verified_bytes(document)
        with (
            patch("inventory.documents.render_pdf", return_value=b"altered"),
            self.assertRaises(ValidationError),
        ):
            delete_pdf(actor=self.admin, document_id=document.pk)
        self.assertEqual(verified_bytes(document), original)
        self.assertFalse(AuditEvent.objects.filter(action="document.file_deleted").exists())

    def test_pdf_failure_rolls_back_stock_and_number_allocation(self):
        with (
            patch("inventory.documents.render_pdf", side_effect=RuntimeError("fictitious failure")),
            self.assertRaises(RuntimeError),
        ):
            self.confirmed()
        self.reference.refresh_from_db()
        self.assertEqual(self.reference.current_stock, 50)
        self.assertFalse(ReportNumber.objects.exists())
        self.assertFalse(ReportSequence.objects.exists())
        self.assertFalse(Document.objects.exists())

    def test_file_and_number_sql_guards_and_immutable_recipe(self):
        movement = self.confirmed()
        document = movement.documents.get(kind="pdf")
        file = ReportFile.objects.get(document=document)
        for operation in (
            lambda: ReportNumber.objects.filter(movement=movement).update(number=999),
            lambda: ReportTemplate.objects.all().delete(),
            lambda: ReportFile.objects.filter(pk=file.pk).update(payload=b"fake"),
        ):
            with self.assertRaises(ValidationError):
                operation()
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL required")
        for sql, params in (
            ("UPDATE inventory_reportfile SET payload=%s WHERE id=%s", [b"fake", file.pk]),
            ("DELETE FROM inventory_reportnumber WHERE document_id=%s", [document.pk]),
            (
                "UPDATE inventory_reportsequence SET last_number=0 WHERE year=%s",
                [movement.date.year],
            ),
            ("DELETE FROM inventory_reportfile WHERE id=%s", [file.pk]),
        ):
            with (
                self.assertRaises(IntegrityError),
                transaction.atomic(),
                connection.cursor() as cursor,
            ):
                cursor.execute(sql, params)
        self.assertEqual(hashlib.sha256(verified_bytes(document)).hexdigest(), document.sha256)

    def test_reverse_migration_refuses_discarding_issued_report_evidence(self):
        from importlib import import_module

        from django.apps import apps
        from django.db.migrations.exceptions import IrreversibleError

        self.confirmed()
        guard = import_module("inventory.migrations.0013_protect_a2_evidence_on_reverse")
        with self.assertRaises(IrreversibleError):
            guard.protect(apps, None)
        self.assertEqual(ReportNumber.objects.count(), 1)

    def test_viewer_cannot_delete_or_regenerate(self):
        document = self.confirmed().documents.get(kind="pdf")
        for operation in (delete_pdf, regenerate_pdf):
            with self.assertRaises(PermissionDenied):
                operation(actor=self.viewer, document_id=document.pk)


class ReportNumberConcurrencyTests(TransactionTestCase):
    def test_simultaneous_confirmations_get_distinct_annual_numbers(self):
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL required")
        actors = [
            get_user_model().objects.create_user(username=f"a2-concurrent-{i}", role="admin")
            for i in range(2)
        ]
        location = Location.objects.create(name="Local concorrente fictício")
        reference = Reference.objects.create(
            code="A2-CONC", name="Garrafa concorrente fictícia", location=location
        )
        drafts = []
        for actor in actors:
            draft = operations.create_draft(actor=actor, kind="entry", references=[reference])
            draft = operations.save_draft(
                draft.pk,
                actor=actor,
                revision=0,
                header={"person_name": "Cliente concorrente fictício"},
                rows=[{"id": draft.lines.get().pk, "units": 2}],
            )
            reviewed, _ = operations.review_draft(draft.pk, actor=actor, revision=draft.revision)
            drafts.append((draft.pk, reviewed.review_token, actor.pk))
        barrier = Barrier(2)

        def run(args):
            connections.close_all()
            try:
                movement_id, token, actor_id = args
                actor = get_user_model().objects.get(pk=actor_id)
                barrier.wait(timeout=10)
                # Stock snapshots conflict as designed, so repeat conference explicitly
                # only after discovering the conflict, never silently in the service.
                try:
                    result = confirm_movement(
                        movement_id, actor=actor, review_token=token, report_requested=True
                    )
                except ValidationError:
                    draft = Movement.objects.get(pk=movement_id)
                    reviewed, _ = operations.review_draft(
                        movement_id, actor=actor, revision=draft.revision
                    )
                    result = confirm_movement(
                        movement_id,
                        actor=actor,
                        review_token=reviewed.review_token,
                        report_requested=True,
                    )
                return result.report_number.number
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            numbers = list(pool.map(run, drafts))
        self.assertEqual(sorted(numbers), [1, 2])
        self.assertEqual(Reference.objects.get(pk=reference.pk).current_stock, 4)
        self.assertEqual(ReportNumber.objects.count(), 2)
