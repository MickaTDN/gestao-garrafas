from django.db import migrations
from django.db.migrations.exceptions import IrreversibleError


def install(apps, editor):
    if editor.connection.vendor != "postgresql":
        return
    editor.execute("""
    CREATE FUNCTION check_sheet_action() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE previous consultation_sheetaction%ROWTYPE;
            official inventory_movement%ROWTYPE;
            received consultation_pendingsheet%ROWTYPE;
    BEGIN
        SELECT * INTO received FROM consultation_pendingsheet WHERE id=NEW.sheet_id FOR UPDATE;
        SELECT * INTO previous FROM consultation_sheetaction
            WHERE sheet_id=NEW.sheet_id ORDER BY sequence DESC LIMIT 1;
        IF NEW.sequence <> COALESCE(previous.sequence, 0)+1
           OR previous.kind IN ('confirmed','rejected') THEN
            RAISE EXCEPTION 'Invalid or closed pending-sheet decision sequence';
        END IF;
        IF NEW.kind IN ('corrected','rejected') AND btrim(NEW.reason)='' THEN
            RAISE EXCEPTION 'A correction/rejection requires a reason';
        END IF;
        IF NEW.kind='confirmed' THEN
            SELECT * INTO official FROM inventory_movement WHERE id=NEW.movement_id;
            IF previous.kind IS DISTINCT FROM 'reviewed'
               OR official.status IS DISTINCT FROM 'confirmed'
               OR official.kind IS DISTINCT FROM (received.payload->>'kind')
               OR official.workflow_version IS DISTINCT FROM 1
               OR (official.source_metadata->>'pending_sheet_id') IS DISTINCT FROM NEW.sheet_id::text
               OR (NEW.data->>'token') IS DISTINCT FROM (previous.data->>'token')
               OR (NEW.data->>'review_id') IS DISTINCT FROM previous.id::text THEN
                RAISE EXCEPTION 'Pending sheet requires its own reviewed and confirmed official movement';
            END IF;
        END IF;
        RETURN NEW;
    END $$;
    CREATE TRIGGER check_sheet_action BEFORE INSERT ON consultation_sheetaction
        FOR EACH ROW EXECUTE FUNCTION check_sheet_action();
    CREATE TRIGGER protect_sheet_action BEFORE UPDATE OR DELETE ON consultation_sheetaction
        FOR EACH ROW EXECUTE FUNCTION protect_sheet_evidence();
    """)


def reverse(apps, editor):
    if apps.get_model("consultation", "SheetAction").objects.exists():
        raise IrreversibleError("Não reverta decisões de folhas recebidas; preserve o histórico e os movimentos oficiais.")
    if editor.connection.vendor == "postgresql":
        editor.execute("DROP TRIGGER protect_sheet_action ON consultation_sheetaction; DROP TRIGGER check_sheet_action ON consultation_sheetaction; DROP FUNCTION check_sheet_action();")


class Migration(migrations.Migration):
    dependencies = [("consultation", "0005_sheetaction")]
    operations = [migrations.RunPython(install, reverse)]
