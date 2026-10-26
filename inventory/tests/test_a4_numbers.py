from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from datetime import timezone as dt_timezone
from importlib import import_module
from threading import Barrier
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, connections, transaction
from django.db.migrations.exceptions import IrreversibleError
from django.test import TestCase, TransactionTestCase

from inventory import operations
from inventory.documents import verified_bytes
from inventory.models import (
    AuditEvent,
    Document,
    Location,
    Movement,
    Reference,
    ReportNumber,
    ReportSequence,
)
from inventory.reporting import delete_pdf, regenerate_pdf
from inventory.services import confirm_movement
from tests.document_fixtures import confirmed_operation


class MovementNumberTests(TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_user(username="a4-number-admin", role="admin")
        self.location = Location.objects.create(name="Local A4 fictício")
        self.ref = Reference.objects.create(
            code="A4-NUM",
            name="Garrafa A4 fictícia",
            current_stock=30,
            box_capacity=6,
            location=self.location,
        )

    def test_entry_without_pdf_has_annual_movement_identity_without_document(self):
        movement = confirmed_operation(self.actor, self.ref, kind="entry", report=False)
        identity = movement.report_number
        self.assertIsNone(identity.document_id)
        self.assertEqual(identity.number, 1)
        self.assertEqual(identity.year, movement.date.year)
        self.assertEqual(str(movement), f"Mov-1/{movement.date.year % 100:02} · Entrada")
        self.assertFalse(movement.documents.exists())
        self.assertFalse(movement.report_requested)
        self.assertEqual(Reference.objects.get(pk=self.ref.pk).current_stock, 32)
        self.assertEqual(
            AuditEvent.objects.get(movement=movement, action="movement.confirmed").details[
                "number"
            ],
            str(identity),
        )

    def test_single_sequence_shared_by_entry_without_pdf_exit_and_entry_with_pdf(self):
        movements = [
            confirmed_operation(self.actor, self.ref, kind=kind, report=report)
            for kind, report in [
                ("entry", False),
                ("exit", False),
                ("entry", True),
                ("entry", False),
            ]
        ]
        self.assertEqual([movement.report_number.number for movement in movements], [1, 2, 3, 4])
        self.assertEqual(ReportSequence.objects.get().last_number, 4)
        self.assertEqual(Document.objects.filter(kind="pdf").count(), 2)
        self.assertEqual(
            [movement.report_number.document_id is None for movement in movements],
            [True, False, False, True],
        )
        for movement in (movements[1], movements[2]):
            document = movement.documents.get(kind="pdf")
            self.assertEqual(document.number, str(movement.report_number))
            self.assertEqual(document.metadata["report_sequence"], movement.report_number.number)

    def test_preparation_save_review_and_cancel_do_not_consume_numbers(self):
        draft = operations.create_draft(actor=self.actor, kind="entry", references=[self.ref])
        draft = operations.save_draft(
            draft.pk,
            actor=self.actor,
            revision=0,
            header={"person_name": "Cliente A4 fictício"},
            rows=[{"id": draft.lines.get().pk, "units": 2}],
        )
        draft, _ = operations.review_draft(draft.pk, actor=self.actor, revision=draft.revision)
        self.assertFalse(ReportNumber.objects.exists())
        self.assertFalse(ReportSequence.objects.exists())
        operations.cancel_draft(draft.pk, actor=self.actor, revision=draft.revision)
        self.assertFalse(ReportNumber.objects.exists())
        self.assertEqual(Reference.objects.get(pk=self.ref.pk).current_stock, 30)

    def test_final_no_pdf_choice_overrides_report_preference_in_existing_draft(self):
        draft = operations.create_draft(actor=self.actor, kind="entry", references=[self.ref])
        draft = operations.save_draft(
            draft.pk,
            actor=self.actor,
            revision=0,
            header={"person_name": "Cliente A4 fictício", "report_requested": True},
            rows=[{"id": draft.lines.get().pk, "units": 2}],
        )
        self.assertTrue(draft.report_requested)
        reviewed, _ = operations.review_draft(draft.pk, actor=self.actor, revision=draft.revision)
        movement = confirm_movement(
            draft.pk, actor=self.actor, review_token=reviewed.review_token, report_requested=False
        )
        self.assertFalse(movement.report_requested)
        self.assertIsNone(movement.report_number.document_id)
        self.assertFalse(movement.documents.exists())
        self.assertEqual(movement.report_number.number, 1)

    def test_year_change_with_and_without_pdf_uses_official_full_year(self):
        results = []
        for year, report in [(2026, False), (2026, True), (2027, False), (2027, True)]:
            with patch(
                "django.utils.timezone.now",
                return_value=datetime(year, 6, 15, 12, tzinfo=dt_timezone.utc),
            ):
                movement = confirmed_operation(self.actor, self.ref, kind="entry", report=report)
                results.append((movement.report_number.year, str(movement.report_number)))
        self.assertEqual(
            results,
            [(2026, "Mov-1/26"), (2026, "Mov-2/26"), (2027, "Mov-1/27"), (2027, "Mov-2/27")],
        )

    def test_midnight_year_boundary_does_not_assign_number_to_previous_day_draft(self):
        with patch(
            "django.utils.timezone.now",
            return_value=datetime(2026, 12, 31, 23, 59, tzinfo=dt_timezone.utc),
        ):
            draft = operations.create_draft(actor=self.actor, kind="entry", references=[self.ref])
            draft = operations.save_draft(
                draft.pk,
                actor=self.actor,
                revision=0,
                header={"person_name": "Cliente passagem de ano fictício"},
                rows=[{"id": draft.lines.get().pk, "units": 2}],
            )
            reviewed, _ = operations.review_draft(
                draft.pk, actor=self.actor, revision=draft.revision
            )
            old_year = confirmed_operation(self.actor, self.ref, kind="entry", report=False)
        with patch(
            "django.utils.timezone.now",
            return_value=datetime(2027, 1, 1, 0, 1, tzinfo=dt_timezone.utc),
        ):
            with self.assertRaisesMessage(ValidationError, "outro dia"):
                confirm_movement(
                    draft.pk,
                    actor=self.actor,
                    review_token=reviewed.review_token,
                    report_requested=False,
                )
            self.assertFalse(ReportSequence.objects.filter(year=2027).exists())
            new_year = confirmed_operation(self.actor, self.ref, kind="entry", report=True)
        self.assertEqual(str(old_year.report_number), "Mov-1/26")
        self.assertEqual(str(new_year.report_number), "Mov-1/27")
        self.assertFalse(ReportNumber.objects.filter(movement=draft).exists())
        self.assertEqual(Reference.objects.get(pk=self.ref.pk).current_stock, 34)

    def test_failure_after_number_stock_and_documents_rolls_back_everything(self):
        draft = operations.create_draft(actor=self.actor, kind="entry", references=[self.ref])
        draft = operations.save_draft(
            draft.pk,
            actor=self.actor,
            revision=0,
            header={"person_name": "Cliente rollback fictício"},
            rows=[{"id": draft.lines.get().pk, "units": 2}],
        )
        reviewed, _ = operations.review_draft(draft.pk, actor=self.actor, revision=draft.revision)
        before = AuditEvent.objects.count()
        original = AuditEvent.objects.create

        def fail_final(**kwargs):
            if kwargs.get("action") == "movement.confirmed":
                raise RuntimeError("Synthetic post-number failure")
            return original(**kwargs)

        for report in (False, True):
            with (
                patch("inventory.services.AuditEvent.objects.create", side_effect=fail_final),
                self.assertRaises(RuntimeError),
            ):
                confirm_movement(
                    draft.pk,
                    actor=self.actor,
                    review_token=reviewed.review_token,
                    report_requested=report,
                )
            self.assertFalse(ReportNumber.objects.exists())
            self.assertFalse(ReportSequence.objects.exists())
            self.assertFalse(Document.objects.exists())
            self.assertEqual(AuditEvent.objects.count(), before)
            self.assertEqual(Reference.objects.get(pk=self.ref.pk).current_stock, 30)
            self.assertEqual(Movement.objects.get(pk=draft.pk).status, "draft")

    def test_repeated_confirmation_does_not_consume_another_number_or_stock(self):
        movement = confirmed_operation(self.actor, self.ref, kind="entry", report=False)
        with self.assertRaises(ValidationError):
            confirm_movement(
                movement.pk,
                actor=self.actor,
                review_token=movement.review_token,
                report_requested=False,
            )
        self.assertEqual(ReportSequence.objects.get().last_number, 1)
        self.assertEqual(ReportNumber.objects.count(), 1)
        self.assertEqual(Reference.objects.get(pk=self.ref.pk).current_stock, 32)

    def test_pdf_deletion_regeneration_and_new_no_pdf_entry_keep_identity_and_bytes(self):
        movement = confirmed_operation(self.actor, self.ref, signed=True)
        pdf = movement.documents.get(kind="pdf")
        original = verified_bytes(pdf)
        delete_pdf(actor=self.actor, document_id=pdf.pk)
        without = confirmed_operation(self.actor, self.ref, kind="entry", report=False)
        regenerate_pdf(actor=self.actor, document_id=pdf.pk)
        self.assertEqual(verified_bytes(pdf), original)
        self.assertEqual((movement.report_number.number, without.report_number.number), (1, 2))
        self.assertEqual(ReportSequence.objects.get().last_number, 2)

    def test_no_pdf_number_is_immutable_in_orm_sql_and_reverse_migration(self):
        movement = confirmed_operation(self.actor, self.ref, kind="entry", report=False)
        with self.assertRaises(ValidationError):
            ReportNumber.objects.filter(movement=movement).update(number=100)
        with self.assertRaises(ValidationError):
            ReportNumber.objects.filter(movement=movement).delete()
        if connection.vendor == "postgresql":
            for statement in (
                "UPDATE inventory_reportnumber SET number=100 WHERE movement_id=%s",
                "DELETE FROM inventory_reportnumber WHERE movement_id=%s",
            ):
                with (
                    self.assertRaises(IntegrityError),
                    transaction.atomic(),
                    connection.cursor() as cursor,
                ):
                    cursor.execute(statement, [movement.pk])
        guard = import_module("inventory.migrations.0014_movement_number_without_pdf")
        with self.assertRaises(IrreversibleError):
            guard.remove(apps, None)
        self.assertEqual(ReportNumber.objects.get(movement=movement).number, 1)


class MovementNumberConcurrencyTests(TransactionTestCase):
    def test_database_refuses_committing_an_identity_for_a_preparation(self):
        from inventory.reporting import allocate_number

        actor = get_user_model().objects.create_user(username="a4-premature-number", role="admin")
        draft = operations.create_draft(actor=actor, kind="entry")
        with self.assertRaises(IntegrityError), transaction.atomic():
            number = allocate_number(draft.date.year)
            ReportNumber.objects.create(movement=draft, year=draft.date.year, number=number)
        self.assertFalse(ReportNumber.objects.exists())
        self.assertFalse(ReportSequence.objects.exists())

    def test_real_concurrent_confirmations_with_and_without_pdf_share_counter(self):
        actors = [
            get_user_model().objects.create_user(username=f"a4-concurrent-{i}", role="admin")
            for i in range(2)
        ]
        location = Location.objects.create(name="Local concorrente A4 fictício")
        drafts = []
        for i, actor in enumerate(actors):
            ref = Reference.objects.create(
                code=f"A4-CONC-{i}", name=f"Garrafa concorrente fictícia {i}", location=location
            )
            draft = operations.create_draft(actor=actor, kind="entry", references=[ref])
            draft = operations.save_draft(
                draft.pk,
                actor=actor,
                revision=0,
                header={"person_name": "Cliente fictício A4"},
                rows=[{"id": draft.lines.get().pk, "units": 2}],
            )
            reviewed, _ = operations.review_draft(draft.pk, actor=actor, revision=draft.revision)
            drafts.append((draft.pk, actor.pk, reviewed.review_token, bool(i)))
        barrier = Barrier(2)

        def confirm(args):
            connections.close_all()
            try:
                pk, actor_id, token, report = args
                actor = get_user_model().objects.get(pk=actor_id)
                barrier.wait(timeout=10)
                movement = confirm_movement(
                    pk, actor=actor, review_token=token, report_requested=report
                )
                return movement.report_number.number
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            result = list(pool.map(confirm, drafts))
        self.assertEqual(sorted(result), [1, 2])
        self.assertEqual(ReportNumber.objects.count(), 2)
        self.assertEqual(ReportSequence.objects.get().last_number, 2)
        self.assertEqual(Document.objects.filter(kind="pdf").count(), 1)
        self.assertEqual(
            list(Reference.objects.order_by("code").values_list("current_stock", flat=True)), [2, 2]
        )

    def test_database_rejects_new_workflow_confirmation_without_identity(self):
        actor = get_user_model().objects.create_user(username="a4-forged-sql", role="admin")
        draft = operations.create_draft(actor=actor, kind="entry")
        with self.assertRaises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                "UPDATE inventory_movement SET status='confirmed' WHERE id=%s", [draft.pk]
            )
        self.assertEqual(Movement.objects.get(pk=draft.pk).status, "draft")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Movement.objects.create(
                kind="entry", status="confirmed", workflow_version=1, created_by=actor
            )
