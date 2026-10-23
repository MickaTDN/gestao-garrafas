"""Persistent domain model. Stock changes belong to services, never to a browser session."""

import uuid

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
    stock_version = models.PositiveBigIntegerField(default=0, editable=False)
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
    quantity = models.IntegerField(null=True, blank=True)
    reconciliation_quantity = models.IntegerField(null=True, blank=True)
    basis = models.CharField(max_length=30, choices=[("counted", "Contagem na fonte"), ("derived_unknown", "Saldo inferido; contagem desconhecida")], default="counted")
    explanation = models.TextField(blank=True)
    date = models.DateField()
    legacy_row = models.OneToOneField(LegacyRow, on_delete=models.PROTECT, null=True, blank=True, related_name="opening_balance")


class HistoryQuerySet(models.QuerySet):
    """Block ordinary ORM mutation of confirmed records (SQL access is privileged)."""

    def _check_mutable(self):
        if self.model.__name__ == "Movement":
            condition = {"status": "confirmed"}
        elif self.model.__name__ == "MovementLineSource":
            condition = {"line__movement__status": "confirmed"}
        else:
            condition = {"movement__status": "confirmed"}
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
        if self.model.__name__ in ("MovementLine", "LocationChange"):
            movement_ids = {obj.movement_id for obj in objs}
            if Movement.objects.filter(pk__in=movement_ids, status="confirmed").exists():
                raise ValidationError("As linhas de um movimento confirmado são imutáveis.")
        if self.model.__name__ == "MovementLineSource":
            if MovementLine.objects.filter(pk__in=[obj.line_id for obj in objs], movement__status="confirmed").exists():
                raise ValidationError("A proveniência de um movimento confirmado é imutável.")
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
        CANCELLED = "cancelled", "Cancelado"

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
    document_number = models.CharField(max_length=250, blank=True)
    source_metadata = models.JSONField(default=dict, blank=True)
    import_batch = models.ForeignKey(ImportBatch, on_delete=models.PROTECT, null=True, blank=True, related_name="movements")
    source_column = models.PositiveIntegerField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="movements")
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    report_requested = models.BooleanField(default=False)
    validation = models.CharField(max_length=15, choices=Validation, blank=True)
    reason = models.TextField(blank=True)
    correction_of = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="corrections")

    workflow_version = models.PositiveSmallIntegerField(default=0, editable=False)
    draft_person_name = models.CharField(max_length=200, blank=True)
    person_name = models.CharField(max_length=200, blank=True)
    inventory_scope = models.CharField(max_length=10, choices=[("partial", "Parcial"), ("full", "Completo")], default="partial")
    revision = models.PositiveIntegerField(default=0, editable=False)
    review_token = models.UUIDField(null=True, blank=True, editable=False)
    review_snapshot = models.JSONField(default=dict, blank=True, editable=False)
    confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="confirmed_movements")

    objects = HistoryQuerySet.as_manager()

    class Meta:
        ordering = ["-date", "-pk"]
        indexes = [models.Index(fields=["date", "kind"]), models.Index(fields=["status"])]
        constraints = [
            models.UniqueConstraint(fields=["import_batch", "source_column"], condition=Q(kind="legacy"), name="one_legacy_movement_per_source_column"),
            models.CheckConstraint(condition=Q(kind__in=["entry", "exit", "inventory", "legacy"]), name="movement_valid_kind"),
            models.CheckConstraint(condition=Q(status__in=["draft", "confirmed", "cancelled"]), name="movement_valid_status"),
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
    quantity = models.IntegerField(null=True, blank=True, help_text="Impacto assinado em garrafas; preservar o sinal no histórico.")
    reference_name = models.CharField(max_length=250, blank=True)
    stock_before = models.IntegerField(null=True, blank=True)
    stock_after = models.IntegerField(null=True, blank=True)
    box_capacity = models.PositiveIntegerField(null=True, blank=True)
    boxes = models.PositiveIntegerField(null=True, blank=True)
    units = models.PositiveIntegerField(null=True, blank=True)
    counted_quantity = models.PositiveIntegerField(null=True, blank=True)
    count_basis = models.JSONField(default=dict, blank=True)
    reason = models.TextField(blank=True)
    target_location = models.ForeignKey(Location, on_delete=models.PROTECT, null=True, blank=True, related_name="planned_lines")
    target_sector = models.ForeignKey(Sector, on_delete=models.PROTECT, null=True, blank=True, related_name="planned_lines")
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


class MovementLineSource(models.Model):
    """Every original contribution remains linked after duplicate references merge."""

    line = models.ForeignKey(MovementLine, on_delete=models.PROTECT, related_name="sources")
    legacy_row = models.ForeignKey(LegacyRow, on_delete=models.PROTECT, related_name="line_sources")
    coordinate = models.CharField(max_length=30)
    quantity = models.IntegerField(null=True, blank=True)
    raw_value = models.JSONField(null=True, blank=True)

    objects = HistoryQuerySet.as_manager()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["legacy_row", "coordinate"], name="unique_import_source_cell")]

    def _check_mutable(self):
        line_ids = {self.line_id}
        if self.pk:
            line_ids.update(MovementLineSource.objects.filter(pk=self.pk).values_list("line_id", flat=True))
        if MovementLine.objects.filter(pk__in=line_ids, movement__status="confirmed").exists():
            raise ValidationError("A proveniência de um movimento confirmado é imutável.")

    def save(self, *args, **kwargs):
        self._check_mutable()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self._check_mutable()
        return super().delete(*args, **kwargs)


