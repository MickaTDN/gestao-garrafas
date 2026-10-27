import json
import tempfile
from pathlib import Path
from unittest import TestCase

from native_windows.package import UnsafeOperation
from native_windows.state import exclusive, update, write_json


class Actions:
    release = "new-version"
    package_sha256 = "synthetic-new-package-hash"

    def __init__(self, failure=None):
        self.failure, self.calls = failure, []

    def do(self, name):
        self.calls.append(name)
        if name == self.failure:
            raise RuntimeError("synthetic interruption")

    def disable(self):
        self.do("disable")

    def stop(self):
        self.do("stop")

    def backup_and_restore_check(self):
        self.do("backup")

    def migrate(self):
        self.do("migrate")

    def health(self):
        self.do("health")

    def activate(self):
        self.do("activate")


class UpdateTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state = {
            "version": "1.0.0",
            "channel": "synthetic",
            "instance": "stable-identity",
            "release": "old",
            "database": "synthetic-database",
        }
        write_json(self.root / "installation.json", self.state)

    def test_order_verified_restore_precedes_migration_and_identity_preserved(self):
        actions = Actions()
        update(self.root, {"version": "1.1.0"}, actions)
        self.assertEqual(
            actions.calls, ["disable", "stop", "backup", "migrate", "health", "activate"]
        )
        final = json.loads((self.root / "installation.json").read_text())
        self.assertEqual(
            final,
            {
                **self.state,
                "version": "1.1.0",
                "release": "new-version",
                "package_sha256": actions.package_sha256,
            },
        )
        self.assertFalse((self.root / "maintenance.json").exists())
        self.assertEqual(len(list(self.root.glob("update-*.json"))), 1)

    def test_failure_at_every_phase_prevents_restart_and_never_runs_inverse_migrations(self):
        for phase in ("disable", "stop", "backup", "migrate", "health", "activate"):
            with self.subTest(phase=phase):
                (self.root / "maintenance.json").unlink(missing_ok=True)
                write_json(self.root / "installation.json", self.state)
                actions = Actions(failure=phase)
                with self.assertRaises(RuntimeError):
                    update(self.root, {"version": "1.1.0"}, actions)
                self.assertTrue(json.loads((self.root / "maintenance.json").read_text())["failed"])
                self.assertNotIn("reverse", actions.calls)
                if phase == "backup":
                    self.assertNotIn("migrate", actions.calls)
                with self.assertRaises(UnsafeOperation):
                    update(self.root, {"version": "1.1.0"}, Actions())

    def test_os_lock_prevents_two_incompatible_instances_and_releases_on_failure(self):
        with exclusive(self.root):
            with self.assertRaises(UnsafeOperation):
                with exclusive(self.root):
                    self.fail("lock must fail")
        with exclusive(self.root):
            pass
