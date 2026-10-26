"""Private pg_dump archives with document inventory; never restores over a database."""

import hashlib
import json
import os
import re
import stat
import subprocess
import tarfile
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from django.conf import settings
from django.core.management.base import CommandError
from django.db import connection
from psycopg import sql

from .documents import verified_bytes
from .models import Document
from .reporting import available_filter

MAX_UNPACKED = 10 * 1024**3


def _database():
    config = settings.DATABASES["default"]
    if connection.vendor != "postgresql":
        raise CommandError("Backup e restauro exigem PostgreSQL.")
    return config


def _tool(name, args, *, stdout=None, stdin=None):
    config = _database()
    prefix = json.loads(os.getenv("PG_TOOL_PREFIX", "[]"))
    if not isinstance(prefix, list) or any(not isinstance(arg, str) for arg in prefix):
        raise CommandError("PG_TOOL_PREFIX deve ser uma lista JSON de argumentos.")
    env = os.environ.copy()
    env.update(
        PGPASSWORD=config.get("PASSWORD", ""),
        PGCONNECT_TIMEOUT="10",
        PGSSLMODE=config.get("OPTIONS", {}).get("sslmode", "prefer"),
    )
    # A separate deployment container can supply PostgreSQL 17 client tools.
    command = prefix + [
        name,
        "--host",
        config["HOST"],
        "--port",
        str(config["PORT"]),
        "--username",
        config["USER"],
        *args,
    ]
    try:
        subprocess.run(
            command,
            env=env,
            stdin=stdin,
            stdout=stdout,
            stderr=subprocess.PIPE,
            check=True,
            timeout=int(os.getenv("BACKUP_TIMEOUT_SECONDS", "600")),
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise CommandError(
            "A ferramenta PostgreSQL falhou; confirme versão, ligação e permissões. Não foram publicados dados de erro privados."
        ) from error


def _root():
    configured = os.getenv("BACKUP_ROOT", "")
    if not configured or not Path(configured).is_absolute():
        raise CommandError("Defina BACKUP_ROOT como diretório privado absoluto e separado.")
    root = Path(configured)
    if root.is_symlink():
        raise CommandError("O diretório de backups não pode ser um link simbólico.")
    root = root.resolve()
    if (
        root == Path(settings.BASE_DIR).resolve()
        or Path(settings.BASE_DIR).resolve() in root.parents
    ):
        raise CommandError("Os backups devem ficar fora do checkout e dos recursos públicos.")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if stat.S_IMODE(root.stat().st_mode) & 0o077:
        raise CommandError("BACKUP_ROOT deve ter permissões 0700, sem acesso de grupo ou público.")
    return root


def _digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_archive(path):
    """Verify every member without arbitrary extraction or trusting archive paths."""
    try:
        with tarfile.open(path, "r:gz") as archive:
            members = archive.getmembers()
            names = [member.name for member in members]
            if len(names) != len(set(names)) or not all(member.isfile() for member in members):
                raise ValueError
            manifest_member = archive.getmember("manifest.json")
            if manifest_member.size > 4 * 1024 * 1024:
                raise ValueError
            manifest = json.load(archive.extractfile(manifest_member))
            if (
                manifest.get("schema") != 1
                or "database.dump" not in manifest["files"]
                or set(names) != set(manifest["files"]) | {"manifest.json"}
            ):
                raise ValueError
            total = 0
            for member in members:
                if member.name == "manifest.json":
                    continue
                if member.name != "database.dump" and not re.fullmatch(
                    r"documents/[0-9]+\.(pdf|png)", member.name
                ):
                    raise ValueError
                total += member.size
                if total > MAX_UNPACKED or member.size != manifest["files"][member.name]["size"]:
                    raise ValueError
                digest = hashlib.sha256()
                with archive.extractfile(member) as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
                if digest.hexdigest() != manifest["files"][member.name]["sha256"]:
                    raise ValueError
            return manifest
    except (OSError, tarfile.TarError, KeyError, ValueError, TypeError) as error:
        raise CommandError("Backup inválido ou com verificação de integridade falhada.") from error


def create_backup(*, synthetic=False):
    config = _database()
    if synthetic and not (
        config["NAME"].startswith("test_") or config["NAME"].endswith("_synthetic")
    ):
        raise CommandError("O modo sintético recusa a base configurada.")
    if settings.PRODUCTION and not os.getenv("BACKUP_GPG_RECIPIENT"):
        raise CommandError(
            "Produção exige BACKUP_GPG_RECIPIENT e uma chave pública de cifragem preparada pelo operador."
        )
    root = _root()
    retained = int(os.getenv("BACKUP_RETENTION_COUNT", "14"))
    if retained < 1 or retained > 1000:
        raise CommandError("Defina uma retenção entre 1 e 1000 backups.")
    with tempfile.TemporaryDirectory(prefix=".building-", dir=root) as temporary:
        staging = Path(temporary)
        manifest = {
            "schema": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "synthetic": synthetic,
            "database": config["NAME"],
            "files": {},
            "documents": [],
        }
        # Exclude concurrent confirmations/publication while dump + explicit document copy run.
        # A session lock, not a transaction, lets pg_dump inspect rows without waiting on locks.
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_lock(%s)", [73194621])
        try:
            dump = staging / "database.dump"
            with dump.open("xb") as output:
                os.chmod(dump, 0o600)
                _tool(
                    "pg_dump",
                    ["--format=custom", "--no-owner", "--no-acl", "--dbname", config["NAME"]],
                    stdout=output,
                )
            for document in Document.objects.filter(
                available_filter(), movement__status="confirmed"
            ).iterator():
                payload = verified_bytes(document)
                name = f"documents/{document.pk}.{'pdf' if document.kind == 'pdf' else 'png'}"
                destination = staging / name
                destination.parent.mkdir(exist_ok=True, mode=0o700)
                destination.write_bytes(payload)
                os.chmod(destination, 0o600)
                manifest["documents"].append(
                    {
                        "id": document.pk,
                        "movement": document.movement_id,
                        "kind": document.kind,
                        "path": name,
                        "sha256": document.sha256,
                    }
                )
        finally:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s)", [73194621])
        for path in staging.rglob("*"):
            if path.is_file():
                manifest["files"][path.relative_to(staging).as_posix()] = {
                    "sha256": _digest(path),
                    "size": path.stat().st_size,
                }
        (staging / "manifest.json").write_text(json.dumps(manifest, sort_keys=True))
        name = f"gg-backup-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex}.tar.gz"
        archive_path = staging / name
        with tarfile.open(archive_path, "w:gz") as archive:
            for name_in_archive in ["manifest.json", *sorted(manifest["files"])]:
                archive.add(staging / name_in_archive, arcname=name_in_archive)
        os.chmod(archive_path, 0o600)
        verify_archive(archive_path)
        if recipient := os.getenv("BACKUP_GPG_RECIPIENT"):
            encrypted = archive_path.with_name(archive_path.name + ".gpg")
            try:
                subprocess.run(
                    [
                        "gpg",
                        "--batch",
                        "--yes",
                        "--trust-model",
                        "always",
                        "--recipient",
                        recipient,
                        "--output",
                        str(encrypted),
                        "--encrypt",
                        str(archive_path),
                    ],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    timeout=120,
                )
            except (OSError, subprocess.SubprocessError) as error:
                raise CommandError(
                    "Não foi possível cifrar o backup. O backup não foi publicado e a retenção não foi aplicada."
                ) from error
            archive_path = encrypted
            os.chmod(archive_path, 0o600)
        target = root / archive_path.name
        os.replace(archive_path, target)
        # Retention only after a complete, verified, optionally encrypted archive exists.
        files = sorted(
            (p for p in root.glob("gg-backup-*.tar.gz*") if p.is_file() and not p.is_symlink()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old in files[retained:]:
            old.unlink()
        return target, manifest


def restore_synthetic(path, *, database):
    config = _database()
    if (
        not re.fullmatch(r"garrafas_restore_[a-z0-9_]{1,40}", database)
        or database == config["NAME"]
    ):
        raise CommandError(
            "O restauro exige uma base NOVA com nome garrafas_restore_..., distinta da base configurada."
        )
    root = _root()
    with tempfile.TemporaryDirectory(prefix=".restore-", dir=root) as temporary:
        staging = Path(temporary)
        archive_path = Path(path)
        if archive_path.suffix == ".gpg":
            decrypted = staging / "backup.tar.gz"
            try:
                subprocess.run(
                    ["gpg", "--batch", "--output", str(decrypted), "--decrypt", str(archive_path)],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    timeout=120,
                )
                os.chmod(decrypted, 0o600)
            except (OSError, subprocess.SubprocessError) as error:
                raise CommandError(
                    "Não foi possível decifrar o backup com a chave privada disponibilizada pelo operador."
                ) from error
            archive_path = decrypted
        manifest = verify_archive(archive_path)
        if not manifest.get("synthetic"):
            raise CommandError(
                "Este comando automático apenas restaura backups declarados sintéticos. Consulte o procedimento manual para produção."
            )
        # Never drop, replace or connect to an existing target database.
        with psycopg.connect(
            dbname="postgres",
            user=config["USER"],
            password=config["PASSWORD"],
            host=config["HOST"],
            port=config["PORT"],
            sslmode=config.get("OPTIONS", {}).get("sslmode", "prefer"),
            autocommit=True,
        ) as admin:
            if admin.execute("SELECT 1 FROM pg_database WHERE datname=%s", [database]).fetchone():
                raise CommandError("A base de destino já existe. Não foi alterada.")
            admin.execute(
                sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(database))
            )
        dump = staging / "database.dump"
        with tarfile.open(archive_path, "r:gz") as archive, dump.open("xb") as destination:
            os.chmod(dump, 0o600)
            with archive.extractfile("database.dump") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    destination.write(chunk)
        with dump.open("rb") as source:
            _tool(
                "pg_restore",
                ["--no-owner", "--no-acl", "--exit-on-error", "--dbname", database],
                stdin=source,
            )
        # Verify document bytes restored from the dump, not just copies in the archive.
        with psycopg.connect(
            dbname=database,
            user=config["USER"],
            password=config["PASSWORD"],
            host=config["HOST"],
            port=config["PORT"],
            sslmode=config.get("OPTIONS", {}).get("sslmode", "prefer"),
        ) as restored:
            has_report_files = restored.execute(
                "SELECT to_regclass('public.inventory_reportfile') IS NOT NULL"
            ).fetchone()[0]
            for record in manifest["documents"]:
                row = restored.execute(
                    (
                        "SELECT COALESCE(d.payload,f.payload),d.sha256 FROM inventory_document d LEFT JOIN inventory_reportfile f ON f.document_id=d.id WHERE d.id=%s"
                        if has_report_files
                        else "SELECT payload,sha256 FROM inventory_document WHERE id=%s"
                    ),
                    [record["id"]],
                ).fetchone()
                if (
                    not row
                    or hashlib.sha256(bytes(row[0])).hexdigest() != row[1]
                    or row[1] != record["sha256"]
                ):
                    raise CommandError(
                        "O restauro concluiu, mas os documentos falharam a verificação. O destino isolado foi conservado para diagnóstico."
                    )
        return manifest
