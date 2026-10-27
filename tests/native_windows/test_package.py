import base64
import json
import tempfile
from pathlib import Path
from unittest import TestCase

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from native_windows.package import (
    CONTEXT,
    UnsafeOperation,
    refuse_reparse,
    regular_tree,
    verify,
    version,
)


class PackageTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bundle = self.root / "package"
        self.bundle.mkdir()
        for name in (
            "python/python.exe",
            "postgres/bin/postgres.exe",
            "postgres/bin/pg_dump.exe",
            "postgres/bin/pg_restore.exe",
            "app/manage.py",
            "host/GVA.Native.exe",
            "nginx/nginx.exe",
        ):
            path = self.bundle / "payload" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"synthetic-fixture-not-an-executable")
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.trust = self.root / "trust.json"
        self.trust.write_text(
            json.dumps(
                {
                    "channel": "synthetic",
                    "public_key": self.key.public_key()
                    .public_bytes(
                        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
                    )
                    .decode(),
                }
            )
        )
        self.manifest = {
            "schema": 1,
            "version": "1.1.0",
            "minimum_version": "1.0.0",
            "postgres_major": 17,
            "channel": "synthetic",
            "files": regular_tree(self.bundle / "payload"),
        }
        self.sign()

    def sign(self, key=None):
        raw = json.dumps(self.manifest).encode()
        (self.bundle / "package.json").write_bytes(raw)
        (self.bundle / "package.sig").write_bytes(
            base64.b64encode((key or self.key).sign(CONTEXT + raw, ec.ECDSA(hashes.SHA256())))
        )

    def test_valid_authenticated_update_10_to_11(self):
        self.assertEqual(
            verify(self.bundle, self.trust, {"version": "1.0.0", "channel": "synthetic"})[
                "version"
            ],
            "1.1.0",
        )

    def test_rejects_tampering_missing_extra_and_replaced_payload(self):
        path = self.bundle / "payload/app/manage.py"
        path.write_bytes(b"tampered")
        with self.assertRaises(UnsafeOperation):
            verify(self.bundle, self.trust)
        path.unlink()
        with self.assertRaises(UnsafeOperation):
            verify(self.bundle, self.trust)
        path.write_bytes(b"synthetic-fixture-not-an-executable")
        (path.parent / "extra.py").write_text("bad")
        with self.assertRaises(UnsafeOperation):
            verify(self.bundle, self.trust)

    def test_rejects_wrong_signer_and_modified_manifest(self):
        self.sign(ec.generate_private_key(ec.SECP256R1()))
        with self.assertRaises(UnsafeOperation):
            verify(self.bundle, self.trust)
        self.sign()
        (self.bundle / "package.json").write_bytes(
            (self.bundle / "package.json").read_bytes() + b" "
        )
        with self.assertRaises(UnsafeOperation):
            verify(self.bundle, self.trust)

    def test_rejects_old_repeat_incompatible_channel_and_postgres(self):
        for installed in (
            {"version": "1.1.0", "channel": "synthetic"},
            {"version": "2.0.0", "channel": "synthetic"},
            {"version": "0.9.0", "channel": "synthetic"},
            {"version": "1.0.0", "channel": "release"},
        ):
            with self.subTest(installed=installed), self.assertRaises(UnsafeOperation):
                verify(self.bundle, self.trust, installed)
        self.manifest["postgres_major"] = 18
        self.sign()
        with self.assertRaises(UnsafeOperation):
            verify(self.bundle, self.trust)

    def test_strict_semantic_versions(self):
        for value in ("1.01.0", "1.0", "-1.0.0", "1.0.0-dev", 1, None):
            with self.subTest(value=value), self.assertRaises(UnsafeOperation):
                version(value)
        self.assertGreater(version("1.10.0"), version("1.9.0"))

    def test_rejects_reparse_ancestors_before_installation_writes(self):
        target = self.root / "existing-protected-data"
        target.mkdir()
        link = self.root / "redirect"
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError:
            self.skipTest("Creating symlinks is not permitted on this test host")
        with self.assertRaises(UnsafeOperation):
            refuse_reparse(link / "new-directory")
        self.assertEqual(list(target.iterdir()), [])

    def test_same_version_only_repairs_a_recognized_uninstall(self):
        self.assertEqual(
            verify(
                self.bundle,
                self.trust,
                {"version": "1.1.0", "channel": "synthetic", "uninstalled": True},
            )["version"],
            "1.1.0",
        )
        with self.assertRaises(UnsafeOperation):
            verify(
                self.bundle,
                self.trust,
                {"version": "1.0.0", "channel": "synthetic", "uninstalled": True},
            )
