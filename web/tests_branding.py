import hashlib
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
                Image.new("RGB", (size, size), "white").save(
                    root / f"branding/copo-com-vida-{size}.png"
                )
            before = self.client.get(reverse("service-worker"))
            for name in (LOGO, "branding/copo-com-vida-192.png", "branding/copo-com-vida-512.png"):
                self.assertContains(before, name)
            self.assertNotContains(before, "icons/icon-")
            Image.new("RGB", (1200, 300), "blue").save(logo)
            after = self.client.get(reverse("service-worker"))
            self.assertNotEqual(before.content, after.content)


class OriginalBrandAssetsTests(SimpleTestCase):
    """Supplied public artwork only; no invoice, stock or database is accessed."""

    root = Path(__file__).resolve().parent.parent / "static" / "branding"

    def test_source_files_are_byte_identical_to_the_supplied_originals(self):
        expected = {
            "copo-com-vida-logo.png": (
                "58e89b8b1c0d930e8418bae77565367f7785e55740ac435c2d3ba88555c24948",
                (1273, 827),
            ),
            "copo-com-vida-simbolo-original.png": (
                "e78fb04f5d1e027aa7803c347292cb935e8e021e470299cea2cf0d2242edf567",
                (143, 246),
            ),
        }
        for name, (digest, size) in expected.items():
            with self.subTest(name=name):
                path = self.root / name
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
                with Image.open(path) as image:
                    self.assertEqual(image.size, size)
                    self.assertEqual(image.mode, "RGB")
                    self.assertEqual(image.info, {})

    def test_icon_pixels_preserve_the_original_ink_and_maskable_safe_area(self):
        from PIL import ImageChops, ImageOps

        from scripts.build_brand_icons import BACKGROUND, SYMBOL, original_ink

        with Image.open(self.root / SYMBOL) as source:
            expected_ink = ImageOps.invert(source.convert("L"))
            expected_ink = expected_ink.crop(expected_ink.getbbox())
        actual_ink = original_ink(self.root / SYMBOL)
        # Every original ink pixel remains; no part of the cup or its inner
        # details has been replaced, filled, traced or thresholded away.
        self.assertEqual(actual_ink.size, expected_ink.size)
        self.assertEqual(
            actual_ink.point(lambda value: 255 if value else 0).tobytes(),
            expected_ink.point(lambda value: 255 if value else 0).tobytes(),
        )
        for size in (192, 512):
            with Image.open(self.root / f"copo-com-vida-{size}.png") as image:
                self.assertEqual(image.size, (size, size))
                self.assertEqual(image.mode, "RGB")
                self.assertEqual(image.getpixel((0, 0)), BACKGROUND)
                self.assertIn((255, 255, 255), image.getdata())
                difference = ImageChops.difference(
                    image, Image.new("RGB", image.size, BACKGROUND)
                ).convert("L")
                bounds = difference.getbbox()
                self.assertIsNotNone(bounds)
                left, top, right, bottom = bounds
                self.assertLessEqual(abs((left + right) / 2 - size / 2), 1)
                self.assertLessEqual(abs((top + bottom) / 2 - size / 2), 1)
                for y in range(top, bottom):
                    for x in range(left, right):
                        if difference.getpixel((x, y)):
                            self.assertLessEqual(
                                (x - size / 2) ** 2 + (y - size / 2) ** 2, (size * 0.4) ** 2
                            )
        with Image.open(self.root / "copo-com-vida.ico") as icon:
            self.assertEqual(
                icon.ico.sizes(), {(size, size) for size in (16, 24, 32, 48, 64, 128, 256)}
            )
            for size in (16, 24, 32, 48, 64, 128, 256):
                frame = icon.ico.getimage((size, size)).convert("RGB")
                self.assertEqual(frame.size, (size, size))
                self.assertEqual(frame.getpixel((0, 0)), BACKGROUND)

    def test_real_logo_and_signature_are_embedded_separately_without_redrawing(self):
        from inventory.documents import validate_signature
        from tests.document_fixtures import signature_png

        snapshot = {
            "id": 1,
            "label": "Saída",
            "kind": "exit",
            "date": "2026-01-02",
            "confirmed_at": "2026-01-02T12:00:00+00:00",
            "person": "Pessoa fictícia",
            "responsible": "Fictício",
            "correction_of": None,
            "reason": "",
            "lines": [],
            "changes": [],
        }
        signature = validate_signature(signature_png())
        reader = PdfReader(io.BytesIO(render_pdf(snapshot, signature)))
        embedded = [image.image.convert("RGB") for page in reader.pages for image in page.images]
        with Image.open(self.root / "copo-com-vida-logo.png") as original:
            self.assertTrue(
                any(
                    image.size == original.size and image.tobytes() == original.tobytes()
                    for image in embedded
                )
            )
        with Image.open(io.BytesIO(signature)) as original:
            self.assertTrue(
                any(
                    image.size == original.size and image.tobytes() == original.tobytes()
                    for image in embedded
                )
            )
        self.assertIn(APP_NAME, reader.pages[0].extract_text())

    def test_installed_assets_are_used_in_login_manifest_and_public_worker(self):
        self.assertContains(self.client.get(reverse("login")), "branding/copo-com-vida-logo.png")
        manifest = self.client.get(reverse("manifest")).json()
        self.assertEqual(manifest["name"], APP_NAME)
        for icon in manifest["icons"]:
            self.assertIn("branding/copo-com-vida-", icon["src"])
            self.assertNotIn("icons/icon-", icon["src"])
        worker = self.client.get(reverse("service-worker"))
        for name in (LOGO, "branding/copo-com-vida-192.png", "branding/copo-com-vida-512.png"):
            self.assertContains(worker, name)
