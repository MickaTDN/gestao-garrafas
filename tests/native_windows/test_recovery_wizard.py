import json
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock, patch

from native_windows.package import UnsafeOperation
from native_windows.recovery_wizard import restore, validate_snapshot


class RecoveryWizardTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.parent = Path(self.temp.name)
        self.root = self.parent / "data"
        self.root.mkdir()
        self.release = self.parent / "release/payload"
        self.release.mkdir(parents=True)
        (self.release.parent / "package.json").write_text("signed-test-package")
        self.old = {
            "instance": "48b6fa36-c939-4028-b92d-c3fa028d1573",
            "schema": 1,
            "postgres_major": 17,
            "database": "gva_native_synthetic",
            "channel": "synthetic",
            "version": "1.1.0",
            "release": str(self.release),
            "package_sha256": "test",
            "db_port": 55432,
            "http_port": 8765,
        }
        (self.root / "installation.json").write_text(json.dumps(self.old))
        (self.root / "cluster").mkdir()
        (self.root / "cluster/precious").write_bytes(b"confirmed-data-and-history")
        (self.root / "package-policy.json").write_text('{"test":"trusted-policy"}')
        self.data = self.parent / "decrypted"
        self.data.mkdir()
        (self.data / "installation.json").write_text(json.dumps(self.old))
        (self.data / "database.dump").write_bytes(b"synthetic")
        (self.data / "backup-policy.json").write_text('{"retain":14,"copy_to":"machine-dependent"}')
        (self.data / "publisher.json").write_text('{"enabled":true}')
        for name in ("secrets", "signing", "tls"):
            (self.data / name).mkdir()
        for name, user in (("owner", "gva_owner"), ("app", "gva_web")):
            (self.data / f"secrets/{name}.json").write_text(
                json.dumps({"username": user, "password": "synthetic", "django_key": "synthetic"})
            )
        for name in (
            "recovery-public.pem",
            "package-policy.json",
            "signing/signing.pem",
            "signing/origin.vatrust.json",
        ):
            (self.data / name).write_text("synthetic")
        self.manifest = {"version": "1.1.0", "minimum_version": "1.0.0", "channel": "synthetic"}
        self.metadata = {
            key: self.old[key] for key in ("instance", "version", "channel", "package_sha256")
        }
        self.saved = {
            **self.metadata,
            "evidence": {"table": {"rows": 1, "sha256": "synthetic"}, "__sequences__": []},
        }
        self.summary = {"token": "test-token", "sha256": "test-hash"}
        self.request = {"confirmed": True, "source_offline": True, "token": "test-token"}

    @contextmanager
    def boundaries(self, failing=None):
        from contextlib import ExitStack

        with ExitStack() as stack:

            @contextmanager
            def prepared(*args):
                yield self.data, self.saved, self.old, self.summary

            stack.enter_context(patch("native_windows.recovery_wizard.prepared", prepared))
            calls = {}
            for name in (
                "administrator",
                "protect",
                "disable_all",
                "stop_all",
                "configure",
                "prepare_acl",
                "create_cluster",
                "pg_tool",
                "manage",
                "grants",
                "activate",
                "health_http",
                "free_port",
                "native",
                "wait_database",
            ):
                calls[name] = stack.enter_context(patch("native_windows.recovery_wizard." + name))
            stack.enter_context(patch("native_windows.maintenance.validate_material"))
            stack.enter_context(patch("native_windows.recovery_wizard.exists", return_value=True))
            stack.enter_context(
                patch("native_windows.recovery_wizard.connection", return_value=MagicMock())
            )
            stack.enter_context(
                patch(
                    "native_windows.recovery_wizard.evidence", return_value=self.saved["evidence"]
                )
            )
            if failing:
                # First activation/check fails; rollback's second invocation succeeds.
                calls[failing].side_effect = [RuntimeError("PRIVATE SENTINEL"), None]
            yield calls

    def test_replacement_preserves_old_cluster_and_disables_machine_specific_publication(self):
        with self.boundaries():
            result = restore(
                self.root,
                self.release,
                self.manifest,
                self.request,
                self.root / "package-policy.json",
            )
        self.assertEqual(result["status"], "verified-and-running")
        self.assertEqual(
            (self.parent / result["previous_preserved"] / "cluster/precious").read_bytes(),
            b"confirmed-data-and-history",
        )
        self.assertFalse(json.loads((self.root / "publisher.json").read_text())["enabled"])
        self.assertIsNone(json.loads((self.root / "backup-policy.json").read_text())["copy_to"])
        self.assertFalse((self.root / "maintenance.json").exists())
        self.assertFalse((self.root / "activation-permit").exists())

    def test_restore_and_activation_failure_restore_original_cluster_without_secret_diagnostics(
        self,
    ):
        for point in ("pg_tool", "create_cluster", "health_http"):
            with self.subTest(point=point), self.boundaries(failing=point):
                with self.assertRaises(UnsafeOperation) as caught:
                    restore(
                        self.root,
                        self.release,
                        self.manifest,
                        self.request,
                        self.root / "package-policy.json",
                    )
                self.assertNotIn("PRIVATE SENTINEL", str(caught.exception))
                self.assertEqual(
                    (self.root / "cluster/precious").read_bytes(), b"confirmed-data-and-history"
                )
                self.assertFalse((self.root / "maintenance.json").exists())
        self.assertEqual(len(list(self.parent.glob("data-Failed-*"))), 3)

    def test_unconfirmed_or_stale_preview_does_not_stop_services(self):
        for change in ({"confirmed": False}, {"source_offline": False}, {"token": "other"}):
            with self.boundaries() as calls, self.assertRaises(UnsafeOperation):
                restore(
                    self.root,
                    self.release,
                    self.manifest,
                    {**self.request, **change},
                    self.root / "package-policy.json",
                )
            calls["stop_all"].assert_not_called()
            self.assertTrue((self.root / "cluster/precious").exists())

    def test_concurrent_journal_and_activation_permit_are_never_removed(self):
        journal = self.root / "maintenance.json"
        permit = self.root / "activation-permit"
        journal.write_text('{"id":"another-operation"}')
        permit.write_text("another-approved-release")
        with self.boundaries() as calls, self.assertRaises(UnsafeOperation):
            restore(
                self.root,
                self.release,
                self.manifest,
                self.request,
                self.root / "package-policy.json",
            )
        calls["disable_all"].assert_not_called()
        calls["stop_all"].assert_not_called()
        self.assertEqual(journal.read_text(), '{"id":"another-operation"}')
        self.assertEqual(permit.read_text(), "another-approved-release")
        self.assertTrue((self.root / "cluster/precious").exists())

    def test_version_channel_and_internal_identity_are_checked(self):
        self.assertEqual(
            validate_snapshot(self.data, self.metadata, self.saved, self.manifest), self.old
        )
        for field, value in (("version", "0.9.0"), ("channel", "release")):
            with self.assertRaises(UnsafeOperation):
                validate_snapshot(
                    self.data, self.metadata, self.saved, {**self.manifest, field: value}
                )
        with self.assertRaises(UnsafeOperation):
            validate_snapshot(
                self.data, {**self.metadata, "instance": "another"}, self.saved, self.manifest
            )

    def test_failed_rollback_keeps_maintenance_gate(self):
        with self.boundaries() as calls:
            calls["health_http"].side_effect = RuntimeError("private")
            with self.assertRaisesRegex(UnsafeOperation, "necessária assistência"):
                restore(
                    self.root,
                    self.release,
                    self.manifest,
                    self.request,
                    self.root / "package-policy.json",
                )
        self.assertTrue((self.root / "maintenance.json").exists())
        self.assertEqual(
            (self.root / "cluster/precious").read_bytes(), b"confirmed-data-and-history"
        )
        self.assertFalse((self.root / "activation-permit").exists())


class ExternalBackupDestinationTests(TestCase):
    def test_program_root_data_root_and_normalized_parent_paths_are_rejected(self):
        from native_windows.backup_wizard import external_destination

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "data"
            data.mkdir()
            release = root / "program/releases/1.1.0/payload"
            release.mkdir(parents=True)
            (data / "installation.json").write_text(json.dumps({"release": str(release)}))
            outside = root / "external"
            outside.mkdir()
            expected = outside / "copy.gvabackup"
            self.assertEqual(external_destination(data, str(expected)), expected.resolve())
            for path in (
                data / "copy.gvabackup",
                root / "program/copy.gvabackup",
                outside / "../data/copy.gvabackup",
            ):
                with self.assertRaises(UnsafeOperation):
                    external_destination(data, str(path))
            self.assertFalse(expected.exists())
