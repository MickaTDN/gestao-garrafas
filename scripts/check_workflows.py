"""Fail closed on accidental CI privilege expansion; never execute workflow code.

This is a regression check, not an approval boundary: an attacker can modify
checks in their PR. Actual trust comes from GitHub permissions, hosted runners,
protected refs and the absence of production keys or a release publisher in CI.
"""

import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
APPROVED = ROOT / ".github/security/approved-actions.json"
HOSTED = {"ubuntu-latest", "ubuntu-24.04", "windows-latest", "windows-2025"}
EVENTS = {"push", "pull_request", "workflow_dispatch"}
ARTIFACT_GUARD = (
    "always() && github.event_name == 'workflow_dispatch' && "
    "github.ref == 'refs/heads/main' && "
    "github.repository == 'MickaTDN/gestao-garrafas'"
)
ARTIFACT_PATHS = {
    "${{ runner.temp }}/gva-native/artifacts/*.exe",
    "${{ runner.temp }}/gva-native/artifacts/SHA256SUMS.txt",
}
NATIVE_JOB_GUARD = (
    "github.repository == 'MickaTDN/gestao-garrafas' && "
    "(github.event_name != 'pull_request' || "
    "github.event.pull_request.head.repo.full_name == github.repository)"
)


class UniqueLoader(yaml.BaseLoader):
    """Keep YAML 1.1's `on`/booleans as strings and reject duplicate keys."""


def unique_mapping(loader, node):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if key in result:
            raise ValueError(f"duplicate YAML key: {key}")
        result[key] = loader.construct_object(value_node)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def load_workflow(text):
    return yaml.load(text, Loader=UniqueLoader)


def validate(workflow, approved):
    errors = []
    if not isinstance(workflow, dict):
        return ["workflow must be a mapping"]
    events = workflow.get("on", {})
    if isinstance(events, str):
        events = [events]
    if not isinstance(events, (dict, list)) or not events or set(events) - EVENTS:
        errors.append("only push, pull_request and explicit workflow_dispatch are allowed")
    if workflow.get("permissions") != {"contents": "read"}:
        errors.append("workflow must declare only contents: read")
    serialized = json.dumps(workflow)
    if re.search(r"\bsecrets\s*[.\[]", serialized):
        errors.append("test workflows must not reference repository/production secrets")
    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        return errors + ["workflow must contain jobs"]
    for name, job in jobs.items():
        prefix = f"{name}: "
        if not isinstance(job, dict):
            errors.append(prefix + "job must be a mapping")
            continue
        runner = job.get("runs-on")
        if not isinstance(runner, str) or runner not in HOSTED:
            errors.append(prefix + "only explicitly approved standard hosted runners are allowed")
        if "uses" in job or "secrets" in job or "environment" in job:
            errors.append(prefix + "no privileged environments, inherited secrets or reusable jobs")
        if "permissions" in job and job["permissions"] not in ({}, {"contents": "read"}):
            errors.append(prefix + "job must not expand permissions")
        if name == "windows-native-synthetic" and job.get("if", "").strip() != NATIVE_JOB_GUARD:
            errors.append(prefix + "native service/ACL installation must not run for fork PRs")
        try:
            if not 1 <= int(job.get("timeout-minutes", "0")) <= 60:
                raise ValueError
        except (ValueError, TypeError):
            errors.append(prefix + "explicit timeout between 1 and 60 minutes required")
        for step in job.get("steps", []):
            if not isinstance(step, dict):
                errors.append(prefix + "step must be a mapping")
                continue
            run = step.get("run", "")
            if re.search(r"\$\{\{[^}]*github\.(?:event\.|head_ref|ref_name)", run):
                errors.append(prefix + "untrusted GitHub fields must not be interpolated into shell")
            uses = step.get("uses")
            if not uses:
                continue
            action, sep, sha = uses.partition("@")
            if not sep or action not in approved or sha != approved[action]["sha"]:
                errors.append(prefix + "action must use its reviewed immutable SHA: " + uses)
            inputs = step.get("with", {})
            if action == "actions/checkout":
                if inputs.get("persist-credentials") != "false":
                    errors.append(prefix + "checkout must disable credential persistence")
                if "ref" in inputs or "repository" in inputs or "token" in inputs:
                    errors.append(prefix + "checkout must use the event ref and default read-only token")
            if action == "actions/upload-artifact":
                condition = step.get("if", "").strip()
                if condition.startswith("${{") and condition.endswith("}}"):
                    condition = condition[3:-2].strip()
                if condition != ARTIFACT_GUARD:
                    errors.append(prefix + "uploads require manual dispatch on the trusted main ref")
                if not inputs.get("name", "").startswith("UNAPPROVED-SYNTHETIC-UNSIGNED-"):
                    errors.append(prefix + "test artefacts must be explicitly unapproved and unsigned")
                if inputs.get("retention-days") != "3":
                    errors.append(prefix + "test artefact retention must be three days")
                if set(inputs.get("path", "").splitlines()) != ARTIFACT_PATHS:
                    errors.append(prefix + "only synthetic installers and checksums may be uploaded")
    return errors


def main():
    approved = json.loads(APPROVED.read_text())
    failures = []
    paths = sorted((ROOT / ".github/workflows").glob("*.y*ml"))
    for path in paths:
        try:
            errors = validate(load_workflow(path.read_text()), approved)
        except (ValueError, TypeError, yaml.YAMLError) as error:
            errors = [str(error)]
        failures.extend(f"{path.name}: {message}" for message in errors)
    if not paths:
        failures.append("No workflows found")
    for failure in failures:
        print(failure, file=sys.stderr)
    if failures:
        return 1
    print(f"Workflow security policy: {len(paths)} workflows passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
