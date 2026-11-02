"""Administrative decisions over immutable receipts. Only confirmation touches stock."""

import uuid
from datetime import date

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.permissions import require_access
from inventory import operations
from inventory.catalog import catalogue_lock
from inventory.models import AuditEvent, Reference
from inventory.services import bottle_total, confirm_movement, reference_state

from .models import PendingSheet, SheetAction
from .sheets import integer, text


def current(sheet):
    action = sheet.actions.order_by("-sequence").first()
    return action, (action.data["payload"] if action else sheet.payload)


def _locked(sheet_id, actor):
    require_access(actor, "admin")
    catalogue_lock()
    sheet = PendingSheet.objects.select_for_update().get(pk=sheet_id)
    action, payload = current(sheet)
    return sheet, action, payload


def _revision(action, sequence):
    if type(sequence) is not int or sequence != (action.sequence if action else 0):
        raise ValidationError("A folha mudou noutra janela. Reabra e confira a versão atual.")
    if action and action.kind in ("confirmed", "rejected"):
        raise ValidationError("A folha já foi confirmada ou rejeitada; a decisão é definitiva.")


def _reason(reason):
    try:
        text(reason, 4000)
        if not reason.strip():
            raise ValueError
    except (TypeError, ValueError, UnicodeError) as error:
        raise ValidationError("Indique um motivo obrigatório (até 4000 caracteres).") from error
    return reason.strip()


def _clean(payload, values):
    try:
        if set(values) != {"person", "physical_date", "notes", "lines"}:
            raise ValueError
        text(values["person"], 200)
        text(values["notes"], 4000)
        if date.fromisoformat(values["physical_date"]).isoformat() != values["physical_date"]:
            raise ValueError
        lines = values["lines"]
        if not isinstance(lines, list) or not 1 <= len(lines) <= 500:
            raise ValueError
        seen = set()
        for line in lines:
            if set(line) != {"reference_id", "boxes", "units", "box_capacity"}:
                raise ValueError
            text(line["reference_id"], 100)
            if not line["reference_id"] or line["reference_id"] in seen:
                raise ValueError
            seen.add(line["reference_id"])
            if line["box_capacity"] is not None:
                integer(line["box_capacity"], 1)
            bottle_total(line["boxes"], line["units"], line["box_capacity"])
        return {**payload, **values}
    except (TypeError, ValueError, KeyError, UnicodeError) as error:
        raise ValidationError(
            "Dados da correção inválidos ou fora dos limites permitidos."
        ) from error


def _plans(payload):
    if not payload["person"].strip():
        raise ValidationError("Indique a pessoa que entregou ou levantou.")
    ids = [line["reference_id"] for line in payload["lines"]]
    numeric = [
        int(i) for i in ids if i.isascii() and i.isdigit() and 0 < int(i) <= 9223372036854775807
    ]
    refs = {
        str(r.pk): r
        for r in Reference.objects.select_for_update().filter(pk__in=numeric).order_by("pk")
    }
    plans = []
    for line in payload["lines"]:
        ref = refs.get(line["reference_id"])
        if not ref:
            raise ValidationError(
                f"Referência desconhecida: {line['reference_id']}. Corrija explicitamente a associação; não é criada automaticamente."
            )
        if not ref.active:
            raise ValidationError(f"{ref.code}: referência inativa.")
        if line["box_capacity"] != ref.box_capacity:
            raise ValidationError(
                f"{ref.code}: capacidade alterada; corrija e confira novamente caixas e garrafas."
            )
        if not ref.location.active or (
            ref.sector_id and (ref.sector.location_id != ref.location_id or not ref.sector.active)
        ):
            raise ValidationError(
                f"{ref.code}: localização/setor inválido ou inativo; reveja o catálogo."
            )
        total = bottle_total(line["boxes"], line["units"], ref.box_capacity)
        if total is None or total <= 0:
            raise ValidationError(f"{ref.code}: indique uma quantidade positiva.")
        delta = total if payload["kind"] == "entry" else -total
        after = ref.current_stock + delta
        if not 0 <= after <= 2147483647:
            raise ValidationError(
                f"{ref.code}: stock efetivamente disponível insuficiente ou acima do limite."
            )
        plans.append(
            {
                "reference": ref,
                "line": line,
                "before": ref.current_stock,
                "quantity": delta,
                "after": after,
            }
        )
    return plans, {pk: reference_state(ref) for pk, ref in refs.items()}


def _conflicts(sheet):
    return sorted(
        str(pk) for pk in sheet.receipts.filter(outcome="conflict").values_list("pk", flat=True)
    )


def _record(sheet, action, *, kind, actor, payload, reason="", extra=None, movement=None):
    event = SheetAction.objects.create(
        sheet=sheet,
        sequence=(action.sequence if action else 0) + 1,
        kind=kind,
        actor=actor,
        reason=reason,
        data={"payload": payload, **(extra or {})},
        movement=movement,
    )
    AuditEvent.objects.create(
        actor=actor,
        movement=movement,
        action="sheets." + kind,
        details={"sheet_id": str(sheet.pk), "action_id": event.pk, "sequence": event.sequence},
    )
    return event


