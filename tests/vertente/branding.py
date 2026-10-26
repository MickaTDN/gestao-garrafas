import json
from pathlib import Path

from django.test import SimpleTestCase
from PIL import Image, ImageOps

from scripts.build_brand_icons import BRAND_ROOT, SYMBOL, original_ink

ROOT = Path(__file__).resolve().parents[2]


class StockBrandingTests(SimpleTestCase):
    def test_manifest_stock_identity_distinct_from_management(self):
        manifest = json.loads((ROOT / "vertente/manifest.webmanifest").read_text())
        self.assertEqual(manifest["name"], "Stock Vertente Aveludada")
        self.assertEqual(manifest["background_color"], "#f6f3ee")
        self.assertEqual(manifest["theme_color"], "#102e28")
        self.assertEqual(manifest["scope"], "/")
        self.assertNotIn("Stock Vendas", (ROOT / "vertente/index.html").read_text())

    def test_stock_cup_uses_the_exact_original_ink_without_tracing(self):
        ink = original_ink(BRAND_ROOT / SYMBOL)
        for size in [192, 512]:
            mask = ImageOps.contain(
                ink, (round(size * 0.72), round(size * 0.72)), Image.Resampling.LANCZOS
            )
            expected = Image.new("RGB", (size, size), (246, 243, 238))
            expected.paste(
                (16, 46, 40), ((size - mask.width) // 2, (size - mask.height) // 2), mask
            )
            with Image.open(ROOT / f"vertente/assets/icon-{size}.png") as icon:
                self.assertEqual(icon.convert("RGB").tobytes(), expected.tobytes())

    def test_generated_shell_is_current_and_never_caches_private_data(self):
        from scripts.build_vertente import build

        self.assertEqual((ROOT / "vertente/service-worker.js").read_text(), build())
        script = (ROOT / "vertente/service-worker.js").read_text()
        self.assertIn("request.method !== 'GET'", script)
        self.assertNotIn("signing.pem", script)
        self.assertNotIn("vastock", script)
        nginx = (ROOT / "deploy/vertente/nginx.conf.template").read_text()
        self.assertIn("ssl_verify_client on;", nginx)
        self.assertIn("location / { return 404; }", nginx)
        self.assertNotIn("proxy_pass", nginx)
