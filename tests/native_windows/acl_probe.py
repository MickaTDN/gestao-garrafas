"""Fast real NTFS check before the expensive build. Disposable Windows CI only."""

import os
import subprocess
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main():
    if os.name != "nt" or os.getenv("GITHUB_ACTIONS") != "true":
        raise RuntimeError("Disposable Windows CI only")
    from native_windows import windows
    from native_windows.install import prepare_acl

    windows.administrator()
    token = uuid.uuid4().hex[:10]
    root = Path(os.environ["RUNNER_TEMP"]) / ("gva-acl-probe-" + token)
    root.mkdir()
    (root / "secrets").mkdir()
    for name in ("owner", "app"):
        (root / f"secrets/{name}.json").write_text("synthetic-acl-fixture")
    names = []
    for kind in windows.SERVICES:
        windows.SERVICES[kind] = "GVAProbe" + token + kind
    try:
        for name in windows.SERVICES.values():
            windows.native(
                [
                    "sc.exe",
                    "create",
                    name,
                    "binPath=",
                    str(Path(os.environ["SystemRoot"]) / "System32/cmd.exe"),
                    "start=",
                    "disabled",
                    "obj=",
                    "NT SERVICE\\" + name,
                ]
            )
            names.append(name)
            windows.native(["sc.exe", "sidtype", name, "unrestricted"])
        prepare_acl(root)
        for path in (root / "secrets/owner.json", root / "secrets/app.json"):
            assert path.read_text() == "synthetic-acl-fixture"
        password_file = root / "runtime/postgres/bootstrap-password"
        password_file.write_text("synthetic-acl-only")
        assert password_file.read_text() == "synthetic-acl-only"
        assert not any((root / "cluster").iterdir())
        print(
            "::notice::PASS: native NTFS service accounts, administrator credential access and private bootstrap directory",
            flush=True,
        )
    except Exception as error:
        label = (
            Path(error.filename).name if isinstance(error, OSError) and error.filename else "none"
        )
        print("::error::NTFS probe: " + type(error).__name__ + "; file=" + label, flush=True)
        # ACL metadata only, never credential contents.
        for path in (
            root,
            root / "secrets",
            root / "secrets/owner.json",
            root / "cluster",
            root / "runtime/postgres",
        ):
            report = subprocess.run(["icacls.exe", str(path)], capture_output=True, text=True)
            print(
                "::notice::ACL " + path.name + ": " + report.stdout.replace("\n", " "), flush=True
            )
        raise
    finally:
        for name in names:
            windows.native(["sc.exe", "delete", name])


if __name__ == "__main__":
    main()
