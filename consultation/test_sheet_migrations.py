"""Apply the real migration join to populated synthetic databases from either line."""

import uuid
from datetime import timedelta

from django.db import DatabaseError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class SheetMigrationJoinTests(TransactionTestCase):
    latest = "0007_merge_review_wifi"

    def go(self, target):
        executor = MigrationExecutor(connection)
        executor.migrate([("consultation", target)])
        # Other applications stay at their actual applied revisions (not merely
        # consultation's minimum swappable-user dependency).
        executor = MigrationExecutor(connection)
        return executor.loader.project_state(list(executor.loader.applied_migrations)).apps

    def setUp(self):
        # Fresh test database only. Existing append-only reverse guards remain in
        # force; no production data, trigger disabling or reverse bypass is used.
        self.go("0004_sheet_evidence_guards")
        self.addCleanup(self.go, self.latest)

    def seed(self, apps, *, device_receipt=False):
        actor = apps.get_model("accounts", "User").objects.create(
            username="synthetic-migration-admin", role="admin"
        )
        location = apps.get_model("inventory", "Location").objects.create(
            name="Local fictício de migração"
        )
        reference = apps.get_model("inventory", "Reference").objects.create(
            code="MERGE-1", name="Referência fictícia", location=location, current_stock=7
        )
        device = apps.get_model("consultation", "AuthorizedDevice").objects.create(
            device_id=uuid.uuid4(),
            public_key_id="a" * 64,
            public_spki="synthetic-migration-only",
            role="employee",
            revision=1,
            sheets_allowed=True,
            expires_at=timezone.now() + timedelta(days=1),
        )
        source = uuid.uuid4()
        sheet = apps.get_model("consultation", "PendingSheet").objects.create(
            source_id=source,
            sheet_id=uuid.uuid4(),
            device=device,
            revision=1,
            content_sha256="b" * 64,
            payload={"kind": "entry", "person": "Pessoa fictícia"},
        )
        raw = b'{"synthetic":"migration-evidence-only"}'
        receipt = apps.get_model("consultation", "SheetReceipt").objects.create(
            sheet=sheet,
            actor=None if device_receipt else actor,
            original=raw,
            file_sha256="c" * 64,
            outcome="pending",
            authorization={"transport": "wifi" if device_receipt else "file"},
        )
        return actor, reference, sheet, receipt, raw

    def preserved(self, ids, *, null_actor=False):
        actor, reference, sheet, receipt, raw = ids
        apps = self.go(self.latest)
        saved = apps.get_model("consultation", "SheetReceipt").objects.get(pk=receipt.pk)
        self.assertEqual(saved.actor_id, None if null_actor else actor.pk)
        self.assertEqual(bytes(saved.original), raw)
        self.assertEqual(saved.file_sha256, "c" * 64)
        self.assertEqual(
            apps.get_model("inventory", "Reference").objects.get(pk=reference.pk).current_stock, 7
        )
        self.assertEqual(
            apps.get_model("consultation", "PendingSheet").objects.get(pk=sheet.pk).payload,
            sheet.payload,
        )
        self.assertFalse(apps.get_model("inventory", "Movement").objects.exists())
        if connection.vendor == "postgresql":
            with self.assertRaises(DatabaseError), transaction.atomic():
                apps.get_model("consultation", "SheetReceipt").objects.filter(pk=saved.pk).update(
                    outcome="duplicate"
                )
        return apps

    def test_populated_wifi_branch_keeps_null_actor_original_stock_and_new_decision_guards(self):
        ids = self.seed(self.go("0005_wifi_receipt_actor"), device_receipt=True)
        apps = self.preserved(ids, null_actor=True)
        self.assertFalse(apps.get_model("consultation", "SheetAction").objects.exists())

    def test_populated_review_branch_keeps_actions_and_enables_device_receipts(self):
        apps = self.go("0006_sheet_action_guards")
        ids = self.seed(apps)
        action = apps.get_model("consultation", "SheetAction").objects.create(
            sheet=ids[2],
            actor=ids[0],
            sequence=1,
            kind="reviewed",
            data={"token": str(uuid.uuid4())},
        )
        apps = self.preserved(ids)
        model = apps.get_model("consultation", "SheetAction")
        self.assertEqual(model.objects.get(pk=action.pk).data, action.data)
        self.assertTrue(
            apps.get_model("consultation", "SheetReceipt")._meta.get_field("actor").null
        )
        if connection.vendor == "postgresql":
            with self.assertRaises(DatabaseError), transaction.atomic():
                model.objects.filter(pk=action.pk).update(kind="rejected")
