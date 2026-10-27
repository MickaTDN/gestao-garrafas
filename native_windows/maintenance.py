"""Verified native backups, new-database rehearsals and migration orchestration."""

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from psycopg import sql

from .crypto_backup import decrypt, encrypt
from .package import UnsafeOperation, digest, regular_tree
from .runtime import environment, manage, read_state
from .state import exclusive, write_json
from .windows import SERVICES, activate, configure, disable_all, native, stop_all


def connection(root, database=None):
    state = read_state(root)
    credentials = json.loads((Path(root) / "secrets/owner.json").read_text())
    return psycopg.connect(
        host="127.0.0.1",
        port=state["db_port"],
        dbname=database or state["database"],
        user=credentials["username"],
        password=credentials["password"],
        autocommit=True,
    )


def pg_tool(root, name, database, *, stdout=None, stdin=None, snapshot=None):
    state = read_state(root)
    credentials = json.loads((Path(root) / "secrets/owner.json").read_text())
    env = environment(root, owner=True)
    env["PGPASSWORD"] = credentials["password"]
    args = [
        str(Path(state["release"]) / f"postgres/bin/{name}.exe"),
        "--host",
        "127.0.0.1",
        "--port",
        str(state["db_port"]),
        "--username",
        credentials["username"],
        "--no-owner",
        "--no-acl",
    ]
    args += (
        ["--format=custom", database]
        if name == "pg_dump"
        else ["--exit-on-error", "--single-transaction", "--dbname", database]
    )
    if snapshot is not None:
        args += ["--snapshot", snapshot]
    subprocess.run(
        args,
        env=env,
        stdout=stdout,
        stdin=stdin,
        stderr=subprocess.DEVNULL,
        check=True,
        timeout=1800,
    )


def evidence(conn):
    """Logical rows, not schema version: detects lost history, sequences and PDF bytes."""
    values = {}
    for (table,) in conn.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
    ):
        # Stable per-row hash and ordering also checks binary payloads, identities and credentials.
        rows = conn.execute(
            sql.SQL("SELECT md5(row_to_json(t)::text) FROM {} t ORDER BY 1").format(
                sql.Identifier(table)
            )
        )
        h = hashlib.sha256()
        count = 0
        for (value,) in rows:
            h.update(value.encode())
            count += 1
        values[table] = {"rows": count, "sha256": h.hexdigest()}
    values["__sequences__"] = list(
        conn.execute(
            "SELECT schemaname,sequencename,last_value FROM pg_sequences WHERE schemaname='public' ORDER BY sequencename"
        )
    )
    return values


def validate_material(root):
    """A restorable database without its matching signing identity is insufficient."""
    import base64

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    root = Path(root)
    required = (
        "secrets/owner.json",
        "secrets/app.json",
        "signing/signing.pem",
        "signing/origin.vatrust.json",
        "package-policy.json",
        "recovery-public.pem",
    )
    if any(not (root / name).is_file() or (root / name).is_symlink() for name in required):
        raise UnsafeOperation(
            "Configuração/chaves incompletas. Backup e atualização recusados; não regenere a identidade Android."
        )
    key = serialization.load_pem_private_key(
        (root / "signing/signing.pem").read_bytes(), password=None
    )
    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
        raise UnsafeOperation("Chave Android inválida.")
    der = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    trust = json.loads((root / "signing/origin.vatrust.json").read_text())
    public = base64.urlsafe_b64encode(der).rstrip(b"=").decode()
    if not any(item["spki"] == public for item in trust["keys"]):
        raise UnsafeOperation("A confiança Android não corresponde à chave da instalação.")
    with connection(root) as conn:
        row = conn.execute(
            "SELECT source_id::text FROM consultation_exportsource WHERE id=1"
        ).fetchone()
        if not row or row[0] != trust["source_id"]:
            raise UnsafeOperation("A origem Android não corresponde à base desta instalação.")


