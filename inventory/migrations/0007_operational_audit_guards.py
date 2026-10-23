"""Extend existing PostgreSQL ledger guards to transfers and append-only audit."""
from django.db import migrations

FORWARD = """
CREATE TRIGGER inventory_confirmed_transfer_guard
BEFORE INSERT OR UPDATE OR DELETE ON inventory_locationchange
FOR EACH ROW EXECUTE FUNCTION inventory_guard_confirmed_line();

CREATE FUNCTION inventory_guard_audit() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Audit events are append only' USING ERRCODE = '23514';
END;
$$;
CREATE TRIGGER inventory_audit_guard BEFORE UPDATE OR DELETE ON inventory_auditevent
FOR EACH ROW EXECUTE FUNCTION inventory_guard_audit();
"""
REVERSE = """
DROP TRIGGER IF EXISTS inventory_audit_guard ON inventory_auditevent;
DROP FUNCTION IF EXISTS inventory_guard_audit();
DROP TRIGGER IF EXISTS inventory_confirmed_transfer_guard ON inventory_locationchange;
"""


def install(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(FORWARD)


def remove(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(REVERSE)


class Migration(migrations.Migration):
    dependencies = [("inventory", "0006_operational_workflows")]
    operations = [migrations.RunPython(install, remove)]
