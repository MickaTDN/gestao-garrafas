"""Explicit browser smoke suite: python manage.py test tests.browser."""

import os
import secrets
import shutil

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.urls import reverse
from playwright.sync_api import sync_playwright

from accounts.models import User
from inventory.models import Location, Reference


class BrowserSmokeTests(StaticLiveServerTestCase):
    def setUp(self):
        self.password = secrets.token_urlsafe(32)
        self.viewer = User.objects.create_user(username="synthetic-browser", password=self.password)
        location = Location.objects.create(name="Local de teste sintético")
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
