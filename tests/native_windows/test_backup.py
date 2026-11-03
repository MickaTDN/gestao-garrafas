import io
import json
import tarfile
import tempfile
from pathlib import Path
from unittest import TestCase

from native_windows.crypto_backup import create_recovery_key, decrypt, encrypt
from native_windows.maintenance import extract_verified, matching_evidence, verify_archive
from native_windows.package import UnsafeOperation, regular_tree


class BackupTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private, cls.public = create_recovery_key("synthetic long recovery phrase")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "plain"
        self.source.write_bytes(b"synthetic-database-and-keys" * 10000)
        self.encrypted = self.root / "encrypted"

    def test_authenticated_roundtrip_and_keys_not_in_encrypted_bytes(self):
        encrypt(self.source, self.encrypted, self.public, {"version": "1.0.0"})
        self.assertNotIn(b"synthetic-database-and-keys", self.encrypted.read_bytes())
        destination = self.root / "restored"
        self.assertEqual(
            decrypt(self.encrypted, destination, self.private, "synthetic long recovery phrase"),
            {"version": "1.0.0"},
        )
        self.assertEqual(destination.read_bytes(), self.source.read_bytes())

    def test_wrong_password_tampering_truncation_never_publish_partial(self):
        encrypt(self.source, self.encrypted, self.public, {})
        original = self.encrypted.read_bytes()
        for data, password in (
            (original, "wrong password"),
            (original[:-1], "synthetic long recovery phrase"),
            (original[:-20] + b"tampered" + original[-12:], "synthetic long recovery phrase"),
        ):
            self.encrypted.write_bytes(data)
            target = self.root / "output"
            with self.assertRaises(UnsafeOperation):
                decrypt(self.encrypted, target, self.private, password)
            self.assertFalse(target.exists())
            self.assertFalse(target.with_suffix(".partial").exists())

    def test_preserves_existing_destination_and_requires_strong_recovery_phrase(self):
        with self.assertRaises(UnsafeOperation):
            create_recovery_key("short")
        self.encrypted.write_bytes(b"existing")
        with self.assertRaises(UnsafeOperation):
            encrypt(self.source, self.encrypted, self.public, {})
        self.assertEqual(self.encrypted.read_bytes(), b"existing")

    def archive(self, entries):
        path = self.root / "test.tar"
        with tarfile.open(path, "w") as handle:
            for name, value in entries:
                info = tarfile.TarInfo(name)
                info.size = len(value)
                handle.addfile(info, io.BytesIO(value))
        return path

    def test_verified_archive_and_safe_new_directory_extraction(self):
        data = self.root / "data"
        data.mkdir()
        (data / "database.dump").write_bytes(b"synthetic-dump")
        manifest = {"schema": 1, "files": regular_tree(data)}
        path = self.archive(
            [("database.dump", b"synthetic-dump"), ("manifest.json", json.dumps(manifest).encode())]
        )
        self.assertEqual(verify_archive(path), manifest)
        target = self.root / "new"
        extract_verified(path, target)
        self.assertEqual((target / "database.dump").read_bytes(), b"synthetic-dump")
        with self.assertRaises(UnsafeOperation):
            extract_verified(path, target)

    def test_rejects_archive_paths_duplicates_and_corruption(self):
        import hashlib

        for name in (
            "../secret",
            "secrets/../../evil",
            "C:/evil",
            "/evil",
            "secrets\\bad",
            "unexpected.bin",
        ):
            raw = b"x"
            manifest = {
                "schema": 1,
                "files": {
                    "database.dump": {"size": 1, "sha256": hashlib.sha256(raw).hexdigest()},
                    name: {"size": 1, "sha256": hashlib.sha256(raw).hexdigest()},
                },
            }
            path = self.archive(
                [
                    ("database.dump", raw),
                    (name, raw),
                    ("manifest.json", json.dumps(manifest).encode()),
                ]
            )
            with self.subTest(name=name), self.assertRaises(UnsafeOperation):
                verify_archive(path)

    def test_sequence_reservations_can_advance_without_changing_snapshot_rows(self):
        expected = {
            "rows": {"sha256": "stable", "rows": 3},
            "__sequences__": [["public", "example_seq", 5]],
        }
        self.assertTrue(
            matching_evidence(
                {**expected, "__sequences__": [["public", "example_seq", 7]]}, expected
            )
        )
        self.assertTrue(matching_evidence(expected, expected))

    def test_restore_evidence_rejects_changed_rows_missing_or_backwards_sequences(self):
        expected = {
            "rows": {"sha256": "stable", "rows": 3},
            "__sequences__": [["public", "example_seq", 5]],
        }
        for actual in (
            {**expected, "rows": {"sha256": "altered", "rows": 3}},
            {**expected, "__sequences__": []},
            {**expected, "__sequences__": [["public", "example_seq", 4]]},
            {**expected, "__sequences__": [["public", "example_seq", None]]},
        ):
            with self.subTest(actual=actual):
                self.assertFalse(matching_evidence(actual, expected))


class RetentionTests(TestCase):
    def test_retention_preserves_legacy_and_last_restore_verified_anchor(self):
        import os

        from native_windows.maintenance import prune_backups
        from native_windows.package import digest

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = []
            for number in range(5):
                path = root / f"gva-{number}.gvabackup"
                path.write_bytes(f"synthetic-{number}".encode())
                os.utime(path, (number + 1, number + 1))
                paths.append(path)
                if number:
                    path.with_suffix(".sha256.json").write_text(
                        json.dumps(
                            {
                                "size": path.stat().st_size,
                                "sha256": digest(path),
                                "authenticated": True,
                                "restore_verified": number == 1,
                            }
                        )
                    )
            prune_backups(root, 2)
            self.assertEqual([p.exists() for p in paths], [True, True, False, True, True])

    def test_modified_receipt_or_backup_is_not_an_authorisation_to_delete(self):
        from native_windows.maintenance import prune_backups

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "gva-old.gvabackup"
            path.write_bytes(b"only-existing-copy")
            path.with_suffix(".sha256.json").write_text(
                json.dumps({"authenticated": True, "sha256": "incorrect", "size": 18})
            )
            prune_backups(root, 2)
            self.assertEqual(path.read_bytes(), b"only-existing-copy")
