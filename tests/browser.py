"""Explicit browser smoke suite: python manage.py test tests.browser."""

import os
import secrets
import shutil
from concurrent.futures import ThreadPoolExecutor

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.db import connections
from django.urls import reverse
from playwright.sync_api import sync_playwright

from accounts.models import User
from inventory.models import Location, Reference


class BrowserSmokeTests(StaticLiveServerTestCase):
    @staticmethod
    def database_call(operation):
        # Playwright's synchronous driver runs an event loop in this thread.
        # Keep ORM work in a separate synchronous thread, with its own connection.
        def run():
            try:
                return operation()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(run).result()

    def setUp(self):
        self.password = secrets.token_urlsafe(32)
        self.viewer = User.objects.create_user(username="synthetic-browser", password=self.password)
        location = Location.objects.create(name="Local de teste sintético")
        self.location_id = location.pk
        Reference.objects.create(
            code="SYN-001",
            name="Referência fictícia azul",
            location=location,
            current_stock=15,
            box_capacity=6,
        )
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(
            executable_path=os.getenv("CHROMIUM_PATH") or shutil.which("chromium"),
            headless=True,
            args=["--no-sandbox"],
        )
        self.addCleanup(self.playwright.stop)
        self.addCleanup(self.browser.close)

    def test_desktop_and_mobile_authenticated_stock(self):
        for width, height in [(1366, 900), (390, 844)]:
            with self.subTest(width=width):
                page = self.browser.new_page(viewport={"width": width, "height": height})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                response = page.goto(self.live_server_url + reverse("web:stock"))
                self.assertEqual(response.status, 200)
                self.assertIn(reverse("login"), page.url)
                page.get_by_label("Utilizador", exact=True).fill(self.viewer.username)
                page.get_by_label("Palavra-passe", exact=True).fill(self.password)
                page.get_by_role("button", name="Entrar", exact=True).click()
                self.assertIn("Referência fictícia azul", page.locator("body").inner_text())
                # Submit through the real form, including query-string round trip.
                page.locator('input[name="q"]').fill("SYN-001")
                page.locator('input[name="q"]').press("Enter")
                self.assertEqual(page.locator("tbody tr").count(), 1)
                self.assertIn("15", page.locator("tbody").inner_text())
                self.assertLessEqual(
                    page.evaluate("document.documentElement.scrollWidth"),
                    width,
                    "A página não deve transbordar horizontalmente em telemóvel.",
                )
                forbidden = page.goto(self.live_server_url + reverse("web:settings"))
                self.assertEqual(forbidden.status, 403)
                self.assertEqual(errors, [])
                page.close()

    def test_administrator_creates_and_edits_reference_on_mobile(self):
        self.database_call(lambda: User.objects.filter(pk=self.viewer.pk).update(role="admin"))
        page = self.browser.new_page(viewport={"width": 390, "height": 844})
        page.goto(self.live_server_url + reverse("web:reference-create"))
        page.get_by_label("Utilizador", exact=True).fill(self.viewer.username)
        page.get_by_label("Palavra-passe", exact=True).fill(self.password)
        page.get_by_role("button", name="Entrar", exact=True).click()
        page.get_by_label("Designação", exact=True).fill("Referência fictícia verde")
        page.get_by_label("Garrafas por caixa", exact=True).fill("6")
        page.get_by_label("Localização", exact=True).select_option(str(self.location_id))
        self.assertFalse(
            page.get_by_label("Ativar alerta de stock mínimo", exact=True).is_checked()
        )
        page.get_by_role("button", name="Guardar", exact=True).click()
        self.assertIn("Referência fictícia verde", page.locator("h1").inner_text())
        reference = self.database_call(
            lambda: Reference.objects.get(name="Referência fictícia verde")
        )
        self.assertEqual(reference.current_stock, 0)
        self.assertIsNone(reference.minimum)
        page.goto(self.live_server_url + reverse("web:reference-edit", args=[reference.pk]))
        page.get_by_label("Ativar alerta de stock mínimo", exact=True).check()
        page.get_by_label("Stock mínimo em garrafas", exact=True).fill("4")
        page.get_by_role("button", name="Guardar", exact=True).click()
        self.database_call(reference.refresh_from_db)
        self.assertEqual(reference.minimum, 4)
        self.assertEqual(reference.current_stock, 0)
        self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), 390)
        page.close()


