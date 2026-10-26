"""Bounded signed snapshots and complete receipt windows; never infer receipts from balances."""

import json
import uuid
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.utils import timezone

from accounts.permissions import require_access
from inventory.models import AuditEvent, MovementLine, Reference

from .models import ExportSource
from .signing import read_key, signed_snapshot

MAX_RECEIPTS = 10000
WINDOW_DAYS = 180
MAX_BYTES = 8 * 1024 * 1024


def instant(value):
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def receipt_rows(start, end):
    rows = list(
        MovementLine.objects.filter(
            movement__kind="entry",
            movement__status="confirmed",
            movement__occurred_at__gte=start,
            movement__occurred_at__lte=end,
        )
        .order_by("movement__occurred_at", "pk")
        .values(
            "id",
            "movement_id",
            "reference_id",
            "movement__date",
            "movement__occurred_at",
            "quantity",
            "boxes",
            "units",
            "box_capacity",
            "reference_name",
        )[: MAX_RECEIPTS + 1]
    )
    if len(rows) > MAX_RECEIPTS:
        raise ValidationError(
            "Mais de 10 000 linhas de Entrada no período. Exporte uma janela menor; não se omitem receções."
        )
    for row in rows:
        total = (row["boxes"] or 0) * (row["box_capacity"] or 0) + (row["units"] or 0)
        if (
            not 0 < row["quantity"] <= 2147483647
            or ((row["boxes"] is not None or row["units"] is not None) and row["quantity"] != total)
            or not row["reference_name"].strip()
        ):
            raise ValidationError(
                "Uma Entrada é incompatível com o formato. Não se omitem nem corrigem movimentos automaticamente."
            )
    return [
        {
            "id": str(row["id"]),
            "movement_id": str(row["movement_id"]),
            "reference_id": str(row["reference_id"]),
            "name": row["reference_name"],
            "date": row["movement__date"].isoformat(),
            "confirmed_at": instant(row["movement__occurred_at"]),
            "bottles": row["quantity"],
            "boxes": row["boxes"],
            "units": row["units"],
            "box_capacity": row["box_capacity"],
        }
        for row in rows
    ]


def _source():
    try:
        return ExportSource.objects.select_for_update().get(pk=1)
    except ExportSource.DoesNotExist as error:
        raise ValidationError(
            "A origem de exportação ainda não foi preparada pela informática."
        ) from error


def _size(envelope):
    if len(json.dumps(envelope, ensure_ascii=False).encode()) > MAX_BYTES:
        raise ValidationError(
            "O ficheiro excede 8 MiB. Peça janelas de receção menores à informática."
        )
    return envelope


def export_snapshot(*, actor, days=WINDOW_DAYS):
    if connection.vendor != "postgresql":
        raise ValidationError("A exportação consistente exige PostgreSQL.")
    if not isinstance(days, int) or isinstance(days, bool) or not 1 <= days <= WINDOW_DAYS:
        raise ValidationError("A janela de receções deve ter entre 1 e 180 dias.")
    with transaction.atomic():
        # SAME existing authorization lock held by all transactional writes,
        # catalogue edits and permission changes: no half-confirmed stock/receipts,
        # no uncommitted earlier receipt hidden behind the exported coverage end.
        require_access(actor, "export")
        key = read_key(settings.VERTENTE_SIGNING_KEY_FILE)
        source = _source()
        now = timezone.now()
        if source.last_exported_at and now <= source.last_exported_at:
            raise ValidationError("O relógio do servidor recuou. Corrija-o antes de exportar.")
        rows = list(
            Reference.objects.filter(active=True)
            .order_by("pk")
            .values(
                "id",
                "name",
                "current_stock",
                "box_capacity",
                "location__name",
                "sector__name",
                "minimum",
            )[:10001]
        )
        if len(rows) > 10000 or source.sequence >= 9007199254740991:
            raise ValidationError("O catálogo ou contador excede os limites do formato.")
        if any(
            not row["name"].strip()
            or not 0 <= row["current_stock"] <= 2147483647
            or (row["box_capacity"] is not None and not 1 <= row["box_capacity"] <= 2147483647)
            or (row["minimum"] is not None and not 0 <= row["minimum"] <= 2147483647)
            for row in rows
        ):
            raise ValidationError(
                "Uma referência é incompatível com o formato. Não foi exportado stock parcial."
            )
        start = now - timedelta(days=days)
        payload = {
            "source_id": str(source.source_id),
            "update_id": str(uuid.uuid4()),
            "sequence": source.sequence + 1,
            "exported_at": instant(now),
            "references": [
                {
                    "id": str(row["id"]),
                    "name": row["name"],
                    "bottles": row["current_stock"],
                    "box_capacity": row["box_capacity"],
                    "location": row["location__name"],
                    "sector": row["sector__name"],
                    "minimum": row["minimum"],
                }
                for row in rows
            ],
            "receipts": receipt_rows(start, now),
            "coverage": {"from": instant(start), "until": instant(now)},
        }
        envelope = _size(signed_snapshot(payload, key))
        source.sequence += 1
        source.last_exported_at = now
        source.save(update_fields=["sequence", "last_exported_at"])
        AuditEvent.objects.create(
            actor=actor,
            action="vertente.exported",
            details={
                "update_id": payload["update_id"],
                "sequence": source.sequence,
                "references": len(rows),
                "receipts": len(payload["receipts"]),
                "days": days,
            },
        )
    return envelope


def recovery_receipts(*, start, end):
    """IT command only. Bounded complete windows; overlaps are deliberately safe."""
    if connection.vendor != "postgresql" or timezone.is_naive(start) or timezone.is_naive(end):
        raise ValidationError("São necessários PostgreSQL e instantes com fuso horário.")
    if start >= end or end > timezone.now():
        raise ValidationError("Indique um período válido, sem datas futuras.")
    key = read_key(settings.VERTENTE_SIGNING_KEY_FILE)
    from accounts.permissions import authorization_lock

    with transaction.atomic():
        authorization_lock()
        source = _source()
        payload = {
            "source_id": str(source.source_id),
            "update_id": str(uuid.uuid4()),
            "exported_at": instant(timezone.now()),
            "coverage": {"from": instant(start), "until": instant(end)},
            "receipts": receipt_rows(start, end),
        }
        envelope = _size(signed_snapshot(payload, key, kind="vertente-receipts", version=1))
        AuditEvent.objects.create(
            action="vertente.receipts_recovered",
            details={
                "update_id": payload["update_id"],
                "coverage": payload["coverage"],
                "receipts": len(payload["receipts"]),
            },
        )
        return envelope
