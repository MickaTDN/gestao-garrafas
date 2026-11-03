import hashlib
import uuid

from consultation.signing import signed_snapshot
from tests.vertente import test_offline_sheets as offline
from tests.vertente.browser import VertenteBrowserBase
from tests.vertente.fixtures import wait_offline_shell


class WifiDeliveryBrowserTests(offline.SheetBrowserMixin, VertenteBrowserBase):
    def setup_delivery(self, role="employee"):
        self.provision_sheets(role)
        self.id = self.new_sheet()
        self.file = self.sheets("exportSheet", self.id, 2)
        policy = signed_snapshot(
            {
                "source_id": self.trust["source_id"],
                "receiver_origin": "https://receiver.synthetic.test:8446",
                "stock_origin": self.url,
            },
            self.key,
            kind="vertente-sheet-transport",
            version=1,
        )
        self.sheets("configureTransport", policy, True)
        self.changes = {}
        self.outcomes = ["pending", "duplicate"]
        self.requests = []

        def acknowledge(request):
            self.requests.append(request)
            data = {
                "source_id": self.trust["source_id"],
                "device_id": self.request["device_id"],
                "sheet_id": self.id,
                "revision": 2,
                "file_sha256": hashlib.sha256(request["body"].encode()).hexdigest(),
                "receipt_id": str(uuid.uuid4()),
                "outcome": self.outcomes.pop(0) if self.outcomes else "duplicate",
                "received_at": "2026-11-02T12:00:00.000Z",
                "request_id": request["request_id"],
                **self.changes,
            }
            return signed_snapshot(data, self.key, kind="vertente-sheet-receipt", version=1)

        self.page.expose_function("syntheticAck", acknowledge)
        self.install_fetch()

    def install_fetch(self):
        self.page.evaluate(
            """()=>{window.fetch=async(url,options)=>new Response(JSON.stringify(await window.syntheticAck({body:options.body,request_id:options.headers['X-GVA-Request']})),{status:200,headers:{'content-type':'application/json'}});} """
        )

    def test_both_profiles_preserve_identity_manual_export_and_verified_duplicate_states(self):
        self.setup_delivery("owner")
        before = self.call("state")["copy"]
        self.sheets("sendSheet", self.id, 2)
        self.assertEqual(self.sheets("sheetState")["deliveries"][self.id]["state"], "received")
        self.sheets("sendSheet", self.id, 2)
        self.assertEqual(self.sheets("sheetState")["deliveries"][self.id]["state"], "duplicate")
        self.assertEqual(self.sheets("exportSheet", self.id, 2), self.file)
        self.assertEqual(self.requests[0]["body"], self.requests[1]["body"])
        self.assertNotEqual(self.requests[0]["request_id"], self.requests[1]["request_id"])
        self.assertEqual(self.call("state")["copy"], before)

    def test_invalid_nonce_device_hash_or_signature_never_claims_receipt(self):
        self.setup_delivery()
        for changed in [
            {"request_id": str(uuid.uuid4())},
            {"device_id": str(uuid.uuid4())},
            {"file_sha256": "0" * 64},
            {"revision": 99},
            {"source_id": str(uuid.uuid4())},
        ]:
            self.changes = changed
            with self.assertRaises(Exception):
                self.sheets("sendSheet", self.id, 2)
            self.assertEqual(self.sheets("sheetState")["deliveries"][self.id]["state"], "failure")
        self.changes = {}
        self.page.evaluate(
            "()=>{window.fetch=async()=>new Response(JSON.stringify({format:'vertente-sheet-receipt',version:1,signature:'forged'}),{status:200,headers:{'content-type':'application/json'}});}"
        )
        with self.assertRaises(Exception):
            self.sheets("sendSheet", self.id, 2)
        self.assertEqual(self.sheets("sheetState")["deliveries"][self.id]["state"], "failure")

    def test_offline_failure_survives_reload_and_retry_keeps_same_file(self):
        self.setup_delivery()
        wait_offline_shell(self.page)
        self.context.set_offline(True)
        with self.assertRaises(Exception):
            self.sheets("sendSheet", self.id, 2)
        self.page.reload()
        self.page.get_by_role("heading", name="Última atualização de stock", exact=True).wait_for()
        self.sheets("unlockSheets", self.password)
        self.assertEqual(self.sheets("sheetState")["deliveries"][self.id]["state"], "failure")
        self.context.set_offline(False)
        self.install_fetch()
        self.sheets("sendSheet", self.id, 2)
        self.assertEqual(self.sheets("exportSheet", self.id, 2), self.file)
        self.assertEqual(self.sheets("sheetState")["deliveries"][self.id]["state"], "received")

    def test_failure_after_success_does_not_erase_valid_proof_and_backup_preserves_it(self):
        self.setup_delivery()
        self.sheets("sendSheet", self.id, 2)
        proof = self.sheets("sheetState")["deliveries"][self.id]
        self.page.evaluate(
            "()=>{window.fetch=async()=>{throw new TypeError('synthetic response loss')};}"
        )
        with self.assertRaises(Exception):
            self.sheets("sendSheet", self.id, 2)
        after = self.sheets("sheetState")["deliveries"][self.id]
        self.assertEqual(after["state"], "received")
        self.assertEqual(after["receipt_id"], proof["receipt_id"])
        backup = self.sheets("backupSheets", self.password)
        self.sheets("restoreSheets", backup, self.password)
        self.assertEqual(
            self.sheets("sheetState")["deliveries"][self.id]["receipt_id"], proof["receipt_id"]
        )
        stored = self.page.evaluate(
            "async()=>JSON.stringify((await(await import('/assets/store.js')).raw()).sheetVault)"
        )
        self.assertNotIn(proof["receipt_id"], stored)
        self.assertNotIn("Pessoa fictícia", stored)

    def test_concurrent_attempts_and_explicit_disable_preserve_local_vault(self):
        self.setup_delivery()
        outcomes = self.page.evaluate(
            """async id=>{const m=await import('/assets/sheets.js');return(await Promise.allSettled([m.sendSheet(id,2),m.sendSheet(id,2)])).map(r=>r.status)}""",
            self.id,
        )
        self.assertEqual(outcomes.count("fulfilled"), 1)
        self.assertEqual(self.sheets("sheetState")["sheets"][0]["revision"], 2)
        self.sheets("disableTransport")
        with self.assertRaises(Exception):
            self.sheets("sendSheet", self.id, 2)
        self.assertEqual(self.sheets("exportSheet", self.id, 2), self.file)

    def test_mobile_interface_shows_verified_reception_without_official_confirmation(self):
        self.setup_delivery()
        self.page.get_by_role("button", name="Preparar folhas", exact=True).click()
        self.page.get_by_role("button", name="Abrir folha " + self.id, exact=True).click()
        self.page.get_by_role("button", name="Enviar pelo Wi-Fi autorizado", exact=True).click()
        self.page.get_by_role("status").filter(has_text="Comprovativo verificado").wait_for()
        self.page.get_by_text("Recebido · não é confirmação oficial", exact=True).wait_for()
        self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"), 393)
