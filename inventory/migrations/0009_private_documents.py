from django.db import migrations, models


def install(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute('''CREATE TRIGGER inventory_confirmed_document_guard
        BEFORE INSERT OR UPDATE OR DELETE ON inventory_document
        FOR EACH ROW EXECUTE FUNCTION inventory_guard_confirmed_line();''')


def remove(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute('DROP TRIGGER IF EXISTS inventory_confirmed_document_guard ON inventory_document;')


class Migration(migrations.Migration):
    dependencies = [('inventory', '0008_historical_labels')]
    operations = [
        migrations.AddField(model_name='document', name='payload', field=models.BinaryField(editable=False, null=True)),
        migrations.AddField(model_name='document', name='byte_size', field=models.PositiveIntegerField(default=0)),
        migrations.AddField(model_name='document', name='content_type', field=models.CharField(blank=True,max_length=100)),
        migrations.AddField(model_name='document', name='metadata', field=models.JSONField(blank=True,default=dict)),
        migrations.RunPython(install, remove),
    ]
