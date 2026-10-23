"""Administrative catalogue changes. These operations never adjust bottle balances."""

import re

from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.db.models import Q
from django.db.models.deletion import ProtectedError

from .models import AuditEvent, Location, LocationChange, Reference, Sector
from .services import require_administrator


def catalogue_lock():
    """Coordinate catalogue creation and publication of the first import on PostgreSQL."""
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [73194621])


def _name(value):
    value = " ".join(value.split())
    if not value:
        raise ValidationError({"name": "Introduza uma designação."})
    return value


def matching_references(name):
    """Match globally without rewriting historical names or folding accents."""
    key = " ".join(name.split()).casefold()
    if not key:
        return []
    return [
        reference
        for reference in Reference.objects.select_related("location").order_by("code")
        if " ".join(reference.name.split()).casefold() == key
    ]


class DuplicateReferenceError(ValidationError):
    def __init__(self, matches):
        self.matches = matches
        super().__init__({
            "name": "Já existem referências com esta designação. Reveja os registos existentes antes de criar uma nova referência.",
        })


def _reference_state(reference):
    return {
        "code": reference.code,
        "name": reference.name,
        "box_capacity": reference.box_capacity,
        "location_id": reference.location_id,
        "sector_id": reference.sector_id,
        "minimum": reference.minimum,
        "active": reference.active,
    }


def _next_reference_code():
    # The advisory lock serializes writers and the database uniqueness remains
    # the final guard. Existing imported identifiers are retained unchanged.
    greatest = max(
        (int(match.group(1)) for code in Reference.objects.values_list("code", flat=True)
         if (match := re.fullmatch(r"GAR-(\d+)", code))),
        default=0,
    )
    return f"GAR-{greatest + 1:04d}"


@transaction.atomic
def save_reference(*, actor, data, reference_id=None):
    require_administrator(actor)
    catalogue_lock()
    if reference_id is None:
        matches = matching_references(_name(data["name"]))
        if matches:
            raise DuplicateReferenceError(matches)
        reference = Reference(code=_next_reference_code(), current_stock=0)
        before = None
    else:
        reference = Reference.objects.select_for_update().get(pk=reference_id)
        before = _reference_state(reference)
    location = Location.objects.select_for_update().get(pk=data["location"].pk)
    sector = (
        Sector.objects.select_for_update().get(pk=data["sector"].pk)
        if data.get("sector") else None
    )
    if not location.active or (sector and not sector.active):
        raise ValidationError("Escolha uma localização e setor ativos.")
    if sector and sector.location_id != location.pk:
        raise ValidationError({"sector": "O setor não pertence à localização escolhida."})
    reference.name = _name(data["name"])
    reference.box_capacity = data.get("box_capacity")
    reference.location = location
    reference.sector = sector
    reference.minimum = data.get("minimum") if data.get("alert_enabled") else None
    if data.get("alert_enabled") and reference.minimum is None:
        raise ValidationError({"minimum": "Defina o mínimo para ativar este alerta."})
    reference.full_clean()
    if before is None:
        reference.save()
    else:
        reference.save(update_fields=["name", "box_capacity", "location", "sector", "minimum"])
        if (before["location_id"], before["sector_id"]) != (reference.location_id, reference.sector_id):
            LocationChange.objects.create(
                reference=reference,
                location_before_id=before["location_id"], location_after=location,
                sector_before_id=before["sector_id"], sector_after=sector,
                changed_by=actor, reason="Alteração na ficha da referência.",
            )
    AuditEvent.objects.create(
        actor=actor, action="reference.created" if before is None else "reference.updated",
        reference=reference, details={"before": before, "after": _reference_state(reference)},
    )
    return reference


@transaction.atomic
def set_reference_active(*, actor, reference_id, active):
    require_administrator(actor)
    catalogue_lock()
    reference = Reference.objects.select_for_update().get(pk=reference_id)
    if not active and reference.current_stock != 0:
        raise ValidationError(
            "Não é possível desativar esta referência porque ainda existem garrafas em stock."
        )
    if reference.active != active:
        before = reference.active
        reference.active = active
        reference.save(update_fields=["active"])
        AuditEvent.objects.create(
            actor=actor, action="reference.state_changed", reference=reference,
            details={"before": before, "after": active},
        )
    return reference


@transaction.atomic
def save_location(*, actor, data, location_id=None):
    require_administrator(actor)
    catalogue_lock()
    location = Location.objects.select_for_update().get(pk=location_id) if location_id else Location()
    before = {"name": location.name} if location.pk else None
    name = _name(data["name"])
    if Location.objects.filter(name__iexact=name).exclude(pk=location.pk).exists():
        raise ValidationError({"name": "Já existe uma localização com esta designação."})
    location.name = name
    location.full_clean()
    location.save()
    AuditEvent.objects.create(
        actor=actor, action="location.updated" if before else "location.created",
        details={"location_id": location.pk, "before": before, "after": {"name": name}},
    )
    return location


@transaction.atomic
def save_sector(*, actor, data, sector_id=None):
    require_administrator(actor)
    catalogue_lock()
    sector = Sector.objects.select_for_update().get(pk=sector_id) if sector_id else Sector()
    before = {"name": sector.name, "location_id": sector.location_id} if sector.pk else None
    location = Location.objects.select_for_update().get(pk=data["location"].pk)
    if before and before["location_id"] != location.pk:
        if sector.references.exists() or sector.changes_from.exists() or sector.changes_to.exists():
            raise ValidationError({"location": "Não pode mover um setor com referências ou histórico associados."})
    name = _name(data["name"])
    if Sector.objects.filter(location=location, name__iexact=name).exclude(pk=sector.pk).exists():
        raise ValidationError({"name": "Já existe um setor com esta designação na localização."})
    sector.name = name
    sector.location = location
    sector.full_clean()
    sector.save()
    AuditEvent.objects.create(
        actor=actor, action="sector.updated" if before else "sector.created",
        details={"sector_id": sector.pk, "before": before, "after": {"name": name, "location_id": location.pk}},
    )
    return sector


@transaction.atomic
def delete_location(*, actor, location_id):
    require_administrator(actor)
    catalogue_lock()
    location = Location.objects.select_for_update().get(pk=location_id)
    if Reference.objects.filter(Q(location=location) | Q(sector__location=location)).exists():
        raise ValidationError("Não pode remover uma localização com referências associadas, mesmo inativas.")
    before = {"location_id": location.pk, "name": location.name}
    try:
        location.sectors.all().delete()
        location.delete()
    except ProtectedError as exc:
        raise ValidationError("Não pode remover esta localização: existe histórico associado.") from exc
    AuditEvent.objects.create(actor=actor, action="location.deleted", details=before)


@transaction.atomic
def delete_sector(*, actor, sector_id):
    require_administrator(actor)
    catalogue_lock()
    sector = Sector.objects.select_for_update().get(pk=sector_id)
    if sector.references.exists():
        raise ValidationError("Não pode remover um setor com referências associadas, mesmo inativas.")
    before = {"sector_id": sector.pk, "name": sector.name, "location_id": sector.location_id}
    try:
        sector.delete()
    except ProtectedError as exc:
        raise ValidationError("Não pode remover este setor: existe histórico associado.") from exc
    AuditEvent.objects.create(actor=actor, action="sector.deleted", details=before)
