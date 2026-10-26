import base64
import io
import json
import tempfile
import uuid
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import AccessProfile, User
from consultation.devices import authorize_device
from consultation.exports import export_snapshot, recovery_receipts
from consultation.models import AuthorizedDevice, ExportSource
from consultation.signing import b64
from inventory.models import AuditEvent, Location, Movement, Reference, Sector
from tests.document_fixtures import confirmed_operation


def decode(file):
    return json.loads(base64.urlsafe_b64decode(file["payload"] + "=="))


class StageBExportTests(TransactionTestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory(prefix="gg-stageb-synthetic-")
        self.addCleanup(self.home.cleanup)
        self.path = Path(self.home.name)
        call_command("vertente_setup", directory=str(self.path), stdout=io.StringIO())
        setting = self.settings(VERTENTE_SIGNING_KEY_FILE=str(self.path / "signing.pem"))
        setting.enable()
        self.addCleanup(setting.disable)
        self.admin = User.objects.create_user(username="b-fiction-admin", role="admin")
        self.viewer = User.objects.create_user(username="b-fiction-viewer")
        self.location = Location.objects.create(name="Corredor sintético B")
        self.sector = Sector.objects.create(name="Setor 10", location=self.location)
        self.ref = Reference.objects.create(
            code="B-SYN",
            name="Garrafa de ensaio",
            location=self.location,
            sector=self.sector,
            current_stock=120,
            box_capacity=6,
            minimum=150,
        )

    def test_receipts_are_real_entries_not_net_stock_change_or_drafts(self):
        first = confirmed_operation(self.admin, self.ref, kind="entry", units=60)
        confirmed_operation(self.admin, self.ref, kind="exit", units=48)
        Movement.objects.create(kind="entry", created_by=self.admin, workflow_version=1)
        data = decode(export_snapshot(actor=self.viewer))
        self.assertEqual(data["references"][0]["bottles"], 132)
        self.assertEqual(len(data["receipts"]), 1)
        received = data["receipts"][0]
        self.assertEqual(received["bottles"], 60)
        self.assertEqual(received["movement_id"], str(first.pk))
        self.assertEqual(received["reference_id"], str(self.ref.pk))
        self.assertEqual(received["units"], 60)
        self.assertIsNone(received["boxes"])
        self.assertEqual(data["references"][0]["location"], self.location.name)
        self.assertEqual(data["references"][0]["sector"], self.sector.name)
        self.assertEqual(data["references"][0]["minimum"], 150)
        self.assertNotIn("person", json.dumps(data))
        self.assertNotIn("Pessoa documental", json.dumps(data))

    def test_missed_exports_repeat_full_receipt_window_with_stable_ids(self):
        first = confirmed_operation(self.admin, self.ref, kind="entry")
        a = decode(export_snapshot(actor=self.viewer))
        export_snapshot(actor=self.viewer)
        second = confirmed_operation(self.admin, self.ref, kind="entry")
        b = decode(export_snapshot(actor=self.viewer))
        self.assertEqual(a["receipts"][0], b["receipts"][0])
        self.assertEqual({x["movement_id"] for x in b["receipts"]}, {str(first.pk), str(second.pk)})
        self.assertEqual(b["sequence"], 3)

    def test_bounded_export_fails_closed_never_drops_receipts(self):
        for _ in range(2):
            confirmed_operation(self.admin, self.ref, kind="entry")
        with patch("consultation.exports.MAX_RECEIPTS", 1), self.assertRaises(ValidationError):
            export_snapshot(actor=self.viewer)
        self.assertEqual(ExportSource.objects.get().sequence, 0)
        self.assertFalse(AuditEvent.objects.filter(action="vertente.exported").exists())
        data = decode(export_snapshot(actor=self.viewer))
        self.assertEqual(len(data["receipts"]), 2)

    def test_receipt_recovery_is_signed_bounded_and_does_not_replace_stock(self):
        confirmed_operation(self.admin, self.ref, kind="entry")
        before = list(Reference.objects.values_list("pk", "current_stock", "stock_version"))
        data = recovery_receipts(
            start=(timezone.now() - timedelta(days=30)).astimezone(timezone.get_fixed_timezone(60)),
            end=timezone.now().astimezone(timezone.get_fixed_timezone(60)),
        )
        self.assertEqual(data["format"], "vertente-receipts")
        self.assertTrue(decode(data)["coverage"]["from"].endswith("Z"))
        self.assertTrue(decode(data)["coverage"]["until"].endswith("Z"))
        self.assertNotIn("references", decode(data))
        self.assertEqual(len(decode(data)["receipts"]), 1)
        self.assertEqual(ExportSource.objects.get().sequence, 0)
        self.assertEqual(
            list(Reference.objects.values_list("pk", "current_stock", "stock_version")), before
        )
        with self.assertRaises(ValidationError):
            recovery_receipts(start=timezone.now(), end=timezone.now() - timedelta(days=1))

    def test_custom_profiles_revocation_required_password_and_forged_requests(self):
        profile = AccessProfile.objects.create(name="Exportador B", capabilities=["export"])
        actor = User.objects.create_user(
            username="b-profile", role="custom", access_profile=profile
        )
        self.client.force_login(actor)
        url = reverse("web:vertente-export")
        self.assertEqual(
            self.client.post(url, {"days": "180", "current_stock": 999999}).status_code, 200
        )
        self.ref.refresh_from_db()
        self.assertEqual(self.ref.current_stock, 120)
        profile.capabilities = []
        profile.save()
        self.assertEqual(self.client.post(url, {"days": "180"}).status_code, 403)
        with self.assertRaises(PermissionDenied):
            export_snapshot(actor=actor)
        self.admin.must_change_password = True
        self.admin.save()
        with self.assertRaises(PermissionDenied):
            export_snapshot(actor=self.admin)
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.post(url, {"days": "99999"}).status_code, 400)

    def test_main_menu_uses_stock_export_keeps_internal_excel_service(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("web:home"))
        self.assertContains(response, "Exportar Stock")
        self.assertNotContains(response, "Exportar Excel")
        self.assertContains(response, reverse("web:vertente-export"))
        self.assertEqual(
            self.client.get(reverse("web:export"), {"dataset": "stock"}).status_code, 200
        )

    def request(self):
        key = ec.generate_private_key(ec.SECP256R1())
        device = str(uuid.uuid4())
        r, s = decode_dss_signature(
            key.sign(("vertente-device-request-v1\0" + device).encode(), ec.ECDSA(hashes.SHA256()))
        )
        return {
            "format": "vertente-device-request",
            "version": 1,
            "device_id": device,
            "spki": b64(
                key.public_key().public_bytes(
                    serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
                )
            ),
            "signature": b64(r.to_bytes(32, "big") + s.to_bytes(32, "big")),
        }

    def test_device_grants_are_signed_role_bound_and_monotonic(self):
        request = self.request()
        a = decode(authorize_device(request, role="employee"))
        self.assertEqual(a["role"], "employee")
        self.assertFalse(a["can_import"])
        b = decode(authorize_device(request, role="employee", allow_import=True))
        self.assertEqual(b["revision"], 2)
        self.assertTrue(b["can_import"])
        with self.assertRaises(ValidationError):
            authorize_device(request, role="owner")
        broken = {**request, "device_id": str(uuid.uuid4())}
        with self.assertRaises(ValidationError):
            authorize_device(broken, role="employee")
        self.assertEqual(AuthorizedDevice.objects.get().revision, 2)
        self.assertEqual(Movement.objects.count(), 0)

    def test_key_rotation_proof_and_no_overwrite(self):
        call_command(
            "vertente_setup",
            directory=str(self.path / "rotation"),
            previous_key=str(self.path / "signing.pem"),
            stdout=io.StringIO(),
        )
        trust = json.loads((self.path / "rotation/origin.vatrust.json").read_text())
        proof = decode(trust["rotation"])
        self.assertEqual(proof["key"], trust["keys"][0])
        self.assertEqual(proof["source_id"], str(ExportSource.objects.get().source_id))
        with self.assertRaises(CommandError):
            call_command("vertente_setup", directory=str(self.path), stdout=io.StringIO())

    def test_additive_migration_keeps_a4_number_and_signed_pdf_bytes(self):
        from inventory.documents import verified_bytes

        m = confirmed_operation(self.admin, self.ref, kind="exit", signed=True)
        pdf = m.documents.get(kind="pdf")
        original = verified_bytes(pdf)
        number = str(m.report_number)
        before = (self.admin.password, self.ref.current_stock)
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        try:
            executor.migrate([("consultation", None)])
            MigrationExecutor(connection).migrate(latest)
            self.assertEqual(verified_bytes(pdf), original)
            self.assertEqual(str(m.report_number), number)
            self.admin.refresh_from_db()
            self.ref.refresh_from_db()
            self.assertEqual((self.admin.password, self.ref.current_stock), (before[0], 118))
        finally:
            MigrationExecutor(connection).migrate(latest)

    def test_receipts_preserve_actual_boxes_units_and_unknown_capacity(self):
        from inventory import operations
        from inventory.services import confirm_movement

        draft = operations.create_draft(actor=self.admin, kind="entry", references=[self.ref])
        line = draft.lines.get()
        draft = operations.save_draft(
            draft.pk,
            actor=self.admin,
            revision=0,
            header={"person_name": "Entrega fictícia B"},
            rows=[{"id": line.pk, "boxes": 2, "units": 3}],
        )
        reviewed, _ = operations.review_draft(draft.pk, actor=self.admin, revision=draft.revision)
        confirm_movement(
            draft.pk, actor=self.admin, review_token=reviewed.review_token, report_requested=False
        )
        self.ref.box_capacity = None
        self.ref.save(update_fields=["box_capacity"])
        confirmed_operation(self.admin, self.ref, kind="entry", units=7)
        data = decode(export_snapshot(actor=self.viewer))
        self.assertEqual(
            [(r["boxes"], r["units"], r["box_capacity"], r["bottles"]) for r in data["receipts"]],
            [(2, 3, 6, 15), (None, 7, None, 7)],
        )
        self.assertIsNone(data["references"][0]["box_capacity"])

    def test_provisioning_commands_require_private_outputs_and_fingerprint(self):
        import hashlib

        request = self.request()
        path = self.path / "device-request.json"
        path.write_text(json.dumps(request))
        fingerprint = hashlib.sha256(base64.urlsafe_b64decode(request["spki"] + "==")).hexdigest()
        out = self.path / "device.vagrant.json"
        with self.assertRaises(CommandError):
            call_command(
                "vertente_device",
                request=str(path),
                output=str(out),
                role="employee",
                confirmed_device_fingerprint="0" * 64,
                stdout=io.StringIO(),
            )
        self.assertFalse(AuthorizedDevice.objects.exists())
        call_command(
            "vertente_device",
            request=str(path),
            output=str(out),
            role="employee",
            confirmed_device_fingerprint=fingerprint,
            stdout=io.StringIO(),
        )
        original = out.read_bytes()
        self.assertFalse(decode(json.loads(original))["can_import"])
        self.assertEqual(out.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(CommandError):
            call_command(
                "vertente_device",
                request=str(path),
                output=str(out),
                role="employee",
                confirmed_device_fingerprint=fingerprint,
                stdout=io.StringIO(),
            )
        self.assertEqual(out.read_bytes(), original)
        self.assertEqual(AuthorizedDevice.objects.get().revision, 1)

    def test_recovery_command_refuses_public_existing_and_incorrect_ranges(self):
        start = (timezone.now() - timedelta(days=1)).isoformat()
        end = timezone.now().isoformat()
        for output in [
            str(Path.cwd() / "synthetic-should-not-be-created.vareceipts.json"),
            "relative.json",
        ]:
            with self.assertRaises(CommandError):
                call_command(
                    "vertente_receipts", start=start, until=end, output=output, stdout=io.StringIO()
                )
        out = self.path / "recovery.vareceipts.json"
        call_command(
            "vertente_receipts", start=start, until=end, output=str(out), stdout=io.StringIO()
        )
        self.assertEqual(json.loads(out.read_text())["format"], "vertente-receipts")
        with self.assertRaises(CommandError):
            call_command(
                "vertente_receipts", start=start, until=end, output=str(out), stdout=io.StringIO()
            )

    def test_earlier_confirmed_entry_is_included_without_inventing_packaging_or_time(self):
        from inventory.models import MovementLine

        known = Movement.objects.create(
            kind="entry", created_by=self.admin, workflow_version=0, occurred_at=timezone.now()
        )
        MovementLine.objects.create(
            movement=known,
            reference=self.ref,
            reference_name="Entrada anterior sintética",
            quantity=4,
        )
        known.status = "confirmed"
        known.save(update_fields=["status"])
        unknown = Movement.objects.create(kind="entry", created_by=self.admin, workflow_version=0)
        MovementLine.objects.create(
            movement=unknown,
            reference=self.ref,
            reference_name="Entrada sem hora sintética",
            quantity=5,
        )
        unknown.status = "confirmed"
        unknown.save(update_fields=["status"])
        data = decode(export_snapshot(actor=self.viewer))
        self.assertEqual(len(data["receipts"]), 1)
        row = data["receipts"][0]
        self.assertEqual(
            (row["movement_id"], row["bottles"], row["boxes"], row["units"]),
            (str(known.pk), 4, None, None),
        )
        self.assertIsNone(unknown.occurred_at)
