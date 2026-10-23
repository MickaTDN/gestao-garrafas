"""Owned drafts, revision checks and explicit review, without quantitative effects."""

import uuid

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import AuditEvent, Movement, MovementLine, Reference
from .services import (
    bottle_total,
    locked_lines,
    movement_plans,
    owned_draft,
    reference_state,
    require_administrator,
    resolve_person,
)


def _lock():
    from .catalog import catalogue_lock

    catalogue_lock()


def _revision(movement, revision):
    if type(revision) is not int or movement.revision != revision:
        raise ValidationError("O rascunho foi alterado noutra janela. Reabra-o antes de guardar.")


def _invalidate(movement):
    movement.revision += 1
    movement.review_token = None
    movement.review_snapshot = {}
    movement.save()


@transaction.atomic
def create_draft(
    *, actor, kind, inventory_scope="partial", references=None, correction_of=None, reason=""
):
    require_administrator(actor)
    _lock()
    if kind not in ("entry", "exit", "inventory") or inventory_scope not in ("partial", "full"):
        raise ValidationError("Tipo de operação inválido.")
    if correction_of and (
        kind != "inventory" or correction_of.status != "confirmed" or not reason.strip()
    ):
        raise ValidationError("A correção exige um movimento confirmado e um motivo.")
    movement = Movement.objects.create(
        kind=kind,
        created_by=actor,
        workflow_version=1,
        inventory_scope=inventory_scope,
        correction_of=correction_of,
        reason=reason.strip(),
        report_requested=kind == "exit",
    )
    if kind == "inventory" and inventory_scope == "full" and references is None:
        references = Reference.objects.filter(active=True)
    for ref in references or []:
        if not ref.active:
            raise ValidationError("Não é possível selecionar referências inativas.")
        if correction_of and not correction_of.lines.filter(reference=ref).exists():
            raise ValidationError("Referência fora do movimento a corrigir.")
        MovementLine.objects.create(
            movement=movement,
            reference=ref,
            box_capacity=ref.box_capacity,
            target_location=ref.location,
            target_sector=ref.sector,
        )
    AuditEvent.objects.create(
        actor=actor,
        movement=movement,
        action="movement.created",
        details={
            "kind": kind,
            "scope": inventory_scope,
            "correction_of": correction_of.pk if correction_of else None,
        },
    )
    return movement


