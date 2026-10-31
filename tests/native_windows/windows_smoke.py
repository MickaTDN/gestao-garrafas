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

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

SMOKE_SUCCESS = (
    "Native installer: fresh EXE, services stop/start, 1.0->1.1, verified encrypted restore, "
    "downgrade refusal, stable Android identity, non-destructive uninstall: PASS"
)


def log(message, *, error=False):
    """Diagnostics must work with redirected Windows cp1252 as well as UTF-8."""
    stream = sys.stderr if error else sys.stdout
    encoding = getattr(stream, "encoding", None) or "utf-8"
    printable = str(message).encode(encoding, errors="backslashreplace").decode(encoding)
    print(printable, file=stream, flush=True)


def run(args, *, expected=0, expect_failure=False, error_log=None, **kwargs):
    # The synthetic host keeps the last preflight error across successful runs.
    # Scope that evidence to THIS invocation, including expected downgrade refusal.
    if error_log is not None:
        error_log = Path(error_log)
        error_log.unlink(missing_ok=True)
    if Path(str(args[0])).name.lower() == "powershell.exe" and "env" not in kwargs:
        # Windows PowerShell 5.1 must not import PowerShell7 modules inherited
        # from the hosted runner shell. This changes only the child process env.
        kwargs["env"] = {
            key: value for key, value in os.environ.items() if key.lower() != "psmodulepath"
        }
    kwargs.setdefault("timeout", 480)
    result = subprocess.run(list(map(str, args)), **kwargs)
    failed = result.returncode == 0 if expect_failure else result.returncode != expected
    if failed:
        detail = ""
        if error_log is not None and error_log.is_file():
            detail = "; current host error=" + error_log.read_text(encoding="utf-8-sig")
        raise RuntimeError(
            f"Synthetic command failed: {Path(str(args[0])).name}, exit={result.returncode}"
            + detail
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
    host_error = directory / "host-error.txt"

    def install(version):
        log("::notice::Native smoke: installing " + version)
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
                "/CITestRequest=" + str(request),
            ],
            error_log=host_error,
            env={**os.environ, "GVA_CI_REQUEST": str(request)},
        )

    install("1.0.0")
    log("::notice::Native smoke: initial installation complete")
    state = json.loads((root / "installation.json").read_text())
    release = Path(state["release"])
    sys.path.insert(0, str(release / "app"))
    from native_windows.crypto_backup import decrypt
    from native_windows.install import health_http
    from native_windows.maintenance import backup, connection, restore_check
    from native_windows.runtime import manage
    from native_windows.windows import SERVICES, activate, stop_all

    health_http(root)
    run([
        "powershell.exe", "-NoProfile", "-NonInteractive", "-File",
        Path(__file__).parent / "Test-PrivateCRT.ps1", "-Release", release,
    ])
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

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from tests.native_windows.tls_probe import main as tls_probe

    tls_probe(root, directory)
    tls_before = {
        path.name: path.read_bytes() for path in (root / "tls").iterdir() if path.is_file()
    }
    packet_before = export_stock(root / "runtime/web/before.vastock.json")
    with connection(root) as conn:
        assert conn.execute(
            "SELECT count(*),sum(current_stock) FROM inventory_reference"
        ).fetchone() == (3, 33)
        assert conn.execute("SELECT count(*) FROM inventory_importbatch").fetchone()[0] == 0
        assert conn.execute("SELECT upper('água'),lower('ÁGUA')").fetchone() == ("ÁGUA", "água")
        assert (
            conn.execute("SELECT to_regclass('public.gva_native_ci_probe')").fetchone()[0] is None
        )
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
    assert {
        path.name: path.read_bytes() for path in (root / "tls").iterdir() if path.is_file()
    } == tls_before
    with connection(root) as conn:
        assert (
            conn.execute("SELECT label FROM gva_native_ci_probe WHERE id=1").fetchone()[0]
            == "synthetic-forward-migration"
        )
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
    log("::notice::Native smoke: update 1.0->1.1 and signed export identity verified")
    # Simulate stale filesystem version metadata after an interrupted upgrade.
    # Old 1.0 code must refuse a DB containing the NEW irreversible migration.
    from native_windows.runtime import environment
    from native_windows.state import write_json

    old_release = (
        Path(os.environ["ProgramFiles"])
        / "GestaoVertenteAveludada-synthetic/releases/1.0.0/payload"
    )
    current_state = json.loads((root / "installation.json").read_text())
    stop_all()
    run(["sc.exe", "start", SERVICES["postgres"]])
    wait_database(root)
    write_json(root / "installation.json", {**current_state, "release": str(old_release)})
    try:
        result = subprocess.run(
            [
                str(old_release / "python/python.exe"),
                "-s",
                "-B",
                str(old_release / "app/manage.py"),
                "shell",
                "-c",
                "from native_windows.schema import assert_current;assert_current()",
            ],
            cwd=old_release / "app",
            env=environment(root, owner=True),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=60,
        )
        assert result.returncode != 0
    finally:
        write_json(root / "installation.json", current_state)
    activate(root)
    health_http(root)
    # Old package is refused before overwriting files or changing service configuration.
    request = directory / "old.json"
    request.write_text("{}")
    run(
        [
            str(directory / "artifacts/GVA-synthetic-1.0.0-win-x64.exe"),
            "/S",
        ],
        error_log=host_error,
        expect_failure=True,
        timeout=120,
    )
    assert json.loads((root / "installation.json").read_text())["version"] == "1.1.0"
    log("::notice::Native smoke: expected downgrade refusal verified (not a recovery failure)")
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
    # Reinstall matching code after uninstall, preserving the SAME cluster/data.
    # This is not a downgrade, migration or synthetic reseed.
    uninstaller = (
        Path(os.environ["ProgramFiles"]) / "GestaoVertenteAveludada-synthetic/Uninstall.exe"
    )
    run([uninstaller, "/S"], error_log=host_error)
    for _ in range(60):
        if not uninstaller.exists():
            break
        time.sleep(1)
    time.sleep(1)
    assert json.loads((root / "installation.json").read_text())["uninstalled"] is True
    install("1.1.0")
    health_http(root)
    assert json.loads((root / "installation.json").read_text())["uninstalled"] is False
    assert (root / "signing/signing.pem").read_bytes() == key_before
    with connection(root) as conn:
        assert conn.execute(
            "SELECT source_id::text,sequence FROM consultation_exportsource"
        ).fetchone() == (source[0], source[1] + 1)
        assert (
            conn.execute("SELECT sum(current_stock) FROM inventory_reference").fetchone()[0] == 33
        )
    log("::notice::Native smoke: exact-version repair preserved data and signing identity")
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
    log("::notice::Native smoke: expected post-migration interruption blocked service restart")
    encrypted = max((root / "backups").glob("gva-*.gvabackup"), key=lambda p: p.stat().st_mtime)
    # Uninstaller removes only code/services; private state, keys and encrypted backups survive.
    uninstall = next(
        Path(os.environ["ProgramFiles"])
        .joinpath("GestaoVertenteAveludada-synthetic")
        .glob("Uninstall.exe")
    )
    run([uninstall, "/S"], error_log=host_error)
    for _ in range(30):
        if not uninstall.exists():
            break
        time.sleep(1)
    assert (root / "cluster/PG_VERSION").read_text().strip() == "17"
    assert (root / "signing/signing.pem").read_bytes() == key_before
    assert encrypted.is_file()
    # Recover an actual encrypted backup in a NEW root after retaining the original
    # synthetic installation. No existing directory or database is overwritten.
    # ProgramData is on C:, while RUNNER_TEMP may be on D:. Rename only on
    # the same volume; preserve the original test cluster without copying/deleting.
    import uuid

    preserved = root.with_name(root.name + "-preserved-" + uuid.uuid4().hex)
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
            "/CITestRequest=" + str(recovery_request),
        ],
        error_log=host_error,
        env={**os.environ, "GVA_CI_REQUEST": str(recovery_request)},
    )
    verified = json.loads((root / "recovery-verified.json").read_text(encoding="utf-8"))
    assert verified == {
        "instance": current_state["instance"],
        "version": "1.1.0",
        "status": "verified-awaiting-IT-cutover",
    }
    # This journal intentionally survives SUCCESS: no automatic recovery cutover.
    assert json.loads((root / "maintenance.json").read_text()) == {"phase": "recovery-started"}
    assert not (root / "activation-permit").exists()
    for kind in ("web", "backup", "publisher"):
        result = subprocess.run(["sc.exe", "start", SERVICES[kind]], capture_output=True)
        assert result.returncode != 0
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
    log(
        "::notice::Native smoke: encrypted recovery verified; data, movements and identity "
        "preserved; activation remains blocked awaiting IT cutover (journal retained by design)"
    )
    log(SMOKE_SUCCESS)


def report_failure(error, root):
    # Host errors are attached by run() only when that child actually fails.
    # A prior, deliberately rejected downgrade is not evidence of recovery failure.
    detail = str(error)
    marker = Path(root) / "maintenance.json"
    if marker.is_file():
        detail += "; maintenance journal=" + marker.read_text(encoding="utf-8")
    # Safe service categories only; never dump secret/config/request files.
    from native_windows.windows import service_failure
    for kind in ("postgres", "web", "backup", "publisher"):
        log("::notice::Service diagnostic " + kind + ": " + service_failure(root, kind))
    log(
        "::error::Native Windows smoke: " + type(error).__name__ + ": " + detail.replace("\n", " "),
        error=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory")
    try:
        main(parser.parse_args().directory)
    except Exception as error:
        root = Path(os.environ["PROGRAMDATA"]) / "GestaoVertenteAveludada-Teste"
        report_failure(error, root)
        raise
