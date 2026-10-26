import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [migrations.CreateModel(
        name="ExportSource",
        fields=[
            ("id", models.PositiveSmallIntegerField(default=1, editable=False, primary_key=True, serialize=False)),
            ("source_id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
            ("sequence", models.PositiveBigIntegerField(default=0)),
            ("last_exported_at", models.DateTimeField(null=True)),
        ],
        options={"constraints": [models.CheckConstraint(condition=models.Q(id=1), name="one_export_source")]},
    )]