@transaction.atomic
def save_draft(
    movement_id, *, actor, revision, header, rows=(), add_ids=(), remove_ids=(), recheck=False
):
    require_administrator(actor)
    _lock()
    movement = Movement.objects.select_for_update().get(pk=movement_id)
    owned_draft(movement, actor)
    _revision(movement, revision)
    movement.draft_person_name = " ".join(
        header.get("person_name", movement.draft_person_name).split()
    )
    if len(movement.draft_person_name) > 200:
        raise ValidationError("Nome demasiado longo.")
    movement.person = (
        resolve_person(movement.draft_person_name) if movement.draft_person_name else None
    )
    movement.date = header.get("date") or movement.date or timezone.localdate()
    movement.reason = header.get("reason", movement.reason).strip()
    movement.report_requested = movement.kind == "exit" or bool(header.get("report_requested"))
    # Validation cannot be selected/forged by an edit request. Only review enables simple confirmation.
    movement.validation = ""
    if movement.correction_of_id and not movement.reason:
        raise ValidationError("A correção exige um motivo obrigatório.")
    lines, references = locked_lines(movement)
    by_id = {line.pk: line for line in lines}
    if len({row["id"] for row in rows}) != len(rows):
        raise ValidationError("Linhas repetidas no pedido.")
    for row in rows:
        if row["id"] not in by_id:
            raise ValidationError("Linha não pertence a este rascunho.")
        line = by_id[row["id"]]
        ref = references[line.reference_id]
        boxes, units = row.get("boxes"), row.get("units")
        total = bottle_total(boxes, units, ref.box_capacity)
        changed = (boxes, units, line.box_capacity) != (line.boxes, line.units, ref.box_capacity)
        if movement.kind == "inventory":
            if changed or recheck or not line.count_basis:
                # Web supplies a signed snapshot of what the counter actually saw.
                basis = row.get("basis", reference_state(ref))
                if basis != reference_state(ref):
                    raise ValidationError(
                        f"{ref.code}: stock ou configuração mudou enquanto contava. Confira os valores atuais."
                    )
                line.count_basis = basis if total is not None else {}
            line.counted_quantity = total
            line.quantity = None  # Never treat a physical count as an adjustment.
            line.target_location = (
                row.get("target_location") or line.target_location or ref.location
            )
            line.target_sector = row.get("target_sector")
            if line.target_sector and line.target_sector.location_id != line.target_location_id:
                raise ValidationError("O setor não pertence à localização escolhida.")
        else:
            line.quantity = (
                None if total is None else total * (1 if movement.kind == "entry" else -1)
            )
        line.boxes, line.units, line.box_capacity = boxes, units, ref.box_capacity
        line.reason = row.get("reason", "").strip()
        line.save()
    remove_ids = set(remove_ids)
    if not remove_ids.issubset(by_id):
        raise ValidationError("Linha inválida para remoção.")
    if remove_ids and movement.kind == "inventory" and movement.inventory_scope == "full":
        raise ValidationError("Um inventário completo deve contar todas as referências abrangidas.")
    movement.lines.filter(pk__in=remove_ids).delete()
    add_ids = set(add_ids)
    refs = list(Reference.objects.filter(pk__in=add_ids).order_by("pk"))
    if len(refs) != len(add_ids) or any(not ref.active for ref in refs):
        raise ValidationError("Selecione apenas referências ativas existentes.")
    if movement.kind == "inventory" and movement.inventory_scope == "full" and add_ids:
        raise ValidationError("O âmbito do inventário completo foi fixado na criação.")
    for ref in refs:
        if (
            movement.correction_of_id
            and not movement.correction_of.lines.filter(reference=ref).exists()
        ):
            raise ValidationError("Referência fora do movimento original.")
        movement.lines.get_or_create(
            reference=ref,
            defaults={
                "box_capacity": ref.box_capacity,
                "target_location": ref.location,
                "target_sector": ref.sector,
            },
        )
    _invalidate(movement)
    AuditEvent.objects.create(
        actor=actor,
        movement=movement,
        action="movement.draft_saved",
        details={"revision": movement.revision, "rechecked": bool(recheck)},
    )
    return movement


@transaction.atomic
def review_draft(movement_id, *, actor, revision):
    require_administrator(actor)
    _lock()
    movement = Movement.objects.select_for_update().get(pk=movement_id)
    owned_draft(movement, actor)
    _revision(movement, revision)
    if movement.kind == "exit":
        movement.validation = Movement.Validation.SIMPLE
    lines, references = locked_lines(movement)
    plans = movement_plans(movement, lines, references)
    movement.review_token = uuid.uuid4()
    movement.review_snapshot = {str(pk): reference_state(ref) for pk, ref in references.items()}
    movement.save()
    AuditEvent.objects.create(
        actor=actor, movement=movement, action="movement.reviewed", details={"revision": revision}
    )
    return movement, plans


@transaction.atomic
def cancel_draft(movement_id, *, actor, revision):
    require_administrator(actor)
    _lock()
    movement = Movement.objects.select_for_update().get(pk=movement_id)
    owned_draft(movement, actor)
    _revision(movement, revision)
    movement.status = Movement.Status.CANCELLED
    movement.review_token = None
    movement.review_snapshot = {}
    movement.save()
    AuditEvent.objects.create(
        actor=actor, movement=movement, action="movement.cancelled", details={"revision": revision}
    )
    return movement
