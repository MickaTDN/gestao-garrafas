import uuid

from django.db import models


class ExportSource(models.Model):
    """Export identity/counter only; never an alternative stock ledger."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    source_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    sequence = models.PositiveBigIntegerField(default=0)
    last_exported_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(id=1), name="one_export_source")]
