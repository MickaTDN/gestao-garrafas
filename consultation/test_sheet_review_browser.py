"""Desktop/mobile administrative flows on the real Django HTTP server."""

import hashlib
import os
import secrets
import shutil
import uuid

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse
from playwright.sync_api import sync_playwright

from consultation.sheets import receive_sheet
from consultation.test_sheets import SheetFixtures
from inventory.models import Movement, Reference
from tests import browser as existing_browser


@override_settings(ALLOWED_HOSTS=["localhost", "127.0.0.1", "testserver"])
class PendingReviewBrowserTests(SheetFixtures, StaticLiveServerTestCase):
    database_call = staticmethod(existing_browser.BrowserSmokeTests.database_call)

    def setUp(self):
        self.prepare()
        self.password = secrets.token_urlsafe(32)
        self.admin.set_password(self.password)
        self.admin.save(update_fields=["password"])
        self.playwright = sync_playwright().start()
        self.addCleanup(self.playwright.stop)
        self.browser = self.playwright.chromium.launch(
            executable_path=os.getenv("CHROMIUM_PATH") or shutil.which("chromium"),
            headless=True,
            args=["--no-sandbox"],
        )
        self.addCleanup(self.browser.close)
        self.page = self.browser.new_page(viewport={"width": 1366, "height": 900})
        self.page.set_default_timeout(10000)
        self.page.goto(self.live_server_url + reverse("login"))
        self.page.locator('input[name="username"]').fill(self.admin.username)
        self.page.locator('input[name="password"]').fill(self.password)
        self.page.get_by_role("button", name="Entrar", exact=True).click()
        self.page.wait_for_url(self.live_server_url + "/")

    def open_sheet(self, kind="entry", unknown=False):
        payload = {**self.payload, "sheet_id": str(uuid.uuid4()), "kind": kind}
        if unknown:
            payload["lines"] = [{**payload["lines"][0], "reference_id": "unresolved"}]
        sheet = self.database_call(
            lambda: receive_sheet(self.packet(payload), actor=self.admin).sheet
        )
        self.page.goto(self.live_server_url + reverse("web:sheet-process", args=[sheet.pk]))
        return sheet

    def finish(self, kind="entry", report="no"):
        self.page.get_by_role("button", name="Conferir folha", exact=True).click()
        self.page.get_by_role(
            "heading", name="Confirmação oficial explícita", exact=True
        ).wait_for()
        if kind == "entry":
            self.page.locator('select[name="report_requested"]').select_option(report)
        self.page.locator('input[name="confirm"]').check()
        self.page.get_by_role("button", name="Confirmar movimento oficial", exact=True).click()
        self.page.get_by_role(
            "link", name="Consultar movimento e documentos oficiais", exact=True
        ).wait_for()

    def test_desktop_entry_without_pdf_is_numbered_and_refresh_is_idempotent(self):
        self.open_sheet()
        self.finish()
        self.page.reload()
        self.assertEqual(
            self.page.get_by_role("button", name="Confirmar movimento oficial", exact=True).count(),
            0,
        )
        self.assertEqual(self.database_call(lambda: Movement.objects.count()), 1)
        self.assertEqual(
            self.database_call(lambda: Reference.objects.get(pk=self.ref.pk).current_stock), 20
        )
        self.page.get_by_text("Entrada sem PDF, conforme opção confirmada.", exact=True).wait_for()

    def test_mobile_exit_generates_verified_pdf(self):
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.open_sheet("exit")
        self.finish("exit")
        response = self.page.request.get(
            self.live_server_url
            + self.page.get_by_role("link", name="Abrir PDF oficial", exact=True).get_attribute(
                "href"
            )
        )
        self.assertEqual(response.status, 200)
        self.assertTrue(response.body().startswith(b"%PDF"))
        expected = self.database_call(lambda: Movement.objects.get().report_number.document.sha256)
        self.assertEqual(hashlib.sha256(response.body()).hexdigest(), expected)
        self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"), 390)

    def test_unknown_reference_correction_with_reason_then_optional_entry_pdf(self):
        sheet = self.open_sheet(unknown=True)
        self.page.get_by_role("button", name="Conferir folha", exact=True).click()
        self.page.get_by_text("Referência desconhecida:", exact=False).first.wait_for()
        self.page.get_by_text("Corrigir a versão de trabalho (exige motivo)", exact=True).click()
        self.page.get_by_label("Identificador da referência", exact=False).first.fill(
            str(self.ref.pk)
        )
        self.page.get_by_label("Motivo obrigatório da correção", exact=False).fill(
            "Referência conferida e associada ao catálogo existente"
        )
        self.page.get_by_role("button", name="Guardar correção com motivo", exact=True).click()
        self.page.get_by_text("Decisão registada.", exact=False).wait_for()
        self.finish(report="yes")
        self.page.get_by_role("link", name="Abrir PDF oficial", exact=True).wait_for()
        self.assertEqual(self.database_call(lambda: Reference.objects.count()), 1)
        self.assertEqual(
            self.database_call(lambda: sheet.actions.get(kind="corrected").reason),
            "Referência conferida e associada ao catálogo existente",
        )
