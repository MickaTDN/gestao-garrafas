import os
import secrets
import subprocess
import uuid
from pathlib import Path

import psycopg
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TransactionTestCase
from psycopg import sql

from inventory.models import Location, Reference


class RestrictedRoleTests(TransactionTestCase):
    def test_app_role_can_confirm_but_not_change_schema_or_delete_ledger(self):
        cfg = settings.DATABASES["default"]
        actor = get_user_model().objects.create_user(username="role-synthetic", role="admin")
        loc = Location.objects.create(name="Privilégios sintéticos")
        ref = Reference.objects.create(
            code="ROLE-SYN", name="Teste sintético de permissões", location=loc, current_stock=5
        )
        role = "gg_test_" + uuid.uuid4().hex[:16]
        password = secrets.token_urlsafe(32)
        conn = psycopg.connect(
            dbname=cfg["NAME"],
            user=cfg["USER"],
            password=cfg["PASSWORD"],
            host=cfg["HOST"],
            port=cfg["PORT"],
            autocommit=True,
        )
        try:
            conn.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                    sql.Identifier(role), sql.Literal(password)
                )
            )
            grants = (
                (Path(settings.BASE_DIR) / "deploy/app-role.sql")
                .read_text()
                .replace(':"app_role"', sql.Identifier(role).as_string(conn))
                .replace(':"DBNAME"', sql.Identifier(cfg["NAME"]).as_string(conn))
            )
            conn.execute(grants)
            with psycopg.connect(
                dbname=cfg["NAME"],
                user=role,
                password=password,
                host=cfg["HOST"],
                port=cfg["PORT"],
                autocommit=True,
            ) as restricted:
                self.assertEqual(
                    restricted.execute(
                        "SELECT current_stock FROM inventory_reference WHERE id=%s", [ref.pk]
                    ).fetchone()[0],
                    5,
                )
                for statement in (
                    "CREATE TABLE should_be_denied(id integer)",
                    "DELETE FROM inventory_auditevent",
                    "DELETE FROM inventory_movement",
                    "DELETE FROM inventory_document",
                    "UPDATE django_migrations SET name='tamper'",
                ):
                    with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                        restricted.execute(statement)
            code = f"from accounts.models import User; from inventory.models import Reference; from tests.document_fixtures import confirmed_operation; confirmed_operation(User.objects.get(pk={actor.pk}),Reference.objects.get(pk={ref.pk}),signed=True)"
            env = {**os.environ, "DB_NAME": cfg["NAME"], "DB_USER": role, "DB_PASSWORD": password}
            result = subprocess.run(
                [
                    str(Path(settings.BASE_DIR) / ".venv/bin/python"),
                    "manage.py",
                    "shell",
                    "--verbosity",
                    "0",
                    "-c",
                    code,
                ],
                cwd=settings.BASE_DIR,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
            )
            self.assertEqual(
                result.returncode,
                0,
                "Application could not confirm using the restricted synthetic role",
            )
            ref.refresh_from_db()
            self.assertEqual(ref.current_stock, 3)
        finally:
            conn.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
            conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))
            conn.close()
