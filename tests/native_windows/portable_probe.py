"""Actual portable restoration on the disposable native Windows CI installation.

Called only by windows_smoke after its existing synthetic-root guards. Never a
command for an operator's Windows installation. No test outputs contain secrets.
"""

import json
import uuid
from pathlib import Path
from unittest.mock import patch

from native_windows.backup_wizard import export_backup
from native_windows.install import health_http
from native_windows.maintenance import connection, evidence
from native_windows.package import UnsafeOperation, digest
from native_windows.recovery_wizard import preview, restore
from native_windows.runtime import read_state


def run(root, directory, key, phrase):
    root, directory = Path(root), Path(directory)
    state = read_state(root)
    assert state["channel"] == "synthetic" and state["database"] == "gva_native_synthetic"
    release = Path(state["release"])
    manifest = json.loads((release.parent / "package.json").read_text())
    archive = directory / ("portable-" + uuid.uuid4().hex + ".gvabackup")
    credential = "synthetic-portable-" + uuid.uuid4().hex
    from native_windows import backup_vault
    from native_windows.backup_wizard import configure_credential

    configure_credential(root, {"portable_password": credential})
    assert credential.encode() not in (root / "secrets" / backup_vault.NAME).read_bytes()
    assert backup_vault.load(root)["password"] == credential
    result = export_backup(
        root,
        {
            "destination": str(archive),
            "recovery_key": str(key),
            "recovery_password": phrase,

        },
    )
    second = directory / ("consecutive-" + uuid.uuid4().hex + ".gvabackup")
    assert export_backup(root, {"destination": str(second)})["sha256"] == digest(second)
    assert result["sha256"] == digest(archive)
    with connection(root) as conn:
        before = evidence(conn)
    request = {"archive": str(archive), "credential": credential}
    original = (root / "installation.json").read_bytes()
    try:
        preview(
            root, release, manifest, {**request, "credential": "incorrect synthetic credential"}
        )
        raise AssertionError("Incorrect credential was accepted")
    except UnsafeOperation:
        assert (root / "installation.json").read_bytes() == original
        health_http(root)
    view = preview(root, release, manifest, request)
    confirmed = {
        **request,
        "confirmed": True,
        "source_offline": True,
        "confirmed_identity_history": True,
        "token": view["token"],
    }
    # Failure AFTER actual pg_restore: check original cluster/keys/services survive.
    with patch(
        "native_windows.recovery_wizard.grants",
        side_effect=RuntimeError("synthetic restore failure"),
    ):
        try:
            restore(root, release, manifest, confirmed, root / "package-policy.json")
            raise AssertionError("Injected restoration failure was accepted")
        except UnsafeOperation:
            assert (root / "installation.json").read_bytes() == original
            health_http(root)
    # A fresh preview is required; no success until actual evidence and health pass.
    view = preview(root, release, manifest, request)
    result = restore(
        root, release, manifest, {**confirmed, "token": view["token"]}, root / "package-policy.json"
    )
    health_http(root)
    assert (
        root.parent / result["previous_preserved"] / "cluster/PG_VERSION"
    ).read_text().strip() == "17"
    assert not (root / "maintenance.json").exists()
    assert (root / "secrets/recovery-envelope.json").is_file()
    with connection(root) as conn:
        after = evidence(conn)
    # Maintenance adds append-only audit events; every other table must match.
    for table, expected in before.items():
        if table not in ("inventory_auditevent", "__sequences__"):
            assert after[table] == expected, "Restored table differs: " + table
    assert json.loads((root / "publisher.json").read_text())["enabled"] is False
    assert not (root / "secrets" / backup_vault.NAME).exists()
    assert not (root / "runtime/wifi/approved").exists()
    assert not (root / "runtime/receiver/approved").exists()
    assert archive.exists()  # Retention/uninstall never owns the selected external file.

    return request


def fresh_destination(root, directory, request):
    from native_windows.windows import uninstall

    root, directory = Path(root), Path(directory)
    state = read_state(root)
    release = Path(state["release"])
    manifest = json.loads((release.parent / "package.json").read_text())
    # This is the disposable CI fixture only. Preserve the previous legacy
    # recovery, remove ONLY its service registrations, and use a truly new root.
    uninstall()
    preserved = root.with_name(root.name + "-LegacyCI-" + uuid.uuid4().hex)
    root.rename(preserved)
    summary = preview(root, release, manifest, request)
    assert summary["replaces_existing"] is False
    result = restore(
        root,
        release,
        manifest,
        {
            **request,
            "confirmed": True,
            "source_offline": True,
            "confirmed_identity_history": True,
            "token": summary["token"],
        },
        directory / "policy.json",
    )
    assert result["status"] == "verified-and-running"
    health_http(root)
    with connection(root) as conn:
        assert (
            conn.execute("SELECT sum(current_stock) FROM inventory_reference").fetchone()[0] == 33
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM inventory_reportfile WHERE payload IS NOT NULL"
            ).fetchone()[0]
            == 6
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM inventory_document WHERE kind='signature' AND payload IS NOT NULL"
            ).fetchone()[0]
            == 3
        )
    assert Path(request["archive"]).exists()
    assert preserved.exists()
