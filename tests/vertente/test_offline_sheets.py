"""Real Chromium/IndexedDB + production receiver. Synthetic keys/data only."""

import base64
import json
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import connections
from django.test import TransactionTestCase
from django.utils import timezone
from jwcrypto import jwk

from consultation.models import ExportSource, PendingSheet, SheetReceipt
from consultation.sheets import receive_sheet
from consultation.signing import signed_snapshot
from inventory.models import Document, Location, Movement, Reference
from tests.vertente.browser import VertenteBrowserBase
from tests.vertente.fixtures import grant, snapshot


class SheetBrowserMixin:
    @staticmethod
    def database_call(operation):
        # Playwright's sync driver runs a loop: never disable Django's async guard.
        def run():
            try:
                return operation()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(run).result()

    def sheets(self, method, *args):
        return self.page.evaluate(
            "async ({method,args})=>(await import('/assets/sheets.js'))[method](...args)",
            {"method": method, "args": args},
        )

    def provision_sheets(self, role="employee"):
        self.call("enroll", self.trust, self.trust["keys"][0]["key_id"])
        self.request = self.call("deviceRequest")
        if getattr(self, "database_reception", False):
            from consultation.devices import authorize_device

            self.temporary = tempfile.TemporaryDirectory()
            self.addCleanup(self.temporary.cleanup)
            path = Path(self.temporary.name) / "signing.pem"
            path.write_bytes(
                self.key.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption(),
                )
            )
            override = self.settings(VERTENTE_SIGNING_KEY_FILE=str(path))
            override.enable()
            self.addCleanup(override.disable)

            def authorize():
                ExportSource.objects.create(pk=1, source_id=self.trust["source_id"])
                return authorize_device(
                    self.request, role=role, allow_import=True, allow_sheets=True
                )

            authorization = self.database_call(authorize)
        else:
            authorization = grant(self.key, self.trust, self.request, role=role, can_import=True)
        self.authorization = authorization
        self.call("activate", authorization)
        if role == "owner":
            self.call("unlock", self.password)
        self.call("importSnapshot", snapshot(self.key, self.trust))
        self.recipient = jwk.JWK.generate(kty="RSA", size=3072)
        recipient = signed_snapshot(
            {
                "source_id": self.trust["source_id"],
                "jwk": json.loads(self.recipient.export_public()),
                "key_id": self.recipient.thumbprint(),
            },
            self.key,
            kind="vertente-sheet-recipient",
            version=1,
        )
        g = json.loads(base64.urlsafe_b64decode(authorization["payload"] + "=="))
        if getattr(self, "database_reception", False):
            (Path(self.temporary.name) / "pending-reception.pem").write_bytes(
                self.recipient.export_to_pem(private_key=True, password=None)
            )
            output = Path(self.temporary.name) / "permission.json"
            self.database_call(
                lambda: call_command(
                    "pending_sheet_authorize", device=self.request["device_id"], output=str(output)
                )
            )
            permission = json.loads(output.read_text())
        else:
            permission = signed_snapshot(
                {
                    "source_id": self.trust["source_id"],
                    "device_id": self.request["device_id"],
                    "device_key_id": g["device_key_id"],
                    "authorization_revision": g["revision"],
                    "expires_at": g["expires_at"],
                    "sheets_allowed": True,
                },
                self.key,
                kind="vertente-sheet-authorization",
                version=1,
            )
        self.permission = permission
        self.sheets("configureSheets", "permission", permission)
        self.sheets("configureSheets", "recipient", recipient)
        self.sheets("unlockSheets", self.password)
        self.refresh()

    def new_sheet(self, kind="entry", person="Pessoa fictícia de ensaio", lines=None):
        id = self.sheets("createSheet", kind)
        self.sheets(
            "editSheet",
            id,
            1,
            {
                "person": person,
                "physical_date": "2026-10-01",
                "notes": "Observação privada sintética",
                "lines": lines
                if lines is not None
                else [
                    {"reference_id": "1", "boxes": 2, "units": 3},
                    {"reference_id": "2", "boxes": None, "units": 4},
                ],
            },
        )
        return id


