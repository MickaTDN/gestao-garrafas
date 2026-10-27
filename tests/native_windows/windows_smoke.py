"""Actual EXE/services/update/restore with synthetic data on disposable Windows CI.

Hosted runners are Windows Server, NOT evidence of a physical Windows11 reboot.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def run(args, *, expected=0, **kwargs):
    result = subprocess.run(list(map(str, args)), timeout=1200, **kwargs)
    if result.returncode != expected:
        raise RuntimeError(
            f"Synthetic command failed: {Path(str(args[0])).name}, exit={result.returncode}"
        )
    return result


def main(directory):
    if sys.platform != "win32" or os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("Disposable Windows CI only")
    directory = Path(directory)
    root = Path(os.environ["PROGRAMDATA"]) / "GestaoVertenteAveludada-Teste"
    if root.exists():
        raise RuntimeError("Synthetic root already exists; never adopted")
    key = directory / "recovery.pem"
    phrase = "synthetic-recovery-only-never-use-in-production"

    def install(version):
        request = directory / f"request-{version}.json"
        request.write_text(
            json.dumps(
                {
                    "username": "synthetic-ci-admin",
                    "password": "Synthetic-only-validation-390127!",
                    "synthetic": True,
                    "recovery_key": str(key),
                    "recovery_password": phrase,
                }
            )
        )
        run(
            [
                directory / f"artifacts/GVA-synthetic-{version}-win-x64.exe",
                "/S",
            ],
            env={**os.environ, "GVA_CI_REQUEST": str(request)},
        )

    install("1.0.0")
    state = json.loads((root / "installation.json").read_text())
    release = Path(state["release"])
    sys.path.insert(0, str(release / "app"))
    from native_windows.crypto_backup import decrypt
    from native_windows.install import health_http
    from native_windows.maintenance import backup, connection, restore_check
    from native_windows.runtime import manage
    from native_windows.windows import SERVICES, activate, stop_all

    health_http(root)
    manage(root, "shell", "-c", (Path(__file__).parent / "operation_fixture.py").read_text())
    run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            Path(__file__).parent / "Test-StandardUser.ps1",
            "-Root",
            root,
            "-Release",
            release,
        ]
    )

    def export_stock(filename):
        manage(
            root,
            "shell",
            "-c",
            "import json;from pathlib import Path;from accounts.models import User;from consultation.exports import export_snapshot;Path("
            + repr(str(filename))
            + ").write_text(json.dumps(export_snapshot(actor=User.objects.get(username='synthetic-ci-admin'))))",
        )
        return json.loads(Path(filename).read_text())

    packet_before = export_stock(root / "runtime/web/before.vastock.json")
    with connection(root) as conn:
        assert conn.execute(
            "SELECT count(*),sum(current_stock) FROM inventory_reference"
        ).fetchone() == (3, 33)
        assert conn.execute("SELECT count(*) FROM inventory_importbatch").fetchone()[0] == 0
        source = conn.execute(
            "SELECT source_id::text,sequence FROM consultation_exportsource"
        ).fetchone()
    key_before = (root / "signing/signing.pem").read_bytes()
    # Real stop/start preserves confirmed opening balances and identity.
    stop_all()
    activate(root)
    health_http(root)
    with connection(root) as conn:
        assert (
            conn.execute("SELECT sum(current_stock) FROM inventory_reference").fetchone()[0] == 33
        )
    # Generate encrypted backup and actually restore ALL rows to a new PG database.
    stop_all()
    run(["sc.exe", "start", SERVICES["postgres"]])
    from native_windows.install import wait_database

    wait_database(root)
    encrypted = backup(root)
    plain = directory / "verified.tar"
    decrypt(encrypted, plain, key.read_bytes(), phrase)
    restore_check(root, plain)
    plain.unlink()
    activate(root)
    install("1.1.0")
    health_http(root)
    assert json.loads((root / "installation.json").read_text())["version"] == "1.1.0"
    assert (root / "signing/signing.pem").read_bytes() == key_before
    packet_after = export_stock(root / "runtime/web/after.vastock.json")
    import base64

    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

    key_object = serialization.load_pem_private_key(key_before, password=None)
    decoded = []
    for packet in (packet_before, packet_after):
        raw = base64.urlsafe_b64decode(packet["payload"] + "==")
        signature = base64.urlsafe_b64decode(packet["signature"] + "==")
        key_object.public_key().verify(
            encode_dss_signature(
                int.from_bytes(signature[:32], "big"), int.from_bytes(signature[32:], "big")
            ),
            b"vertente-stock-v2\0" + raw,
            ec.ECDSA(hashes.SHA256()),
        )
        decoded.append(json.loads(raw))
    assert decoded[0]["source_id"] == decoded[1]["source_id"]
    assert decoded[0]["sequence"] + 1 == decoded[1]["sequence"]
    assert decoded[0]["references"] == decoded[1]["references"]
    assert decoded[0]["receipts"] == decoded[1]["receipts"]
    with connection(root) as conn:
        assert conn.execute(
            "SELECT source_id::text,sequence FROM consultation_exportsource"
        ).fetchone() == (source[0], source[1] + 1)
        assert (
            conn.execute("SELECT sum(current_stock) FROM inventory_reference").fetchone()[0] == 33
        )
    # Old package is refused before overwriting files or changing service configuration.
    request = directory / "old.json"
    request.write_text("{}")
    result = subprocess.run(
        [
            str(directory / "artifacts/GVA-synthetic-1.0.0-win-x64.exe"),
            "/S",
        ],
        timeout=120,
    )
    assert result.returncode != 0
    assert json.loads((root / "installation.json").read_text())["version"] == "1.1.0"
    # SQL roles are isolated; web cannot alter users' installation roles or enroll devices.
    app = json.loads((root / "secrets/app.json").read_text())
    import psycopg

    with psycopg.connect(
        host="127.0.0.1",
        port=state["db_port"],
        dbname=state["database"],
        user=app["username"],
        password=app["password"],
    ) as conn:
        assert conn.execute(
            "SELECT rolsuper,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname=current_user"
        ).fetchone() == (False, False, False)
    # Actual service/DB failure after migration: all services remain disabled,
    # a durable journal blocks restart, and only NEW-root recovery may resume.
    from native_windows.maintenance import UpdateActions
    from native_windows.state import update

    class InterruptedUpdate(UpdateActions):
        def migrate(self):
            super().migrate()
            raise RuntimeError("Synthetic interruption after migration")

    current_release = Path(json.loads((root / "installation.json").read_text())["release"])
    try:
        update(root, {"version": "1.2.0"}, InterruptedUpdate(root, current_release, key, phrase))
        raise AssertionError("Synthetic update should fail")
    except RuntimeError as error:
        assert str(error) == "Synthetic interruption after migration"
    assert (root / "maintenance.json").is_file()
    for name in SERVICES.values():
        if name == SERVICES["publisher"]:
            continue
        result = subprocess.run(["sc.exe", "start", name], capture_output=True)
        assert result.returncode != 0  # disabled persists across OS restarts
    encrypted = max((root / "backups").glob("gva-*.gvabackup"), key=lambda p: p.stat().st_mtime)
    # Uninstaller removes only code/services; private state, keys and encrypted backups survive.
    uninstall = next(
        Path(os.environ["ProgramFiles"])
        .joinpath("GestaoVertenteAveludada-synthetic")
        .glob("Uninstall.exe")
    )
    run([uninstall, "/S"])
    for _ in range(30):
        if not uninstall.exists():
            break
        time.sleep(1)
    assert (root / "cluster/PG_VERSION").read_text().strip() == "17"
    assert (root / "signing/signing.pem").read_bytes() == key_before
    assert encrypted.is_file()
    # Recover an actual encrypted backup in a NEW root after retaining the original
    # synthetic installation. No existing directory or database is overwritten.
    preserved = directory / "preserved-original-synthetic-data"
    root.rename(preserved)
    recovery_request = directory / "recovery-request.json"
    recovery_request.write_text(
        json.dumps(
            {
                "archive": str(preserved / "backups" / encrypted.name),
                "recovery_key": str(key),
                "recovery_password": phrase,
            }
        )
    )
    run(
        [
            directory / "artifacts/GVA-synthetic-1.1.0-win-x64.exe",
            "/S",
        ],
        env={**os.environ, "GVA_CI_REQUEST": str(recovery_request)},
    )
    assert (root / "recovery-verified.json").is_file()
    assert (root / "maintenance.json").is_file()
    assert (root / "signing/signing.pem").read_bytes() == key_before
    with connection(root) as conn:
        assert (
            conn.execute("SELECT sum(current_stock) FROM inventory_reference").fetchone()[0] == 33
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM inventory_movement WHERE status='confirmed'"
            ).fetchone()[0]
            == 2
        )
        assert conn.execute(
            "SELECT source_id::text,sequence FROM consultation_exportsource"
        ).fetchone() == (source[0], source[1] + 1)
    assert preserved.is_dir()  # Original data retained, not replaced/deleted.
    print(
        "Native installer: fresh EXE, services stop/start, 1.0→1.1, verified encrypted restore, downgrade refusal, stable Android identity, non-destructive uninstall: PASS"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory")
    try:
        main(parser.parse_args().directory)
    except Exception as error:
        host = Path(os.environ["RUNNER_TEMP"]) / "gva-native/host-error.txt"
        detail = host.read_text() if host.is_file() else str(error)
        print(
            "::error::Native Windows smoke: "
            + type(error).__name__
            + ": "
            + detail.replace("\n", " "),
            file=sys.stderr,
        )
        raise
