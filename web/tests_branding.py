import io
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from PIL import Image
from pypdf import PdfReader

from inventory.documents import render_pdf
from web.branding import APP_NAME, LOGO, icon_asset


class BrandingTests(SimpleTestCase):
    def test_login_and_management_pwa_use_new_name_without_invented_logo(self):
        with patch("web.branding.original_asset", return_value=None):
            response = self.client.get(reverse("login"))
            self.assertContains(response, APP_NAME)
            self.assertNotContains(response, "Gestão de Garrafas")
            self.assertNotContains(response, 'class="brand-mark"')
            self.assertNotContains(response, "<img")
            manifest = self.client.get(reverse("manifest")).json()
            self.assertEqual(manifest["name"], APP_NAME)
            self.assertEqual(icon_asset(192), "icons/icon-192.png")

    def test_original_asset_slots_are_selected_without_redrawing(self):
        # Test-only artwork, never shipped as a logo.
        with tempfile.TemporaryDirectory() as directory, override_settings(BASE_DIR=directory):
            folder = Path(directory) / "static" / "branding"
            folder.mkdir(parents=True)
            Image.new("RGB", (1200, 300), "green").save(folder / "copo-com-vida-logo.png")
            for size in (192, 512):
                Image.new("RGB", (size, size), "white").save(folder / f"copo-com-vida-{size}.png")
            response = self.client.get(reverse("login"))
            self.assertContains(response, "branding/copo-com-vida-logo.png")
            self.assertContains(response, 'alt="Copo com Vida"')
            self.assertEqual(icon_asset(512), "branding/copo-com-vida-512.png")
            manifest = self.client.get(reverse("manifest")).json()
            self.assertEqual(manifest["name"], "Gestão Vertente Aveludada")
            for icon in manifest["icons"]:
                size = int(icon["sizes"].split("x")[0])
                self.assertIn(f"branding/copo-com-vida-{size}.png", icon["src"])
                self.assertEqual(icon["purpose"], "any maskable")
            snapshot = {
                "id": 1,
                "label": "Entrada",
                "kind": "entry",
                "date": "2026-01-02",
                "confirmed_at": "2026-01-02T12:00:00+00:00",
                "person": "Pessoa fictícia",
                "responsible": "Fictício",
                "correction_of": None,
                "reason": "",
                "lines": [],
                "changes": [],
            }
            reader = PdfReader(io.BytesIO(render_pdf(snapshot)))
            self.assertIn(APP_NAME, reader.pages[0].extract_text())
            self.assertTrue(list(reader.pages[0].images))
            embedded = list(reader.pages[0].images)[0].image
            self.assertEqual(embedded.size, (1200, 300))
            self.assertEqual(embedded.getpixel((600, 150)), (0, 128, 0))
            self.assertEqual(LOGO, "branding/copo-com-vida-logo.png")

    def test_public_worker_uses_original_assets_and_refreshes_when_the_logo_changes(self):
        repository = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as directory, override_settings(BASE_DIR=directory):
            root = Path(directory) / "static"
            for name in ("css/app.css", "js/pwa.js", "js/service-worker.js"):
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(repository / "static" / name, target)
            (root / "branding").mkdir()
            logo = root / LOGO
            Image.new("RGB", (1200, 300), "green").save(logo)
            for size in (192, 512):
                Image.new("RGB", (size, size), "white").save(root / f"branding/copo-com-vida-{size}.png")
            before = self.client.get(reverse("service-worker"))
            for name in (LOGO, "branding/copo-com-vida-192.png", "branding/copo-com-vida-512.png"):
                self.assertContains(before, name)
            self.assertNotContains(before, "icons/icon-")
            Image.new("RGB", (1200, 300), "blue").save(logo)
            after = self.client.get(reverse("service-worker"))
            self.assertNotEqual(before.content, after.content)
