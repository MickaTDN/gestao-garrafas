"""Transactional entry point for future HTTP/CLI stock operations."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from .models import AuditEvent, Movement, Person, Reference, normalize_person_name


def require_administrator(actor):
    if not actor or not actor.is_authenticated or not actor.is_active or actor.role != "admin":
        raise PermissionDenied("Este perfil é apenas de consulta.")


def resolve_person(name):
    display = " ".join(name.split())
    if not display:
        raise ValidationError("Indique o nome da pessoa.")
    return Person.objects.get_or_create(normalized_name=normalize_person_name(display), defaults={"name": display})[0]


@transaction.atomic
def confirm_movement(movement_id, *, actor):
    """Confirm once, lock stock in a stable order and commit all lines or none.

    Each line quantity is signed: entry > 0, exit < 0, inventory +/-/0.
    Legacy data is imported by a separate reconciled process, never this command.
    PostgreSQL is required for concurrent production writers; SQLite is for local
    smoke tests only, because its select_for_update does not lock rows.
    """
    require_administrator(actor)
    movement = Movement.objects.select_for_update().get(pk=movement_id)
    if movement.status != Movement.Status.DRAFT:
        raise ValidationError("O movimento já foi confirmado.")
    if movement.kind == Movement.Kind.LEGACY:
        raise ValidationError("O histórico deve ser carregado pela importação reconciliada.")
    if movement.kind in (Movement.Kind.ENTRY, Movement.Kind.EXIT) and not movement.person_id:
        raise ValidationError("Indique a pessoa responsável.")
    if movement.kind == Movement.Kind.EXIT and movement.validation not in (Movement.Validation.SIMPLE, Movement.Validation.SIGNED):
        raise ValidationError("Confirme a conferência da saída antes de validar.")
    if movement.validation == Movement.Validation.SIGNED and not movement.documents.filter(kind="signature").exists():
        raise ValidationError("A assinatura deve ser guardada antes da confirmação.")

    lines = list(movement.lines.select_for_update().order_by("reference_id"))
    if not lines:
        raise ValidationError("Adicione pelo menos uma referência.")
    references = {
        ref.pk: ref
        for ref in Reference.objects.select_for_update().filter(pk__in=[line.reference_id for line in lines]).order_by("pk")
    }
    for line in lines:
        reference = references[line.reference_id]
        if not reference.active:
            raise ValidationError("Não é possível movimentar uma referência inativa.")
        if movement.kind == Movement.Kind.ENTRY and line.quantity <= 0:
            raise ValidationError("Uma entrada deve ter quantidade positiva.")
        if movement.kind == Movement.Kind.EXIT and line.quantity >= 0:
            raise ValidationError("Uma saída deve ter quantidade negativa.")
        if movement.kind == Movement.Kind.INVENTORY and line.quantity and not movement.reason.strip():
            raise ValidationError("Indique o motivo da diferença de inventário.")
        if line.boxes is not None or line.units is not None:
            boxes, units = line.boxes or 0, line.units or 0
            if boxes < 0 or units < 0 or (boxes and reference.box_capacity is None):
                raise ValidationError("Quantidades de caixas e unidades inválidas.")
            if boxes * (reference.box_capacity or 0) + units != abs(line.quantity):
                raise ValidationError("As caixas e unidades não correspondem ao total de garrafas.")
        after = reference.current_stock + line.quantity
        if after < 0:
            raise ValidationError("Stock insuficiente para essa saída ou ajuste.")
        line.stock_before = reference.current_stock
        line.stock_after = after
        line.box_capacity = reference.box_capacity
        line.reference_name = reference.name
        line.save(update_fields=["stock_before", "stock_after", "box_capacity", "reference_name"])
        reference.current_stock = after
        reference.save(update_fields=["current_stock"])

    movement.status = Movement.Status.CONFIRMED
    movement.occurred_at = timezone.now()
    movement.created_by = movement.created_by or actor
    movement.report_requested = movement.report_requested or movement.kind == Movement.Kind.EXIT
    movement.save(update_fields=["status", "occurred_at", "created_by", "report_requested"])
    AuditEvent.objects.create(actor=actor, action="movement.confirmed", movement=movement, details={"kind": movement.kind, "line_count": len(lines)})
    return movement