class OperationalBrowserTests(StaticLiveServerTestCase):
    """Exercise actual forms and JS on both viewport sizes with synthetic fixtures."""

    database_call = staticmethod(BrowserSmokeTests.database_call)

    def setUp(self):
        self.password = secrets.token_urlsafe(32)
        self.admin = User.objects.create_user(
            username="synthetic-operations", password=self.password, role="admin"
        )
        self.location = Location.objects.create(name="Origem browser sintética")
        self.destination = Location.objects.create(name="Destino browser sintético")
        self.first = Reference.objects.create(
            code="SYN-OP-1",
            name="Azul sintética operacional",
            box_capacity=6,
            current_stock=15,
            location=self.location,
        )
        self.second = Reference.objects.create(
            code="SYN-OP-2",
            name="Verde sintética operacional",
            current_stock=5,
            location=self.location,
        )
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(
            executable_path=os.getenv("CHROMIUM_PATH") or shutil.which("chromium"),
            headless=True,
            args=["--no-sandbox"],
        )
        self.addCleanup(self.playwright.stop)
        self.addCleanup(self.browser.close)

    def page(self, kind, width):
        page = self.browser.new_page(
            viewport={"width": width, "height": 900 if width > 760 else 844}
        )
        self.addCleanup(page.close)
        page.set_default_timeout(6000)
        self.errors = []
        page.on("pageerror", lambda error: self.errors.append(str(error)))
        page.goto(self.live_server_url + reverse(f"web:{kind}"))
        page.get_by_label("Utilizador", exact=True).fill(self.admin.username)
        page.get_by_label("Palavra-passe", exact=True).fill(self.password)
        page.get_by_role("button", name="Entrar", exact=True).click()
        return page

    def assert_responsive(self, page, width):
        self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
        self.assertEqual(self.errors, [])
        if directory := os.getenv("BROWSER_ARTIFACT_DIR"):
            os.makedirs(directory, exist_ok=True)
            self.screenshot_count = getattr(self, "screenshot_count", 0) + 1
            page.screenshot(
                path=os.path.join(directory, f"{self._testMethodName}-{self.screenshot_count}.png"),
                full_page=True,
            )

    def stocks(self):
        return self.database_call(
            lambda: list(Reference.objects.order_by("code").values_list("current_stock", flat=True))
        )

    def entry_exit(self, kind, width):
        page = self.page(kind, width)
        page.get_by_role("button", name="Criar rascunho", exact=True).click()
        page.get_by_label("Adicionar SYN-OP-1", exact=True).check()
        page.get_by_label("Adicionar SYN-OP-2", exact=True).check()
        page.get_by_role("button", name="Adicionar selecionadas e guardar", exact=True).click()
        edit_url = page.url
        self.assertEqual(
            page.locator(".operation-line").count(), 2, page.locator("body").inner_text()
        )
        first = page.locator(".operation-line").filter(has_text="SYN-OP-1")
        second = page.locator(".operation-line").filter(has_text="SYN-OP-2")
        for row in (first, second):
            self.assertEqual(row.get_by_label("Caixas", exact=True).input_value(), "")
            self.assertEqual(row.get_by_label("Garrafas soltas", exact=True).input_value(), "")
        page.get_by_label("Pessoa que entregou / levantou", exact=True).fill(
            "Pessoa browser sintética"
        )
        first.get_by_label("Caixas", exact=True).fill("1")
        first.get_by_label("Garrafas soltas", exact=True).fill("8" if kind == "entry" else "2")
        second.get_by_label("Garrafas soltas", exact=True).fill("3")
        self.assertEqual(
            first.locator(".line-total").inner_text(), "14" if kind == "entry" else "8"
        )
        self.assertIn("29" if kind == "entry" else "7", first.locator(".line-after").inner_text())
        self.assert_responsive(page, width)
        page.get_by_role("button", name="Guardar rascunho", exact=True).click()
        self.assertEqual(self.stocks(), [15, 5])
        page.goto(self.live_server_url + reverse("web:drafts"))
        page.get_by_role("link", name="Continuar / editar", exact=True).click()
        self.assertEqual(page.url, edit_url)
        self.assertEqual(page.locator('input[name="form-0-boxes"]').input_value(), "1")
        self.assertEqual(page.locator('input[name="form-1-boxes"]').input_value(), "")
        page.get_by_role("button", name="Guardar e conferir operação", exact=True).click()
        self.assertIn("/conferir/", page.url)
        self.assertEqual(self.stocks(), [15, 5])
        # Correction before confirmation is available and invalidates the old review.
        page.get_by_role("link", name="Corrigir referências ou quantidades", exact=True).click()
        page.get_by_role("button", name="Guardar e conferir operação", exact=True).click()
        if kind == "entry":
            page.locator('select[name="report_requested"]').select_option("yes")
        self.assert_responsive(page, width)
        page.locator('input[name="confirm"]').check()
        page.get_by_role(
            "button", name="Confirmar entrada" if kind == "entry" else "Confirmar saída", exact=True
        ).click()
        self.assertIn("CONFIRMADO", page.locator("body").inner_text())
        self.assertEqual(self.stocks(), [29, 8] if kind == "entry" else [7, 2])
        self.assertIn("geração PDF pendente", page.locator("body").inner_text())
        self.assert_responsive(page, width)

    def inventory_flow(self, width):
        page = self.page("inventory", width)
        page.get_by_label("Âmbito", exact=True).select_option("full")
        page.get_by_role("button", name="Criar rascunho", exact=True).click()
        first = page.locator(".operation-line").filter(has_text="SYN-OP-1")
        second = page.locator(".operation-line").filter(has_text="SYN-OP-2")
        self.assertEqual(first.get_by_label("Caixas", exact=True).input_value(), "")
        self.assertEqual(second.get_by_label("Garrafas soltas", exact=True).input_value(), "")
        first.get_by_label("Caixas", exact=True).fill("2")
        first.get_by_label("Garrafas soltas", exact=True).fill("1")
        first.get_by_label("Motivo da diferença / transferência", exact=True).fill(
            "Contagem física browser sintética"
        )
        first.get_by_label("Localização após inventário", exact=True).select_option(
            str(self.destination.pk)
        )
        self.assertEqual(first.locator(".line-total").inner_text(), "13")
        self.assertEqual(first.locator(".line-difference").inner_text(), "-2")
        second.get_by_label("Garrafas soltas", exact=True).fill("0")
        second.get_by_label("Motivo da diferença / transferência", exact=True).fill(
            "Zero contado explicitamente"
        )
        self.assertEqual(second.locator(".line-total").inner_text(), "0")
        self.assert_responsive(page, width)
        page.get_by_role("button", name="Guardar rascunho", exact=True).click()
        self.assertEqual(self.stocks(), [15, 5])
        page.get_by_role("button", name="Guardar e conferir operação", exact=True).click()
        self.assertIn("/conferir/", page.url)
        page.locator('input[name="confirm"]').check()
        page.get_by_role("button", name="Confirmar inventário", exact=True).click()
        self.assertIn("CONFIRMADO", page.locator("body").inner_text())
        self.assertEqual(self.stocks(), [13, 0])
        destination_id = self.database_call(
            lambda: Reference.objects.get(pk=self.first.pk).location_id
        )
        self.assertEqual(destination_id, self.destination.pk)
        self.assertIn("Transferência", page.locator("body").inner_text())
        self.assert_responsive(page, width)

    def test_entry_desktop(self):
        self.entry_exit("entry", 1366)

    def test_entry_mobile(self):
        self.entry_exit("entry", 390)

    def test_exit_desktop(self):
        self.entry_exit("exit", 1366)

    def test_exit_mobile(self):
        self.entry_exit("exit", 390)

    def test_inventory_desktop(self):
        self.inventory_flow(1366)

    def test_inventory_mobile(self):
        self.inventory_flow(390)
