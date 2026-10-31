"""Service failure evidence stays useful without exposing raw exceptions or SQL."""

import json
import sys
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from native_windows import cli
from native_windows.package import UnsafeOperation
from native_windows.postgres_process import startup_failure
from native_windows.windows import SERVICES, activate, native, service_failure


class ServiceDiagnosticTests(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        for kind in SERVICES:
            (self.root / "runtime" / kind).mkdir(parents=True)

    def test_service_exception_keeps_category_and_basename_without_raw_message(self):
        error = PermissionError(13, "PRIVATE SQL PASSWORD TOKEN", "/private/installation.json")
        with patch.object(cli, "data_root", return_value=self.root), patch(
            "sys.argv", ["cli", "service", "--kind", "web", "--stop-file", str(self.root / "stop")]
        ), patch("native_windows.runtime.service", side_effect=error):
            with self.assertRaises(PermissionError):
                cli.main()
        content = (self.root / "runtime/web/failure.json").read_text()
        self.assertEqual(json.loads(content), {"category": "PermissionError", "file": "installation.json", "errno": 13})
        self.assertNotIn("PRIVATE", content)
        self.assertNotIn("/private", content)

    def test_non_utf8_windows_utility_output_never_changes_exit_status(self):
        # Simulate localized sc/icacls bytes under the UTF-8 installer host.
        script = "import sys;sys.stdout.buffer.write(bytes([0x80,0xe7]));sys.exit(0)"
        self.assertEqual(native([sys.executable, "-c", script]).returncode, 0)
        with self.assertRaisesRegex(UnsafeOperation, "código 7"):
            native([sys.executable, "-c", script.replace("sys.exit(0)", "sys.exit(7)")])

    def test_diagnostic_reader_ignores_unknown_values_and_malformed_shape(self):
        path = self.root / "runtime/web/failure.json"
        for record in (["PRIVATE"], {"category": "PRIVATE SQL TOKEN"}, {"category": "PermissionError", "file": "../PRIVATE KEY"}):
            with self.subTest(record=record):
                path.write_text(json.dumps(record))
                result = service_failure(self.root, "web")
                self.assertNotIn("PRIVATE", result)
        (self.root / "runtime/postgres/startup-diagnostic.json").write_text("[]")
        self.assertIn("diagnóstico", startup_failure(self.root))

    def test_activation_reports_failed_service_without_activating_dependants(self):
        (self.root / "runtime/postgres/failure.json").write_text('{"category":"PermissionError"}')
        with patch("native_windows.windows.exists", return_value=True), patch(
            "native_windows.windows.service_state", side_effect=[1, 1]
        ), patch("native_windows.windows.native") as call:
            with self.assertRaisesRegex(UnsafeOperation, "postgres.*PermissionError"):
                activate(self.root)
        self.assertFalse(any(SERVICES["web"] in args[0] for args, _ in call.call_args_list))

    def test_activation_waits_for_readiness_instead_of_treating_pending_as_ready(self):
        with patch("native_windows.windows.exists", side_effect=lambda name: name == SERVICES["postgres"]), patch(
            "native_windows.windows.service_state", side_effect=[1, 2, 4]
        ), patch("native_windows.windows.native") as call, patch("native_windows.windows.time.sleep") as pause:
            activate(self.root)
        pause.assert_called_once_with(1)
        self.assertEqual(call.call_args.args[0], ["sc.exe", "start", SERVICES["postgres"]])