class OfflineSheetBrowserTests(SheetBrowserMixin, VertenteBrowserBase):
    def test_blank_fields_explicit_zero_and_capacity_survive_stock_refresh_and_reload(self):
        self.provision_sheets()
        id = self.sheets("createSheet", "entry")
        self.sheets(
            "editSheet",
            id,
            1,
            {
                "person": "",
                "physical_date": "",
                "notes": "",
                "lines": [{"reference_id": "1", "boxes": None, "units": 0}],
            },
        )
        refs = json.loads(
            base64.urlsafe_b64decode(snapshot(self.key, self.trust)["payload"] + "==")
        )["references"]
        refs[0]["box_capacity"] = 12
        self.call("importSnapshot", snapshot(self.key, self.trust, sequence=2, references=refs))
        self.page.reload()
        self.page.get_by_role("heading", name="Última atualização de stock", exact=True).wait_for()
        self.sheets("unlockSheets", self.password)
        s = self.sheets("sheetState")["sheets"][0]
        self.assertEqual((s["id"], s["revision"], s["person"], s["physical_date"]), (id, 2, "", ""))
        self.assertEqual(s["lines"][0]["boxes"], None)
        self.assertEqual(s["lines"][0]["units"], 0)
        self.assertEqual(s["lines"][0]["box_capacity"], 6)

    def test_idle_lock_hides_person_and_preserves_encrypted_draft(self):
        self.provision_sheets()
        id = self.new_sheet()
        self.page.clock.install()
        self.page.clock.fast_forward(300001)
        self.assertFalse(self.sheets("sheetState")["unlocked"])
        self.assertEqual(self.sheets("sheetState")["sheets"], [])
        self.sheets("unlockSheets", self.password)
        self.assertEqual(self.sheets("sheetState")["sheets"][0]["id"], id)

    def test_employee_touch_flow_offline_blank_fields_save_reopen_and_download(self):
        from tests.vertente.fixtures import wait_offline_shell

        self.provision_sheets()
        wait_offline_shell(self.page)
        self.context.set_offline(True)
        self.page.get_by_role("button", name="Preparar folhas", exact=True).click()
        self.page.get_by_role("button", name="Preparar entrada", exact=True).click()
        self.page.get_by_label("Quem entregou", exact=True).fill("Pessoa fictícia de ensaio")
        search = self.page.get_by_label("Pesquisar referência para a folha", exact=True)
        search.fill("AGUA")
        self.page.get_by_role("button", name="1 · Água de Ensaio", exact=True).click()
        self.assertEqual(self.page.get_by_label("Caixas", exact=True).input_value(), "")
        self.assertEqual(self.page.get_by_label("Garrafas soltas", exact=True).input_value(), "")
        self.page.get_by_label("Caixas", exact=True).fill("2")
        self.page.get_by_label("Garrafas soltas", exact=True).fill("3")
        search.fill("CORACAO")
        self.page.get_by_role("button", name="2 · Coração Zero", exact=True).click()
        self.assertTrue(self.page.get_by_label("Caixas", exact=True).nth(1).is_disabled())
        self.page.get_by_label("Garrafas soltas", exact=True).nth(1).fill("4")
        self.page.get_by_role("button", name="Guardar rascunho", exact=True).click()
        self.page.get_by_role("status").filter(has_text="Rascunho guardado").wait_for()
        self.page.reload()
        self.page.get_by_role("button", name="Preparar folhas", exact=True).click()
        self.page.get_by_label("Frase-passe dos rascunhos", exact=True).fill(self.password)
        self.page.get_by_role("button", name="Desbloquear rascunhos", exact=True).click()
        self.page.get_by_role("button", name="Abrir folha", exact=False).click()
        self.assertEqual(self.page.get_by_label("Caixas", exact=True).first.input_value(), "2")
        self.page.get_by_role("button", name="Rever e exportar folha", exact=True).click()
        with self.page.expect_download() as exported:
            self.page.get_by_role("button", name="Confirmar", exact=True).click()
        wire = json.loads(Path(exported.value.path()).read_text())
        self.assertEqual(wire["format"], "vertente-pending-sheet")
        self.assertNotIn("Pessoa fictícia", json.dumps(wire))
        self.page.get_by_role("status").filter(has_text="ainda não estão comprovadas").wait_for()
        self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"), 393)

    def test_drafts_are_encrypted_separate_from_owner_and_employee_cannot_read_orders(self):
        self.provision_sheets()
        id = self.new_sheet("exit")
        before = self.call("state")["copy"]
        stored = self.page.evaluate(
            "async()=>{const m=await import('/assets/store.js');const r=await m.raw();return JSON.stringify([r.meta,r.sheetVault,r.vault]);}"
        )
        self.assertNotIn("Pessoa fictícia", stored)
        self.assertNotIn("Observação privada", stored)
        for method, args in [
            ("unlock", [self.password]),
            ("backupPreferences", [self.password]),
            ("createOrder", ["1", {}]),
        ]:
            with self.assertRaises(Exception):
                self.call(method, *args)
        self.assertEqual(self.call("state")["copy"], before)
        self.sheets("lockSheets")
        self.assertEqual(self.sheets("sheetState")["sheets"], [])
        with self.assertRaises(Exception):
            self.sheets("unlockSheets", "Incorrect-secret-phrase-for-test")
        self.sheets("unlockSheets", self.password)
        self.assertEqual(self.sheets("sheetState")["sheets"][0]["id"], id)

    def test_owner_orders_fifo_backup_and_sheets_remain_independent(self):
        self.provision_sheets("owner")
        self.call("createOrder", "1", {"units": 8})
        self.new_sheet()
        self.assertEqual(len(self.call("state")["orders"]), 1)
        backup = self.call("backupPreferences", self.password)
        self.assertEqual(backup["format"], "vertente-owner-encrypted")
        self.sheets("lockSheets")
        self.assertEqual(len(self.call("state")["orders"]), 1)
        self.call("lock")
        self.assertFalse(self.sheets("sheetState")["unlocked"])

    def test_export_is_immutable_identical_retry_and_cancel_never_changes_stock(self):
        self.provision_sheets()
        id = self.new_sheet()
        before = self.call("state")["copy"]
        file = self.sheets("exportSheet", id, 2)
        self.assertEqual(self.sheets("exportSheet", id, 2), file)
        with self.assertRaises(Exception):
            self.sheets("editSheet", id, 2, {}, True)
        cancelled = self.sheets("createSheet", "exit")
        self.sheets("editSheet", cancelled, 1, {}, True)
        with self.assertRaises(Exception):
            self.sheets("exportSheet", cancelled, 2)
        self.assertEqual(self.call("state")["copy"], before)

    def test_empty_zero_negative_unknown_capacity_and_limits(self):
        self.provision_sheets()
        id = self.sheets("createSheet", "exit")
        with self.assertRaises(Exception):
            self.sheets("exportSheet", id, 1)
        for boxes, units, ref in [
            (None, None, "1"),
            (0, 0, "1"),
            (-1, 2, "1"),
            (1, None, "2"),
            (1.5, 0, "1"),
            (2147483647, 0, "1"),
        ]:
            with self.subTest(boxes=boxes, units=units):
                draft = self.sheets("createSheet", "entry")
                try:
                    self.sheets(
                        "editSheet",
                        draft,
                        1,
                        {
                            "person": "Pessoa fictícia",
                            "physical_date": "2026-10-01",
                            "notes": "",
                            "lines": [{"reference_id": ref, "boxes": boxes, "units": units}],
                        },
                    )
                    self.sheets("exportSheet", draft, 2)
                except Exception:
                    continue
                self.fail("Invalid or incomplete quantity exported")
        self.assertTrue(all(s["state"] == "draft" for s in self.sheets("sheetState")["sheets"]))

    def test_backup_restore_preserves_exports_and_refuses_conflicting_rollback(self):
        self.provision_sheets()
        id = self.new_sheet()
        earlier = self.sheets("backupSheets", self.password)
        file = self.sheets("exportSheet", id, 2)
        with self.assertRaises(Exception):
            self.sheets("restoreSheets", earlier, self.password)
        backup = self.sheets("backupSheets", self.password)
        self.sheets("restoreSheets", backup, self.password)
        self.assertEqual(self.sheets("exportSheet", id, 2), file)
        with self.assertRaises(Exception):
            self.sheets("restoreSheets", backup, "Incorrect-secret-phrase-for-test")
        self.page.evaluate("""async()=>{const db=await(await import('/assets/store.js')).database();
          await new Promise((ok,no)=>{const tx=db.transaction('vault','readwrite');tx.objectStore('vault').delete('sheets');tx.oncomplete=ok;tx.onabort=no;});}""")
        self.sheets("lockSheets")
        self.sheets("unlockSheets", self.password)
        self.assertEqual(self.sheets("sheetState")["sheets"], [])
        self.sheets("restoreSheets", backup, self.password)
        self.assertEqual(self.sheets("exportSheet", id, 2), file)

    def test_tampered_permission_recipient_and_wrong_device_are_rejected(self):
        self.provision_sheets()
        altered = {**self.permission, "signature": "AAAA"}
        with self.assertRaises(Exception):
            self.sheets("configureSheets", "permission", altered)
        with self.assertRaises(Exception):
            self.call(
                "activate", self.authorization if hasattr(self, "authorization") else {}, "owner"
            )
        self.assertTrue(self.sheets("sheetState")["allowed"])
        wrong_source = signed_snapshot(
            {
                "source_id": "00000000-0000-4000-8000-000000000001",
                "jwk": json.loads(self.recipient.export_public()),
                "key_id": self.recipient.thumbprint(),
            },
            self.key,
            kind="vertente-sheet-recipient",
            version=1,
        )
        with self.assertRaises(Exception):
            self.sheets("configureSheets", "recipient", wrong_source)
        data = json.loads(base64.urlsafe_b64decode(self.permission["payload"] + "=="))
        for change in [
            {"device_id": "00000000-0000-4000-8000-000000000001"},
            {"sheets_allowed": False},
            {"authorization_revision": 99},
            {"expires_at": "2020-01-01T00:00:00.000Z"},
        ]:
            wrong = signed_snapshot(
                {**data, **change}, self.key, kind="vertente-sheet-authorization", version=1
            )
            with self.assertRaises(Exception):
                self.sheets("configureSheets", "permission", wrong)
        self.assertTrue(self.sheets("sheetState")["allowed"])

    def test_export_failure_does_not_freeze_draft_and_concurrent_exports_have_one_winner(self):
        self.provision_sheets()
        id = self.new_sheet()
        result = self.page.evaluate(
            """async id=>{const m=await import('/assets/sheets.js');
          const original=crypto.subtle.encrypt.bind(crypto.subtle);crypto.subtle.encrypt=async()=>{throw Error('synthetic encryption failure')};
          try{await m.exportSheet(id,2);return false;}catch(_){return true;}finally{crypto.subtle.encrypt=original;}}""",
            id,
        )
        self.assertTrue(result)
        self.assertEqual(self.sheets("sheetState")["sheets"][0]["state"], "draft")
        outcomes = self.page.evaluate(
            """async id=>{const m=await import('/assets/sheets.js');return(await Promise.allSettled([m.exportSheet(id,2),m.exportSheet(id,2)])).map(r=>r.status)}""",
            id,
        )
        self.assertEqual(outcomes.count("fulfilled"), 1)
        self.assertEqual(outcomes.count("rejected"), 1)

    def test_visible_names_and_profile_choice_do_not_grant_privileges(self):
        self.assertEqual(
            self.page.get_by_label("Utilizador autorizado").locator("option").all_text_contents(),
            ["Fábio", "Daniel"],
        )
        self.provision_sheets("employee")
        self.page.get_by_role("button", name="Atualizações e cópias", exact=True).click()
        self.page.get_by_text("Utilizador: Daniel", exact=False).wait_for()
        self.assertTrue(self.page.get_by_role("button", name="Encomendas", exact=True).is_hidden())
        self.assertEqual(self.call("state")["grant"]["role"], "employee")


