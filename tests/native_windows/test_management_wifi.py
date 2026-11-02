import json
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from native_windows.management_wifi import approved, render, setup
from native_windows.package import UnsafeOperation


class ManagementWifiTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "installation.json").write_text(
            json.dumps({"db_port": 55432, "http_port": 8765})
        )
        self.config = {
            "address": "192.168.20.10",
            "hostname": "gestao.example.internal",
            "port": 8443,
            "backend_port": 8766,
            "clients": ["192.168.20.50/32"],
            "proxy_token": "a" * 64,
        }

    def test_defaults_off_and_runtime_approval_not_inside_backup_secrets(self):
        self.assertFalse(approved(self.root))
        (self.root / "runtime/wifi").mkdir(parents=True)
        (self.root / "runtime/wifi/approved").write_text("approved")
        self.assertTrue(approved(self.root))

    def test_render_separates_stock_and_never_retries_mutating_requests(self):
        with patch("native_windows.publisher.render"):
            text = render(self.root, self.root, self.config)
        self.assertIn("proxy_next_upstream off", text)
        self.assertIn("ssl_verify_client on", text)
        self.assertIn("ssl_crl ", text)
        self.assertIn("127.0.0.1:8766", text)
        self.assertNotIn("55432", text)
        self.assertIn('proxy_set_header X-Forwarded-For ""', text)
        self.assertNotIn("/srv/vertente", text)

    def test_backend_port_collision_and_injection_refused(self):
        for changes in (
            {"backend_port": 55432},
            {"backend_port": 8765},
            {"hostname": "bad;return 200;"},
            {"proxy_token": "untrusted"},
        ):
            with patch("native_windows.publisher.render"), self.assertRaises(UnsafeOperation):
                render(self.root, self.root, {**self.config, **changes})

    def test_configuration_requires_explicit_approval_before_any_service_change(self):
        path = self.root / "request.json"
        path.write_text("{}")
        with (
            patch("native_windows.management_wifi.administrator"),
            patch("native_windows.management_wifi.configure") as configure,
        ):
            with self.assertRaises(UnsafeOperation):
                setup(self.root, {"configuration": str(path)})
            configure.assert_not_called()
