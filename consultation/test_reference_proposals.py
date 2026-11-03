import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature

from consultation.review import confirm_sheet, correct_sheet, reject_sheet, review_sheet
from consultation.sheets import receive_sheet
from consultation.signing import signed_snapshot
from consultation.test_sheet_transport import TransportFixtures
from consultation.transport import accept_upload
from inventory.models import Document, Movement, Reference, ReportNumber


class ProposalFixtures(TransportFixtures):
    def new_line(self, name="Nova garrafa fictícia"):
        return {
            "reference_id": "proposal:" + str(uuid.uuid4()),
            "proposal": {"name": name},
            "boxes": 1,
            "units": 2,
            "box_capacity": 6,
        }

    def packet_v2(self, payload):
        signed = signed_snapshot(payload, self.key, kind="vertente-sheet", version=2)
        packet = json.loads(self.packet(payload, signed=signed))
        packet["version"] = 2
        return json.dumps(packet).encode()

    def received_proposal(self):
        self.line = self.new_line()
        self.payload = {**self.payload, "lines": [self.payload["lines"][0], self.line]}
        self.raw = self.packet_v2(self.payload)
        proof = accept_upload(self.raw, principal=self.principal, request_id=str(uuid.uuid4()))
        from consultation.models import PendingSheet

        self.assertEqual(self.ack(proof)["outcome"], "pending")
        return PendingSheet.objects.get()

    def approve(self, sheet):
        lines = [*sheet.payload["lines"]]
        lines[-1] = {
            **lines[-1],
            "proposal": {
                "name": lines[-1]["proposal"]["name"],
                "location_id": self.ref.location_id,
                "sector_id": None,
            },
        }
        event = correct_sheet(
            sheet.pk,
            actor=self.admin,
            sequence=0,
            reason="Aprovação e localização conferidas",
            values={
                **{k: sheet.payload[k] for k in ("person", "physical_date", "notes")},
                "lines": lines,
            },
        )
        return review_sheet(sheet.pk, actor=self.admin, sequence=event.sequence)[0]

    def confirm(self, sheet, review):
        return confirm_sheet(
            sheet.pk,
            actor=self.admin,
            sequence=review.sequence,
            token=review.data["token"],
            confirmed=True,
            report_requested=True,
        )


