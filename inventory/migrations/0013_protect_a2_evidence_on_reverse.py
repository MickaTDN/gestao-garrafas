from django.db import migrations
from django.db.migrations.exceptions import IrreversibleError


def protect(apps, schema_editor):
    for name in ("ReportNumber", "ReportFile", "ReportTemplate"):
        if apps.get_model("inventory", name).objects.exists():
            raise IrreversibleError(
                "A2 contem evidencias de relatorios. Nao eliminar o esquema: preserve a base e recupere uma copia do backup com codigo compativel."
            )
    if apps.get_model("inventory", "MovementLine").objects.filter(quantity_checked=True).exists():
        raise IrreversibleError(
            "Existem quantidades A2 conferidas. Use a copia preservada do piloto anterior; nao force a remocao de campos."
        )


class Migration(migrations.Migration):
    dependencies = [("inventory", "0012_a2_report_guards")]
    operations = [migrations.RunPython(migrations.RunPython.noop, protect)]
