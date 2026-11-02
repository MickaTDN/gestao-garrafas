from django.db import migrations
from django.db.migrations.exceptions import IrreversibleError


def install(apps, editor):
    if editor.connection.vendor != 'postgresql':
        return
    editor.execute("""CREATE FUNCTION protect_sheet_evidence() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'Received sheet evidence is immutable'; END $$;
    CREATE TRIGGER protect_pending_sheet BEFORE UPDATE OR DELETE ON consultation_pendingsheet FOR EACH ROW EXECUTE FUNCTION protect_sheet_evidence();
    CREATE TRIGGER protect_sheet_receipt BEFORE UPDATE OR DELETE ON consultation_sheetreceipt FOR EACH ROW EXECUTE FUNCTION protect_sheet_evidence();""")


def reverse(apps, editor):
    if apps.get_model('consultation','PendingSheet').objects.exists() or apps.get_model('consultation','SheetReceipt').objects.exists() or apps.get_model('consultation','AuthorizedDevice').objects.exclude(public_spki='').exists():
        raise IrreversibleError('Preserve folhas, autorizações e chaves. Não reverta este esquema com evidências existentes.')
    if editor.connection.vendor == 'postgresql':
        editor.execute('DROP TRIGGER protect_pending_sheet ON consultation_pendingsheet; DROP TRIGGER protect_sheet_receipt ON consultation_sheetreceipt; DROP FUNCTION protect_sheet_evidence();')


class Migration(migrations.Migration):
    dependencies = [('consultation','0003_authorizeddevice_expires_at_and_more')]
    operations = [migrations.RunPython(install,reverse)]
