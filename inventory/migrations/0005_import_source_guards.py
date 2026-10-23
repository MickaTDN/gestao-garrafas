"""Keep merged source contributions immutable once their movement is confirmed."""

from django.db import migrations


SQL = """
CREATE FUNCTION inventory_guard_confirmed_source() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE parent_status varchar;
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        SELECT m.status INTO parent_status
          FROM inventory_movement m JOIN inventory_movementline l ON l.movement_id=m.id
         WHERE l.id=OLD.line_id FOR UPDATE OF m;
        IF parent_status = 'confirmed' THEN
            RAISE EXCEPTION 'Confirmed source contributions are immutable'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        SELECT m.status INTO parent_status
          FROM inventory_movement m JOIN inventory_movementline l ON l.movement_id=m.id
         WHERE l.id=NEW.line_id FOR UPDATE OF m;
        IF parent_status = 'confirmed' THEN
            RAISE EXCEPTION 'Cannot add or rewrite confirmed source contributions'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER inventory_confirmed_source_guard
BEFORE INSERT OR UPDATE OR DELETE ON inventory_movementlinesource
FOR EACH ROW EXECUTE FUNCTION inventory_guard_confirmed_source();
"""


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(SQL)


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("DROP TRIGGER IF EXISTS inventory_confirmed_source_guard ON inventory_movementlinesource; DROP FUNCTION IF EXISTS inventory_guard_confirmed_source();")


class Migration(migrations.Migration):
    dependencies = [("inventory", "0004_reconciled_import")]
    operations = [migrations.RunPython(forwards, backwards)]
