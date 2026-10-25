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

from consultation.signing import public_key
from tests.vertente.fixtures import fixture, snapshot

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
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.goto(self.url)
        self.page.get_by_role(
            "heading", name="Ainda não existe uma cópia válida", exact=True
        ).wait_for()
        self.key, self.trust = fixture()
        self.first = snapshot(self.key, self.trust)

    def call(self, name, *args):
        return self.page.evaluate(
            "async ({name,args}) => {const m=await import('/assets/store.js');return m[name](...args);}",
            {"name": name, "args": args},
        )

    def enroll(self):
        self.call("enroll", self.trust, self.trust["keys"][0]["key_id"])

    def ready(self):
        self.enroll()
        self.call("importSnapshot", self.first)
        self.page.reload()
        self.page.get_by_role("heading", name="A sua fotografia de stock", exact=True).wait_for()

    def data(self):
        return self.call("state")

    def error(self, name, *args):
        return self.page.evaluate(
            "async ({name,args}) => {try {const m=await import('/assets/store.js');await m[name](...args);return null;}catch(e){return e.message;}}",
            {"name": name, "args": args},
        )

    def test_touch_home_search_accents_zero_unknown_capacity_and_no_default_alerts(self):
        self.ready()
        self.assertEqual(self.page.title(), "Vertente Aveludada")
        self.assertEqual(self.page.locator(".reference-card").count(), 3)
        self.assertIn(
            "3 caixas completas + 0 garrafas soltas",
            self.page.locator('[data-id="1"]').inner_text(),
        )
        self.assertIn(
            "Capacidade por caixa desconhecida", self.page.locator('[data-id="2"]').inner_text()
        )
        self.assertEqual(self.data()["alerts"], [])
        self.page.get_by_label("Pesquisar designação ou código", exact=True).fill("CORACAO")
        self.assertEqual(self.page.locator(".reference-card").count(), 1)
        self.page.get_by_label("Pesquisar designação ou código", exact=True).fill("agua")
        self.assertIn("Água de Ensaio", self.page.locator("#results").inner_text())
        self.page.get_by_label("Pesquisar designação ou código", exact=True).fill("")
        self.page.locator('.metric[data-filter="zero"]').click()
        self.assertEqual(self.page.locator(".reference-card").count(), 1)
        self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"), 393)
        self.assertEqual(self.errors, [])

    def test_file_onboarding_stock_import_and_encrypted_backup_restore_ui(self):
        def upload(label, value, name):
            self.page.get_by_label(label, exact=True).set_input_files(
                {"name": name, "mimeType": "application/json", "buffer": json.dumps(value).encode()}
            )

        self.page.get_by_role("button", name="Atualizações e cópias", exact=True).click()
        upload("Ficheiro de origem autorizada", self.trust, "synthetic.vatrust.json")
        self.page.get_by_label("Fingerprint SHA-256 confirmado com a informática", exact=True).fill(
            self.trust["keys"][0]["key_id"]
        )
        self.page.get_by_role(
            "button", name="Instalar ou atualizar chave pública", exact=True
        ).click()
        self.assertIsNone(self.data().get("trust"))
        self.page.locator("#confirmation").get_by_role(
            "button", name="Confirmar", exact=True
        ).click()
        self.page.get_by_role("status").filter(has_text="chaves públicas confirmadas").wait_for()
        upload("Ficheiro de atualização de stock", self.first, "synthetic.vastock.json")
        self.page.get_by_role("button", name="Importar atualização de stock", exact=True).click()
        self.page.get_by_role("status").filter(has_text="Atualização verificada").wait_for()
        self.page.get_by_role("button", name="Stock", exact=True).click()
        self.assertEqual(self.page.locator(".reference-card").count(), 3)
        ref = self.data()["copy"]["data"]["references"][0]
        self.call("setAlert", ref, 24)
        self.call("markOrdered", ref)
        self.page.get_by_role("button", name="Atualizações e cópias", exact=True).click()
        password = "a synthetic preference backup phrase"
        self.page.get_by_label("Frase-passe para proteger o backup", exact=True).fill(password)
        self.page.get_by_label("Repetir frase-passe", exact=True).fill(password)
        with self.page.expect_download() as download:
            self.page.get_by_role(
                "button", name="Exportar preferências cifradas", exact=True
            ).click()
        envelope = json.loads(Path(download.value.path()).read_text())
        self.page.get_by_role("status").filter(has_text="Backup cifrado preparado").wait_for()
        self.assertNotIn(password, json.dumps(self.data()))
        self.call("setAlert", ref, None)
        upload("Backup de preferências cifradas", envelope, "synthetic.vaprefs.json")
        self.page.get_by_label("Frase-passe do backup", exact=True).fill(password)
        self.page.get_by_role("button", name="Restaurar preferências", exact=True).click()
        self.page.locator("#confirmation").get_by_role(
            "button", name="Confirmar", exact=True
        ).click()
        self.page.get_by_role("status").filter(has_text="Preferências restauradas").wait_for()
        self.assertEqual(self.data()["alerts"], [{"id": "1", "limit": 24}])
        self.assertEqual(self.data()["orders"][0]["state"], "open")

    def test_complete_alert_and_order_ui_cancel_and_close(self):
        self.ready()
        card = self.page.locator('[data-id="1"]')
        card.get_by_text("Configurar alerta mínimo", exact=True).click()
        card.get_by_label("Limite de garrafas", exact=True).fill("24")
        card.get_by_role("button", name="Guardar alerta", exact=True).click()
        self.page.get_by_role("status").filter(has_text="Alerta guardado").wait_for()
        self.assertEqual(self.page.locator('.metric[data-filter="low"] strong').inner_text(), "1")
        card.get_by_role("button", name="Já encomendada", exact=True).click()
        self.page.locator("#confirmation").get_by_role(
            "button", name="Confirmar", exact=True
        ).click()
        self.page.get_by_role("status").filter(has_text="Encomenda registada").wait_for()
        self.assertEqual(self.page.locator('.metric[data-filter="todo"] strong').inner_text(), "0")
        self.assertEqual(self.page.locator('.metric[data-filter="low"] strong').inner_text(), "1")
        self.page.get_by_role("button", name="Encomendas", exact=True).click()
        self.page.get_by_role("button", name="Anular marcação", exact=True).click()
        self.page.locator("#confirmation").get_by_role(
            "button", name="Confirmar", exact=True
        ).click()
        self.page.get_by_role("status").filter(has_text="Marcação anulada").wait_for()
        self.page.get_by_role("button", name="Stock", exact=True).click()
        self.page.get_by_role("button", name="Já encomendada", exact=True).click()
        self.page.locator("#confirmation").get_by_role(
            "button", name="Confirmar", exact=True
        ).click()
        self.page.get_by_role("status").filter(has_text="Encomenda registada").wait_for()
        self.page.get_by_role("button", name="Encerrar acompanhamento", exact=True).click()
        self.page.locator("#confirmation").get_by_role(
            "button", name="Confirmar", exact=True
        ).click()
        self.page.get_by_role("status").filter(has_text="Acompanhamento encerrado").wait_for()
        self.assertEqual(sorted(o["state"] for o in self.data()["orders"]), ["cancelled", "closed"])
        self.assertEqual(self.data()["copy"]["data"]["references"][0]["bottles"], 18)

    def test_threshold_equal_below_change_remove_zero_and_individual_only(self):
        self.ready()
        ref = self.data()["copy"]["data"]["references"][0]
        self.call("setAlert", ref, 18)
        self.page.reload()
        self.assertEqual(self.page.locator('.metric[data-filter="low"] strong').inner_text(), "1")
        self.call("setAlert", ref, 17)
        self.page.reload()
        self.assertEqual(self.page.locator('.metric[data-filter="low"] strong').inner_text(), "0")
        self.call("setAlert", ref, 24)
        self.page.reload()
        self.assertEqual(self.page.locator('.metric[data-filter="low"] strong').inner_text(), "1")
        self.call("setAlert", ref, None)
        self.assertEqual(self.data()["tracked"], [])
        zero = self.data()["copy"]["data"]["references"][1]
        self.call("setAlert", zero, 0)
        self.page.reload()
        self.assertEqual(self.page.locator('.metric[data-filter="low"] strong').inner_text(), "1")
        self.assertEqual(len(self.data()["alerts"]), 1)

    def test_import_preserves_orders_and_alerts_never_closes_on_stock_rise(self):
        self.ready()
        ref = self.data()["copy"]["data"]["references"][0]
        self.call("setAlert", ref, 24)
        self.call("markOrdered", ref)
        refs = copy.deepcopy(self.data()["copy"]["data"]["references"])
        refs[0]["bottles"] = 100
        self.call("importSnapshot", snapshot(self.key, self.trust, 2, references=refs))
        self.page.reload()
        state = self.data()
        self.assertEqual(state["alerts"], [{"id": "1", "limit": 24}])
        self.assertEqual(state["orders"][0]["state"], "open")
        self.assertEqual(self.page.locator('.metric[data-filter="low"] strong').inner_text(), "0")
        self.assertEqual(
            self.page.locator('.metric[data-filter="ordered"] strong').inner_text(), "1"
        )

    def test_stale_copy_is_explicit_and_never_presented_as_live_stock(self):
        self.enroll()
        old = (
            (datetime.now(timezone.utc) - timedelta(days=2))
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
        self.call("importSnapshot", snapshot(self.key, self.trust, exported_at=old))
        self.page.reload()
        self.page.get_by_text("Cópia desatualizada:", exact=False).wait_for()
        self.assertIn("Não é stock em tempo real", self.page.locator(".stamp").inner_text())
        self.assertIn("Última importação", self.page.locator(".stamp").inner_text())

    def test_concurrent_imports_cannot_overwrite_a_newer_committed_copy(self):
        self.ready()
        updates = [snapshot(self.key, self.trust, 2), snapshot(self.key, self.trust, 3)]
        outcomes = self.page.evaluate(
            "async updates=>{const m=await import('/assets/store.js');return Promise.allSettled(updates.map(u=>m.importSnapshot(u))).then(r=>r.map(x=>x.status));}",
            updates,
        )
        self.assertEqual(sorted(outcomes), ["fulfilled", "rejected"])
        saved = self.data()
        self.assertEqual(saved["watermark"]["sequence"], saved["copy"]["data"]["sequence"])
        if saved["watermark"]["sequence"] == 2:
            self.call("importSnapshot", updates[1])
        self.assertEqual(self.data()["watermark"]["sequence"], 3)

    def test_absent_reference_preserved_and_reappears_without_duplicate_tracking(self):
        self.ready()
        ref = self.data()["copy"]["data"]["references"][0]
        self.call("setAlert", ref, 24)
        self.call("markOrdered", ref)
        refs = self.data()["copy"]["data"]["references"][1:]
        self.call("importSnapshot", snapshot(self.key, self.trust, 2, references=refs))
        self.page.reload()
        self.assertEqual(self.page.locator('.metric[data-filter="all"] strong').inner_text(), "2")
        self.page.locator('.metric[data-filter="ordered"]').click()
        self.assertIn("Ausente ou desativada", self.page.locator("#results").inner_text())
        self.assertNotIn("garrafas soltas", self.page.locator('[data-id="1"]').inner_text())
        self.call("importSnapshot", snapshot(self.key, self.trust, 3))
        self.page.reload()
        self.assertEqual(len(self.data()["orders"]), 1)
        self.assertEqual(len(self.data()["alerts"]), 1)

    def test_repeated_older_invalid_incomplete_files_preserve_latest(self):
        self.ready()
        self.assertIn("já foi", self.error("importSnapshot", self.first))
        second = snapshot(self.key, self.trust, 3)
        self.call("importSnapshot", second)
        self.assertIn("anterior", self.error("importSnapshot", snapshot(self.key, self.trust, 2)))
        variants = [
            {"format": "unknown"},
            {**self.first, "version": 2},
            {**self.first, "signature": "AA"},
        ]
        for variant in variants:
            self.assertTrue(self.error("importSnapshot", variant))
        bad = snapshot(
            self.key, self.trust, 4, references=[{"id": "1", "code": "VA-1", "name": "Incomplete"}]
        )
        self.assertTrue(self.error("importSnapshot", bad))
        self.assertEqual(
            self.data()["copy"]["data"]["update_id"],
            json.loads(__import__("base64").urlsafe_b64decode(second["payload"] + "=="))[
                "update_id"
            ],
        )

    def test_signature_origin_key_rotation_and_revocation(self):
        self.ready()
        other_key, other_trust = fixture()
        self.assertIn(
            "Chave não autorizada",
            self.error("importSnapshot", snapshot(other_key, other_trust, 2)),
        )
        wrong_origin = snapshot(self.key, other_trust, 2)
        self.assertIn("outra instalação", self.error("importSnapshot", wrong_origin))
        changed = copy.deepcopy(self.first)
        changed["payload"] = snapshot(self.key, self.trust, 2)["payload"]
        self.assertIn("Assinatura inválida", self.error("importSnapshot", changed))
        rotated = {**self.trust, "keys": [public_key(other_key)]}
        self.call("enroll", rotated, rotated["keys"][0]["key_id"])
        self.assertIsNotNone(self.data()["copy"])
        self.assertIn("revogada", self.error("importSnapshot", snapshot(self.key, self.trust, 2)))
        self.call("importSnapshot", snapshot(other_key, self.trust, 2))
        self.assertIn(
            "outra instalação", self.error("enroll", other_trust, other_trust["keys"][0]["key_id"])
        )

    def test_negative_fractional_duplicates_future_dates_and_xss(self):
        self.ready()
        refs = self.data()["copy"]["data"]["references"]
        for quantity in (-1, 1.5, True):
            bad = copy.deepcopy(refs)
            bad[0]["bottles"] = quantity
            self.assertTrue(
                self.error("importSnapshot", snapshot(self.key, self.trust, 2, references=bad))
            )
        bad = refs + [refs[0]]
        self.assertTrue(
            self.error("importSnapshot", snapshot(self.key, self.trust, 2, references=bad))
        )
        self.assertIn(
            "futuro",
            self.error(
                "importSnapshot",
                snapshot(self.key, self.trust, 2, exported_at="2099-01-01T00:00:00.000Z"),
            ),
        )
        refs[0]["name"] = '<img src=x onerror="window.injected=true">'
        self.call("importSnapshot", snapshot(self.key, self.trust, 2, references=refs))
        self.page.reload()
        self.assertFalse(self.page.evaluate("Boolean(window.injected)"))
        self.assertEqual(self.page.locator(".reference-card img").count(), 0)

    def test_atomic_storage_failure_and_verified_previous_copy_recovery(self):
        self.ready()
        self.page.evaluate(
            "() => {const original=IDBObjectStore.prototype.put;IDBObjectStore.prototype.put=function(value,...args){if(this.name==='snapshots')throw new DOMException('Synthetic quota failure','QuotaExceededError');return original.call(this,value,...args);};}"
        )
        self.assertTrue(self.error("importSnapshot", snapshot(self.key, self.trust, 2)))
        self.page.reload()
        self.assertEqual(self.data()["watermark"]["sequence"], 1)
        self.call("importSnapshot", snapshot(self.key, self.trust, 2))
        self.page.evaluate(
            "async () => {const db=await (await import('/assets/store.js')).database();await new Promise((resolve,reject)=>{const tx=db.transaction('snapshots','readwrite');tx.objectStore('snapshots').put({id:2,envelope:{},imported_at:new Date().toISOString()});tx.oncomplete=resolve;tx.onabort=reject;});}"
        )
        self.page.reload()
        saved = self.data()
        self.assertTrue(saved["recovered"])
        self.assertEqual(saved["copy"]["data"]["sequence"], 1)
        self.assertEqual(saved["watermark"]["sequence"], 2)
        self.assertIn("anterior", self.error("importSnapshot", self.first))
        self.call("importSnapshot", snapshot(self.key, self.trust, 3))
        self.assertFalse(self.data()["recovered"])

    def test_encrypted_preferences_backup_restore_wrong_password_origin_and_tampering(self):
        self.ready()
        ref = self.data()["copy"]["data"]["references"][0]
        self.call("setAlert", ref, 24)
        self.call("markOrdered", ref)
        password = "synthetic backup phrase 71"
        backup = self.call("backupPreferences", password)
        self.assertNotIn("Água", json.dumps(backup))
        self.assertNotIn("bottles", json.dumps(backup))
        self.assertIn(
            "incorreta", self.error("decodePreferences", backup, "wrong synthetic phrase")
        )
        damaged = {**backup, "ciphertext": backup["ciphertext"][:-2] + "AA"}
        self.assertTrue(self.error("decodePreferences", damaged, password))
        decoded = self.call("decodePreferences", backup, password)
        self.call("setAlert", ref, None)
        self.call("finishOrder", self.data()["orders"][0]["id"], "closed")
        self.call("restorePreferences", decoded)
        self.assertEqual(self.data()["orders"][0]["state"], "open")
        self.assertEqual(self.data()["alerts"], [{"id": "1", "limit": 24}])
        self.assertEqual(self.data()["watermark"]["sequence"], 1)
        self.assertIn(
            "outra origem",
            self.error("restorePreferences", {**decoded, "source_id": fixture()[1]["source_id"]}),
        )

    def test_offline_reload_local_edits_reopen_and_public_shell_only(self):
        self.ready()
        self.page.evaluate("async () => {await navigator.serviceWorker.ready;}")
        self.page.reload()
        self.page.wait_for_function("navigator.serviceWorker.controller !== null")
        ref = self.data()["copy"]["data"]["references"][0]
        self.context.set_offline(True)
        self.page.reload()
        self.page.get_by_role("heading", name="A sua fotografia de stock", exact=True).wait_for()
        self.assertIn("Sem ligação", self.page.locator("#connection").inner_text())
        self.call("setAlert", ref, 24)
        self.call("markOrdered", ref)
        self.page.reload()
        self.assertEqual(self.data()["orders"][0]["state"], "open")
        self.call("importSnapshot", snapshot(self.key, self.trust, 2))
        self.assertEqual(self.data()["watermark"]["sequence"], 2)
        cached = self.page.evaluate(
            "async () => {const urls=[];for(const key of await caches.keys())for(const r of await (await caches.open(key)).keys())urls.push(new URL(r.url).pathname);return urls;}"
        )
        self.assertTrue(
            all(
                p in ("/", "/index.html", "/manifest.webmanifest") or p.startswith("/assets/")
                for p in cached
            )
        )
        self.assertEqual(self.page.evaluate("localStorage.length"), 0)
        self.context.set_offline(False)
