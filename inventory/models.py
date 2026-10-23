"""Persistent domain model. Stock changes belong to services, never to a browser session."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Location(models.Model):
    name = models.CharField(max_length=150, unique=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["pk"]

    def __str__(self):
        return self.name


class Sector(models.Model):
    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="sectors")
    name = models.CharField(max_length=100)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["pk"]
        constraints = [models.UniqueConstraint(fields=["location", "name"], name="unique_sector_per_location")]

    def __str__(self):
        return f"{self.location} / {self.name}"


def normalize_person_name(name):
    return " ".join(name.split()).casefold()


class Person(models.Model):
    name = models.CharField(max_length=200)
    normalized_name = models.CharField(max_length=200, unique=True, editable=False)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def save(self, *args, **kwargs):
        self.name = " ".join(self.name.split())
        self.normalized_name = normalize_person_name(self.name)
        if not self.name:
            raise ValidationError({"name": "Indique o nome da pessoa."})
        if kwargs.get("update_fields") is not None:
            kwargs["update_fields"] = set(kwargs["update_fields"]) | {"name", "normalized_name"}
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Reference(models.Model):
    code = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=250)
    box_capacity = models.PositiveIntegerField(null=True, blank=True)
    current_stock = models.PositiveIntegerField(default=0)
    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="references")
    sector = models.ForeignKey(Sector, on_delete=models.PROTECT, null=True, blank=True, related_name="references")
    active = models.BooleanField(default=True)
    minimum = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["code"]
        indexes = [models.Index(fields=["location", "active"]), models.Index(fields=["name"])]
        constraints = [models.CheckConstraint(condition=Q(box_capacity__isnull=True) | Q(box_capacity__gt=0), name="reference_positive_capacity")]

    def clean(self):
        super().clean()
        if self.sector_id and self.location_id and self.sector.location_id != self.location_id:
            raise ValidationError({"sector": "O setor deve pertencer à localização da referência."})

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.code} · {self.name}"


class ImportBatch(models.Model):
    class Status(models.TextChoices):
        STAGED = "staged", "Em análise"
        RECONCILED = "reconciled", "Reconciliado"
        IMPORTED = "imported", "Importado"
        REJECTED = "rejected", "Rejeitado"

    source_name = models.CharField(max_length=250)
    sha256 = models.CharField(max_length=64, unique=True)
    status = models.CharField(max_length=20, choices=Status, default=Status.STAGED)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="import_batches")
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    summary = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]


class LegacyRow(models.Model):
    import_batch = models.ForeignKey(ImportBatch, on_delete=models.PROTECT, related_name="rows")
    sheet = models.CharField(max_length=100, default="Stock")
    row_number = models.PositiveIntegerField()
    reference = models.ForeignKey(Reference, on_delete=models.PROTECT, null=True, blank=True, related_name="legacy_rows")
    raw_data = models.JSONField(default=dict)
    opening_stock = models.IntegerField(null=True, blank=True)
    reported_stock = models.IntegerField(null=True, blank=True)
    reconciled_stock = models.IntegerField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["import_batch", "sheet", "row_number"], name="unique_import_source_row")]


class OpeningBalance(models.Model):
    reference = models.ForeignKey(Reference, on_delete=models.PROTECT, related_name="opening_balances")
    quantity = models.IntegerField()
    date = models.DateField()
    legacy_row = models.OneToOneField(LegacyRow, on_delete=models.PROTECT, null=True, blank=True, related_name="opening_balance")


class HistoryQuerySet(models.QuerySet):
    """Block ordinary ORM mutation of confirmed records (SQL access is privileged)."""

    def _check_mutable(self):
        condition = {"status": "confirmed"} if self.model.__name__ == "Movement" else {"movement__status": "confirmed"}
        if self.filter(**condition).exists():
            raise ValidationError("Movimentos confirmados são imutáveis; registe um ajuste relacionado.")

    def update(self, **kwargs):
        self._check_mutable()
        return super().update(**kwargs)

    def delete(self):
        self._check_mutable()
        return super().delete()

    def bulk_update(self, objs, fields, batch_size=None):
        objs = list(objs)
        self.filter(pk__in=[obj.pk for obj in objs])._check_mutable()
        return super().bulk_update(objs, fields, batch_size=batch_size)

    def bulk_create(self, objs, batch_size=None, ignore_conflicts=False, update_conflicts=False, update_fields=None, unique_fields=None):
        objs = list(objs)
        if update_conflicts:
            raise ValidationError("O histórico não permite upserts; use a importação auditada.")
        if self.model.__name__ == "MovementLine":
            movement_ids = {obj.movement_id for obj in objs}
            if Movement.objects.filter(pk__in=movement_ids, status="confirmed").exists():
                raise ValidationError("As linhas de um movimento confirmado são imutáveis.")
        return super().bulk_create(
            objs, batch_size=batch_size, ignore_conflicts=ignore_conflicts,
            update_conflicts=update_conflicts, update_fields=update_fields,
            unique_fields=unique_fields,
        )


class Movement(models.Model):
    class Kind(models.TextChoices):
        ENTRY = "entry", "Entrada"
        EXIT = "exit", "Saída"
        INVENTORY = "inventory", "Inventário"
        LEGACY = "legacy", "Histórico importado"

    class Status(models.TextChoices):
        DRAFT = "draft", "Rascunho"
        CONFIRMED = "confirmed", "Confirmado"

    class Validation(models.TextChoices):
        SIMPLE = "simple", "Confirmação simples"
        SIGNED = "signed", "Assinatura desenhada"
        IMPORT = "import", "Importação reconciliada"

    kind = models.CharField(max_length=15, choices=Kind)
    status = models.CharField(max_length=15, choices=Status, default=Status.DRAFT)
    date = models.DateField(default=timezone.localdate)
    occurred_at = models.DateTimeField(null=True, blank=True)
    person = models.ForeignKey(Person, on_delete=models.PROTECT, null=True, blank=True, related_name="movements")
    original_label = models.CharField(max_length=250, blank=True)
    import_batch = models.ForeignKey(ImportBatch, on_delete=models.PROTECT, null=True, blank=True, related_name="movements")
    source_column = models.PositiveIntegerField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="movements")
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    report_requested = models.BooleanField(default=False)
    validation = models.CharField(max_length=15, choices=Validation, blank=True)
    reason = models.TextField(blank=True)
    correction_of = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="corrections")

    objects = HistoryQuerySet.as_manager()

    class Meta:
        ordering = ["-date", "-pk"]
        indexes = [models.Index(fields=["date", "kind"]), models.Index(fields=["status"])]
        constraints = [
            models.CheckConstraint(condition=Q(kind__in=["entry", "exit", "inventory", "legacy"]), name="movement_valid_kind"),
            models.CheckConstraint(condition=Q(status__in=["draft", "confirmed"]), name="movement_valid_status"),
            models.CheckConstraint(condition=~Q(kind="legacy") | (Q(import_batch__isnull=False) & Q(occurred_at__isnull=True)), name="legacy_requires_source_no_time"),
        ]

    def _check_mutable(self):
        if self.pk and Movement.objects.filter(pk=self.pk, status=self.Status.CONFIRMED).exists():
            raise ValidationError("Movimentos confirmados são imutáveis; registe um ajuste relacionado.")

    def save(self, *args, **kwargs):
        self._check_mutable()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self._check_mutable()
        return super().delete(*args, **kwargs)

    def __str__(self):
        return f"MOV-{self.pk or '—'} · {self.get_kind_display()}"


class MovementLine(models.Model):
    movement = models.ForeignKey(Movement, on_delete=models.PROTECT, related_name="lines")
    reference = models.ForeignKey(Reference, on_delete=models.PROTECT, related_name="movement_lines")
    quantity = models.IntegerField(help_text="Impacto assinado em garrafas; preservar o sinal no histórico.")
    reference_name = models.CharField(max_length=250, blank=True)
    stock_before = models.IntegerField(null=True, blank=True)
    stock_after = models.IntegerField(null=True, blank=True)
    box_capacity = models.PositiveIntegerField(null=True, blank=True)
    boxes = models.PositiveIntegerField(null=True, blank=True)
    units = models.PositiveIntegerField(null=True, blank=True)
    legacy_row = models.ForeignKey(LegacyRow, on_delete=models.PROTECT, null=True, blank=True, related_name="movement_lines")

    objects = HistoryQuerySet.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["movement", "reference"], name="one_reference_per_movement"),
            models.CheckConstraint(condition=Q(box_capacity__isnull=True) | Q(box_capacity__gt=0), name="line_positive_capacity"),
        ]

    def _check_mutable(self):
        movement_ids = {self.movement_id}
        if self.pk:
            movement_ids.update(MovementLine.objects.filter(pk=self.pk).values_list("movement_id", flat=True))
        if Movement.objects.filter(pk__in=movement_ids, status=Movement.Status.CONFIRMED).exists():
            raise ValidationError("As linhas de um movimento confirmado são imutáveis.")

    def save(self, *args, **kwargs):
        self._check_mutable()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self._check_mutable()
        return super().delete(*args, **kwargs)


class LocationChange(models.Model):
    reference = models.ForeignKey(Reference, on_delete=models.PROTECT, related_name="location_changes")
    movement = models.ForeignKey(Movement, on_delete=models.PROTECT, null=True, blank=True, related_name="location_changes")
    location_before = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="changes_from")
    location_after = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="changes_to")
    sector_before = models.ForeignKey(Sector, on_delete=models.PROTECT, null=True, blank=True, related_name="changes_from")
    sector_after = models.ForeignKey(Sector, on_delete=models.PROTECT, null=True, blank=True, related_name="changes_to")
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    changed_at = models.DateTimeField(default=timezone.now, editable=False)
    reason = models.TextField(blank=True)

    def clean(self):
        for suffix in ("before", "after"):
            sector = getattr(self, f"sector_{suffix}")
            if sector and sector.location_id != getattr(self, f"location_{suffix}_id"):
                raise ValidationError({f"sector_{suffix}": "O setor não pertence à localização."})

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)


class Document(models.Model):
    """Private object key only. File upload and signed download are a later stage."""

    movement = models.ForeignKey(Movement, on_delete=models.PROTECT, related_name="documents")
    kind = models.CharField(max_length=20, choices=[("pdf", "Relatório PDF"), ("signature", "Assinatura")])
    storage_key = models.CharField(max_length=500, unique=True)
    sha256 = models.CharField(max_length=64)
    created_at = models.DateTimeField(default=timezone.now, editable=False)


class AuditEvent(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)
    action = models.CharField(max_length=100)
    movement = models.ForeignKey(Movement, on_delete=models.PROTECT, null=True, blank=True, related_name="audit_events")
    reference = models.ForeignKey(Reference, on_delete=models.PROTECT, null=True, blank=True, related_name="audit_events")
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
