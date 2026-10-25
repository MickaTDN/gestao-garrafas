"""Installation-only synthetic bootstrap. Never imports a workbook or adopts a database."""

import json
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
MARKER = "gg_windows_pilot"


def context():
    if (
        os.getenv("DJANGO_SETTINGS_MODULE") != "config.windows_local"
        or os.getenv("GG_WINDOWS_PILOT") != "synthetic-v1"
    ):
        raise RuntimeError("Perfil do piloto invalido.")
    instance = str(uuid.UUID(os.environ["GG_PILOT_ID"]))
    import django

    django.setup()
    from django.conf import settings

    config = settings.DATABASES["default"]
    if config["HOST"] != "db" or config["NAME"] != "garrafas_windows_synthetic":
        raise RuntimeError("Destino do piloto invalido.")
    return instance, config


def check_marker(cursor, instance):
    cursor.execute("SELECT instance_id::text, seeded FROM gg_windows_pilot WHERE id=1")
    row = cursor.fetchone()
    if not row or row[0] != instance:
        raise RuntimeError("A base pertence a outra instalacao. Nao foi alterada.")
    return row[1]


def initialize(instance, config, *, verified_recovery=False):
    if os.getenv("GG_BOOTSTRAP_OWNER") != "1" or config["USER"] != "gg_pilot_owner":
        raise RuntimeError("A inicializacao exige o processo separado de instalacao.")
    import psycopg
    from psycopg import sql

    with psycopg.connect(
        dbname=config["NAME"],
        user=config["USER"],
        password=config["PASSWORD"],
        host=config["HOST"],
        port=config["PORT"],
        autocommit=True,
    ) as owner:
        owner.execute("SELECT pg_advisory_lock(73194623)")
        try:
            tables = [
                row[0]
                for row in owner.execute(
                    "SELECT tablename FROM pg_tables WHERE schemaname='public'"
                )
            ]
            if MARKER not in tables:
                if tables:
                    raise RuntimeError(
                        "Base preexistente sem marcador do piloto: inicializacao recusada."
                    )
                owner.execute(
                    "CREATE TABLE gg_windows_pilot(id integer PRIMARY KEY CHECK(id=1), instance_id uuid NOT NULL, seeded boolean NOT NULL DEFAULT false)"
                )
                owner.execute(
                    "INSERT INTO gg_windows_pilot(id,instance_id) VALUES(1,%s)", [instance]
                )
            with owner.cursor() as cursor:
                seeded = check_marker(cursor, instance)
            if not owner.execute("SELECT 1 FROM pg_roles WHERE rolname='gg_pilot_app'").fetchone():
                password = Path("/run/secrets/db_app_password").read_text().strip()
                owner.execute(
                    sql.SQL(
                        "CREATE ROLE gg_pilot_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}"
                    ).format(sql.Literal(password))
                )
            from django.core.management import call_command
            from django.db import connection
            from django.db.migrations.executor import MigrationExecutor

            executor = MigrationExecutor(connection)
            pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
            if seeded and pending and not verified_recovery:
                raise RuntimeError(
                    "Uma atualizacao com migracoes exige backup verificado e recuperacao num piloto novo. A base existente nao foi migrada."
                )
            call_command("migrate", interactive=False, verbosity=0)
            # Reuse the reviewed application grants instead of creating another privilege model.
            grants = (
                (ROOT / "deploy/app-role.sql")
                .read_text()
                .replace(':"app_role"', '"gg_pilot_app"')
                .replace(':"DBNAME"', '"garrafas_windows_synthetic"')
            )
            owner.execute(grants)
            seed(instance)
            # Docker creates an empty backup volume as root. Set only this pilot's mount.
            backup_root = Path("/backups")
            backup_root.mkdir(exist_ok=True)
            if backup_root.stat().st_uid != os.getuid():
                raise RuntimeError(
                    "O volume de backups precisa de permissao do utilizador da aplicacao."
                )
            backup_root.chmod(0o700)
            print(
                "Piloto sintetico inicializado. Nao foram criadas contas ou passwords predefinidas."
            )
        finally:
            owner.execute("SELECT pg_advisory_unlock(73194623)")


def seed(instance):
    from django.db import connection, transaction
    from django.utils import timezone

    from inventory.models import (
        AuditEvent,
        ImportBatch,
        Location,
        OpeningBalance,
        Person,
        Reference,
    )

    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            "SELECT instance_id::text,seeded FROM gg_windows_pilot WHERE id=1 FOR UPDATE"
        )
        row = cursor.fetchone()
        if not row or row[0] != instance:
            raise RuntimeError("Marcador do piloto invalido.")
        if row[1]:
            return
        if Reference.objects.exists() or ImportBatch.objects.exists():
            raise RuntimeError("O piloto recusa misturar dados preexistentes com demonstracao.")
        location = Location.objects.order_by("pk").first()
        if location is None:
            raise RuntimeError("Configuracao estrutural ausente.")
        for code, name, capacity, quantity in [
            ("SYN-WIN-001", "Demonstracao ficticia Azul", 6, 24),
            ("SYN-WIN-002", "Demonstracao ficticia Verde", 12, 0),
            ("SYN-WIN-003", "Demonstracao ficticia Capacidade desconhecida", None, 9),
        ]:
            ref = Reference.objects.create(
                code=code,
                name=name,
                box_capacity=capacity,
                current_stock=quantity,
                location=location,
            )
            OpeningBalance.objects.create(
                reference=ref,
                quantity=quantity,
                date=timezone.localdate(),
                explanation="Dados exclusivamente ficticios do piloto Windows; nao provem do Excel.",
            )
        Person.objects.create(name="Pessoa ficticia do piloto Windows")
        AuditEvent.objects.create(
            action="windows_pilot.synthetic_seed", details={"instance": instance, "references": 3}
        )
        cursor.execute("UPDATE gg_windows_pilot SET seeded=true WHERE id=1")


