import io
import os
import stat
import subprocess
import tarfile
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

import psycopg
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import CommandError
from django.test import TransactionTestCase, override_settings
from psycopg import sql

from inventory.backups import create_backup, restore_synthetic, verify_archive
from inventory.models import Location, Reference
from tests.document_fixtures import confirmed_operation


class BackupTests(TransactionTestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory(prefix="garrafas-backup-test-")
        self.addCleanup(self.root.cleanup)
        self.environment = patch.dict(
            os.environ,
            {
                "BACKUP_ROOT": self.root.name,
                "BACKUP_RETENTION_COUNT": "2",
                "BACKUP_GPG_RECIPIENT": "",
            },
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.admin = get_user_model().objects.create_user(username="backup-synthetic", role="admin")
        loc = Location.objects.create(name="Backup sintético")
        self.ref = Reference.objects.create(
            code="BACKUP-1", name="Referência sintética de restauro", current_stock=15, location=loc
        )
        self.movement = confirmed_operation(self.admin, self.ref, signed=True)

    def admin_connection(self, database="postgres"):
        cfg = settings.DATABASES["default"]
        return psycopg.connect(
            dbname=database,
            user=cfg["USER"],
            password=cfg["PASSWORD"],
            host=cfg["HOST"],
            port=cfg["PORT"],
            autocommit=True,
        )

    def test_real_postgresql17_dump_and_restore_stock_documents_and_triggers(self):
        archive, manifest = create_backup(synthetic=True)
        self.assertEqual(stat.S_IMODE(archive.stat().st_mode), 0o600)
        self.assertEqual(len(manifest["documents"]), 2)
        self.assertEqual(verify_archive(archive), manifest)
        database = "garrafas_restore_" + uuid.uuid4().hex[:20]
        restored = restore_synthetic(archive, database=database)
        try:
            with self.admin_connection(database) as conn:
                self.assertEqual(
                    conn.execute(
                        "SELECT current_stock FROM inventory_reference WHERE code='BACKUP-1'"
                    ).fetchone()[0],
                    13,
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT count(*) FROM inventory_document WHERE payload IS NOT NULL"
                    ).fetchone()[0],
                    2,
                )
                with self.assertRaises(psycopg.errors.CheckViolation):
                    conn.execute(
                        "UPDATE inventory_movement SET reason='tamper' WHERE id=%s",
                        [self.movement.pk],
                    )
                with self.assertRaises(psycopg.errors.CheckViolation):
                    conn.execute(
                        "DELETE FROM inventory_document WHERE movement_id=%s", [self.movement.pk]
                    )
            self.assertEqual(restored["documents"], manifest["documents"])
        finally:
            with self.admin_connection() as conn:
                conn.execute(
                    sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database))
                )
        self.ref.refresh_from_db()
        self.assertEqual(self.ref.current_stock, 13)

    def test_restore_never_accepts_existing_or_protected_target(self):
        archive, _ = create_backup(synthetic=True)
        for database in (
            settings.DATABASES["default"]["NAME"],
            "garrafas",
            "postgres",
            "garrafas_restore_bad;DROP DATABASE postgres",
        ):
            with self.assertRaises(CommandError):
                restore_synthetic(archive, database=database)
        database = "garrafas_restore_" + uuid.uuid4().hex[:20]
        with self.admin_connection() as conn:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
        try:
            with self.assertRaisesMessage(CommandError, "já existe"):
                restore_synthetic(archive, database=database)
            with self.admin_connection(database) as conn:
                self.assertEqual(
                    conn.execute(
                        "SELECT count(*) FROM pg_tables WHERE schemaname='public'"
                    ).fetchone()[0],
                    0,
                )
        finally:
            with self.admin_connection() as conn:
                conn.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))

    def test_integrity_rejects_tampering_or_path_traversal(self):
        archive, _ = create_backup(synthetic=True)
        for bad_path in (False, True):
            destination = Path(self.root.name) / f"tampered-{bad_path}.tar.gz"
            with (
                tarfile.open(archive, "r:gz") as source,
                tarfile.open(destination, "w:gz") as target,
            ):
                for member in source.getmembers():
                    data = source.extractfile(member).read()
                    if member.name == "database.dump":
                        data = b"corrupt" if not bad_path else data
                        if bad_path:
                            member.name = "../private-file"
                    member.size = len(data)
                    target.addfile(member, io.BytesIO(data))
            with self.assertRaises(CommandError):
                verify_archive(destination)

    def test_retention_only_removes_old_complete_owned_archives(self):
        other = Path(self.root.name) / "unrelated-private-file"
        other.write_text("synthetic")
        paths = [create_backup(synthetic=True)[0] for _ in range(3)]
        self.assertFalse(paths[0].exists())
        self.assertTrue(paths[1].exists() and paths[2].exists() and other.exists())
        self.assertEqual(len(list(Path(self.root.name).glob("gg-backup-*"))), 2)

    def test_failed_dump_does_not_apply_retention_or_publish_incomplete_archive(self):
        before = create_backup(synthetic=True)[0]
        with (
            patch("inventory.backups._tool", side_effect=CommandError("Synthetic failure")),
            self.assertRaises(CommandError),
        ):
            create_backup(synthetic=True)
        self.assertTrue(before.exists())
        self.assertEqual(len(list(Path(self.root.name).glob("gg-backup-*"))), 1)
        self.assertFalse(list(Path(self.root.name).glob(".building-*")))

    def test_public_or_checkout_backup_directory_rejected(self):
        with (
            patch.dict(os.environ, {"BACKUP_ROOT": str(settings.BASE_DIR / "public-backups")}),
            self.assertRaises(CommandError),
        ):
            create_backup(synthetic=True)
        public = Path(self.root.name) / "public"
        public.mkdir(mode=0o755)
        public.chmod(0o755)
        with patch.dict(os.environ, {"BACKUP_ROOT": str(public)}), self.assertRaises(CommandError):
            create_backup(synthetic=True)

    @override_settings(PRODUCTION=True)
    def test_production_refuses_unencrypted_backup(self):
        with self.assertRaisesMessage(CommandError, "GPG"):
            create_backup()

    def test_encrypted_backup_can_be_decrypted_and_verified_with_ephemeral_key(self):
        keyhome = Path(self.root.name) / "gpg"
        keyhome.mkdir(mode=0o700)
        env = {**os.environ, "GNUPGHOME": str(keyhome)}
        # Ephemeral synthetic key, never committed or used for an account.
        result = subprocess.run(
            [
                "gpg",
                "--batch",
                "--pinentry-mode",
                "loopback",
                "--passphrase-fd",
                "0",
                "--quick-generate-key",
                "Backup Sintético <synthetic@example.invalid>",
                "rsa2048",
                "encr",
                "0",
            ],
            input=b"\n",
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(result.returncode, 0, "Synthetic GPG key generation failed")
        with patch.dict(
            os.environ,
            {"GNUPGHOME": str(keyhome), "BACKUP_GPG_RECIPIENT": "synthetic@example.invalid"},
        ):
            archive, manifest = create_backup(synthetic=True)
            self.assertEqual(archive.suffix, ".gpg")
            decrypted = Path(self.root.name) / "decrypted.tar.gz"
            result = subprocess.run(
                ["gpg", "--batch", "--output", str(decrypted), "--decrypt", str(archive)],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(result.returncode, 0, "Synthetic GPG decryption failed")
            self.assertEqual(verify_archive(decrypted), manifest)
