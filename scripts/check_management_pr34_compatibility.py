"""Selective, disposable composition of the gateway with exact PR34 runtime.

No refs are merged and no service/ACL/GUI conflicts are silently resolved. This
checks the shared network-validation contract; complete deployment remains future.
"""

import io
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = "24c6904ba1dc14d436961eb12188c3a2e9aa9b97"


def main():
    if subprocess.run(["git", "cat-file", "-e", TARGET], cwd=ROOT, capture_output=True).returncode:
        subprocess.run(["git", "fetch", "--no-tags", "origin", TARGET], cwd=ROOT, check=True)
    archive = subprocess.check_output(["git", "archive", TARGET], cwd=ROOT)
    with tempfile.TemporaryDirectory(prefix="gva-management-pr34-") as directory:
        target = Path(directory)
        with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
            bundle.extractall(target, filter="data")
        for name in [
            "native_windows/management_wifi.py",
            "tests/native_windows/test_management_wifi.py",
        ]:
            shutil.copyfile(ROOT / name, target / name)
        # Keep PR34's publisher/receiver byte-for-byte. Tests exercise its policy
        # reader while both gateways are denied any publisher TLS file access.
        subprocess.run(
            [
                sys.executable,
                "-m",
                "unittest",
                "tests.native_windows.test_management_wifi",
                "tests.native_windows.test_sheet_receiver",
                "tests.native_windows.test_profile",
            ],
            cwd=target,
            env={**os.environ, "PYTHONPATH": str(target)},
            check=True,
        )
    print("PASS: exact PR34 renderer composition; no publisher TLS access added to either gateway.")


if __name__ == "__main__":
    main()