def status(instance):
    from django.db import connection

    from accounts.models import User
    from inventory.models import ImportBatch, Reference

    with connection.cursor() as cursor:
        seeded = check_marker(cursor, instance)
    if ImportBatch.objects.exists():
        raise RuntimeError("O piloto nao deve conter lotes de importacao.")
    print(
        json.dumps(
            {
                "mode": "synthetic-v1",
                "instance": instance,
                "seeded": seeded,
                "references": Reference.objects.count(),
                "administrator_exists": User.objects.filter(role="admin", is_active=True).exists(),
            }
        )
    )


def recover(instance, config):
    """Restore only our synthetic archive into an EMPTY, new pilot database."""
    if os.getenv("GG_BOOTSTRAP_OWNER") != "1":
        raise RuntimeError("Restauro exige processo de instalacao separado.")
    import hashlib
    import tarfile
    import tempfile

    import psycopg

    from inventory.backups import _tool, verify_archive

    archive_path = Path("/restore/pilot.tar.gz")
    manifest = verify_archive(archive_path)
    if (
        manifest.get("synthetic") is not True
        or manifest.get("database") != "garrafas_windows_synthetic"
    ):
        raise RuntimeError("Este arquivo nao e um backup do piloto sintetico Windows.")
    with psycopg.connect(
        dbname=config["NAME"],
        user=config["USER"],
        password=config["PASSWORD"],
        host=config["HOST"],
        port=config["PORT"],
        autocommit=True,
    ) as owner:
        if owner.execute("SELECT 1 FROM pg_tables WHERE schemaname='public'").fetchone():
            raise RuntimeError("O destino de recuperacao ja contem tabelas. Nao foi alterado.")
    with tempfile.TemporaryFile() as dump, tarfile.open(archive_path, "r:gz") as archive:
        with archive.extractfile("database.dump") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                dump.write(chunk)
        dump.seek(0)
        _tool(
            "pg_restore",
            ["--no-owner", "--no-acl", "--exit-on-error", "--dbname", config["NAME"]],
            stdin=dump,
        )
    from django.db import connection, transaction

    from inventory.models import AuditEvent, ImportBatch

    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            "SELECT instance_id::text,seeded FROM gg_windows_pilot WHERE id=1 FOR UPDATE"
        )
        old = cursor.fetchone()
        if not old or not old[1] or ImportBatch.objects.exists():
            raise RuntimeError("O restauro nao corresponde a um piloto sintetico completo.")
        cursor.execute("SELECT to_regclass('public.inventory_reportfile') IS NOT NULL")
        has_report_files = cursor.fetchone()[0]
        for document in manifest["documents"]:
            cursor.execute(
                (
                    "SELECT COALESCE(d.payload,f.payload),d.sha256 FROM inventory_document d LEFT JOIN inventory_reportfile f ON f.document_id=d.id WHERE d.id=%s"
                    if has_report_files
                    else "SELECT payload,sha256 FROM inventory_document WHERE id=%s"
                ),
                [document["id"]],
            )
            row = cursor.fetchone()
            if (
                not row
                or hashlib.sha256(bytes(row[0])).hexdigest() != row[1]
                or row[1] != document["sha256"]
            ):
                raise RuntimeError("Documento restaurado falhou a verificacao de integridade.")
        cursor.execute("UPDATE gg_windows_pilot SET instance_id=%s WHERE id=1", [instance])
        AuditEvent.objects.create(
            action="windows_pilot.synthetic_recovery",
            details={"source_instance": old[0], "instance": instance},
        )
    initialize(instance, config, verified_recovery=True)
    print("Recuperacao sintetica concluida num destino novo. A origem nao foi alterada.")


def main():
    action = sys.argv[1] if len(sys.argv) == 2 else ""
    if action not in ("initialize", "status", "health", "recover"):
        raise RuntimeError("Acao invalida.")
    instance, config = context()
    if action == "initialize":
        initialize(instance, config)
    elif action == "recover":
        recover(instance, config)
    else:
        status(instance)
        if action == "health":
            import urllib.request

            # Confirms Gunicorn is serving HTTP as well as database availability.
            with urllib.request.urlopen("http://127.0.0.1:8000/entrar/", timeout=3) as response:
                if response.status != 200:
                    raise RuntimeError("Servidor HTTP indisponivel.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Never print connection strings, passwords, signatures or raw SQL.
        print("Categoria de diagnostico: " + type(error).__name__, file=sys.stderr)
        if isinstance(error, RuntimeError):
            print(str(error), file=sys.stderr)
        print(
            "Falha no piloto Windows. Confirme perfil, marcador e permissoes; preserve os volumes e segredos.",
            file=sys.stderr,
        )
        sys.exit(1)
