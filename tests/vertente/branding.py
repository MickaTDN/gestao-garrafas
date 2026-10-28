import hashlib
import json
from pathlib import Path

from django.test import SimpleTestCase
from PIL import Image

from scripts.build_brand_icons import BRAND_ROOT, SYMBOL

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
        # Anchor the approved raster and every approved icon pixel. Re-rendering
        # with a newer Pillow can change resampling; that must not force a change
        # to already approved artwork merely to upgrade a security dependency.
        self.assertEqual(
            hashlib.sha256((BRAND_ROOT / SYMBOL).read_bytes()).hexdigest(),
            "e78fb04f5d1e027aa7803c347292cb935e8e021e470299cea2cf0d2242edf567",
        )
        approved_pixels = {
            192: "59680d1851434fa3582bbfa987530ce611cbfc64b07e0c03237f4589b6a51445",
            512: "74d3800632de60c14e0c000c56283c4ba05b73a801ce571063951bc8c7b092ef",
        }
        for size, expected in approved_pixels.items():
            with Image.open(ROOT / f"vertente/assets/icon-{size}.png") as icon:
                self.assertEqual(icon.size, (size, size))
                self.assertEqual(hashlib.sha256(icon.convert("RGB").tobytes()).hexdigest(), expected)

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
