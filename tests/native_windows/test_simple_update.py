import json
from unittest import TestCase
from unittest.mock import patch

from native_windows.maintenance import UpdateActions
from native_windows.package import UnsafeOperation
from native_windows.state import update, write_json
from tests.native_windows import test_update as fixtures


class AutomaticUpdateTests(TestCase):
    setUp = fixtures.UpdateTests.setUp
    def test_missing_vault_refuses_before_any_service_or_journal_change(self):
        release = self.root / "new/payload"
        release.mkdir(parents=True)
        (release.parent / "package.json").write_text("{}")
        with patch("native_windows.backup_vault.load", side_effect=UnsafeOperation("lost")):
            with self.assertRaisesRegex(UnsafeOperation, "Dados e serviços não foram alterados"):
                UpdateActions(self.root, release)
        self.assertFalse((self.root / "maintenance.json").exists())

    def test_bootstrap_key_stays_in_memory_and_is_checked_before_service_changes(self):
        release = self.root / "new/payload"
        release.mkdir(parents=True)
        (release.parent / "package.json").write_text("{}")
        (self.root / "recovery-public.pem").write_bytes(b"public synthetic")
        with (
            patch(
                "native_windows.backup_vault.load",
                return_value={"pem": "private synthetic", "phrase": "synthetic phrase"},
            ),
            patch("native_windows.portable.envelope") as verify,
        ):
            actions = UpdateActions(self.root, release)
        verify.assert_called_once()
        self.assertEqual(actions.private_pem, b"private synthetic")
        self.assertIsNone(actions.recovery_key)
        self.assertFalse((self.root / "maintenance.json").exists())

    def test_verified_rollback_only_before_migration_boundary(self):
        for phase in ("backup", "migrate", "health", "activate"):
            with self.subTest(phase=phase):
                (self.root / "maintenance.json").unlink(missing_ok=True)
                write_json(self.root / "installation.json", self.state)
                actions = fixtures.Actions(failure=phase)
                actions.rollback_before_migration = lambda: actions.calls.append("safe-rollback")
                with self.assertRaises((RuntimeError, UnsafeOperation)):
                    update(self.root, {"version": "1.1.0"}, actions)
                self.assertEqual("safe-rollback" in actions.calls, phase == "backup")
                self.assertEqual((self.root / "maintenance.json").exists(), phase != "backup")
                if phase == "backup":
                    self.assertEqual(
                        json.loads((self.root / "installation.json").read_text()), self.state
                    )
