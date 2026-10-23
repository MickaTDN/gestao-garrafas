from django.db import migrations


LOCATIONS = (
    ("Corredor Esquerdo", 8),
    ("Patamar Superior Esquerdo", 5),
    ("Corredor Direito", 7),
    ("Patamar Superior Direito", 7),
)


def seed_locations(apps, schema_editor):
    Location = apps.get_model("inventory", "Location")
    Sector = apps.get_model("inventory", "Sector")
    for name, count in LOCATIONS:
        location, _ = Location.objects.get_or_create(name=name)
        for number in range(1, count + 1):
            Sector.objects.get_or_create(location=location, name=f"Setor {number}")


class Migration(migrations.Migration):
    dependencies = [("inventory", "0001_initial")]
    # Unapplying does not delete user configuration that may now be in use.
    operations = [migrations.RunPython(seed_locations, migrations.RunPython.noop)]
