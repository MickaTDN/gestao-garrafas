import json
import os
import struct
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from native_windows.package import UnsafeOperation
from native_windows.postgres_process import child_environment, command, startup_failure
from scripts.native.private_crt import REQUIRED, deploy, verify_microsoft


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

    def test_daemon_launcher_returns_without_waiting_for_inherited_pipe_eof(self):
        # Real child/grandchild processes reproduce Windows pg_ctl's lifetime:
        # launcher exits, daemon keeps inherited handles open until signalled.
        stop = self.root / "daemon-stop"
        done = self.root / "daemon-done"
        daemon = (
            "import pathlib,time; s=pathlib.Path(" + repr(str(stop)) + ");"
            "deadline=time.monotonic()+10;"
            "\nwhile not s.exists() and time.monotonic()<deadline: time.sleep(.01)"
            "\np=pathlib.Path(" + repr(str(done) + ".new") + ");p.touch();p.replace(" + repr(str(done)) + ")"
        )
        # A Windows process holds its working directory open until shutdown.
        # The fixture daemon needs inherited pipes, not a handle on the test
        # directory while TemporaryDirectory cleans up after the done marker.
        parent = "import subprocess,sys;subprocess.Popen([sys.executable,'-c'," + repr(daemon) + "],cwd=sys.prefix)"
        original_run = subprocess.run
        returned = threading.Event()
        errors = []

        def child(*args, **kwargs):
            return original_run([sys.executable, "-c", parent], **kwargs)

        def exercise():
            try:
                with patch("native_windows.postgres_process.subprocess.run", side_effect=child):
                    command(self.root, self.release, "pg_ctl", ["start"], timeout=5)
            except Exception as error:
                errors.append(error)
            finally:
                returned.set()

        worker = threading.Thread(target=exercise)
        worker.start()
        try:
            self.assertTrue(returned.wait(3), "Launcher waited for daemon's inherited pipe EOF")
            self.assertEqual(errors, [])
        finally:
            stop.touch()
            worker.join(15)
        # The daemon is cooperative and bounded; no process is forcibly killed.
        import time
        deadline = time.monotonic() + 3
        while not done.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(done.exists())

    def test_daemon_launcher_failure_remains_a_failure_without_output_capture(self):
        result = SimpleNamespace(returncode=1, stdout=None, stderr=None)
        with patch("native_windows.postgres_process.subprocess.run", return_value=result) as run:
            with self.assertRaises(UnsafeOperation):
                command(self.root, self.release, "pg_ctl", ["start"], timeout=90)
        self.assertEqual(run.call_args.kwargs["stdout"], subprocess.DEVNULL)
        self.assertEqual(run.call_args.kwargs["stderr"], subprocess.DEVNULL)
        self.assertNotIn("capture_output", run.call_args.kwargs)


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

    def test_signer_probe_uses_windows_powershell_without_pwsh_module_paths(self):
        result = SimpleNamespace(returncode=0, stdout=json.dumps({"signer": "a" * 64, "status": "Valid", "microsoft": True}).encode())
        with patch.dict(os.environ, {"PSModulePath": "incompatible-pwsh-modules"}), patch("scripts.native.private_crt.subprocess.run", return_value=result) as run:
            verify_microsoft(self.source / "vcruntime140.dll", ["a" * 64])
        self.assertFalse(any(k.lower() == "psmodulepath" for k in run.call_args.kwargs["env"]))
        self.assertIn("Get-AuthenticodeSignature", run.call_args.args[0][-1])

    def test_current_release_thread_runtime_is_supported_but_not_arbitrary_dlls(self):
        template = (self.source / "vcruntime140.dll").read_bytes()
        (self.source / "vcruntime140_threads.dll").write_bytes(template)
        deploy(self.payload, self.source, self.metadata, verifier=lambda *args: None)
        self.assertTrue((self.payload / "postgres/bin/vcruntime140_threads.dll").is_file())
