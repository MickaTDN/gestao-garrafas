"""Composed service accounts and restored network activation, no live installation."""

import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from native_windows.install import prepare_acl
from native_windows.windows import SERVICES, activate, stop_all


class IntegratedGatewayTests(TestCase):
    def test_restored_gateway_keys_keep_separate_dacls_and_recovery_envelope_private(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for folder in ("management-wifi", "sheet-receiver"):
                target = root / "secrets" / folder
                target.mkdir(parents=True)
                (target / "server.key").write_text("synthetic")
            (root / "secrets/recovery-envelope.json").write_text("{}")
            with (
                patch("native_windows.install.native"),
                patch("native_windows.install.protect") as protect,
            ):
                prepare_acl(root)
            grants = {args[0]: args[1] for args, _ in protect.call_args_list}
            for folder, account in [("management-wifi", "wifi"), ("sheet-receiver", "receiver")]:
                self.assertEqual(
                    grants[root / "secrets" / folder / "server.key"],
                    [(account, "R"), ("backup", "R")],
                )
            self.assertEqual(grants[root / "secrets/recovery-envelope.json"], [("backup", "R")])
            self.assertEqual(grants[root / "tls"], [("publisher", "R"), ("backup", "R")])

    def test_recovered_runtime_without_approvals_starts_only_local_services(self):
        with tempfile.TemporaryDirectory() as temp:
            with (
                patch("native_windows.windows.exists", return_value=True),
                patch("native_windows.windows.service_state", return_value=4),
                patch("native_windows.windows.native") as call,
            ):
                activate(Path(temp))
            commands = [args[0] for args, _ in call.call_args_list]
            for kind in ("publisher", "receiver", "wifi"):
                self.assertFalse(any(SERVICES[kind] in command for command in commands))
            for kind in ("postgres", "web", "backup"):
                self.assertTrue(any(SERVICES[kind] in command for command in commands))

    def test_shutdown_stops_both_gateways_before_database(self):
        with patch("native_windows.windows.stop") as stop:
            stop_all()
        self.assertEqual(
            [args[0] for args, _ in stop.call_args_list],
            [SERVICES[k] for k in ("wifi", "receiver", "publisher", "backup", "web", "postgres")],
        )
