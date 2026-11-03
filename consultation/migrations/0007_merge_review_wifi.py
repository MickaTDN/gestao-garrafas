"""Join the published sibling migrations without rewriting either history."""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("consultation", "0005_wifi_receipt_actor"),
        ("consultation", "0006_sheet_action_guards"),
    ]
    operations = []
