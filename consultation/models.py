import uuid

from django.core.exceptions import ValidationError
from django.db import models

from inventory.models import AppendOnlyQuerySet


class ExportSource(models.Model):
    """Export identity/counter only; never an alternative stock ledger."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    source_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    sequence = models.PositiveBigIntegerField(default=0)
    last_exported_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(id=1), name="one_export_source")]


class AuthorizedDevice(models.Model):
    """Offline authorizations issued by IT, not application accounts or passwords."""

    device_id = models.UUIDField(primary_key=True)
    public_key_id = models.CharField(max_length=64)
    role = models.CharField(
        max_length=10, choices=[("owner", "Proprietário"), ("employee", "Empregado")]
    )
    revision = models.PositiveIntegerField(default=0)
    public_spki = models.TextField(blank=True)
    sheets_allowed = models.BooleanField(default=False)
    expires_at = models.DateTimeField(null=True)
    revoked_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(role__in=["owner", "employee"]), name="valid_stock_device_role"
            )
        ]


class SheetEvidence(models.Model):
    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("A evidência recebida é imutável.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("A evidência recebida não pode ser eliminada.")


class PendingSheet(SheetEvidence):
    """Inbound evidence, never a movement or an alternative stock ledger."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_id = models.UUIDField()
    sheet_id = models.UUIDField()
    device = models.ForeignKey(AuthorizedDevice, on_delete=models.PROTECT)
    revision = models.PositiveIntegerField()
    content_sha256 = models.CharField(max_length=64)
    payload = models.JSONField()
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source_id", "sheet_id"], name="unique_pending_sheet_source_uuid"
            )
        ]


class SheetReceipt(SheetEvidence):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sheet = models.ForeignKey(PendingSheet, on_delete=models.PROTECT, related_name="receipts")
    actor = models.ForeignKey("accounts.User", on_delete=models.PROTECT)
    original = models.BinaryField(editable=False)
    file_sha256 = models.CharField(max_length=64)
    authorization = models.JSONField(default=dict)
    outcome = models.CharField(
        max_length=20,
        choices=[("pending", "Pendente"), ("duplicate", "Repetida"), ("conflict", "Conflito")],
    )
    created_at = models.DateTimeField(auto_now_add=True)


class SheetAction(SheetEvidence):
    """Append-only working copies and decisions; never rewrites incoming evidence."""

    class Kind(models.TextChoices):
        CORRECTED = "corrected", "Corrigida"
        REVIEWED = "reviewed", "Conferida"
        REJECTED = "rejected", "Rejeitada"
        CONFIRMED = "confirmed", "Confirmada"

    sheet = models.ForeignKey(PendingSheet, on_delete=models.PROTECT, related_name="actions")
    sequence = models.PositiveIntegerField()
    kind = models.CharField(max_length=15, choices=Kind)
    actor = models.ForeignKey("accounts.User", on_delete=models.PROTECT)
    reason = models.TextField(blank=True)
    data = models.JSONField(default=dict)
    movement = models.OneToOneField("inventory.Movement", on_delete=models.PROTECT, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["sheet", "sequence"], name="unique_sheet_action_sequence"
            ),
            models.UniqueConstraint(
                fields=["sheet"],
                condition=models.Q(kind="confirmed"),
                name="one_sheet_confirmation",
            ),
            models.CheckConstraint(
                condition=models.Q(kind__in=["corrected", "reviewed", "rejected", "confirmed"]),
                name="valid_sheet_action_kind",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(kind="confirmed", movement__isnull=False)
                    | (~models.Q(kind="confirmed") & models.Q(movement__isnull=True))
                ),
                name="confirmed_sheet_requires_movement",
            ),
        ]
