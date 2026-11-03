import base64
import importlib.util
import json
import shutil
import tempfile
import uuid
from pathlib import Path
from unittest import TestCase, skipUnless
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
            {"address": "0.0.0.0"},
            {"clients": ["0.0.0.0/0"]},
            {"port": True},
        ):
            with self.assertRaises((UnsafeOperation, ValueError)):
                render(self.root, self.root, {**self.config, **changes})

    def test_private_publisher_policy_and_certificates_need_no_management_read_access(self):
        folder = self.root / "tls"
        folder.mkdir()
        for name in ("sheet-transport.public.json", "server.key", "server-chain.crt"):
            (folder / name).write_text("synthetic inaccessible publisher file")
        original = Path.read_text

        def restricted(path, *args, **kwargs):
            # Model the real separate virtual-service DACL. Do not hide the
            # validator behind mocks: only the installation marker is readable.
            if path != self.root / "installation.json":
                raise PermissionError("Publisher content stays inaccessible")
            return original(path, *args, **kwargs)

        with patch.object(Path, "read_text", restricted):
            text = render(self.root, self.root, self.config)
        self.assertIn("secrets/management-wifi/server.key", text)
        self.assertNotIn("sheet-transport.public.json", text)
        self.assertNotIn(str(folder / "server.key").replace("\\", "/"), text)

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

    @skipUnless(
        importlib.util.find_spec("native_windows.sheet_receiver"),
        "Only in the disposable PR34 composition",
    )
    def test_pr34_composition_keeps_three_renderers_and_their_tls_access_separate(self):
        from native_windows.publisher import render as publisher
        from native_windows.sheet_receiver import render as receiver

        release = self.root / "release"
        template = release / "app/deploy/vertente"
        template.mkdir(parents=True)
        shutil.copyfile(
            Path(__file__).resolve().parents[2] / "deploy/vertente/nginx.conf.template",
            template / "nginx.conf.template",
        )
        tls = self.root / "tls"
        tls.mkdir()
        policy = {
            "stock_origin": "https://stock.synthetic.test:8444",
            "receiver_origin": "https://sheets.synthetic.test:8446",
        }
        (tls / "sheet-transport.public.json").write_text(
            json.dumps(
                {
                    "payload": base64.urlsafe_b64encode(json.dumps(policy).encode())
                    .decode()
                    .rstrip("=")
                }
            )
        )
        config = {
            **self.config,
            "hostname": "sheets.synthetic.test",
            "port": 8446,
            "backend_port": 8767,
            "stock_origin": policy["stock_origin"],
            "devices": {"b" * 64: str(uuid.uuid4())},
        }
        original = Path.read_text

        def restricted(path, *args, **kwargs):
            if path.is_relative_to(tls):
                raise PermissionError("Publisher TLS belongs only to the publisher")
            return original(path, *args, **kwargs)

        with patch.object(Path, "read_text", restricted):
            administrative = render(self.root, release, self.config)
            reception = receiver(self.root, release, config)
        stock = publisher(
            release, self.root, {**self.config, "hostname": "stock.synthetic.test", "port": 8444}
        )
        self.assertIn("secrets/management-wifi/server.key", administrative)
        self.assertIn("secrets/sheet-receiver/server.key", reception)
        self.assertIn("tls/server.key", stock)
        self.assertIn("127.0.0.1:8766", administrative)
        self.assertIn("127.0.0.1:8767", reception)
        self.assertNotIn("proxy_pass", stock)
        self.assertIn("connect-src 'self' https://sheets.synthetic.test:8446;", stock)
