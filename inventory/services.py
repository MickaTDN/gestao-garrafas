"""Authoritative stock transaction; drafts and reviews live in operations.py."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from .models import (
    AuditEvent,
    Location,
    LocationChange,
    Movement,
    Person,
    Reference,
    Sector,
    normalize_person_name,
)


def require_administrator(actor):
    if not actor or not actor.is_authenticated or not actor.is_active or actor.role != "admin":
        raise PermissionDenied("Este perfil é apenas de consulta.")


def resolve_person(name):
    display = " ".join(name.split())
    if not display or len(display) > 200 or len(normalize_person_name(display)) > 200:
        raise ValidationError("Indique o nome da pessoa (até 200 caracteres).")
    return Person.objects.get_or_create(
        normalized_name=normalize_person_name(display), defaults={"name": display}
    )[0]


def reference_state(reference):
    # Version detects stock changed and restored to the same number (ABA).
    return {
        "stock": reference.current_stock,
        "version": reference.stock_version,
        "capacity": reference.box_capacity,
        "location": reference.location_id,
        "sector": reference.sector_id,
        "active": reference.active,
        "name": reference.name,
    }


def bottle_total(boxes, units, capacity):
    for value in (boxes, units):
        if value is not None and (type(value) is not int or value < 0 or value > 2147483647):
            raise ValidationError("Introduza quantidades inteiras não negativas.")
    if boxes is None and units is None:
        return None
    if boxes and capacity is None:
        raise ValidationError(
            "Capacidade da caixa por definir: introduza apenas garrafas individuais."
        )
    total = (boxes or 0) * (capacity or 0) + (units or 0)
    if total > 2147483647:
        raise ValidationError("Quantidade acima do limite permitido.")
    return total


def owned_draft(movement, actor):
    require_administrator(actor)
    if movement.created_by_id and movement.created_by_id != actor.pk:
        raise PermissionDenied("Só pode alterar os seus próprios rascunhos.")
    if movement.status != Movement.Status.DRAFT:
        raise ValidationError("A operação já foi confirmada ou cancelada.")
    if movement.kind not in ("entry", "exit", "inventory"):
        raise ValidationError("O histórico deve ser carregado pela importação reconciliada.")


def locked_lines(movement):
    lines = list(movement.lines.select_for_update().order_by("reference_id"))
    references = {
        ref.pk: ref
        for ref in Reference.objects.select_for_update()
        .filter(pk__in=[line.reference_id for line in lines])
        .order_by("pk")
    }
    return lines, references


def movement_plans(movement, lines, references):
    """Validate everything before writing. Caller holds locks, including catalogue lock."""
    if not lines:
        raise ValidationError("Adicione pelo menos uma referência.")
    if movement.kind in ("entry", "exit") and not movement.person_id:
        raise ValidationError("Indique a pessoa responsável.")
    if movement.validation == Movement.Validation.SIGNED:
        raise ValidationError("A assinatura desenhada só estará disponível na Etapa 4.")
    if movement.kind == "exit" and movement.validation != Movement.Validation.SIMPLE:
        raise ValidationError("Confirme a conferência da saída antes de validar.")
    if movement.correction_of_id:
        if (
            movement.kind != "inventory"
            or not movement.reason.strip()
            or movement.correction_of.status != "confirmed"
        ):
            raise ValidationError(
                "Uma correção exige um movimento confirmado e um motivo obrigatório."
            )
        allowed = set(movement.correction_of.lines.values_list("reference_id", flat=True))
        if any(line.reference_id not in allowed for line in lines):
            raise ValidationError("A correção só pode abranger referências do movimento original.")
    plans = []
    conflicts = []
    for line in lines:
        ref = references[line.reference_id]
        if not ref.active:
            raise ValidationError(f"{ref.code}: não é possível movimentar uma referência inativa.")
        total = bottle_total(line.boxes, line.units, ref.box_capacity)
        if movement.workflow_version and line.box_capacity != ref.box_capacity:
            raise ValidationError(
                f"{ref.code}: a capacidade mudou. Edite e confira novamente as quantidades."
            )
        if movement.kind == "inventory":
            if total is None or line.counted_quantity is None:
                raise ValidationError(
                    f"{ref.code}: ainda não contado. Um campo vazio nunca significa zero."
                )
            if total != line.counted_quantity:
                raise ValidationError("As caixas e garrafas não correspondem à contagem física.")
            if line.count_basis != reference_state(ref):
                conflicts.append(
                    f"{ref.code}: stock na contagem {line.count_basis.get('stock', '—')}, stock atual {ref.current_stock}. Stock ou configuração alterados; volte a conferir explicitamente."
                )
            quantity = total - ref.current_stock
            if quantity and not (line.reason.strip() or movement.reason.strip()):
                raise ValidationError(f"{ref.code}: indique o motivo da diferença de inventário.")
        else:
            if movement.workflow_version:
                if total is None or total == 0:
                    raise ValidationError(f"{ref.code}: introduza uma quantidade superior a zero.")
                quantity = total if movement.kind == "entry" else -total
                if line.quantity != quantity:
                    raise ValidationError("As caixas e garrafas não correspondem à quantidade.")
            else:
                quantity = line.quantity
                if (
                    quantity is None
                    or (movement.kind == "entry" and quantity <= 0)
                    or (movement.kind == "exit" and quantity >= 0)
                ):
                    raise ValidationError("Quantidade ou sinal do movimento inválido.")
                if total is not None and total != abs(quantity):
                    raise ValidationError(
                        "As caixas e garrafas não correspondem ao total de garrafas."
                    )
        after = ref.current_stock + quantity
        if after < 0 or after > 2147483647:
            raise ValidationError(f"{ref.code}: stock insuficiente ou acima do limite permitido.")
        location, sector = ref.location, ref.sector
        if movement.kind == "inventory":
            if not line.target_location_id:
                raise ValidationError("Escolha a localização principal.")
            location = Location.objects.get(pk=line.target_location_id)
            sector = Sector.objects.get(pk=line.target_sector_id) if line.target_sector_id else None
            if sector and sector.location_id != location.pk:
                raise ValidationError("O setor não pertence à localização escolhida.")
            if (location.pk != ref.location_id and not location.active) or (
                sector and sector.pk != ref.sector_id and not sector.active
            ):
                raise ValidationError("Escolha localizações e setores ativos.")
        plans.append(
            {
                "line": line,
                "reference": ref,
                "quantity": quantity,
                "before": ref.current_stock,
                "after": after,
                "location": location,
                "sector": sector,
            }
        )
    if conflicts:
        raise ValidationError(conflicts)
    return plans


@transaction.atomic
def confirm_movement(movement_id, *, actor, review_token=None, report_requested=None):
    """Lock parent and stock in stable order; confirm exactly once, all lines or none."""
    # Same order as catalogue/import: advisory lock -> movement -> lines -> refs.
    from .catalog import catalogue_lock

    require_administrator(actor)
    catalogue_lock()
    movement = Movement.objects.select_for_update().get(pk=movement_id)
    owned_draft(movement, actor)
    lines, references = locked_lines(movement)
    plans = movement_plans(movement, lines, references)
    if movement.workflow_version:
        if movement.kind == "entry":
            if type(report_requested) is not bool:
                raise ValidationError("Indique se pretende um futuro relatório desta entrada.")
            movement.report_requested = report_requested
        if not review_token or str(movement.review_token) != str(review_token):
            raise ValidationError("Reveja a operação antes de confirmar.")
        snapshot = {str(pk): reference_state(ref) for pk, ref in references.items()}
        if movement.review_snapshot != snapshot:
            raise ValidationError(
                "O stock ou a configuração mudou desde a conferência. Reveja novamente a operação."
            )
    for plan in plans:
        line, ref = plan["line"], plan["reference"]
        line.quantity, line.stock_before, line.stock_after = (
            plan["quantity"],
            plan["before"],
            plan["after"],
        )
        line.box_capacity, line.reference_name = ref.box_capacity, ref.name
        line.save()
        location, sector = plan["location"], plan["sector"]
        if (ref.location_id, ref.sector_id) != (location.pk, sector.pk if sector else None):
            change = LocationChange.objects.create(
                reference=ref,
                movement=movement,
                location_before_id=ref.location_id,
                sector_before_id=ref.sector_id,
                location_after=location,
                sector_after=sector,
                changed_by=actor,
                reason=line.reason or movement.reason or "Transferência no inventário.",
            )
            AuditEvent.objects.create(
                actor=actor,
                movement=movement,
                reference=ref,
                action="movement.location_changed",
                details={
                    "change_id": change.pk,
                    "before": [ref.location_id, ref.sector_id],
                    "after": [location.pk, sector.pk if sector else None],
                },
            )
        ref.current_stock = plan["after"]
        ref.stock_version += 1
        ref.location, ref.sector = location, sector
        ref.save(update_fields=["current_stock", "stock_version", "location", "sector"])
    movement.status = Movement.Status.CONFIRMED
    movement.occurred_at = timezone.now()
    movement.created_by = movement.created_by or actor
    movement.confirmed_by = actor
    movement.person_name = movement.person.name if movement.person_id else ""
    movement.report_requested = movement.report_requested or movement.kind == Movement.Kind.EXIT
    movement.save(
        update_fields=[
            "status",
            "occurred_at",
            "created_by",
            "confirmed_by",
            "person_name",
            "report_requested",
        ]
    )
    AuditEvent.objects.create(
        actor=actor,
        action="movement.confirmed",
        movement=movement,
        details={
            "kind": movement.kind,
            "line_count": len(lines),
            "correction_of": movement.correction_of_id,
        },
    )
    return movement
