"""Exercise Windows encodings and failure reporting without installing anything."""

import io
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from tests.native_windows.windows_smoke import SMOKE_SUCCESS, log, report_failure, run


class SmokeDiagnosticTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.host = self.root / "host-error.txt"

    def test_final_success_message_in_real_cp1252_subprocess(self):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from tests.native_windows.windows_smoke import SMOKE_SUCCESS,log;"
                "log(SMOKE_SUCCESS)",
            ],
            env={**os.environ, "PYTHONIOENCODING": "cp1252:strict", "PYTHONUTF8": "0"},
            capture_output=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.decode("cp1252").strip(), SMOKE_SUCCESS)
        self.assertIn("1.0->1.1", SMOKE_SUCCESS)

    def test_unicode_diagnostics_preserve_information_in_supported_encodings(self):
        message = "Recuperação 1.0\u21921.1 — falha \u2603"
        for encoding in ("cp1252", "ascii", "utf-8"):
            with self.subTest(encoding=encoding):
                buffer = io.BytesIO()
                with io.TextIOWrapper(buffer, encoding=encoding, errors="strict") as stream:
                    with patch("sys.stdout", stream):
                        log(message)
                    self.assertEqual(
                        buffer.getvalue().decode(encoding).strip(),
                        message.encode(encoding, "backslashreplace").decode(encoding),
                    )

    def test_failure_reporting_retains_original_failure_and_journal_under_cp1252(self):
        (self.root / "maintenance.json").write_text(
            '{"phase":"synthetic-recovery-failure"}', encoding="utf-8"
        )
        self.host.write_text("stale downgrade refusal", encoding="utf-8")
        buffer = io.BytesIO()
        with io.TextIOWrapper(buffer, encoding="cp1252", errors="strict") as stream:
            with patch("sys.stderr", stream):
                report_failure(RuntimeError("restauro \u2192 falhou"), self.root)
            text = buffer.getvalue().decode("cp1252")
        self.assertIn("RuntimeError: restauro \\u2192 falhou", text)
        self.assertIn("synthetic-recovery-failure", text)
        self.assertNotIn("stale downgrade refusal", text)

    def test_string_stream_without_an_encoding(self):
        with patch("sys.stdout", new_callable=io.StringIO) as stream:
            log("1.0\u21921.1")
            self.assertEqual(stream.getvalue(), "1.0\u21921.1\n")

    def test_current_host_error_is_attached_only_to_its_failed_child(self):
        def failed_child(*args, **kwargs):
            self.assertFalse(self.host.exists())
            self.host.write_text("Recuperação recusada", encoding="utf-8-sig")
            return subprocess.CompletedProcess(args, 1)

        self.host.write_text("old downgrade refusal", encoding="utf-8")
        with patch("subprocess.run", side_effect=failed_child):
            with self.assertRaisesRegex(RuntimeError, "current host error=Recuperação recusada"):
                run(["synthetic.exe"], error_log=self.host)

    def test_stale_host_error_is_not_attached_to_an_unrelated_failure(self):
        self.host.write_text("old downgrade refusal", encoding="utf-8")
        with patch("subprocess.run", return_value=subprocess.CompletedProcess([], 7)):
            with self.assertRaisesRegex(RuntimeError, "exit=7$"):
                run(["synthetic.exe"], error_log=self.host)
        self.assertFalse(self.host.exists())

    def test_expected_downgrade_refusal_does_not_contaminate_next_success(self):
        def refused_child(*args, **kwargs):
            self.host.write_text("expected downgrade refusal", encoding="utf-8")
            return subprocess.CompletedProcess(args, 1)

        with patch("subprocess.run", side_effect=refused_child):
            run(["old.exe"], error_log=self.host, expect_failure=True)
        with patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0)):
            run(["recovery.exe"], error_log=self.host)
        self.assertFalse(self.host.exists())

    def test_expected_refusal_must_actually_fail(self):
        with patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0)):
            with self.assertRaisesRegex(RuntimeError, "exit=0"):
                run(["old.exe"], expect_failure=True)

    def test_unexpected_failure_still_fails_and_explicit_timeout_is_honoured(self):
        with patch("subprocess.run", return_value=subprocess.CompletedProcess([], 2)) as child:
            with self.assertRaisesRegex(RuntimeError, "exit=2"):
                run(["recovery.exe"], timeout=120)
        self.assertEqual(child.call_args.kwargs["timeout"], 120)

    def test_child_timeout_is_not_reported_as_success(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("recovery.exe", 120)):
            with self.assertRaises(subprocess.TimeoutExpired):
                run(["recovery.exe"], timeout=120)
