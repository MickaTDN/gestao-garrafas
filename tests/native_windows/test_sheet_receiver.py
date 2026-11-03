import json
import secrets
import shutil
import tempfile
import uuid
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from native_windows.package import UnsafeOperation
from native_windows.publisher import render as render_publisher
from native_windows.sheet_receiver import approved, control, prepare_account, render

ROOT = Path(__file__).resolve().parents[2]


class SheetReceiverProfileTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "data"
        self.release = Path(self.temp.name) / "release"
        self.root.mkdir()
        target = self.release / "app/deploy/vertente"
        target.mkdir(parents=True)
        shutil.copyfile(
            ROOT / "deploy/vertente/nginx.conf.template", target / "nginx.conf.template"
        )
        (self.root / "installation.json").write_text(
            json.dumps({"db_port": 55432, "http_port": 8765})
        )
        self.config = {
            "address": "192.168.5.20",
            "hostname": "sheets.synthetic.test",
            "port": 8446,
            "backend_port": 8767,
            "stock_origin": "https://stock.synthetic.test:8444",
            "clients": ["192.168.5.30/32"],
            "proxy_token": secrets.token_hex(32),
            "devices": {"a" * 64: str(uuid.uuid4())},
        }

    def test_receiver_exposes_only_authenticated_post_not_stock_or_admin_routes(self):
        text = render(self.root, self.release, self.config)
        for required in [
            "ssl_verify_client on",
            "ssl_crl",
            "limit_except POST OPTIONS",
            "location = /v1/pending-sheets",
            "proxy_next_upstream off",
            "proxy_set_header X-GVA-Cert $ssl_client_escaped_cert",
            "location / { return 404; }",
            'proxy_set_header Cookie ""',
            "127.0.0.1:8767",
        ]:
            self.assertIn(required, text)
        self.assertNotIn("55432", text)
        self.assertFalse(approved(self.root))

    def test_invalid_addresses_ports_bindings_and_admin_overlap_fail_closed(self):
        for change in [
            {"address": "0.0.0.0"},
            {"clients": ["0.0.0.0/0"]},
            {"backend_port": 55432},
            {"port": 8444},
            {"proxy_token": "bad"},
            {"devices": {}},
            {"hostname": "bad;return 200"},
        ]:
            with (
                self.subTest(change=list(change)),
                self.assertRaises((UnsafeOperation, ValueError)),
            ):
                render(self.root, self.release, {**self.config, **change})
        folder = self.root / "secrets/management-wifi"
        folder.mkdir(parents=True)
        (folder / "config.json").write_text(json.dumps({"port": 8445, "backend_port": 8767}))
        with self.assertRaises(UnsafeOperation):
            render(self.root, self.release, self.config)

    def test_receiver_network_validation_never_reads_the_publishers_tls_folder(self):
        # Real Windows failure: its account must NOT read publisher certificates
        # or even require the public policy through that restricted parent DACL.
        folder = self.root / "tls"
        folder.mkdir()
        (folder / "sheet-transport.public.json").write_text("{}")
        original = Path.read_text

        def restricted(path, *args, **kwargs):
            if path.is_relative_to(folder):
                raise PermissionError("Publisher TLS stays isolated")
            return original(path, *args, **kwargs)

        with patch.object(Path, "read_text", restricted):
            text = render(self.root, self.release, self.config)
        self.assertIn("secrets/sheet-receiver/server.key", text)
        self.assertNotIn("sheet-transport.public.json", text)

    def test_stock_publisher_stays_get_only_and_csp_expands_only_for_approved_origin(self):
        cfg = {**self.config, "hostname": "stock.synthetic.test", "port": 8444}
        before = render_publisher(self.release, self.root, cfg)
        self.assertIn("connect-src 'self';", before)
        self.assertNotIn("proxy_pass", before)
        self.assertIn("limit_except GET", before)
        # File is admin-owned, nonsecret signed policy, readable by the publisher.
        import base64

        folder = self.root / "tls"
        folder.mkdir()
        payload = {
            "stock_origin": self.config["stock_origin"],
            "receiver_origin": "https://sheets.synthetic.test:8446",
        }
        (folder / "sheet-transport.public.json").write_text(
            json.dumps(
                {
                    "payload": base64.urlsafe_b64encode(json.dumps(payload).encode())
                    .decode()
                    .rstrip("=")
                }
            )
        )
        after = render_publisher(self.release, self.root, cfg)
        self.assertIn("connect-src 'self' https://sheets.synthetic.test:8446;", after)
        self.assertNotIn("proxy_pass", after)
        self.assertIn("limit_except GET", after)

    def test_activation_requires_explicit_it_approval_and_failure_removes_marker(self):
        (self.root / "runtime/receiver").mkdir(parents=True)
        with (
            patch("native_windows.sheet_receiver.administrator"),
            patch("native_windows.sheet_receiver.stop"),
            patch("native_windows.sheet_receiver.native"),
        ):
            with self.assertRaises(UnsafeOperation):
                control(self.root, {"enable": True})
            self.assertFalse(approved(self.root))
            with patch("native_windows.windows.service_state", return_value=1):
                with self.assertRaises(UnsafeOperation):
                    control(self.root, {"enable": True, "it_network_ready": True})
            self.assertFalse(approved(self.root))
            with patch("native_windows.windows.service_state", return_value=4):
                control(self.root, {"enable": True, "it_network_ready": True})
            self.assertTrue(approved(self.root))
            control(self.root, {"enable": False})
            self.assertFalse(approved(self.root))

    def test_opt_in_on_older_installation_adds_only_exact_receiver_read_grants(self):
        with patch("native_windows.sheet_receiver.native") as command:
            prepare_account(self.root)
        self.assertEqual(command.call_count, 8)
        for args in command.call_args_list:
            text = " ".join(args.args[0])
            self.assertNotIn("owner.json", text)
            self.assertNotIn("recovery", text)
            self.assertNotIn("(OI)", text)
            self.assertNotIn("/inheritance", text)
            self.assertIn("NT SERVICE\\GVASheetReceiver:", text)
