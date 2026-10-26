import base64
import json
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connections
from django.test import Client, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from inventory.models import AuditEvent, Location, Movement, MovementLine, Person, Reference
from inventory.services import confirm_movement

from .exports import export_snapshot
from .models import ExportSource
from .signing import read_key


def decode(envelope):
    return json.loads(base64.urlsafe_b64decode(envelope["payload"] + "=="))


class ConsultationExportTests(TransactionTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="gg-vertente-keys-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        call_command("vertente_setup", directory=str(self.root), stdout=open_output())
        self.keypath = str(self.root / "signing.pem")
        self.settings_override = self.settings(VERTENTE_SIGNING_KEY_FILE=self.keypath)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.admin = User.objects.create_user(username="va-admin", role="admin")
        self.viewer = User.objects.create_user(username="va-viewer")
        self.location = Location.objects.create(name="Local fictício VA")
        self.first = Reference.objects.create(
            code="VA-SYN-1",
            name="Água sintética",
            location=self.location,
            box_capacity=6,
            current_stock=18,
        )
        self.zero = Reference.objects.create(
            code="VA-SYN-2", name="Zero sintético", location=self.location, current_stock=0
        )
        Reference.objects.create(
            code="VA-SYN-3",
            name="Inativa sintética",
            location=self.location,
            current_stock=0,
            active=False,
        )

    def test_signed_complete_snapshot_includes_zero_and_unknown_capacity(self):
        envelope = export_snapshot(actor=self.viewer)
        data = decode(envelope)
        self.assertEqual(
            [r["id"] for r in data["references"]], [str(self.first.pk), str(self.zero.pk)]
        )
        self.assertEqual(data["references"][1]["bottles"], 0)
        self.assertIsNone(data["references"][1]["box_capacity"])
        raw = base64.urlsafe_b64decode(envelope["payload"] + "==")
        signature = base64.urlsafe_b64decode(envelope["signature"] + "==")
        self.assertEqual(len(signature), 64)
        read_key(self.keypath).public_key().verify(
            encode_dss_signature(int.from_bytes(signature[:32]), int.from_bytes(signature[32:])),
            b"vertente-stock-v2\0" + raw,
            ec.ECDSA(hashes.SHA256()),
        )

    def test_no_people_documents_history_or_official_stock_changes(self):
        Person.objects.create(name="Pessoa fictícia privada não exportável")
        draft = Movement.objects.create(kind="entry", created_by=self.admin)
        MovementLine.objects.create(movement=draft, reference=self.first, quantity=100)
        before = list(Reference.objects.values_list("pk", "current_stock", "stock_version"))
        data = decode(export_snapshot(actor=self.admin))
        self.assertEqual(
            set(data),
            {
                "source_id",
                "update_id",
                "sequence",
                "exported_at",
                "references",
                "receipts",
                "coverage",
            },
        )
        self.assertEqual(
            set(data["references"][0]),
            {"id", "name", "bottles", "box_capacity", "location", "sector", "minimum"},
        )
        self.assertNotIn("privada", json.dumps(data))
        self.assertEqual(
            list(Reference.objects.values_list("pk", "current_stock", "stock_version")), before
        )
        self.assertEqual(Movement.objects.count(), 1)
        self.assertEqual(data["references"][0]["bottles"], 18)

    def test_source_and_reference_ids_stay_stable_across_updates(self):
        first = decode(export_snapshot(actor=self.viewer))
        self.first.name = "Designação alterada fictícia"
        self.first.save(update_fields=["name"])
        second = decode(export_snapshot(actor=self.viewer))
        self.assertEqual(first["source_id"], second["source_id"])
        self.assertEqual(first["references"][0]["id"], second["references"][0]["id"])
        self.assertEqual(second["sequence"], first["sequence"] + 1)
        self.assertNotEqual(first["update_id"], second["update_id"])

    def test_signing_failure_rolls_back_counter_and_audit(self):
        with patch(
            "consultation.exports.signed_snapshot", side_effect=ValueError("synthetic failure")
        ):
            with self.assertRaises(ValueError):
                export_snapshot(actor=self.viewer)
        self.assertEqual(ExportSource.objects.get().sequence, 0)
        self.assertFalse(AuditEvent.objects.filter(action="vertente.exported").exists())

    def test_missing_key_and_wrong_key_type_fail_closed(self):
        for key in ("", str(self.root / "absent.pem"), str(self.root / "origin.vatrust.json")):
            with self.settings(VERTENTE_SIGNING_KEY_FILE=key), self.assertRaises(ValidationError):
                export_snapshot(actor=self.viewer)
        self.assertEqual(ExportSource.objects.get().sequence, 0)

    def test_missing_source_not_created_by_download(self):
        ExportSource.objects.all().delete()
        with self.assertRaises(ValidationError):
            export_snapshot(actor=self.viewer)
        self.assertFalse(ExportSource.objects.exists())

    def test_clock_rollback_rejected(self):
        ExportSource.objects.update(last_exported_at=timezone.now() + timezone.timedelta(days=1))
        with self.assertRaises(ValidationError):
            export_snapshot(actor=self.viewer)

    def test_view_requires_authentication_and_csrf_for_both_profiles(self):
        url = reverse("web:vertente-export")
        self.assertEqual(self.client.get(url).status_code, 302)
        for user in (self.admin, self.viewer):
            client = Client(enforce_csrf_checks=True)
            client.force_login(user)
            response = client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(client.post(url).status_code, 403)
            token = response.cookies["csrftoken"].value
            self.assertEqual(
                client.post(
                    url, HTTP_X_CSRFTOKEN=token, HTTP_ORIGIN="https://evil.invalid", secure=True
                ).status_code,
                403,
            )
            download = client.post(url, {"days": 180}, HTTP_X_CSRFTOKEN=token)
            self.assertEqual(download.status_code, 200)
            self.assertIn("attachment", download["Content-Disposition"])
            self.assertIn("no-store", download["Cache-Control"])

    def test_disabled_user_cannot_export(self):
        self.viewer.is_active = False
        with self.assertRaises(PermissionDenied):
            export_snapshot(actor=self.viewer)

    def test_key_rotation_preserves_source_and_refuses_overwrite(self):
        first = ExportSource.objects.get().source_id
        with self.assertRaises(CommandError):
            call_command("vertente_setup", directory=str(self.root), stdout=open_output())
        call_command("vertente_setup", directory=str(self.root / "rotation"), stdout=open_output())
        self.assertEqual(ExportSource.objects.get().source_id, first)
        old = json.loads((self.root / "origin.vatrust.json").read_text())
        new = json.loads((self.root / "rotation/origin.vatrust.json").read_text())
        self.assertNotEqual(old["keys"], new["keys"])
        self.assertEqual((self.root / "signing.pem").stat().st_mode & 0o777, 0o600)

    def test_export_counter_serialized_in_real_postgresql(self):
        def worker():
            try:
                return decode(export_snapshot(actor=self.viewer))["sequence"]
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: worker(), range(2)))
        self.assertEqual(sorted(results), [1, 2])

    def test_explicit_sequence_recovery_preserves_source_and_stock(self):
        source = ExportSource.objects.get()
        call_command(
            "vertente_sequence",
            source=str(source.source_id),
            after=50,
            reason="Reconciliação fictícia concluída",
            confirm_reconciled=True,
            stdout=open_output(),
        )
        data = decode(export_snapshot(actor=self.viewer))
        self.assertEqual(data["sequence"], 51)
        self.assertEqual(data["source_id"], str(source.source_id))
        self.assertEqual(data["references"][0]["bottles"], 18)
        self.assertTrue(AuditEvent.objects.filter(action="vertente.sequence_recovered").exists())

    def test_sequence_recovery_requires_confirmation_and_never_rolls_back(self):
        source = ExportSource.objects.get()
        for options in (
            {"confirm_reconciled": False, "source": str(source.source_id), "after": 10},
            {"confirm_reconciled": True, "source": "wrong-origin", "after": 10},
            {"confirm_reconciled": True, "source": str(source.source_id), "after": -1},
        ):
            with self.assertRaises(CommandError):
                call_command(
                    "vertente_sequence",
                    **options,
                    reason="Recuperação fictícia",
                    stdout=open_output(),
                )
        self.assertEqual(ExportSource.objects.get().sequence, 0)

    def test_one_snapshot_during_multireference_confirmation(self):
        movement = Movement.objects.create(
            kind="entry",
            created_by=self.admin,
            person=Person.objects.create(name="Pessoa fictícia de ensaio concorrente"),
        )
        for ref in (self.first, self.zero):
            MovementLine.objects.create(movement=movement, reference=ref, quantity=2, units=2)
        entered, release = threading.Event(), threading.Event()
        save = Reference.save

        def pause(instance, *args, **kwargs):
            outcome = save(instance, *args, **kwargs)
            if instance.pk == self.first.pk and "current_stock" in kwargs.get("update_fields", []):
                entered.set()
                if not release.wait(10):
                    raise RuntimeError("Synthetic timeout")
            return outcome

        def confirm():
            try:
                return confirm_movement(movement.pk, actor=self.admin)
            finally:
                connections.close_all()

        def export_parallel():
            try:
                return decode(export_snapshot(actor=self.viewer))
            finally:
                connections.close_all()

        with patch.object(Reference, "save", pause), ThreadPoolExecutor(max_workers=2) as pool:
            future = pool.submit(confirm)
            try:
                self.assertTrue(entered.wait(10))
                exported = pool.submit(export_parallel)
                # Export takes the same lock. It cannot observe half an operation.
                release.set()
                future.result(timeout=10)
                data = exported.result(timeout=10)
                self.assertEqual([r["bottles"] for r in data["references"]], [20, 2])
            finally:
                release.set()


def open_output():
    import io

    return io.StringIO()