class ReferenceProposalTests(ProposalFixtures, TestCase):
    def setUp(self):
        self.prepare_transport()

    def test_receive_wifi_file_approval_and_confirmation_create_only_once(self):
        sheet = self.received_proposal()
        self.assertEqual(Reference.objects.count(), 1)
        self.assertEqual(receive_sheet(self.raw, actor=self.admin).outcome, "duplicate")
        with self.assertRaises(ValidationError):
            review_sheet(sheet.pk, actor=self.admin, sequence=0)
        review = self.approve(sheet)
        self.assertEqual(Reference.objects.count(), 1)
        result = self.confirm(sheet, review)
        created = Reference.objects.exclude(pk=self.ref.pk).get()
        self.assertTrue(created.code.startswith("GAR-"))
        self.assertEqual(created.current_stock, 8)
        self.ref.refresh_from_db()
        self.assertEqual(self.ref.current_stock, 20)
        self.assertEqual(self.confirm(sheet, review).pk, result.pk)
        self.assertEqual(receive_sheet(self.raw, actor=self.admin).outcome, "duplicate")
        self.assertEqual(Reference.objects.count(), 2)
        self.assertEqual(ReportNumber.objects.count(), 1)
        self.assertEqual(result.lines.count(), 2)
        self.assertEqual(
            result.source_metadata["proposal_reference_ids"][self.line["reference_id"]], created.pk
        )
        sheet.refresh_from_db()
        self.assertEqual(sheet.payload, self.payload)

    def test_pdf_failure_rolls_back_reference_codes_stock_and_audit_then_retry(self):
        sheet = self.received_proposal()
        review = self.approve(sheet)
        with patch(
            "inventory.documents.render_pdf", side_effect=RuntimeError("Synthetic PDF failure")
        ):
            with self.assertRaises(RuntimeError):
                self.confirm(sheet, review)
        self.assertEqual(Reference.objects.count(), 1)
        for model in (Movement, Document, ReportNumber):
            self.assertFalse(model.objects.exists())
        self.ref.refresh_from_db()
        self.assertEqual(self.ref.current_stock, 12)
        self.confirm(sheet, review)
        self.assertEqual(Reference.objects.count(), 2)

    def test_inactive_duplicate_can_only_be_explicitly_associated_after_reactivation(self):
        self.ref.active = False
        self.ref.name = "  NOVA   GARRAFA FICTÍCIA "
        self.ref.save(update_fields=["active", "name"])
        sheet = self.received_proposal()
        with self.assertRaises(ValidationError):
            self.approve(sheet)
        self.assertEqual(Reference.objects.count(), 1)
        reject_sheet(sheet.pk, actor=self.admin, sequence=1, reason="Já existe referência inativa")
        self.assertEqual(Reference.objects.count(), 1)
        self.assertFalse(Movement.objects.exists())

    def test_version_one_rejects_proposals_and_exits_reject_version_two_proposals(self):
        payload = {**self.payload, "lines": [self.new_line()]}
        for raw in (self.packet(payload), self.packet_v2({**payload, "kind": "exit"})):
            with self.assertRaises(ValidationError):
                receive_sheet(raw, actor=self.admin)
        self.assertEqual(Reference.objects.count(), 1)

    def test_legacy_unknown_identifier_with_prefix_remains_receivable_without_creation(self):
        line = {**self.payload["lines"][0], "reference_id": "proposal:" + str(uuid.uuid4())}
        receipt = receive_sheet(self.packet({**self.payload, "lines": [line]}), actor=self.admin)
        self.assertEqual(receipt.outcome, "pending")
        self.assertEqual(Reference.objects.count(), 1)
        with self.assertRaises(ValidationError):
            review_sheet(receipt.sheet_id, actor=self.admin, sequence=0)

    def test_explicit_association_preserves_inactive_identity_and_requires_reactivation(self):
        from inventory.catalog import set_reference_active

        self.ref.current_stock = 0
        self.ref.active = False
        self.ref.save(update_fields=["current_stock", "active"])
        line = self.new_line(self.ref.name)
        payload = {**self.payload, "lines": [line]}
        sheet = receive_sheet(self.packet_v2(payload), actor=self.admin).sheet
        corrected = {"reference_id": str(self.ref.pk), "boxes": 1, "units": 2, "box_capacity": 6}
        event = correct_sheet(
            sheet.pk,
            actor=self.admin,
            sequence=0,
            reason="Associação explícita à referência original",
            values={
                **{k: payload[k] for k in ("person", "physical_date", "notes")},
                "lines": [corrected],
            },
        )
        with self.assertRaises(ValidationError):
            review_sheet(sheet.pk, actor=self.admin, sequence=event.sequence)
        set_reference_active(actor=self.admin, reference_id=self.ref.pk, active=True)
        review, _ = review_sheet(sheet.pk, actor=self.admin, sequence=event.sequence)
        self.confirm(sheet, review)
        self.assertEqual(Reference.objects.count(), 1)
        self.ref.refresh_from_db()
        self.assertEqual(self.ref.current_stock, 8)
        self.assertEqual(self.ref.code, "SHEET-1")
        sheet.refresh_from_db()
        self.assertEqual(sheet.payload, payload)

    def test_new_protocol_marker_refuses_downgrade_when_v2_evidence_exists(self):
        import importlib

        from django.apps import apps
        from django.db.migrations.exceptions import IrreversibleError

        self.received_proposal()
        migration = importlib.import_module(
            "consultation.migrations.0008_reference_proposal_protocol"
        )
        with self.assertRaises(IrreversibleError):
            migration.protect_reverse(apps, None)


@skipUnlessDBFeature("has_select_for_update")
class ProposalConcurrencyTests(ProposalFixtures, TransactionTestCase):
    def setUp(self):
        self.prepare_transport()

    def test_two_confirmations_allocate_one_reference_and_movement(self):
        sheet = self.received_proposal()
        review = self.approve(sheet)
        barrier = Barrier(2)

        def worker(_):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return self.confirm(sheet, review).pk
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            ids = list(pool.map(worker, range(2)))
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(Reference.objects.count(), 2)
        self.assertEqual(Movement.objects.count(), 1)
