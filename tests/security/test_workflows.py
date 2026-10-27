"""Meaningful policy attacks and solo-maintainer ruleset safeguards; no database."""

import copy
import json
import unittest

from scripts.check_workflows import (
    APPROVED,
    ARTIFACT_GUARD,
    ARTIFACT_PATHS,
    NATIVE_JOB_GUARD,
    ROOT,
    load_workflow,
    validate,
)


class WorkflowSecurityTests(unittest.TestCase):
    def setUp(self):
        self.approved = json.loads(APPROVED.read_text())
        self.workflow = load_workflow((ROOT / ".github/workflows/ci.yml").read_text())

    def check_rejected(self, mutate):
        workflow = copy.deepcopy(self.workflow)
        mutate(workflow)
        self.assertTrue(validate(workflow, self.approved))

    def test_repository_workflows_follow_policy(self):
        for path in (ROOT / ".github/workflows").glob("*.y*ml"):
            with self.subTest(workflow=path.name):
                self.assertEqual(validate(load_workflow(path.read_text()), self.approved), [])

    def test_privileged_pull_request_target_is_rejected(self):
        self.check_rejected(lambda w: w["on"].update(pull_request_target={}))

    def test_workflow_run_privilege_handoff_is_rejected(self):
        self.check_rejected(lambda w: w["on"].update(workflow_run={}))

    def test_write_token_is_rejected_at_workflow_and_job_level(self):
        for location in ("workflow", "job"):
            with self.subTest(location=location):
                def mutate(w):
                    target = w if location == "workflow" else w["jobs"]["django-postgresql"]
                    target["permissions"] = {"contents": "write"}
                self.check_rejected(mutate)

    def test_self_hosted_or_custom_runner_is_rejected(self):
        for runner in ("self-hosted", ["self-hosted", "windows"], "company-windows", "${{ matrix.runner }}"):
            self.check_rejected(
                lambda w: w["jobs"]["django-postgresql"].update({"runs-on": runner})
            )

    def test_mutable_action_tag_and_unapproved_action_are_rejected(self):
        for action in ("actions/checkout@v4", "other/action@" + "a" * 40):
            self.check_rejected(
                lambda w: w["jobs"]["django-postgresql"]["steps"][0].update(uses=action)
            )

    def test_checkout_credentials_and_custom_ref_are_rejected(self):
        for field, value in (("persist-credentials", "true"), ("ref", "unreviewed")):
            def mutate(w):
                w["jobs"]["django-postgresql"]["steps"][0]["with"][field] = value
            self.check_rejected(mutate)

    def test_production_secrets_and_environments_are_rejected(self):
        for field, value in (
            ("env", {"SIGNING_KEY": "${{ secrets.PRODUCTION_KEY }}"}),
            ("environment", "production"),
            ("secrets", "inherit"),
        ):
            self.check_rejected(lambda w: w["jobs"]["django-postgresql"].update({field: value}))

    def test_untrusted_pr_text_cannot_be_interpolated_in_shell(self):
        self.check_rejected(
            lambda w: w["jobs"]["django-postgresql"]["steps"].append(
                {"run": 'echo "${{ github.event.pull_request.title }}"'}
            )
        )

    def test_duplicate_yaml_keys_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate YAML key"):
            load_workflow("permissions: {}\npermissions: {contents: write}\n")

    def test_native_service_installation_requires_the_internal_repository_guard(self):
        job = {"runs-on": "windows-2025", "timeout-minutes": "60", "steps": []}
        self.workflow["jobs"]["windows-native-synthetic"] = job
        self.assertTrue(validate(self.workflow, self.approved))
        job["if"] = NATIVE_JOB_GUARD
        self.assertEqual(validate(self.workflow, self.approved), [])

    def upload(self):
        return {
            "uses": "actions/upload-artifact@" + self.approved["actions/upload-artifact"]["sha"],
            "if": ARTIFACT_GUARD,
            "with": {
                "name": "UNAPPROVED-SYNTHETIC-UNSIGNED-NOT-FOR-DISTRIBUTION-test",
                "retention-days": "3",
                "path": "\n".join(sorted(ARTIFACT_PATHS)),
            },
        }

    def test_only_manual_trusted_ref_can_upload_synthetic_artifacts(self):
        step = self.upload()
        self.workflow["jobs"]["django-postgresql"]["steps"].append(step)
        self.assertEqual(validate(self.workflow, self.approved), [])
        step["if"] = "always()"
        self.assertTrue(validate(self.workflow, self.approved))

    def test_unlabelled_or_overbroad_uploads_are_rejected(self):
        for field, value in (("name", "Official Installer"), ("path", "${{ runner.temp }}/**")):
            workflow = copy.deepcopy(self.workflow)
            step = self.upload()
            step["with"][field] = value
            workflow["jobs"]["django-postgresql"]["steps"].append(step)
            self.assertTrue(validate(workflow, self.approved))


class PublicRulesetTests(unittest.TestCase):
    def test_proposal_is_disabled_and_does_not_lock_out_solo_owner(self):
        proposal = json.loads((ROOT / ".github/security/main-ruleset.public.json").read_text())
        self.assertEqual(proposal["enforcement"], "disabled")
        self.assertEqual(proposal["conditions"]["ref_name"]["include"], ["refs/heads/main"])
        self.assertEqual(proposal["bypass_actors"], [])
        rules = {r["type"]: r for r in proposal["rules"]}
        self.assertIn("deletion", rules)
        self.assertIn("non_fast_forward", rules)
        self.assertEqual(rules["pull_request"]["parameters"]["required_approving_review_count"], 0)
        checks = rules["required_status_checks"]["parameters"]["required_status_checks"]
        actual = {
            job.get("name", name) for path in (ROOT / ".github/workflows").glob("*.y*ml")
            for name, job in load_workflow(path.read_text())["jobs"].items()
        }
        self.assertTrue({check["context"] for check in checks} <= actual)
        self.assertNotIn("windows-native-synthetic", {check["context"] for check in checks})


if __name__ == "__main__":
    unittest.main()