@transaction.atomic
def correct_sheet(sheet_id, *, actor, sequence, values, reason):
    sheet, action, payload = _locked(sheet_id, actor)
    _revision(action, sequence)
    reason = _reason(reason)
    data = _clean(payload, values)
    return _record(sheet, action, kind="corrected", actor=actor, payload=data, reason=reason)


@transaction.atomic
def reject_sheet(sheet_id, *, actor, sequence, reason):
    sheet, action, payload = _locked(sheet_id, actor)
    _revision(action, sequence)
    return _record(
        sheet, action, kind="rejected", actor=actor, payload=payload, reason=_reason(reason)
    )


@transaction.atomic
def review_sheet(sheet_id, *, actor, sequence, acknowledge_conflicts=False, reason=""):
    sheet, action, payload = _locked(sheet_id, actor)
    _revision(action, sequence)
    plans, basis = _plans(payload)
    conflicts = _conflicts(sheet)
    if conflicts:
        if acknowledge_conflicts is not True:
            raise ValidationError(
                "Existem ficheiros divergentes: reveja os originais e confirme explicitamente a versão de trabalho."
            )
        reason = _reason(reason)
    event = _record(
        sheet,
        action,
        kind="reviewed",
        actor=actor,
        payload=payload,
        reason=reason,
        extra={
            "basis": basis,
            "token": str(uuid.uuid4()),
            "official_date": timezone.localdate().isoformat(),
            "conflicts": conflicts,
        },
    )
    return event, plans


@transaction.atomic
def _confirm_sheet(
    sheet_id, *, actor, sequence, token, confirmed, report_requested, validation, signature_data
):
    sheet, action, payload = _locked(sheet_id, actor)
    if confirmed is not True:
        raise ValidationError("Confirme explicitamente a operação oficial.")
    if action and action.kind == "confirmed":
        if str(token) != action.data["token"]:
            raise ValidationError("Folha já confirmada. Consulte o movimento oficial existente.")
        return action.movement
    _revision(action, sequence)
    if not action or action.kind != "reviewed" or str(token) != action.data["token"]:
        raise ValidationError("Confira a folha antes de confirmar.")
    if action.data["official_date"] != timezone.localdate().isoformat():
        raise ValidationError(
            "A conferência é de outro dia. Volte a conferir; não se altera a data oficial silenciosamente."
        )
    plans, basis = _plans(payload)
    if basis != action.data["basis"] or _conflicts(sheet) != action.data["conflicts"]:
        raise ValidationError(
            "Stock, catálogo ou ficheiros divergentes mudaram desde a conferência. Volte a conferir."
        )
    refs = [p["reference"] for p in plans]
    movement = operations.create_draft(actor=actor, kind=payload["kind"], references=refs)
    by_ref = {str(line.reference_id): line for line in movement.lines.all()}
    movement = operations.save_draft(
        movement.pk,
        actor=actor,
        revision=movement.revision,
        header={
            "person_name": payload["person"],
            "date": timezone.localdate(),
            "reason": payload["notes"],
            "report_requested": report_requested,
        },
        rows=[
            {"id": by_ref[line["reference_id"]].pk, "boxes": line["boxes"], "units": line["units"]}
            for line in payload["lines"]
        ],
    )
    movement.source_metadata = {
        "pending_sheet_id": str(sheet.pk),
        "sender_sheet_id": str(sheet.sheet_id),
        "source_id": str(sheet.source_id),
        "device_id": str(sheet.device_id),
        "physical_date": payload["physical_date"],
        "sender_revision": sheet.revision,
        "sheet_review_id": action.pk,
    }
    movement.save(update_fields=["source_metadata"])
    reviewed, _ = operations.review_draft(movement.pk, actor=actor, revision=movement.revision)
    result = confirm_movement(
        movement.pk,
        actor=actor,
        review_token=reviewed.review_token,
        report_requested=report_requested,
        validation=validation,
        signature_data=signature_data,
    )
    _record(
        sheet,
        action,
        kind="confirmed",
        actor=actor,
        payload=payload,
        movement=result,
        extra={
            "token": str(token),
            "basis": basis,
            "official_date": result.date.isoformat(),
            "review_id": action.pk,
        },
    )
    return result


def confirm_sheet(
    sheet_id,
    *,
    actor,
    sequence,
    token,
    confirmed=False,
    report_requested=None,
    validation=None,
    signature_data=None,
):
    require_access(actor, "admin")
    try:
        return _confirm_sheet(
            sheet_id,
            actor=actor,
            sequence=sequence,
            token=token,
            confirmed=confirmed,
            report_requested=report_requested,
            validation=validation,
            signature_data=signature_data,
        )
    except PermissionDenied:
        raise
    except Exception as error:
        # Failed stock/PDF writes have already rolled back. Log only a safe category.
        with transaction.atomic():
            require_access(actor, "admin")
            AuditEvent.objects.create(
                actor=actor,
                action="sheets.confirmation_failed",
                details={"sheet_id": str(sheet_id), "category": type(error).__name__},
            )
        raise