class ImportPreview(models.Model):
    """Private, immutable reconciliation snapshot; publication requires its token."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    import_batch = models.ForeignKey(ImportBatch, on_delete=models.PROTECT, related_name="previews")
    decisions = models.JSONField(default=dict)
    summary = models.JSONField(default=dict)
    rows = models.JSONField(default=list)
    source_digest = models.CharField(max_length=64)
    target_digest = models.CharField(max_length=64)
    reconciliation_digest = models.CharField(max_length=64)
    confirmation_token = models.UUIDField(default=uuid.uuid4, editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    published_at = models.DateTimeField(null=True, blank=True)
    validation_report = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]


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

    before_snapshot = models.JSONField(default=dict, blank=True)
    after_snapshot = models.JSONField(default=dict, blank=True)

    objects = HistoryQuerySet.as_manager()

    def _check_mutable(self):
        ids = {self.movement_id}
        if self.pk:
            ids.update(LocationChange.objects.filter(pk=self.pk).values_list("movement_id", flat=True))
        if Movement.objects.filter(pk__in=ids, status="confirmed").exists():
            raise ValidationError("As transferências de movimentos confirmados são imutáveis.")

    def delete(self, *args, **kwargs):
        self._check_mutable()
        return super().delete(*args, **kwargs)

    def clean(self):
        for suffix in ("before", "after"):
            sector = getattr(self, f"sector_{suffix}")
            if sector and sector.location_id != getattr(self, f"location_{suffix}_id"):
                raise ValidationError({f"sector_{suffix}": "O setor não pertence à localização."})

    def save(self, *args, **kwargs):
        self._check_mutable()
        self.clean()
        if not self.pk:
            for suffix, field in (("before", "before_snapshot"), ("after", "after_snapshot")):
                location, sector = getattr(self, f"location_{suffix}"), getattr(self, f"sector_{suffix}")
                setattr(self, field, {"location": location.name, "sector": sector.name if sector else None})
        return super().save(*args, **kwargs)


class Document(models.Model):
    """Immutable private bytes committed atomically with the ledger in PostgreSQL."""

    movement = models.ForeignKey(Movement, on_delete=models.PROTECT, related_name="documents")
    kind = models.CharField(max_length=20, choices=[("pdf", "Relatório PDF"), ("signature", "Assinatura")])
    storage_key = models.CharField(max_length=500, unique=True)
    payload = models.BinaryField(null=True, editable=False)
    byte_size = models.PositiveIntegerField(default=0)
    content_type = models.CharField(max_length=100, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    objects = HistoryQuerySet.as_manager()

    def save(self, *args, **kwargs):
        if self.pk or Movement.objects.filter(pk=self.movement_id, status="confirmed").exists():
            raise ValidationError("Documentos históricos são imutáveis.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if Movement.objects.filter(pk=self.movement_id, status="confirmed").exists():
            raise ValidationError("Documentos históricos são imutáveis.")
        return super().delete(*args, **kwargs)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["movement", "kind"], condition=Q(payload__isnull=False), name="one_stored_document_per_kind")]

    sha256 = models.CharField(max_length=64)
    created_at = models.DateTimeField(default=timezone.now, editable=False)


class AppendOnlyQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("A auditoria é apenas de acréscimo.")

    def delete(self):
        raise ValidationError("A auditoria é apenas de acréscimo.")

    def bulk_update(self, *args, **kwargs):
        raise ValidationError("A auditoria é apenas de acréscimo.")


class AuditEvent(models.Model):
    objects = AppendOnlyQuerySet.as_manager()

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("A auditoria é apenas de acréscimo.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("A auditoria é apenas de acréscimo.")

    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)
    action = models.CharField(max_length=100)
    movement = models.ForeignKey(Movement, on_delete=models.PROTECT, null=True, blank=True, related_name="audit_events")
    reference = models.ForeignKey(Reference, on_delete=models.PROTECT, null=True, blank=True, related_name="audit_events")
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
