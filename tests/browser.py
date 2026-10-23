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
            code="SYN-001", name="Referência fictícia azul", location=location,
            current_stock=15, box_capacity=6,
        )
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(
            executable_path=os.getenv("CHROMIUM_PATH") or shutil.which("chromium"),
            headless=True, args=["--no-sandbox"],
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
                    page.evaluate("document.documentElement.scrollWidth"), width,
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
        self.assertFalse(page.get_by_label("Ativar alerta de stock mínimo", exact=True).is_checked())
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