def backup(root):
    root = Path(root)
    state = read_state(root)
    validate_material(root)
    target_root = root / "backups"
    # Daily service sees only this admin-configured path; never accepts browser file paths.
    config = json.loads((root / "backup-policy.json").read_text())
    keep = config["retain"]
    if type(keep) is not int or not 2 <= keep <= 1000:
        raise UnsafeOperation("A retenção deve conservar entre 2 e 1000 backups.")
    with (
        exclusive(target_root),
        tempfile.TemporaryDirectory(prefix=".building-", dir=target_root) as temporary,
    ):
        staging = Path(temporary)
        with connection(root) as conn:
            conn.execute("SELECT pg_advisory_lock(73194622)")
            conn.execute("SELECT pg_advisory_lock(73194621)")
            try:
                conn.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
                snapshot = conn.execute("SELECT pg_export_snapshot()").fetchone()[0]
                before = evidence(conn)
                with (staging / "database.dump").open("xb") as output:
                    pg_tool(root, "pg_dump", state["database"], stdout=output, snapshot=snapshot)
                # Config, signing keys and certificates are inside the ENCRYPTED archive only.
                for name in (
                    "installation.json",
                    "backup-policy.json",
                    "recovery-public.pem",
                    "package-policy.json",
                    "secrets",
                    "signing",
                    "tls",
                    "publisher.json",
                ):
                    source = root / name
                    if source.is_dir():
                        shutil.copytree(source, staging / name)
                    elif source.is_file():
                        shutil.copy2(source, staging / name)
                manifest = {
                    "schema": 1,
                    "instance": state["instance"],
                    "version": state["version"],
                    "channel": state["channel"],
                    "evidence": before,
                    "files": regular_tree(staging),
                }
            finally:
                conn.execute("ROLLBACK")
                conn.execute("SELECT pg_advisory_unlock(73194621)")
                conn.execute("SELECT pg_advisory_unlock(73194622)")
        write_json(staging / "manifest.json", manifest)
        archive = staging / "backup.tar"
        with tarfile.open(archive, "w") as handle:
            for name in [*manifest["files"], "manifest.json"]:
                handle.add(staging / name, arcname=name, recursive=False)
        verify_archive(archive)
        target = target_root / (
            "gva-"
            + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            + "-"
            + uuid.uuid4().hex
            + ".gvabackup"
        )
        encrypt(
            archive,
            target,
            (root / "recovery-public.pem").read_bytes(),
            {
                "instance": state["instance"],
                "version": state["version"],
                "channel": state["channel"],
            },
        )
        # Record transport integrity. GCM authentication is checked during recovery/update.
        write_json(
            target.with_suffix(".sha256.json"),
            {"sha256": digest(target), "size": target.stat().st_size},
        )
        destination = config.get("copy_to")
        if destination:
            directory = Path(destination)
            if not directory.is_absolute() or not directory.is_dir():
                raise UnsafeOperation(
                    "Destino empresarial de backup indisponível; cópia local conservada."
                )
            partial = directory / (target.name + ".partial")
            final = directory / target.name
            if final.exists() or partial.exists():
                raise UnsafeOperation("Destino de backup já existe.")
            shutil.copyfile(target, partial)
            if digest(partial) != digest(target):
                raise UnsafeOperation(
                    "A cópia empresarial falhou a integridade; cópia local conservada."
                )
            os.replace(partial, final)
        # Only completed files owned by this installation's backup directory; remote copies untouched.
        for old in sorted(
            target_root.glob("gva-*.gvabackup"), key=lambda p: p.stat().st_mtime, reverse=True
        )[keep:]:
            old.unlink()
            old.with_suffix(".sha256.json").unlink(missing_ok=True)
        return target


def verify_archive(path):
    with tarfile.open(path, "r:") as archive:
        members = archive.getmembers()
        if len(members) > 50000 or any(
            not item.isfile() or item.size > 100 * 1024**3 for item in members
        ):
            raise UnsafeOperation("Backup com membros inválidos.")
        names = [item.name for item in members]
        if (
            len(names) != len(set(names))
            or "manifest.json" not in names
            or archive.getmember("manifest.json").size > 16 * 1024 * 1024
        ):
            raise UnsafeOperation("Manifesto inválido.")
        manifest = json.load(archive.extractfile("manifest.json"))
        if (
            manifest["schema"] != 1
            or set(names) != set(manifest["files"]) | {"manifest.json"}
            or "database.dump" not in names
        ):
            raise UnsafeOperation("Backup incompleto.")
        total = 0
        for item in members:
            if item.name == "manifest.json":
                continue
            name = item.name
            if (
                "\\" in name
                or ":" in name
                or name.startswith("/")
                or any(part in ("", ".", "..") for part in name.split("/"))
            ):
                raise UnsafeOperation("Caminho inválido no backup.")
            if name not in {
                "database.dump",
                "installation.json",
                "backup-policy.json",
                "recovery-public.pem",
                "package-policy.json",
                "publisher.json",
            } and name.split("/")[0] not in {"secrets", "signing", "tls"}:
                raise UnsafeOperation("Ficheiro inesperado no backup.")
            total += item.size
            if total > 100 * 1024**3:
                raise UnsafeOperation("Backup demasiado grande.")
            expected = manifest["files"][name]
            if item.size != expected["size"]:
                raise UnsafeOperation("Tamanho inválido no backup.")
            h = hashlib.sha256()
            with archive.extractfile(item) as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    h.update(block)
            if h.hexdigest() != expected["sha256"]:
                raise UnsafeOperation("Integridade do backup falhou.")
        return manifest


