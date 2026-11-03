"""Forward compatibility marker for v2 evidence and deferred entry metadata."""

from django.db import migrations
from django.db.migrations.exceptions import IrreversibleError
from django.db.models import Q


def protect_reverse(apps, editor):
    movement = apps.get_model("inventory", "Movement")
    if movement.objects.filter(Q(source_metadata__has_key="reference_proposals") | Q(source_metadata__has_key="proposal_reference_ids")).exists():
        raise IrreversibleError("Preserve as propostas e a sua identidade; não execute código anterior ao protocolo v2.")
    for model, field in [("PendingSheet", "payload"), ("SheetAction", "data")]:
        for value in apps.get_model("consultation", model).objects.values_list(field, flat=True).iterator():
            payload = value.get("payload", value)
            if any("proposal" in line for line in payload.get("lines", [])):
                raise IrreversibleError("Preserve a evidência e a auditoria das propostas; não reverta o protocolo v2.")


class Migration(migrations.Migration):
    dependencies = [("consultation", "0007_merge_review_wifi")]
    operations = [migrations.RunPython(migrations.RunPython.noop, protect_reverse)]
