import hashlib
import json
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import ec
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, close_old_connections, connection, transaction
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from jwcrypto import jwe, jwk

from consultation.models import AuthorizedDevice, ExportSource, PendingSheet, SheetReceipt
from consultation.sheets import receive_sheet, reference_warnings, revoke_device
from consultation.signing import public_key, signed_snapshot
from inventory.models import AuditEvent, Document, Location, Movement, Reference


class SheetFixtures:
    def prepare(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.recipient = jwk.JWK.generate(kty="RSA", size=3072)
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.other = ec.generate_private_key(ec.SECP256R1())
        self.setting = self.settings(
            VERTENTE_SIGNING_KEY_FILE=str(Path(self.temp.name) / "signing.pem")
        )
        self.setting.enable()
        self.addCleanup(self.setting.disable)
        (Path(self.temp.name) / "pending-reception.pem").write_bytes(
            self.recipient.export_to_pem(private_key=True, password=None)
        )
        self.admin = get_user_model().objects.create_user(
            username="sheets-synthetic-admin", role="admin"
        )
        self.viewer = get_user_model().objects.create_user(
            username="sheets-synthetic-viewer", role="viewer"
        )
        self.source = ExportSource.objects.create(pk=1)
        pub = public_key(self.key)
        self.device = AuthorizedDevice.objects.create(
            device_id=uuid.uuid4(),
            public_key_id=pub["key_id"],
            public_spki=pub["spki"],
            role="employee",
            revision=1,
            sheets_allowed=True,
            expires_at=timezone.now() + timedelta(days=1),
        )
        self.ref = Reference.objects.create(
            code="SHEET-1",
            name="Referência sintética",
            location=Location.objects.create(name="Local sintético"),
            box_capacity=6,
            current_stock=12,
        )
        self.payload = {
            "source_id": str(self.source.source_id),
            "device_id": str(self.device.pk),
            "authorization_revision": 1,
            "sheet_id": str(uuid.uuid4()),
            "revision": 1,
            "kind": "entry",
            "physical_date": "2026-01-02",
            "person": "Pessoa fictícia",
            "notes": "Observação sintética",
            "lines": [
                {"reference_id": str(self.ref.pk), "boxes": 1, "units": 2, "box_capacity": 6}
            ],
        }

    def packet(self, payload=None, key=None, signed=None):
        signed = signed or signed_snapshot(
            payload or self.payload, key or self.key, kind="vertente-sheet", version=1
        )
        message = jwe.JWE(
            json.dumps(signed).encode(),
            protected={"alg": "RSA-OAEP-256", "enc": "A256GCM", "kid": self.recipient.thumbprint()},
            recipient=self.recipient.public(),
        )
        return json.dumps(
            {
                "format": "vertente-pending-sheet",
                "version": 1,
                "jwe": message.serialize(compact=True),
            }
        ).encode()


class SheetTests(SheetFixtures, TestCase):
    def setUp(self):
        self.prepare()

    def test_invalid_unicode_is_rejected_and_audited_not_a_server_error(self):
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

        from consultation.signing import b64

        data = json.dumps({**self.payload, "notes": "\ud800"}, ensure_ascii=True).encode()
        r, s = decode_dss_signature(
            self.key.sign(b"vertente-sheet-v1\0" + data, ec.ECDSA(hashes.SHA256()))
        )
        signed = signed_snapshot(self.payload, self.key, kind="vertente-sheet", version=1)
        signed["payload"], signed["signature"] = (
            b64(data),
            b64(r.to_bytes(32, "big") + s.to_bytes(32, "big")),
        )
        with self.assertRaises(ValidationError):
            receive_sheet(self.packet(signed=signed), actor=self.admin)
        self.assertFalse(PendingSheet.objects.exists())
        self.assertTrue(AuditEvent.objects.filter(action="sheets.rejected_file").exists())

    def test_receive_entry_exit_and_unknown_references_without_stock_or_documents(self):
        for kind in ("entry", "exit"):
            receipt = receive_sheet(
                self.packet(
                    {
                        **self.payload,
                        "kind": kind,
                        "sheet_id": str(uuid.uuid4()),
                        "lines": self.payload["lines"]
                        + [
                            {
                                "reference_id": "not-known",
                                "boxes": None,
                                "units": 3,
                                "box_capacity": None,
                            }
                        ],
                    }
                ),
                actor=self.admin,
            )
            self.assertEqual(receipt.outcome, "pending")
            self.assertEqual(
                reference_warnings(receipt.sheet)[0]["reason"], "Referência desconhecida"
            )
        self.ref.refresh_from_db()
        self.assertEqual(self.ref.current_stock, 12)
        self.assertEqual(Reference.objects.count(), 1)
        self.assertFalse(Movement.objects.exists())
        self.assertFalse(Document.objects.exists())

    def test_repeat_same_payload_reencrypted_is_idempotent_but_divergent_revision_is_conflict(self):
        first = self.packet()
        receipt = receive_sheet(first, actor=self.admin)
        duplicate = receive_sheet(self.packet(), actor=self.admin)
        conflict = receive_sheet(
            self.packet({**self.payload, "revision": 2, "notes": "Outra observação"}),
            actor=self.admin,
        )
        self.assertEqual((duplicate.outcome, conflict.outcome), ("duplicate", "conflict"))
        self.assertEqual(PendingSheet.objects.count(), 1)
        self.assertEqual(SheetReceipt.objects.count(), 3)
        self.assertEqual(bytes(receipt.original), first)
        self.assertEqual(receipt.sheet.payload, self.payload)

    def test_corruption_wrong_recipient_signature_origin_and_authorization_refused(self):
        raw = self.packet()
        invalids = [
            raw[:-5],
            b"{}",
            self.packet(key=self.other),
            self.packet({**self.payload, "source_id": str(uuid.uuid4())}),
            self.packet({**self.payload, "authorization_revision": 2}),
        ]
        wrapped = json.loads(raw)
        wrapped["jwe"] = wrapped["jwe"][:-8] + "AAAAAAAA"
        invalids.append(json.dumps(wrapped).encode())
        signed = signed_snapshot(self.payload, self.key, kind="vertente-stock", version=2)
        invalids.append(self.packet(signed=signed))
        for value in invalids:
            with self.subTest(size=len(value)), self.assertRaises(ValidationError):
                receive_sheet(value, actor=self.admin)
        self.assertFalse(PendingSheet.objects.exists())
        self.assertEqual(
            AuditEvent.objects.filter(action="sheets.rejected_file").count(), len(invalids)
        )

    def test_revocation_expiry_missing_public_key_or_permission_prevent_receipt(self):
        for change in (
            {"sheets_allowed": False},
            {"public_spki": ""},
            {"expires_at": timezone.now() - timedelta(seconds=1)},
        ):
            with transaction.atomic():
                AuthorizedDevice.objects.filter(pk=self.device.pk).update(**change)
                with self.assertRaises(ValidationError):
                    receive_sheet(self.packet(), actor=self.admin)
                transaction.set_rollback(True)
        revoke_device(self.device.pk, actor=self.admin)
        with self.assertRaises(ValidationError):
            receive_sheet(self.packet(), actor=self.admin)

    def test_invalid_quantities_and_dates_are_rejected_and_original_values_preserved(self):
        for changes in (
            {"boxes": -1},
            {"units": 1.5},
            {"boxes": True},
            {"boxes": 1, "box_capacity": None},
            {"boxes": None, "units": None},
            {"boxes": 0, "units": 0},
            {"units": 2147483647},
        ):
            line = {**self.payload["lines"][0], **changes}
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                receive_sheet(self.packet({**self.payload, "lines": [line]}), actor=self.admin)
        receipt = receive_sheet(
            self.packet(
                {
                    **self.payload,
                    "lines": [
                        {
                            "reference_id": str(self.ref.pk),
                            "boxes": None,
                            "units": 2,
                            "box_capacity": None,
                        }
                    ],
                }
            ),
            actor=self.admin,
        )
        self.assertIsNone(receipt.sheet.payload["lines"][0]["boxes"])
        self.assertEqual(receipt.sheet.payload["physical_date"], "2026-01-02")

    def test_only_admin_can_receive_view_download_and_revoke(self):
        with self.assertRaises(PermissionDenied):
            receive_sheet(self.packet(), actor=self.viewer)
        self.client.force_login(self.admin)
        raw = self.packet()
        response = self.client.post(
            reverse("web:sheets"), {"file": SimpleUploadedFile("fake.vasheet", raw)}
        )
        self.assertEqual(response.status_code, 302)
        receipt = SheetReceipt.objects.get()
        url = reverse("web:sheet-original", args=[receipt.pk])
        self.assertEqual(self.client.get(url).content, raw)
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(reverse("web:sheets"), {}).status_code, 403)
        self.assertEqual(
            self.client.post(reverse("web:sheet-revoke", args=[self.device.pk])).status_code, 403
        )

    def test_received_evidence_is_immutable_even_in_postgresql(self):
        receipt = receive_sheet(self.packet(), actor=self.admin)
        with self.assertRaises(ValidationError):
            receipt.delete()
        if connection.vendor == "postgresql":
            for table in ("consultation_pendingsheet", "consultation_sheetreceipt"):
                with self.assertRaises(DatabaseError), transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("DELETE FROM " + table)

    def test_ciphertext_does_not_contain_person_notes_or_quantities(self):
        raw = self.packet()
        self.assertNotIn(self.payload["person"].encode(), raw)
        self.assertNotIn(self.payload["notes"].encode(), raw)
        self.assertNotIn(b"box_capacity", raw)
        receipt = receive_sheet(raw, actor=self.admin)
        self.assertEqual(receipt.file_sha256, hashlib.sha256(raw).hexdigest())
        self.assertEqual(receipt.authorization["public_key_id"], self.device.public_key_id)

    def test_csrf_required_for_file_reception(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        response = client.post(
            reverse("web:sheets"), {"file": SimpleUploadedFile("fake.vasheet", self.packet())}
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(PendingSheet.objects.exists())

    def test_bounds_and_schema_are_validated_before_persistence(self):
        for change in (
            {"physical_date": "2026-02-30"},
            {"revision": True},
            {"person": ""},
            {"notes": "x" * 4001},
            {"lines": self.payload["lines"] * 501},
        ):
            with self.subTest(change=list(change)), self.assertRaises(ValidationError):
                receive_sheet(self.packet({**self.payload, **change}), actor=self.admin)
        self.assertFalse(PendingSheet.objects.exists())

    def test_original_and_payload_roundtrip_from_database(self):
        raw = self.packet()
        receipt = receive_sheet(raw, actor=self.admin)
        receipt.refresh_from_db()
        self.assertEqual(bytes(receipt.original), raw)
        self.assertEqual(receipt.sheet.payload, self.payload)

    def test_lost_key_is_not_silently_replaced_after_receipt(self):
        receive_sheet(self.packet(), actor=self.admin)
        path = Path(self.temp.name) / "pending-reception.pem"
        path.unlink()
        with self.assertRaisesMessage(CommandError, "Recupere a chave original"):
            call_command("pending_sheet_setup")
        self.assertFalse(path.exists())


class SheetConcurrencyTests(SheetFixtures, TransactionTestCase):
    def setUp(self):
        self.prepare()

    def test_concurrent_identical_imports_create_one_pending_and_two_receipts(self):
        if connection.vendor != "postgresql":
            self.skipTest("Requires real PostgreSQL locking")
        raw = self.packet()

        def submit(_):
            close_old_connections()
            try:
                return receive_sheet(raw, actor=self.admin).outcome
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(submit, range(2)))
        self.assertEqual(sorted(outcomes), ["duplicate", "pending"])
        self.assertEqual(PendingSheet.objects.count(), 1)
        self.assertEqual(SheetReceipt.objects.count(), 2)
        self.ref.refresh_from_db()
        self.assertEqual(self.ref.current_stock, 12)
