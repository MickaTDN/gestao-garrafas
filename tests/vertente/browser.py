"""Synthetic isolated-origin functional tests; real trusted TLS is tested separately."""

import copy
import functools
import json
import os
import shutil
import threading
from datetime import datetime, timedelta, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from django.test import SimpleTestCase
from playwright.sync_api import sync_playwright

from tests.vertente.fixtures import fixture, snapshot, wait_offline_shell

ROOT = Path(__file__).resolve().parents[2]


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def end_headers(self):
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; worker-src 'self'; manifest-src 'self'; form-action 'none'; base-uri 'none'; object-src 'none'",
        )
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()


class VertenteBrowserTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.server = ThreadingHTTPServer(
            ("127.0.0.1", 0), functools.partial(Handler, directory=str(ROOT / "vertente"))
        )
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.addClassCleanup(cls.server.server_close)
        cls.addClassCleanup(cls.server.shutdown)
        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)
        cls.browser = cls.playwright.chromium.launch(
            executable_path=os.getenv("CHROMIUM_PATH") or shutil.which("chromium"),
            headless=True,
            args=["--no-sandbox"],
        )
        cls.addClassCleanup(cls.browser.close)
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    def setUp(self):
        self.context = self.browser.new_context(
            viewport={"width": 393, "height": 851},
            is_mobile=True,
            has_touch=True,
            accept_downloads=True,
        )
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.page.set_default_timeout(10000)
        self.key, self.trust = fixture()
        self.password = "Synthetic-owner-only-vault-phrase-35"
        self.page.goto(self.url)
        self.page.locator("#trust-file").wait_for()

    def call(self, method, *args):
        return self.page.evaluate(
            "async ({method,args})=>(await import('/assets/store.js'))[method](...args)",
            {"method": method, "args": args},
        )

    def provision(self, role="owner", can_import=None, import_first=True, now=None):
        from tests.vertente.fixtures import grant

        self.call("enroll", self.trust, self.trust["keys"][0]["key_id"])
        self.request = self.call("deviceRequest")
        self.authorization = grant(
            self.key, self.trust, self.request, role=role, can_import=can_import, now=now
        )
        self.call("activate", self.authorization)
        if role == "owner":
            self.call("unlock", self.password)
        if import_first:
            self.call("importSnapshot", snapshot(self.key, self.trust))
        if import_first:
            self.refresh()
        else:
            self.page.get_by_role("button", name="Stock", exact=True).click()
            self.page.get_by_role(
                "heading", name="Importe a primeira cópia de stock", exact=True
            ).wait_for()

    def refresh(self):
        self.page.get_by_role("button", name="Stock", exact=True).click()
        self.page.get_by_role("heading", name="Última atualização de stock", exact=True).wait_for()
        self.page.locator("#content[aria-busy]").wait_for(state="detached")

    def new_order(self, units=None, ref="1", **fields):
        self.call("createOrder", ref, {"boxes": None, "units": units, **fields})
        return self.call("state")["orders"][-1]

    def after(self, order, seconds=1):
        return datetime.fromisoformat(order["created_at"].replace("Z", "+00:00")) + timedelta(
            seconds=seconds
        )

    def import_receipts(self, receipts, sequence=2, **changes):
        from tests.vertente.fixtures import stamp

        latest = max(
            [datetime.fromisoformat(r["confirmed_at"].replace("Z", "+00:00")) for r in receipts],
            default=datetime.now(timezone.utc),
        ) + timedelta(seconds=1)
        changes.setdefault("exported_at", stamp(latest))
        self.last_snapshot = snapshot(
            self.key, self.trust, sequence=sequence, receipts=receipts, **changes
        )
        return self.call("importSnapshot", self.last_snapshot)

    def test_owner_onboarding_ui_original_icon_mobile_and_name_only_search(self):
        from tests.vertente.fixtures import grant

        self.page.get_by_label("Origem autorizada (.vatrust.json)", exact=True).set_input_files(
            {
                "name": "origin.vatrust.json",
                "mimeType": "application/json",
                "buffer": json.dumps(self.trust).encode(),
            }
        )
        self.page.get_by_label(
            "Fingerprint da origem confirmado pela informática", exact=True
        ).fill(self.trust["keys"][0]["key_id"])
        self.page.get_by_role("button", name="Instalar origem autorizada", exact=True).click()
        self.page.get_by_role("status").filter(has_text="Origem autorizada guardada").wait_for()
        with self.page.expect_download() as d:
            self.page.get_by_role(
                "button", name="Criar / exportar pedido do dispositivo", exact=True
            ).click()
        request = json.loads(Path(d.value.path()).read_text())
        self.page.get_by_role("status").filter(
            has_text="Pedido de autorização preparado"
        ).wait_for()
        authorization = grant(self.key, self.trust, request)
        self.page.get_by_label("Autorização assinada do dispositivo", exact=True).set_input_files(
            {
                "name": "device.vagrant.json",
                "mimeType": "application/json",
                "buffer": json.dumps(authorization).encode(),
            }
        )
        self.page.get_by_role("button", name="Ativar dispositivo", exact=True).click()
        self.page.get_by_role("status").filter(has_text="Dispositivo autorizado").wait_for()
        self.page.get_by_label("Frase-passe do cofre", exact=True).fill(self.password)
        self.page.get_by_label("Repetir frase-passe do cofre", exact=True).fill(self.password)
        self.page.get_by_role("button", name="Criar cofre", exact=True).click()
        self.page.get_by_role("status").filter(has_text="Cofre desbloqueado").wait_for()
        self.page.get_by_role("button", name="Atualizações e cópias", exact=True).click()
        self.page.get_by_label(
            "Ficheiro de atualização de stock ou recuperação", exact=True
        ).set_input_files(
            {
                "name": "stock.json",
                "mimeType": "application/json",
                "buffer": json.dumps(snapshot(self.key, self.trust)).encode(),
            }
        )
        self.page.get_by_role("button", name="Importar Stock", exact=True).click()
        self.page.get_by_role("status").filter(has_text="3 referências importadas").wait_for()
        self.refresh()
        self.assertEqual(self.page.title(), "Stock Vertente Aveludada")
        search = self.page.get_by_label("Pesquisar pelo nome", exact=True)
        search.fill("AGUA")
        self.assertEqual(self.page.locator(".reference").count(), 1)
        search.fill("cOrAcAo")
        self.assertEqual(self.page.locator(".reference").count(), 1)
        self.page.get_by_role("button", name="Coração Zero", exact=True).click()
        self.page.get_by_text("Setor: Sem setor definido", exact=True).wait_for()
        self.page.get_by_text(
            "0 garrafas · capacidade da caixa não definida", exact=True
        ).wait_for()
        self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"), 393)
        if root := os.getenv("STOCK_SCREENSHOTS"):
            Path(root).mkdir(parents=True, exist_ok=True)
            self.page.screenshot(path=str(Path(root) / "stock-mobile.png"), full_page=True)
        self.page.set_viewport_size({"width": 1366, "height": 900})
        self.refresh()
        search = self.page.get_by_label("Pesquisar pelo nome", exact=True)
        search.fill("VA-001")
        self.assertEqual(self.page.locator(".reference").count(), 0)
        if root := os.getenv("STOCK_SCREENSHOTS"):
            search.fill("")
            self.page.screenshot(path=str(Path(root) / "stock-desktop.png"), full_page=True)
        self.assertEqual(self.context.cookies(), [])

    def test_employee_without_import_cannot_access_owner_service_or_backup(self):
        self.provision("employee", can_import=False, import_first=False)
        for method, args in [
            ("unlock", [self.password]),
            ("createOrder", ["1", {}]),
            ("backupPreferences", [self.password]),
            ("restorePreferences", [{}]),
            ("importSnapshot", [snapshot(self.key, self.trust)]),
        ]:
            with self.assertRaises(Exception, msg=method):
                self.call(method, *args)
        self.page.reload()
        self.page.get_by_role("button", name="Atualizações e cópias", exact=True).click()
        self.page.get_by_text(
            "A informática não autorizou importações neste dispositivo.", exact=True
        ).wait_for()
        self.assertTrue(self.page.locator("#nav-orders").is_hidden())
        self.assertEqual(
            self.page.get_by_role("button", name="Importar Stock", exact=True).count(), 0
        )
        self.assertEqual(self.page.get_by_text("Stock baixo", exact=True).count(), 0)

    def test_authorized_employee_imports_offline_but_no_owner_controls(self):
        self.provision("employee", can_import=True)
        self.assertEqual(len(self.call("state")["copy"]["data"]["references"]), 3)
        self.context.set_offline(True)
        self.page.reload()
        self.page.get_by_role("heading", name="Última atualização de stock", exact=True).wait_for()
        self.call("importSnapshot", snapshot(self.key, self.trust, sequence=2))
        self.assertEqual(self.call("state")["watermark"]["sequence"], 2)
        self.assertEqual(self.call("state")["orders"], [])
        with self.assertRaises(Exception):
            self.call("createOrder", "1", {})
        self.assertTrue(self.page.locator("#nav-orders").is_hidden())

    def test_signed_device_grant_wrong_origin_device_expiry_replay_and_forgery(self):
        from tests.vertente.fixtures import grant

        self.provision("employee", can_import=True)
        with self.assertRaises(Exception):
            self.call("activate", self.authorization)
        for file in [
            grant(
                self.key, self.trust, {**self.request, "device_id": str(__import__("uuid").uuid4())}
            ),
            grant(
                self.key,
                self.trust,
                self.request,
                now=datetime.now(timezone.utc) - timedelta(days=366),
            ),
            grant(*fixture(), self.request),
        ]:
            with self.assertRaises(Exception):
                self.call("activate", file)
        forged = copy.deepcopy(self.authorization)
        data = json.loads(__import__("base64").urlsafe_b64decode(forged["payload"] + "=="))
        data["role"] = "owner"
        forged["payload"] = (
            __import__("base64").urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()
        )
        with self.assertRaises(Exception):
            self.call("activate", forged)
        changed = grant(
            self.key, self.trust, self.request, role="employee", can_import=False, revision=2
        )
        self.call("activate", changed)
        with self.assertRaises(Exception):
            self.call("importSnapshot", snapshot(self.key, self.trust, sequence=2))
        self.assertEqual(self.call("state")["grant"]["role"], "employee")

    def test_vault_is_encrypted_password_not_stored_and_owner_lock(self):
        self.provision()
        self.new_order(12, note="PRIVATE-OWNER-OBSERVATION-SYNTHETIC")
        raw = self.page.evaluate(
            "async()=>{const m=await import('/assets/store.js');const db=await m.database();return await new Promise((ok,no)=>{const tx=db.transaction(['meta','vault'],'readonly');let out=[];for(const n of ['meta','vault']){const r=tx.objectStore(n).getAll();r.onsuccess=()=>out.push([n,r.result]);}tx.oncomplete=()=>ok(JSON.stringify(out));tx.onerror=no;});}"
        )
        self.assertNotIn("PRIVATE-OWNER-OBSERVATION-SYNTHETIC", raw)
        self.assertNotIn(self.password, raw)
        self.call("lock")
        self.assertEqual(self.call("state")["orders"], [])
        with self.assertRaises(Exception):
            self.call("unlock", "Incorrect-owner-passphrase-xyz")
        self.call("unlock", self.password)
        self.assertEqual(len(self.call("state")["orders"]), 1)
        self.page.reload()
        self.page.get_by_role("button", name="Desbloquear", exact=True).wait_for()
        self.assertEqual(self.call("state")["orders"], [])
        self.assertFalse(
            self.page.evaluate(
                "async()=>{const db=await(await import('/assets/store.js')).database();const d=await new Promise(ok=>{const r=db.transaction('meta').objectStore('meta').get('device');r.onsuccess=()=>ok(r.result.value);});return d.privateKey.extractable;}"
            )
        )

    def test_orders_any_stock_optional_quantity_blank_fields_and_zero_rejection(self):
        self.provision()
        refs = json.loads(
            __import__("base64").urlsafe_b64decode(snapshot(self.key, self.trust)["payload"] + "==")
        )["references"]
        refs[2]["bottles"] = 60
        self.call("importSnapshot", snapshot(self.key, self.trust, sequence=2, references=refs))
        self.refresh()
        self.page.get_by_role("button", name="Tinto Fictício", exact=True).click()
        self.page.get_by_role("button", name="Criar encomenda", exact=True).click()
        self.assertEqual(self.page.get_by_label("Caixas", exact=True).input_value(), "")
        self.assertEqual(self.page.get_by_label("Garrafas soltas", exact=True).input_value(), "")
        self.page.get_by_role("button", name="Guardar encomenda", exact=True).click()
        self.page.get_by_role("status").filter(has_text="Encomenda guardada").wait_for()
        self.assertIsNone(self.call("state")["orders"][0]["quantity"])
        for fields in [{"units": 0}, {"units": -1}, {"units": 1.5}, {"boxes": 2, "units": None}]:
            with self.assertRaises(Exception):
                self.call("createOrder", "2", fields)
        self.new_order(ref="2")
        self.new_order(ref="3", boxes=2, units=3)
        order = self.call("state")["orders"][-1]
        self.assertEqual(order["quantity"], 27)
        self.assertEqual((order["boxes"], order["units"]), (2, 3))

    def test_fifo_partial_complete_multiple_orders_and_net_stock_is_not_receipt(self):
        from tests.vertente.fixtures import receipt

        self.provision()
        a = self.new_order(60)
        b = self.new_order(30)
        refs = json.loads(
            __import__("base64").urlsafe_b64decode(snapshot(self.key, self.trust)["payload"] + "==")
        )["references"]
        refs[0]["bottles"] = 30
        r1 = receipt(101, bottles=36, confirmed_at=self.after(b))
        self.import_receipts([r1], references=refs)
        saved = self.call("state")
        self.assertEqual([o["state"] for o in saved["orders"]], ["partial", "waiting"])
        self.assertEqual(sum(x["bottles"] for x in saved["allocations"]), 36)
        r2 = receipt(102, bottles=54, confirmed_at=self.after(b, 2))
        self.import_receipts([r1, r2], sequence=3, references=refs)
        saved = self.call("state")
        self.assertEqual([o["state"] for o in saved["orders"]], ["received", "received"])
        totals = {
            o["id"]: sum(x["bottles"] for x in saved["allocations"] if x["order_id"] == o["id"])
            for o in saved["orders"]
        }
        self.assertEqual(totals, {a["id"]: 60, b["id"]: 30})
        self.assertEqual(saved["copy"]["data"]["references"][0]["bottles"], 30)
        with self.assertRaises(Exception):
            self.call("importSnapshot", snapshot(self.key, self.trust, sequence=2))
        self.assertEqual(self.call("state")["allocations"], saved["allocations"])

    def test_unknown_order_consumes_first_eligible_remainder_old_entries_excluded(self):
        from tests.vertente.fixtures import receipt

        self.provision()
        a = self.new_order()
        b = self.new_order(12)
        old = receipt(201, bottles=100, confirmed_at=self.after(a, -1))
        new = receipt(202, bottles=18, confirmed_at=self.after(b))
        self.import_receipts([old, new])
        saved = self.call("state")
        self.assertEqual([o["state"] for o in saved["orders"]], ["received", "waiting"])
        self.assertEqual(
            saved["allocations"], [{"receipt_id": "202", "order_id": a["id"], "bottles": 18}]
        )
        self.import_receipts(
            [old, new, receipt(203, bottles=12, confirmed_at=self.after(b, 2))], sequence=3
        )
        self.assertEqual(
            [o["state"] for o in self.call("state")["orders"]], ["received", "received"]
        )

    def test_edit_cancel_retains_allocations_never_reallocates_received_quantity(self):
        from tests.vertente.fixtures import receipt

        self.provision()
        a = self.new_order(12)
        self.call("editOrder", a["id"], {"boxes": None, "units": 18, "note": "Alterada"})
        r = receipt(301, bottles=6, confirmed_at=self.after(a))
        self.import_receipts([r])
        a = self.call("state")["orders"][0]
        with self.assertRaises(Exception):
            self.call("editOrder", a["id"], {"boxes": None, "units": 24, "note": "Não permitido"})
        self.call("editOrder", a["id"], {"cancel": True, "note": "Cancelada sintética"})
        b = self.new_order(6)
        self.import_receipts(
            [r],
            sequence=3,
            exported_at=__import__("tests.vertente.fixtures", fromlist=["stamp"]).stamp(
                self.after(b, 2)
            ),
        )
        saved = self.call("state")
        self.assertEqual(saved["orders"][0]["state"], "cancelled")
        self.assertEqual(saved["orders"][1]["state"], "waiting")
        self.assertEqual(sum(x["bottles"] for x in saved["allocations"]), 6)

    def test_minimum_equality_zero_and_no_automatic_close_from_stock_growth(self):
        self.provision()
        a = self.new_order(6)
        self.assertTrue(self.page.locator('[data-filter="low"]').inner_text().startswith("2"))
        refs = json.loads(
            __import__("base64").urlsafe_b64decode(snapshot(self.key, self.trust)["payload"] + "==")
        )["references"]
        refs[0]["bottles"] = 999
        refs[1]["minimum"] = 0
        self.call("importSnapshot", snapshot(self.key, self.trust, sequence=2, references=refs))
        saved = self.call("state")
        self.assertEqual(saved["orders"][0]["state"], "waiting")
        self.assertEqual(saved["orders"][0]["id"], a["id"])
        self.refresh()
        self.assertTrue(self.page.locator('[data-filter="low"]').inner_text().startswith("2"))

    def test_older_missing_inactive_reference_keeps_private_order_history(self):
        self.provision()
        a = self.new_order(6)
        refs = json.loads(
            __import__("base64").urlsafe_b64decode(snapshot(self.key, self.trust)["payload"] + "==")
        )["references"][1:]
        self.call("importSnapshot", snapshot(self.key, self.trust, sequence=2, references=refs))
        self.refresh()
        self.page.get_by_role("button", name="Encomendas", exact=True).click()
        self.page.get_by_text(
            "Referência ausente ou desativada na última atualização. O acompanhamento foi preservado.",
            exact=True,
        ).wait_for()
        self.assertEqual(self.call("state")["orders"][0]["id"], a["id"])
        self.assertEqual(len(self.call("state")["copy"]["data"]["references"]), 2)

    def test_invalid_incomplete_wrong_origin_and_repeated_files_preserve_everything(self):
        self.provision()
        self.new_order(6)
        before = self.call("state")
        candidates = []
        invalid = copy.deepcopy(snapshot(self.key, self.trust, sequence=2))
        invalid["signature"] = "A" + invalid["signature"][1:]
        candidates.append(invalid)
        candidates += [
            snapshot(*fixture(), sequence=2),
            snapshot(self.key, self.trust, sequence=1),
            snapshot(self.key, self.trust, sequence=2, references=[{"id": "1"}]),
        ]
        for file in candidates:
            with self.assertRaises(Exception):
                self.call("importSnapshot", file)
            self.assertEqual(self.call("state")["watermark"], before["watermark"])
            self.assertEqual(self.call("state")["orders"], before["orders"])

    def test_write_failure_rolls_back_stock_vault_and_receipt_dedup(self):
        from tests.vertente.fixtures import receipt

        self.provision()
        a = self.new_order(6)
        before = self.call("state")
        file = snapshot(
            self.key,
            self.trust,
            sequence=2,
            receipts=[receipt(401, bottles=6, confirmed_at=self.after(a))],
            exported_at=__import__("tests.vertente.fixtures", fromlist=["stamp"]).stamp(
                self.after(a, 2)
            ),
        )
        self.page.evaluate(
            "()=>{window.originalPut=IDBObjectStore.prototype.put;IDBObjectStore.prototype.put=function(...args){if(this.name==='vault')throw new Error('synthetic storage failure');return window.originalPut.apply(this,args);};}"
        )
        with self.assertRaises(Exception):
            self.call("importSnapshot", file)
        self.page.evaluate("()=>{IDBObjectStore.prototype.put=window.originalPut;}")
        saved = self.call("state")
        self.assertEqual(saved["watermark"], before["watermark"])
        self.assertEqual(saved["orders"], before["orders"])
        self.assertEqual(saved["allocations"], [])
        self.call("importSnapshot", file)
        self.assertEqual(self.call("state")["orders"][0]["state"], "received")

    def test_backup_restore_new_device_preserves_receipts_and_rejects_wrong_password(self):
        from tests.vertente.fixtures import grant, receipt

        self.provision()
        a = self.new_order(12)
        r = receipt(501, bottles=6, confirmed_at=self.after(a))
        self.import_receipts([r])
        backup = self.call("backupPreferences", self.password)
        self.assertNotIn("orders", json.dumps(backup))
        self.assertNotIn(self.password, json.dumps(backup))
        with self.assertRaises(Exception):
            self.call("decodePreferences", backup, "wrong-backup-password-phrase")
        data = self.call("decodePreferences", backup, self.password)
        self.assertEqual(data["orders"][0]["state"], "partial")
        context2 = self.browser.new_context(viewport={"width": 393, "height": 851})
        self.addCleanup(context2.close)
        self.page = context2.new_page()
        self.page.goto(self.url)
        self.page.locator("#trust-file").wait_for()
        self.call("enroll", self.trust, self.trust["keys"][0]["key_id"])
        request = self.call("deviceRequest")
        self.call("activate", grant(self.key, self.trust, request))
        self.call("unlock", self.password)
        restored = self.call("decodePreferences", backup, self.password)
        self.call("restorePreferences", restored)
        with self.assertRaises(Exception):
            self.call("importSnapshot", snapshot(self.key, self.trust, sequence=1))
        self.call("importSnapshot", self.last_snapshot)
        self.assertEqual(sum(x["bottles"] for x in self.call("state")["allocations"]), 6)
        self.import_receipts(
            [r, receipt(502, bottles=6, confirmed_at=self.after(a, 2))], sequence=3
        )
        self.assertEqual(self.call("state")["orders"][0]["state"], "received")

    def test_corrupt_latest_snapshot_recovers_previous_without_lowering_watermark(self):
        self.provision()
        self.call("importSnapshot", snapshot(self.key, self.trust, sequence=2))
        self.page.evaluate(
            "async()=>{const db=await(await import('/assets/store.js')).database();await new Promise(ok=>{const tx=db.transaction('snapshots','readwrite'),s=tx.objectStore('snapshots'),r=s.get(2);r.onsuccess=()=>{r.result.envelope.signature='invalid';s.put(r.result);};tx.oncomplete=ok;});}"
        )
        saved = self.call("state")
        self.assertTrue(saved["recovered"])
        self.assertEqual(saved["copy"]["data"]["sequence"], 1)
        self.assertEqual(saved["watermark"]["sequence"], 2)
        with self.assertRaises(Exception):
            self.call("importSnapshot", snapshot(self.key, self.trust, sequence=2))
        self.call("importSnapshot", snapshot(self.key, self.trust, sequence=3))
        self.assertFalse(self.call("state")["recovered"])

    def test_offline_reload_search_orders_and_automatic_lock(self):
        self.provision()
        self.new_order(6)
        self.page.evaluate("async()=>{await navigator.serviceWorker.ready;}")
        self.page.reload()
        wait_offline_shell(self.page)
        self.context.set_offline(True)
        self.page.reload()
        self.page.get_by_role("heading", name="Última atualização de stock", exact=True).wait_for()
        self.assertEqual(self.call("state")["orders"], [])
        self.call("unlock", self.password)
        self.assertEqual(len(self.call("state")["orders"]), 1)
        self.refresh()
        self.page.get_by_label("Pesquisar pelo nome", exact=True).fill("agua")
        self.assertEqual(self.page.locator(".reference").count(), 1)
        self.page.clock.install()
        self.page.clock.set_fixed_time(datetime.now(timezone.utc) + timedelta(minutes=6))
        self.assertEqual(self.call("state")["orders"], [])

    def test_gap_detection_and_signed_historical_recovery_without_stock_regression(self):
        from consultation.signing import signed_snapshot
        from tests.vertente.fixtures import receipt, stamp

        now = datetime.now(timezone.utc)
        old = now - timedelta(days=181)
        self.page.clock.install(time=old)
        self.provision(import_first=False, now=now - timedelta(days=200))
        first = snapshot(
            self.key,
            self.trust,
            exported_at=stamp(old),
            coverage={"from": stamp(old - timedelta(days=180)), "until": stamp(old)},
        )
        self.call("importSnapshot", first)
        self.new_order(6)
        self.page.clock.set_fixed_time(now)
        self.call("unlock", self.password)
        r = receipt(601, bottles=6, confirmed_at=now - timedelta(days=179))
        self.call("importSnapshot", snapshot(self.key, self.trust, sequence=2, receipts=[r]))
        saved = self.call("state")
        self.assertTrue(saved["orders"][0]["gap"])
        self.assertEqual(saved["orders"][0]["state"], "waiting")
        recovery = signed_snapshot(
            {
                "source_id": self.trust["source_id"],
                "update_id": str(__import__("uuid").uuid4()),
                "exported_at": stamp(now),
                "coverage": {
                    "from": stamp(old - timedelta(days=1)),
                    "until": stamp(now - timedelta(days=178)),
                },
                "receipts": [r],
            },
            self.key,
            kind="vertente-receipts",
            version=1,
        )
        self.call("unlock", self.password)
        self.call("importSnapshot", recovery)
        saved = self.call("state")
        self.assertEqual(saved["orders"][0]["state"], "received")
        self.assertEqual(saved["watermark"]["sequence"], 2)
        self.call("importSnapshot", recovery)
        self.assertEqual(sum(x["bottles"] for x in self.call("state")["allocations"]), 6)

    def test_two_tabs_concurrent_imports_have_one_atomic_winner(self):
        from tests.vertente.fixtures import receipt

        self.provision()
        a = self.new_order(6)
        files = [
            snapshot(
                self.key,
                self.trust,
                sequence=n,
                receipts=[receipt(701, bottles=6, confirmed_at=self.after(a))],
                exported_at=__import__("tests.vertente.fixtures", fromlist=["stamp"]).stamp(
                    self.after(a, n)
                ),
            )
            for n in [2, 3]
        ]
        result = self.page.evaluate(
            "async files=>{const m=await import('/assets/store.js'),original=crypto.subtle.encrypt.bind(crypto.subtle);let count=0,release;const gate=new Promise(ok=>release=ok);crypto.subtle.encrypt=async(...args)=>{if(++count===2)release();await gate;return original(...args);};try{return (await Promise.allSettled(files.map(f=>m.importSnapshot(f)))).map(x=>x.status);}finally{crypto.subtle.encrypt=original;}}",
            files,
        )
        self.assertEqual(sorted(result), ["fulfilled", "rejected"])
        saved = self.call("state")
        self.assertEqual(saved["orders"][0]["state"], "received")
        self.assertEqual(sum(x["bottles"] for x in saved["allocations"]), 6)

    def test_rotation_requires_old_signed_authority_and_reauthorization(self):
        from consultation.signing import signed_snapshot
        from tests.vertente.fixtures import grant

        self.provision()
        new_key, new_trust = fixture()
        new_trust["source_id"] = self.trust["source_id"]
        with self.assertRaises(Exception):
            self.call("enroll", new_trust, new_trust["keys"][0]["key_id"])
        new_trust["rotation"] = signed_snapshot(
            {"source_id": self.trust["source_id"], "key": new_trust["keys"][0]},
            self.key,
            kind="vertente-key-rotation",
            version=1,
        )
        self.call("enroll", new_trust, new_trust["keys"][0]["key_id"])
        self.assertFalse(self.call("state")["authorized"])
        self.call("activate", grant(new_key, new_trust, self.request, revision=2))
        self.call("unlock", self.password)
        self.assertTrue(self.call("state")["authorized"])
        self.assertEqual(self.call("state")["copy"]["data"]["sequence"], 1)
        with self.assertRaises(Exception):
            self.call("importSnapshot", snapshot(self.key, self.trust, sequence=2))
        self.call("importSnapshot", snapshot(new_key, new_trust, sequence=2))
        self.assertEqual(self.call("state")["watermark"]["sequence"], 2)

    def test_confirmation_history_is_not_executable_file_content(self):
        self.provision()
        refs = json.loads(
            __import__("base64").urlsafe_b64decode(snapshot(self.key, self.trust)["payload"] + "==")
        )["references"]
        refs[0]["name"] = '<img src=x onerror="window.syntheticExecuted=true">'
        self.call("importSnapshot", snapshot(self.key, self.trust, sequence=2, references=refs))
        self.refresh()
        self.assertFalse(self.page.evaluate("Boolean(window.syntheticExecuted)"))
        self.page.get_by_role("button", name=refs[0]["name"], exact=True).click()
        self.assertEqual(self.page.locator("#content img").count(), 0)
        self.assertFalse(self.page.evaluate("Boolean(window.syntheticExecuted)"))

    def test_idle_check_preserves_unsaved_form_and_background_file_selection(self):
        self.provision()
        self.page.get_by_role("button", name="Água de Ensaio", exact=True).click()
        self.page.get_by_role("button", name="Criar encomenda", exact=True).click()
        self.page.get_by_label("Garrafas soltas", exact=True).fill("13")
        self.page.clock.install()
        self.page.clock.fast_forward(31000)
        self.assertEqual(self.page.get_by_label("Garrafas soltas", exact=True).input_value(), "13")
        self.page.evaluate(
            "()=>{Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'));}"
        )
        self.assertTrue(self.page.locator("#content").is_hidden())
        self.page.evaluate(
            "()=>{Object.defineProperty(document,'hidden',{configurable:true,value:false});document.dispatchEvent(new Event('visibilitychange'));}"
        )
        self.assertEqual(self.page.get_by_label("Garrafas soltas", exact=True).input_value(), "13")

    def test_order_calendar_dates_and_historical_capacity_are_validated(self):
        from tests.vertente.fixtures import receipt

        self.provision()
        for value in ["2026-02-31", "2026-13-01", "9999-01-01"]:
            with self.assertRaises(Exception):
                self.new_order(6, ordered_on=value)
        self.call("createOrder", "1", {"boxes": 2, "units": 0})
        o = self.call("state")["orders"][0]
        refs = json.loads(
            __import__("base64").urlsafe_b64decode(snapshot(self.key, self.trust)["payload"] + "==")
        )["references"]
        refs[0]["box_capacity"] = 12
        self.import_receipts(
            [receipt(801, bottles=12, boxes=1, units=0, capacity=12, confirmed_at=self.after(o))],
            references=refs,
        )
        saved = self.call("state")
        self.assertEqual(saved["orders"][0]["quantity"], 12)
        self.assertEqual(saved["orders"][0]["box_capacity"], 6)
        self.assertEqual(saved["orders"][0]["state"], "received")

    def test_success_notice_waits_for_the_refreshed_owner_interface(self):
        self.provision()
        self.page.reload()
        self.page.get_by_role("button", name="Desbloquear", exact=True).wait_for()
        self.page.evaluate(
            "()=>{const original=crypto.subtle.verify.bind(crypto.subtle);crypto.subtle.verify=async(...args)=>{await new Promise(ok=>setTimeout(ok,120));return original(...args);};}"
        )
        self.page.get_by_label("Frase-passe do cofre", exact=True).fill(self.password)
        self.page.get_by_role("button", name="Desbloquear", exact=True).click()
        self.page.get_by_role("status").filter(has_text="Cofre desbloqueado").wait_for()
        self.assertEqual(self.page.get_by_role("button", name="Desbloquear", exact=True).count(), 0)
        self.page.get_by_role("button", name="Água de Ensaio", exact=True).click()
        self.page.get_by_role("button", name="Criar encomenda", exact=True).wait_for()
