import base64
import json
import os
import tempfile
from pathlib import Path
from unittest import TestCase

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from native_windows.crypto_backup import create_recovery_key, decrypt, encrypt
from native_windows.package import UnsafeOperation
from native_windows.portable import decrypt_backup, demo_material, envelope, header, unlock


class PortableTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_phrase = "synthetic legacy recovery phrase"
        cls.password = "synthetic portable recovery phrase"
        cls.private, cls.public = create_recovery_key(cls.old_phrase)
        cls.wrapped = envelope(cls.private, cls.old_phrase, cls.password, cls.public)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "database"
        self.source.write_bytes(os.urandom(12000))
        self.backup = self.root / "test.gvabackup"
        encrypt(
            self.source,
            self.backup,
            self.public,
            {"version": "1.1.0"},
            recovery_envelope=self.wrapped,
        )

    def test_single_file_restores_with_credential_and_preserves_legacy_key(self):
        target = self.root / "restored"
        result = decrypt_backup(self.backup, target, {"credential": self.password}, "synthetic")
        self.assertEqual(result["version"], "1.1.0")
        self.assertEqual(target.read_bytes(), self.source.read_bytes())
        decrypt(self.backup, self.root / "legacy", self.private, self.old_phrase)
        self.assertEqual((self.root / "legacy").read_bytes(), self.source.read_bytes())
        self.assertNotIn(self.password.encode(), self.backup.read_bytes())
        self.assertNotIn(self.private, self.backup.read_bytes())

    def test_wrong_credential_tampering_and_truncation_publish_nothing(self):
        original = self.backup.read_bytes()
        for content, password in (
            (original, "wrong credential of valid length"),
            (original[:-3], self.password),
            (original[:-50] + bytes([original[-50] ^ 1]) + original[-49:], self.password),
        ):
            with self.subTest(length=len(content)):
                self.backup.write_bytes(content)
                with self.assertRaises(UnsafeOperation):
                    decrypt_backup(
                        self.backup, self.root / "out", {"credential": password}, "synthetic"
                    )
                self.assertFalse((self.root / "out").exists())
                self.assertFalse((self.root / "out.partial").exists())

    def test_wrong_original_key_or_weak_password_cannot_enable_portability(self):
        _, other = create_recovery_key(self.old_phrase)
        for public, password in ((other, self.password), (self.public, "weak")):
            with self.assertRaises(UnsafeOperation):
                envelope(self.private, self.old_phrase, password, public)

    def test_tampered_envelope_and_unsupported_version_rejected(self):
        for value in (
            {**self.wrapped, "version": 99},
            {**self.wrapped, "nonce": "AAAA"},
            {**self.wrapped, "ciphertext": "AAAA"},
        ):
            with self.assertRaises(UnsafeOperation):
                unlock(value, self.password)

    def kit(self):
        code, nonce = os.urandom(32), os.urandom(12)
        data = {
            "Username": "synthetic",
            "Password": "not-used-for-restore",
            "PrivateKey": base64.b64encode(self.private).decode(),
            "RecoveryPassword": self.old_phrase,
        }
        cipher = AESGCM(code).encrypt(nonce, json.dumps(data).encode(), b"gva-synthetic-kit-v1")
        path = self.root / "original.gvademo"
        path.write_text(
            json.dumps(
                {
                    "format": "gva-synthetic-kit",
                    "version": 1,
                    "nonce": base64.b64encode(nonce).decode(),
                    "ciphertext": base64.b64encode(cipher[:-16]).decode(),
                    "tag": base64.b64encode(cipher[-16:]).decode(),
                }
            )
        )
        return path, base64.b64encode(code).decode()

    def test_original_dotnet_kit_restores_legacy_backup_without_pem_file(self):
        kit, code = self.kit()
        legacy = self.root / "old.gvabackup"
        encrypt(self.source, legacy, self.public, {})
        original = kit.read_bytes()
        decrypt_backup(
            legacy, self.root / "out", {"demo_kit": str(kit), "credential": code}, "synthetic"
        )
        self.assertEqual((self.root / "out").read_bytes(), self.source.read_bytes())
        self.assertEqual(kit.read_bytes(), original)
        self.assertEqual(list(self.root.glob("*.pem")), [])

    def test_kit_wrong_code_production_and_missing_legacy_key_fail_closed(self):
        kit, code = self.kit()
        for channel, credential in (
            ("release", code),
            ("synthetic", base64.b64encode(os.urandom(32)).decode()),
        ):
            with self.assertRaises(UnsafeOperation):
                demo_material(kit, credential, channel)
        legacy = self.root / "old.gvabackup"
        encrypt(self.source, legacy, self.public, {})
        with self.assertRaisesRegex(UnsafeOperation, "backup antigo exige"):
            decrypt_backup(legacy, self.root / "out", {"credential": self.password}, "synthetic")

    def test_preexisting_partial_is_not_deleted_by_failed_encryption_or_decryption(self):
        target = self.root / "occupied"
        partial = self.root / "occupied.partial"
        partial.write_bytes(b"previous-private-data")
        with self.assertRaises(FileExistsError):
            encrypt(self.source, target, self.public, {})
        self.assertEqual(partial.read_bytes(), b"previous-private-data")
        with self.assertRaises(UnsafeOperation):
            decrypt(self.backup, target, self.private, self.old_phrase)
        self.assertEqual(partial.read_bytes(), b"previous-private-data")


class PortableHeaderTests(TestCase):
    def test_invalid_header_is_sanitized_and_never_echoes_private_input(self):
        import struct

        from native_windows.crypto_backup import MAGIC

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.gvabackup"
            for value in (
                b"PRIVATE SENTINEL",
                MAGIC + struct.pack(">I", 131072),
                MAGIC + struct.pack(">I", 2) + b"[]",
                MAGIC + struct.pack(">I", 14) + b"PRIVATE VALUE!",
            ):
                path.write_bytes(value)
                with self.assertRaises(UnsafeOperation) as caught:
                    header(path)
                self.assertNotIn("PRIVATE", str(caught.exception))
                self.assertEqual(path.read_bytes(), value)
