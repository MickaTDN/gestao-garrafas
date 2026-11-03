"""Compose exact reviewed sibling trees in a disposable directory; never merge refs.

Only the known synthetic Windows fixture conflict is resolved, by retaining the
transport fixture; joint native smoke remains a future integration check. Runtime
conflicts abort this check rather than hiding changes to either implementation.
"""

import io
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

REVIEW = "4fd188146a87ca17be4a310f4e1280d218ff9fac"
ROOT = Path(__file__).resolve().parents[1]


def git(*args, **kwargs):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, **kwargs)


def main():
    if git("rev-parse", "--is-shallow-repository", text=True).stdout.strip() == "true":
        subprocess.run(["git", "fetch", "--unshallow", "--no-tags", "origin"], cwd=ROOT, check=True)
    if git("cat-file", "-e", REVIEW).returncode:
        subprocess.run(["git", "fetch", "--no-tags", "origin", REVIEW], cwd=ROOT, check=True)
    result = git("merge-tree", "--write-tree", "--name-only", "HEAD", REVIEW, text=True)
    if result.returncode not in (0, 1):
        raise RuntimeError("Cannot compose exact sibling trees")
    tree, *lines = result.stdout.splitlines()
    conflicts = []
    for line in lines:
        if not line:
            break
        conflicts.append(line)
    if conflicts not in ([], ["tests/native_windows/windows_smoke.py"]):
        raise RuntimeError("Unexpected composition conflicts: " + repr(conflicts))
    with tempfile.TemporaryDirectory(prefix="gva-review-composition-") as directory:
        target = Path(directory)
        archive = git("archive", tree, check=True).stdout
        with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
            bundle.extractall(target, filter="data")
        for name in conflicts:
            shutil.copyfile(ROOT / name, target / name)
        (target / "consultation/migrations/0007_merge_review_wifi.py").write_text(
            "from django.db import migrations\n"
            "class Migration(migrations.Migration):\n"
            "    dependencies=[('consultation','0005_wifi_receipt_actor'),"
            "('consultation','0006_sheet_action_guards')]\n"
            "    operations=[]\n"
        )
        # Reuse only this disposable CI run's configuration; never print its secrets.
        shutil.copyfile(ROOT / ".env", target / ".env")
        (target / ".env").chmod(0o600)
        env = {**os.environ, "PYTHONPATH": str(target)}
        subprocess.run(
            [sys.executable, "manage.py", "makemigrations", "--check", "--dry-run"],
            cwd=target,
            env=env,
            check=True,
        )
        subprocess.run(
            [
                sys.executable,
                "manage.py",
                "test",
                "consultation.test_sheet_review",
                "consultation.test_sheet_transport",
                "consultation.test_sheet_transport_https",
                "--testrunner",
                "tests.ci.AnnotatingRunner",
                "--noinput",
            ],
            cwd=target,
            env=env,
            check=True,
        )
    print(
        "PASS: exact PR31 composition, explicit migration join, receipt/admin confirmation separation."
    )


if __name__ == "__main__":
    main()
