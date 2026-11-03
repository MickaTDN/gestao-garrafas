"""Non-catalogue entry proposals; official identities are allocated only at confirmation."""

import uuid

from django.core.exceptions import ValidationError
from django.db import transaction

from accounts.permissions import require_access

from . import catalog
from .models import AuditEvent, Location, Movement, MovementLine, Sector

PREFIX = "proposal:"


def proposal_id(value):
    try:
        return (
            value.startswith(PREFIX)
            and str(uuid.UUID(value[len(PREFIX) :])) == value[len(PREFIX) :]
        )
    except (ValueError, TypeError, AttributeError):
        return False


def validate_line(line, *, approved=False):
    from .services import bottle_total

    p = line.get("proposal")
    if not proposal_id(line.get("reference_id")) or not isinstance(p, dict):
        raise ValidationError("Identidade da proposta inválida.")
    allowed = (
        {"name", "location_id", "sector_id", "minimum", "alert_enabled"} if approved else {"name"}
    )
    if (
        set(p) - allowed
        or "name" not in p
        or not isinstance(p["name"], str)
        or not 1 <= len(p["name"]) <= 250
    ):
        raise ValidationError("Designação da proposta inválida.")
    name = catalog._name(p["name"])
    try:
        name.encode("utf-8")
        if "\x00" in name:
            raise ValueError
    except (ValueError, UnicodeError) as error:
        raise ValidationError("Designação inválida.") from error
    capacity = line.get("box_capacity")
    if capacity is not None and (type(capacity) is not int or not 1 <= capacity <= 2147483647):
        raise ValidationError("Capacidade inválida.")
    total = bottle_total(line.get("boxes"), line.get("units"), capacity)
    if total is None or total <= 0:
        raise ValidationError("Indique uma quantidade positiva para a proposta.")
    if not approved:
        return {"name": name}, total
    matches = catalog.matching_references(name)
    if matches:
        raise catalog.DuplicateReferenceError(matches)
    if type(p.get("location_id")) is not int or not 1 <= p["location_id"] <= 9223372036854775807:
        raise ValidationError("Escolha uma localização para aprovar a proposta.")
    if p.get("sector_id") is not None and (
        type(p["sector_id"]) is not int or not 1 <= p["sector_id"] <= 9223372036854775807
    ):
        raise ValidationError("Setor inválido.")
    try:
        location = Location.objects.select_for_update().get(pk=p.get("location_id"), active=True)
        sector = (
            Sector.objects.select_for_update().get(pk=p["sector_id"], active=True)
            if p.get("sector_id")
            else None
        )
    except (Location.DoesNotExist, Sector.DoesNotExist, ValueError, TypeError) as error:
        raise ValidationError("Escolha uma localização ativa para aprovar a proposta.") from error
    if sector and sector.location_id != location.pk:
        raise ValidationError("O setor não pertence à localização.")
    minimum = p.get("minimum") if p.get("alert_enabled") else None
    if p.get("alert_enabled") and (type(minimum) is not int or not 0 <= minimum <= 2147483647):
        raise ValidationError("Alerta de stock mínimo inválido.")
    return {
        "name": name,
        "box_capacity": capacity,
        "boxes": line.get("boxes"),
        "units": line.get("units"),
        "total": total,
        "location_id": location.pk,
        "sector_id": sector.pk if sector else None,
        "location_name": location.name,
        "sector_name": sector.name if sector else None,
        "minimum": minimum,
        "alert_enabled": bool(p.get("alert_enabled")),
        "stock": 0,
    }, total


def create_approved(line, *, actor):
    require_access(actor, "admin")
    data, _ = validate_line(line, approved=True)
    return catalog.save_reference(
        actor=actor,
        data={
            "name": data["name"],
            "box_capacity": data["box_capacity"],
            "location": Location.objects.get(pk=data["location_id"]),
            "sector": Sector.objects.get(pk=data["sector_id"]) if data["sector_id"] else None,
            "alert_enabled": data["alert_enabled"],
            "minimum": data["minimum"],
        },
    )


