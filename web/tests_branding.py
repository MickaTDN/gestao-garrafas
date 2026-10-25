import io
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image
from pypdf import PdfReader

from inventory.documents import render_pdf
from web.branding import APP_NAME, LOGO, icon_asset


class BrandingTests(TestCase):
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
            self.assertEqual(LOGO, "branding/copo-com-vida-logo.png")