def extract_verified(path, target):
    manifest = verify_archive(path)
    target = Path(target)
    if target.exists():
        raise UnsafeOperation("O destino de extração deve ser novo.")
    target.mkdir()
    with tarfile.open(path) as archive:
        for name in manifest["files"]:
            destination = target / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as output, archive.extractfile(name) as inp:
                shutil.copyfileobj(inp, output)
    return manifest


def restore_check(root, archive):
    manifest = verify_archive(archive)
    state = read_state(root)
    if (
        manifest["instance"] != state["instance"]
        or manifest["version"] != state["version"]
        or manifest["channel"] != state["channel"]
    ):
        raise UnsafeOperation("O backup não corresponde a esta instalação/versão.")
    database = "gva_restore_" + uuid.uuid4().hex
    # The rehearsal database is NEW and never substituted for the operational DB.
    with connection(root, "postgres") as conn:
        conn.execute(
            sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(database))
        )
    with (
        tarfile.open(archive) as handle,
        handle.extractfile("database.dump") as source,
        tempfile.TemporaryFile() as dump,
    ):
        shutil.copyfileobj(source, dump)
        dump.seek(0)
        pg_tool(root, "pg_restore", database, stdin=dump)
    with connection(root, database) as conn:
        actual = evidence(conn)
        if json.loads(json.dumps(actual)) != manifest["evidence"]:
            raise UnsafeOperation(
                "O restauro de ensaio difere do original; preservado para diagnóstico."
            )
    # Only drop the generated rehearsal after exact verification; never accept an input DB name.
    with connection(root, "postgres") as conn:
        conn.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))
    return manifest


class UpdateActions:
    def __init__(self, root, release, recovery_key, password):
        self.root, self.release = Path(root), Path(release)
        self.recovery_key, self.password = Path(recovery_key), password
        self.old = read_state(root)

    def disable(self):
        disable_all()

    def stop(self):
        stop_all()

    def database_start(self):
        # Launch only the existing PG17 service, still DISABLED for the next boot.
        native(["sc.exe", "config", SERVICES["postgres"], "start=", "demand"])
        native(["sc.exe", "start", SERVICES["postgres"]])
        from .install import wait_database

        wait_database(self.root)

    def backup_and_restore_check(self):
        self.database_start()
        encrypted = backup(self.root)
        with tempfile.TemporaryDirectory(dir=self.root / "backups", prefix=".verify-") as temp:
            plain = Path(temp) / "verified.tar"
            decrypt(encrypted, plain, self.recovery_key.read_bytes(), self.password)
            restore_check(self.root, plain)
        self.password = ""

    def migrate(self):
        # Old code never starts again. Schema migration runs as owner with NEW code.
        state_path = self.root / "installation.json"
        write_json(state_path, {**self.old, "release": str(self.release)})
        try:
            manage(self.root, "migrate", "--noinput")
            grants(self.root)
        finally:
            # Keep old version marker until the final commit point; journal blocks startup.
            write_json(state_path, self.old)

    def health(self):
        state_path = self.root / "installation.json"
        write_json(state_path, {**self.old, "release": str(self.release)})
        try:
            manage(self.root, "check", "--fail-level", "WARNING")
            manage(self.root, "migrate", "--check")
        finally:
            write_json(state_path, self.old)
        stop_all()

    def activate(self):
        configure(self.root, self.release)
        # Journal is removed only AFTER activation. Web deliberately refuses to start
        # until a separate activation permit is created, bound to the new release.
        (self.root / "activation-permit").write_text(str(self.release))
        try:
            activate(self.root)
            from .install import health_http

            health_http(self.root)
        finally:
            (self.root / "activation-permit").unlink(missing_ok=True)


def grants(root):
    state = read_state(root)
    text = (
        (Path(state["release"]) / "app/deploy/app-role.sql")
        .read_text()
        .replace(':"app_role"', '"gva_web"')
        .replace(':"DBNAME"', '"' + state["database"] + '"')
    )
    with connection(root) as conn:
        conn.execute(text)