class SheetInteroperabilityTests(SheetBrowserMixin, VertenteBrowserBase, TransactionTestCase):
    databases = {"default"}
    database_reception = True
    browser_per_test = True

    def test_browser_exports_both_types_and_real_receiver_preserves_stock_and_originals(self):
        self.provision_sheets()
        files = []
        for kind in ["entry", "exit"]:
            id = self.new_sheet(kind)
            exported = self.sheets("exportSheet", id, 2)
            raw = self.page.evaluate("file=>JSON.stringify(file)", exported).encode()
            files.append((kind, exported, raw))
        self.context.close()
        self.stop_browser()
        admin = get_user_model().objects.create_user(
            username="synthetic-sheet-receiver", role="admin"
        )
        Reference.objects.create(
            pk=1,
            code="SYNTHETIC-1",
            name="Água de Ensaio",
            current_stock=12,
            location=Location.objects.create(name="Local sintético"),
            box_capacity=6,
        )
        for kind, exported, raw in files:
            receipt = receive_sheet(raw, actor=admin)
            self.assertEqual(receipt.outcome, "pending")
            self.assertEqual(bytes(receipt.original), raw)
            self.assertEqual(receipt.sheet.payload["kind"], kind)
            self.assertEqual(receipt.sheet.payload["lines"][0]["boxes"], 2)
            self.assertEqual(receipt.sheet.payload["lines"][0]["units"], 3)
            self.assertEqual(receive_sheet(raw, actor=admin).outcome, "duplicate")
            parts = exported["jwe"].split(".")
            for index in [1, 3, 4]:
                tampered = parts.copy()
                tampered[index] = ("A" if tampered[index][0] != "A" else "B") + tampered[index][1:]
                with self.assertRaises(ValidationError):
                    receive_sheet(
                        json.dumps({**exported, "jwe": ".".join(tampered)}).encode(), actor=admin
                    )
        self.assertEqual(Reference.objects.get(pk=1).current_stock, 12)
        self.assertEqual(Reference.objects.count(), 1)
        self.assertEqual(PendingSheet.objects.count(), 2)
        self.assertEqual(SheetReceipt.objects.count(), 4)
        self.assertEqual(Movement.objects.count(), 0)
        self.assertEqual(Document.objects.count(), 0)

    def test_export_from_now_unauthorized_or_revoked_device_is_refused_by_real_receiver(self):
        from consultation.models import AuthorizedDevice

        self.provision_sheets()
        id = self.new_sheet()
        exported = json.dumps(self.sheets("exportSheet", id, 2)).encode()
        self.context.close()
        self.stop_browser()
        admin = get_user_model().objects.create_user(
            username="synthetic-sheet-receiver", role="admin"
        )
        device = AuthorizedDevice.objects.get(pk=self.request["device_id"])
        device.sheets_allowed = False
        device.save(update_fields=["sheets_allowed"])
        with self.assertRaises(ValidationError):
            receive_sheet(exported, actor=admin)
        device.sheets_allowed = True
        device.revoked_at = timezone.now()
        device.save(update_fields=["sheets_allowed", "revoked_at"])
        with self.assertRaises(ValidationError):
            receive_sheet(exported, actor=admin)
        device.revoked_at = None
        device.expires_at = timezone.now() - timedelta(days=1)
        device.save(update_fields=["revoked_at", "expires_at"])
        with self.assertRaises(ValidationError):
            receive_sheet(exported, actor=admin)
        device.expires_at = timezone.now() + timedelta(days=1)
        device.revision += 1
        device.save(update_fields=["expires_at", "revision"])
        with self.assertRaises(ValidationError):
            receive_sheet(exported, actor=admin)
        self.assertFalse(PendingSheet.objects.exists())
        self.assertFalse(Movement.objects.exists())