def pending(movement):
    return (
        []
        if movement.source_metadata.get("proposal_reference_ids")
        else movement.source_metadata.get("reference_proposals", [])
    )


def snapshot(movement, *, actor):
    lines = pending(movement)
    if not lines:
        return None
    require_access(actor, "admin")
    require_access(actor, "catalog_manage")
    if (
        movement.kind != "entry"
        or movement.correction_of_id
        or not isinstance(lines, list)
        or len(lines) > 500
    ):
        raise ValidationError("Só entradas normais permitem propostas de referências.")
    result, seen = [], set()
    for line in lines:
        clean, _ = validate_line(line, approved=True)
        key = clean["name"].casefold()
        if key in seen:
            raise ValidationError("Existem propostas duplicadas nesta entrada.")
        seen.add(key)
        result.append({"reference_id": line["reference_id"], **clean})
    return result


@transaction.atomic
def add_to_entry(movement_id, *, actor, revision, data):
    from .operations import _invalidate, _revision
    from .services import owned_draft

    require_access(actor, "admin")
    require_access(actor, "catalog_manage")
    catalog.catalogue_lock()
    movement = Movement.objects.select_for_update().get(pk=movement_id)
    owned_draft(movement, actor)
    _revision(movement, revision)
    if movement.kind != "entry" or movement.correction_of_id:
        raise ValidationError("Só entradas permitem novas referências.")
    identity = data.get("proposal_id") or PREFIX + str(uuid.uuid4())
    previous = pending(movement)
    if data.get("proposal_id") and not any(p["reference_id"] == identity for p in previous):
        raise ValidationError("Proposta fora desta entrada.")
    line = {
        "reference_id": identity,
        "proposal": {
            "name": data["name"],
            "location_id": data["location"].pk,
            "sector_id": data["sector"].pk if data.get("sector") else None,
            "alert_enabled": data.get("alert_enabled", False),
            "minimum": data.get("minimum"),
        },
        "box_capacity": data.get("box_capacity"),
        "boxes": data.get("boxes"),
        "units": data.get("units"),
    }
    movement.source_metadata = {
        **movement.source_metadata,
        "reference_proposals": [p for p in previous if p["reference_id"] != identity] + [line],
    }
    snapshot(movement, actor=actor)
    _invalidate(movement)
    AuditEvent.objects.create(
        actor=actor,
        movement=movement,
        action="movement.reference_proposed",
        details={"proposal": line},
    )
    return movement


@transaction.atomic
def remove_from_entry(movement_id, *, actor, revision, identity):
    from .operations import _invalidate, _revision
    from .services import owned_draft

    require_access(actor, "admin")
    catalog.catalogue_lock()
    movement = Movement.objects.select_for_update().get(pk=movement_id)
    owned_draft(movement, actor)
    _revision(movement, revision)
    if movement.kind != "entry" or not any(
        p["reference_id"] == identity for p in pending(movement)
    ):
        raise ValidationError("Proposta fora desta entrada.")
    movement.source_metadata = {
        **movement.source_metadata,
        "reference_proposals": [p for p in pending(movement) if p["reference_id"] != identity],
    }
    _invalidate(movement)
    AuditEvent.objects.create(
        actor=actor,
        movement=movement,
        action="movement.proposal_removed",
        details={"proposal_id": identity},
    )
    return movement


def materialize(movement, *, actor):
    mapping = {}
    for line in pending(movement):
        reference = create_approved(line, actor=actor)
        from .services import bottle_total

        MovementLine.objects.create(
            movement=movement,
            reference=reference,
            box_capacity=reference.box_capacity,
            boxes=line["boxes"],
            units=line["units"],
            quantity=bottle_total(line["boxes"], line["units"], reference.box_capacity),
            quantity_checked=True,
            reference_name=reference.name,
            target_location=reference.location,
            target_sector=reference.sector,
        )
        mapping[line["reference_id"]] = reference.pk
    if mapping:
        movement.source_metadata = {**movement.source_metadata, "proposal_reference_ids": mapping}
        movement.save(update_fields=["source_metadata"])
    return mapping
