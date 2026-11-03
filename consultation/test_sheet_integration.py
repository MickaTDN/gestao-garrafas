"""Mixed transports never bypass administrative review or duplicate official stock."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature

from consultation.models import PendingSheet, SheetAction, SheetReceipt
from consultation.review import confirm_sheet, reject_sheet, review_sheet
from consultation.sheets import receive_sheet
from consultation.test_sheet_transport import TransportFixtures
from consultation.transport import accept_upload
from inventory.documents import verified_bytes
from inventory.models import Document, Movement, ReportNumber
from tests.document_fixtures import signature_png


class IntegratedFixtures(TransportFixtures):
    def wifi(self, raw):
        return self.ack(accept_upload(raw, principal=self.principal, request_id=str(uuid.uuid4())))

    def confirm(self, sheet, review, **kwargs):
        # An entry always requires an explicit report choice, even in concurrent
        # service calls. Keep that production validation in force.
        kwargs.setdefault("report_requested", False)
        return confirm_sheet(
            sheet.pk,
            actor=self.admin,
            sequence=review.sequence,
            token=review.data["token"],
            confirmed=True,
            **kwargs,
        )


class IntegratedSheetTests(IntegratedFixtures, TestCase):
    def setUp(self):
        self.prepare_transport()

    def flow(self, kind):
        raw = self.packet({**self.payload, "kind": kind})
        self.assertEqual(self.wifi(raw)["outcome"], "pending")
        self.assertEqual(self.wifi(raw)["outcome"], "duplicate")  # lost response retry
        receipt = receive_sheet(raw, actor=self.admin)
        self.assertEqual(receipt.outcome, "duplicate")
        sheet = receipt.sheet
        self.ref.refresh_from_db()
        self.assertEqual(self.ref.current_stock, 12)
        self.assertFalse(Movement.objects.exists())
        with self.assertRaises(PermissionDenied):
            review_sheet(sheet.pk, actor=self.viewer, sequence=0)
        review, _ = review_sheet(sheet.pk, actor=self.admin, sequence=0)
        args = {
            "report_requested": True,
            "validation": "signed" if kind == "exit" else None,
            "signature_data": signature_png() if kind == "exit" else None,
        }
        official = self.confirm(sheet, review, **args)
        self.assertTrue(verified_bytes(official.report_number.document).startswith(b"%PDF"))
        self.assertEqual(receive_sheet(raw, actor=self.admin).outcome, "duplicate")
        self.assertEqual(self.wifi(raw)["outcome"], "duplicate")
        self.assertEqual(self.confirm(sheet, review, **args).pk, official.pk)
        self.assertEqual(Movement.objects.count(), 1)
        self.assertEqual(ReportNumber.objects.count(), 1)
        self.assertEqual(SheetAction.objects.filter(kind="confirmed").count(), 1)
        self.assertTrue(all(bytes(r.original) == raw for r in SheetReceipt.objects.all()))
        self.ref.refresh_from_db()
        self.assertEqual(self.ref.current_stock, 20 if kind == "entry" else 4)
        self.assertEqual(official.source_metadata["pending_sheet_id"], str(sheet.pk))

    def test_entry_mixed_delivery_and_repeated_confirmation_have_one_stock_effect(self):
        self.flow("entry")

    def test_signed_exit_mixed_delivery_has_one_pdf_number_and_stock_effect(self):
        self.flow("exit")

    def test_wifi_pdf_failure_rolls_back_official_records_not_original_evidence(self):
        raw = self.packet({**self.payload, "kind": "exit"})
        self.wifi(raw)
        sheet = PendingSheet.objects.get()
        review, _ = review_sheet(sheet.pk, actor=self.admin, sequence=0)
        with patch(
            "inventory.documents.render_pdf", side_effect=RuntimeError("Synthetic PDF failure")
        ):
            with self.assertRaises(RuntimeError):
                self.confirm(sheet, review)
        self.ref.refresh_from_db()
        self.assertEqual(self.ref.current_stock, 12)
        for model in (Movement, ReportNumber, Document):
            self.assertFalse(model.objects.exists())
        self.assertEqual(bytes(SheetReceipt.objects.get().original), raw)
        self.assertEqual(self.wifi(raw)["outcome"], "duplicate")
        self.assertEqual(self.confirm(sheet, review).status, "confirmed")

    def test_cross_transport_conflict_and_rejection_never_reopen_or_overwrite_original(self):
        raw = self.packet()
        self.wifi(raw)
        sheet = PendingSheet.objects.get()
        divergent = self.packet({**self.payload, "revision": 2, "notes": "Conflito sintético"})
        self.assertEqual(receive_sheet(divergent, actor=self.admin).outcome, "conflict")
        with self.assertRaises(ValidationError):
            review_sheet(sheet.pk, actor=self.admin, sequence=0)
        rejected = reject_sheet(sheet.pk, actor=self.admin, sequence=0, reason="Rejeição auditada")
        self.assertEqual(self.wifi(raw)["outcome"], "duplicate")
        with self.assertRaises(ValidationError):
            review_sheet(sheet.pk, actor=self.admin, sequence=rejected.sequence)
        self.assertFalse(Movement.objects.exists())
        sheet.refresh_from_db()
        self.assertEqual(sheet.payload, self.payload)
        self.assertEqual(SheetReceipt.objects.filter(outcome="conflict").get().original, divergent)


@skipUnlessDBFeature("has_select_for_update")
class IntegratedSheetConcurrencyTests(IntegratedFixtures, TransactionTestCase):
    def setUp(self):
        self.prepare_transport()

    def parallel(self, jobs):
        barrier = Barrier(len(jobs))

        def run(job):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return job()
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
            return list(pool.map(run, jobs))

    def test_manual_wifi_race_then_two_confirmations_and_retransmission(self):
        raw = self.packet()
        outcomes = self.parallel(
            [
                lambda: self.wifi(raw)["outcome"],
                lambda: receive_sheet(raw, actor=self.admin).outcome,
            ]
        )
        self.assertCountEqual(outcomes, ["pending", "duplicate"])
        self.assertEqual(PendingSheet.objects.count(), 1)
        self.assertFalse(Movement.objects.exists())
        sheet = PendingSheet.objects.get()
        review, _ = review_sheet(sheet.pk, actor=self.admin, sequence=0)
        results = self.parallel(
            [
                lambda: self.confirm(sheet, review).pk,
                lambda: self.confirm(sheet, review).pk,
                lambda: self.wifi(raw)["outcome"],
            ]
        )
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[2], "duplicate")
        self.assertEqual(Movement.objects.count(), 1)
        self.assertEqual(ReportNumber.objects.count(), 1)
        self.ref.refresh_from_db()
        self.assertEqual(self.ref.current_stock, 20)
