import json
import os
import tempfile
from pathlib import Path
from unittest import TestCase, skipUnless
from unittest.mock import patch

from native_windows import backup_vault
from native_windows.backup_wizard import configure_credential, credential_status
from native_windows.package import UnsafeOperation


class BackupCredentialTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "secrets").mkdir()
        (self.root / "secrets/recovery-envelope.json").write_text('{"old":"immutable"}')

    def test_existing_envelope_is_verified_and_never_replaced(self):
        path = self.root / "secrets/recovery-envelope.json"
        original = path.read_bytes()
        with (
            patch("native_windows.backup_wizard.administrator"),
            patch("native_windows.backup_wizard.unlock") as unlock,
            patch("native_windows.backup_vault.save") as save,
        ):
            configure_credential(
                self.root, {"portable_password": "synthetic phrase longer than 16"}
            )
            unlock.assert_called_once()
            save.assert_called_once_with(self.root, {"password": "synthetic phrase longer than 16"})
        self.assertEqual(path.read_bytes(), original)

    def test_wrong_phrase_cannot_replace_vault_or_existing_envelope(self):
        with (
            patch("native_windows.backup_wizard.administrator"),
            patch("native_windows.backup_wizard.unlock", side_effect=UnsafeOperation("incorrect")),
            patch("native_windows.backup_vault.save") as save,
        ):
            with self.assertRaises(UnsafeOperation):
                configure_credential(self.root, {"portable_password": "wrong"})
            save.assert_not_called()
        self.assertEqual(
            json.loads((self.root / "secrets/recovery-envelope.json").read_text()),
            {"old": "immutable"},
        )

    def test_missing_vault_requires_original_phrase_and_not_silent_replacement(self):
        with (
            patch("native_windows.backup_wizard.administrator"),
            patch("native_windows.backup_vault.load", side_effect=UnsafeOperation("lost")),
        ):
            self.assertEqual(
                credential_status(self.root), {"configured": False, "bootstrap": False}
            )

    @skipUnless(os.name == "nt", "Real Windows DPAPI required")
    def test_machine_dpapi_roundtrip_and_tampering(self):
        secret = b"unique synthetic credential"
        cipher = backup_vault.crypt(secret)
        self.assertNotIn(secret, cipher)
        self.assertEqual(backup_vault.crypt(cipher, decrypt=True), secret)
        with self.assertRaises(UnsafeOperation):
            backup_vault.crypt(cipher[:-12] + b"altered data", decrypt=True)
