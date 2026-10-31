import json
import os
import struct
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from native_windows.package import UnsafeOperation
from native_windows.postgres_process import child_environment, command, startup_failure
from scripts.native.private_crt import REQUIRED, deploy


class PostgresBootstrapTests(TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "runtime/postgres").mkdir(parents=True)
        self.release = self.root / "release"

    def test_private_temp_and_no_inherited_postgres_credentials(self):
        with patch.dict(os.environ, {"PGPASSWORD": "PRIVATE", "PGDATA": "reserved", "TEMP": "external"}):
            env = child_environment(self.root, self.release)
        self.assertNotIn("PGPASSWORD", env)
        self.assertNotIn("PGDATA", env)
        self.assertEqual(env["TEMP"], str(self.root / "runtime/postgres/tmp"))
        self.assertEqual(env["TMP"], env["TEMP"])
        self.assertEqual(env["LC_ALL"], "C")

    def test_missing_runtime_is_classified_without_logging_output_or_secrets(self):
        result = SimpleNamespace(returncode=-1073741515, stdout=b"PRIVATE PASSWORD", stderr=b"PRIVATE TOKEN")
        with patch("native_windows.postgres_process.subprocess.run", return_value=result) as run:
            with self.assertRaisesRegex(UnsafeOperation, "Dependência Windows"):
                command(self.root, self.release, "initdb", ["--version"], timeout=15)
        diagnostic = self.root / "runtime/postgres/startup-diagnostic.json"
        data = json.loads(diagnostic.read_text())
        self.assertEqual(data, {"command": "initdb", "exit_code": -1073741515, "reason": "dependency"})
        self.assertNotIn("PRIVATE", diagnostic.read_text())
        self.assertNotIn("PRIVATE", startup_failure(self.root))
        self.assertEqual(run.call_args.kwargs["cwd"], self.root / "runtime/postgres")
        self.assertTrue(run.call_args.kwargs["capture_output"])

    def test_permission_error_and_timeout_remain_failures(self):
        for error, reason in ((PermissionError(5, "PRIVATE"), "permission"), (subprocess.TimeoutExpired("PRIVATE", 1), "timeout")):
            with self.subTest(reason=reason), patch("native_windows.postgres_process.subprocess.run", side_effect=error):
                with self.assertRaises(UnsafeOperation):
                    command(self.root, self.release, "initdb", [], timeout=1)
            data = json.loads((self.root / "runtime/postgres/startup-diagnostic.json").read_text())
            self.assertEqual(data["reason"], reason)

    def test_diagnostic_reader_rejects_untrusted_fields(self):
        path = self.root / "runtime/postgres/startup-diagnostic.json"
        path.write_text(json.dumps({"reason": "PRIVATE", "exit_code": "PRIVATE"}))
        self.assertNotIn("PRIVATE", startup_failure(self.root))

    def test_success_does_not_create_diagnostic(self):
        result = SimpleNamespace(returncode=0)
        with patch("native_windows.postgres_process.subprocess.run", return_value=result):
            self.assertIs(command(self.root, self.release, "initdb", [], timeout=1), result)
        self.assertFalse((self.root / "runtime/postgres/startup-diagnostic.json").exists())


class PrivateCRTTests(TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.payload = self.root / "payload"
        for folder in ("postgres/bin", "nginx"):
            (self.payload / folder).mkdir(parents=True)
        self.source = self.root / "crt"
        self.source.mkdir()
        data = bytearray(256)
        data[:2] = b"MZ"
        struct.pack_into("<I", data, 0x3C, 128)
        data[128:132] = b"PE\0\0"
        struct.pack_into("<H", data, 132, 0x8664)
        for name in REQUIRED:
            (self.source / name).write_bytes(data)
        self.metadata = {"signers_sha256": ["a" * 64]}

    def test_complete_reviewed_crt_copied_app_local_only(self):
        checked = []
        deploy(self.payload, self.source, self.metadata, verifier=lambda p, s: checked.append(p.name))
        self.assertEqual(set(checked), REQUIRED)
        for folder in ("postgres/bin", "nginx"):
            self.assertEqual({p.name for p in (self.payload / folder).iterdir()}, REQUIRED)
            for name in REQUIRED:
                self.assertEqual((self.payload / folder / name).read_bytes(), (self.source / name).read_bytes())

    def test_missing_dll_wrong_arch_and_untrusted_signer_rejected_before_copy(self):
        file = self.source / "vcruntime140.dll"
        original = file.read_bytes()
        file.unlink()
        with self.assertRaises(UnsafeOperation):
            deploy(self.payload, self.source, self.metadata, verifier=lambda *args: None)
        file.write_bytes(b"not a DLL")
        with self.assertRaises(UnsafeOperation):
            deploy(self.payload, self.source, self.metadata, verifier=lambda *args: None)
        file.write_bytes(original)
        def reject(*args):
            raise UnsafeOperation("Untrusted signer")
        with self.assertRaises(UnsafeOperation):
            deploy(self.payload, self.source, self.metadata, verifier=reject)
        self.assertEqual(list((self.payload / "postgres/bin").iterdir()), [])

    def test_extra_file_and_missing_fingerprints_rejected(self):
        (self.source / "private.txt").write_text("SYNTHETIC SENTINEL")
        with self.assertRaises(UnsafeOperation):
            deploy(self.payload, self.source, self.metadata, verifier=lambda *args: None)
        with self.assertRaises(UnsafeOperation):
            deploy(self.payload, self.source, {}, verifier=lambda *args: None)
