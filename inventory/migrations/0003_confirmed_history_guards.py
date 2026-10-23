"""PostgreSQL protects the ledger even if a caller bypasses the model layer."""

from django.db import migrations


FORWARD = """
CREATE FUNCTION inventory_guard_confirmed_movement() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status = 'confirmed' THEN
        RAISE EXCEPTION 'Confirmed movements are immutable; record a correction'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER inventory_confirmed_movement_guard
BEFORE UPDATE OR DELETE ON inventory_movement
FOR EACH ROW EXECUTE FUNCTION inventory_guard_confirmed_movement();

CREATE FUNCTION inventory_guard_confirmed_line() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE parent_status varchar;
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        SELECT status INTO parent_status FROM inventory_movement
            WHERE id = OLD.movement_id FOR UPDATE;
        IF parent_status = 'confirmed' THEN
            RAISE EXCEPTION 'Confirmed movement lines are immutable'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        SELECT status INTO parent_status FROM inventory_movement
            WHERE id = NEW.movement_id FOR UPDATE;
        IF parent_status = 'confirmed' THEN
            RAISE EXCEPTION 'Cannot add or change a confirmed movement line'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER inventory_confirmed_line_guard
BEFORE INSERT OR UPDATE OR DELETE ON inventory_movementline
FOR EACH ROW EXECUTE FUNCTION inventory_guard_confirmed_line();
"""

REVERSE = """
DROP TRIGGER IF EXISTS inventory_confirmed_line_guard ON inventory_movementline;
DROP FUNCTION IF EXISTS inventory_guard_confirmed_line();
DROP TRIGGER IF EXISTS inventory_confirmed_movement_guard ON inventory_movement;
DROP FUNCTION IF EXISTS inventory_guard_confirmed_movement();
"""


def install_guards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(FORWARD)


def remove_guards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(REVERSE)


class Migration(migrations.Migration):
    dependencies = [("inventory", "0002_seed_locations")]
    operations = [migrations.RunPython(install_guards, remove_guards)]
