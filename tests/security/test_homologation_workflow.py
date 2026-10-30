"""Prevent partial/unvalidated Etapa D downloads; synthetic bytes, no databases."""

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.check_workflows import ARTIFACT_GUARD, ROOT, load_workflow

SOURCE = "f88861ce057b98be3636f9a23ae3b36aff08c8bb"
WORKFLOW = ROOT / ".github/workflows/windows11-homologation.yml"


class HomologationDownloadTests(unittest.TestCase):
    def setUp(self):
        self.workflow = load_workflow(WORKFLOW.read_text())
        self.job = self.workflow["jobs"]["validated-synthetic-download"]
        self.steps = self.job["steps"]
        self.stage = next(s for s in self.steps if s.get("name", "").startswith("Stage only"))
        python = self.stage["run"].split("@'\n", 1)[1].split("\n'@", 1)[0]
        self.code = compile(python, "<homologation-staging>", "exec")
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.private = self.base / "validation/gva-native"
        (self.private / "artifacts").mkdir(parents=True)
        self.names = [f"GVA-synthetic-{v}-win-x64.exe" for v in ("1.0.0", "1.1.0")]
        self.hashes = {}
        for name in self.names:
            content = ("Fictitious non-executable test bytes: " + name).encode()
            (self.private / "artifacts" / name).write_bytes(content)
            self.hashes[name] = hashlib.sha256(content).hexdigest()
        (self.private / "tested-hashes.json").write_text(json.dumps(self.hashes))
        self.target = self.base / "gva-native/artifacts"
        self.env = {
            "GVA_VALIDATION_TEMP": str(self.base / "validation"),
            "RUNNER_TEMP": str(self.base),
            "GITHUB_SHA": "a" * 40,
            "GITHUB_SERVER_URL": "https://github.com",
            "GITHUB_REPOSITORY": "MickaTDN/gestao-garrafas",
            "GITHUB_RUN_ID": "123",
            "GITHUB_RUN_ATTEMPT": "2",
            "GITHUB_STEP_SUMMARY": str(self.base / "summary"),
        }

    def run_stage(self, head=SOURCE):
        with patch.dict(os.environ, self.env), patch(
            "subprocess.check_output", return_value=head + "\n"
        ):
            exec(self.code, {})

    def blocked(self, head=SOURCE):
        with self.assertRaises(Exception):
            self.run_stage(head)
        self.assertFalse(self.target.exists())

    def test_only_manual_trusted_main_can_run_without_source_inputs(self):
        self.assertEqual(set(self.workflow["on"]), {"workflow_dispatch"})
        self.assertFalse(self.workflow["on"]["workflow_dispatch"])
        for guard in (
            "github.event_name == 'workflow_dispatch'",
            "github.ref == 'refs/heads/main'",
            "github.repository == 'MickaTDN/gestao-garrafas'",
        ):
            self.assertIn(guard, self.job["if"])
        source = self.steps[1]["run"]
        self.assertIn("git fetch --no-tags --depth=1", source)
        self.assertIn("git checkout --detach " + SOURCE, source)
        self.assertIn("$head -ne '" + SOURCE + "'", source)

    def test_tests_must_pass_before_atomic_staging(self):
        self.assertEqual(self.stage["if"], "success()")
        previous = self.steps[: self.steps.index(self.stage)]
        for prefix in ("Workflow security", "Native updater", "Real NTFS", "Actual synthetic EXE"):
            self.assertTrue(any(s.get("name", "").startswith(prefix) for s in previous))
        self.assertFalse(any("continue-on-error" in step for step in self.steps))
        self.assertEqual(self.steps[-1]["if"].strip(), ARTIFACT_GUARD)
        self.assertEqual(self.steps[-1]["with"]["if-no-files-found"], "error")
        self.assertIn("staging.rename(publish_root / \"artifacts\")", self.stage["run"])

    def test_pair_uses_same_synthetic_authority_and_expected_versions(self):
        authority = next(s["run"] for s in self.steps if s.get("name") == "Synthetic signing authority (private key never uploaded)")
        self.assertIn("'channel':'synthetic'", authority)
        build = next(s["run"] for s in self.steps if s.get("name", "").startswith("Build initial"))
        self.assertIn("foreach ($version in @('1.0.0','1.1.0'))", build)
        self.assertIn('"$root\\policy.json" --key "$root\\signing.pem"', build)
        self.assertIn("'/DChannel=synthetic'", build)

    def test_valid_pair_has_only_three_public_files_and_provenance(self):
        (self.private / "signing.pem").write_text("PRIVATE TEST SENTINEL")
        self.run_stage()
        self.assertEqual(
            {p.name for p in self.target.iterdir()}, set(self.names) | {"SHA256SUMS.txt"}
        )
        checksums = (self.target / "SHA256SUMS.txt").read_text()
        self.assertIn(SOURCE, checksums)
        self.assertIn("/actions/runs/123/attempts/2", checksums)
        self.assertNotIn("PRIVATE TEST SENTINEL", checksums)
        for name, digest in self.hashes.items():
            self.assertIn(digest + "  " + name, checksums)

    def test_missing_second_installer_never_publishes_first(self):
        (self.private / "artifacts" / self.names[1]).unlink()
        self.blocked()

    def test_changed_installer_rejected(self):
        (self.private / "artifacts" / self.names[1]).write_text("changed")
        self.blocked()

    def test_incomplete_manifest_rejected(self):
        (self.private / "tested-hashes.json").write_text(json.dumps({self.names[0]: "0" * 64}))
        self.blocked()

    def test_wrong_source_commit_rejected(self):
        self.blocked("b" * 40)

    def test_symlink_rejected(self):
        name = self.private / "artifacts" / self.names[1]
        content = name.read_bytes()
        name.unlink()
        other = self.private / "another.exe"
        other.write_bytes(content)
        name.symlink_to(other)
        self.blocked()

    def test_existing_publication_not_adopted(self):
        self.target.parent.mkdir()
        sentinel = self.target.parent / "sentinel"
        sentinel.write_text("preserve")
        self.blocked()
        self.assertEqual(sentinel.read_text(), "preserve")

    def test_corrupted_copy_rejected(self):
        with patch("shutil.copyfile", side_effect=lambda src, dst: Path(dst).write_bytes(b"bad")):
            self.blocked()

    def test_interrupted_second_copy_does_not_publish_partial_pair(self):
        import shutil

        original = shutil.copyfile

        def copy(source, destination):
            if Path(source).name == self.names[1]:
                raise OSError("Synthetic copy interruption")
            return original(source, destination)

        with patch("shutil.copyfile", side_effect=copy):
            self.blocked()

    def test_summary_write_failure_does_not_publish(self):
        self.env["GITHUB_STEP_SUMMARY"] = str(self.base / "missing/summary")
        self.blocked()

    def test_rename_failure_does_not_publish(self):
        with patch("pathlib.Path.rename", side_effect=OSError("Synthetic rename failure")):
            self.blocked()
