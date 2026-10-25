from django.db import migrations


def install(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        """
    CREATE FUNCTION inventory_a2_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'A2 historical evidence is immutable' USING ERRCODE='23514'; END; $$;
    CREATE TRIGGER report_template_immutable BEFORE UPDATE OR DELETE ON inventory_reporttemplate
      FOR EACH ROW EXECUTE FUNCTION inventory_a2_immutable();
    CREATE TRIGGER report_number_immutable BEFORE UPDATE OR DELETE ON inventory_reportnumber
      FOR EACH ROW EXECUTE FUNCTION inventory_a2_immutable();
    CREATE FUNCTION inventory_a2_number_insert_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      PERFORM 1 FROM inventory_document d JOIN inventory_movement m ON m.id=d.movement_id
      JOIN inventory_reportsequence s ON s.year=NEW.year
      WHERE d.id=NEW.document_id AND m.id=NEW.movement_id
        AND d.kind='pdf' AND d.metadata->>'presentation'='3'
        AND EXTRACT(YEAR FROM m.date)::integer=NEW.year
        AND (d.metadata->>'report_year')::integer=NEW.year
        AND (d.metadata->>'report_sequence')::bigint=NEW.number
        AND s.last_number>=NEW.number;
      IF NOT FOUND THEN RAISE EXCEPTION 'Report number must match immutable evidence and official year' USING ERRCODE='23514'; END IF;
      RETURN NEW;
    END; $$;
    CREATE TRIGGER report_number_insert_guard BEFORE INSERT ON inventory_reportnumber
      FOR EACH ROW EXECUTE FUNCTION inventory_a2_number_insert_guard();
    CREATE FUNCTION inventory_a2_sequence_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'Report numbers cannot be reused' USING ERRCODE='23514'; END IF;
      IF NEW.year <> OLD.year OR NEW.last_number <> OLD.last_number + 1 THEN
        RAISE EXCEPTION 'Invalid report sequence transition' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END; $$;
    CREATE TRIGGER report_sequence_guard BEFORE UPDATE OR DELETE ON inventory_reportsequence
      FOR EACH ROW EXECUTE FUNCTION inventory_a2_sequence_guard();
    CREATE FUNCTION inventory_a2_file_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE evidence inventory_document%ROWTYPE;
    BEGIN
      IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'File identity cannot be deleted' USING ERRCODE='23514'; END IF;
      SELECT * INTO STRICT evidence FROM inventory_document WHERE id=NEW.document_id;
      IF evidence.kind <> 'pdf' OR evidence.payload IS NOT NULL OR evidence.metadata->>'presentation' IS DISTINCT FROM '3' THEN
        RAISE EXCEPTION 'Only reproducible A2 PDF files are mutable' USING ERRCODE='23514';
      END IF;
      IF NEW.payload IS NOT NULL AND (encode(sha256(NEW.payload),'hex') <> evidence.sha256 OR octet_length(NEW.payload) <> evidence.byte_size) THEN
        RAISE EXCEPTION 'Restored PDF must equal original evidence' USING ERRCODE='23514';
      END IF;
      IF TG_OP = 'UPDATE' AND (
          NEW.id <> OLD.id OR NEW.document_id <> OLD.document_id OR
          ((NEW.payload IS NULL) = (OLD.payload IS NULL)) OR
          NEW.reproductions <> OLD.reproductions + CASE WHEN NEW.payload IS NULL THEN 0 ELSE 1 END
      ) THEN RAISE EXCEPTION 'Invalid PDF file transition' USING ERRCODE='23514'; END IF;
      RETURN NEW;
    END; $$;
    CREATE TRIGGER report_file_guard BEFORE INSERT OR UPDATE OR DELETE ON inventory_reportfile
      FOR EACH ROW EXECUTE FUNCTION inventory_a2_file_guard();
    """,
        params=None,
    )


def remove(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("""
        DROP TRIGGER IF EXISTS report_file_guard ON inventory_reportfile;
        DROP TRIGGER IF EXISTS report_sequence_guard ON inventory_reportsequence;
        DROP TRIGGER IF EXISTS report_number_insert_guard ON inventory_reportnumber;
        DROP TRIGGER IF EXISTS report_number_immutable ON inventory_reportnumber;
        DROP TRIGGER IF EXISTS report_template_immutable ON inventory_reporttemplate;
        DROP FUNCTION IF EXISTS inventory_a2_number_insert_guard();
        DROP FUNCTION IF EXISTS inventory_a2_file_guard();
        DROP FUNCTION IF EXISTS inventory_a2_sequence_guard();
        DROP FUNCTION IF EXISTS inventory_a2_immutable();
        """)


class Migration(migrations.Migration):
    dependencies = [("inventory", "0011_reportsequence_reporttemplate_and_more")]
    operations = [migrations.RunPython(install, remove)]
