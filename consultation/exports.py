import json
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.utils import timezone

from inventory.models import AuditEvent, Reference

from .models import ExportSource
from .signing import read_key, signed_snapshot


def export_snapshot(*, actor):
    if not actor.is_authenticated or not actor.is_active or actor.role not in ("admin", "viewer"):
        raise ValidationError("É necessária uma conta com permissão de consulta.")
    if connection.vendor != "postgresql":
        raise ValidationError("A exportação consistente exige PostgreSQL.")
    key = read_key(settings.VERTENTE_SIGNING_KEY_FILE)
    with transaction.atomic():
        try:
            source = ExportSource.objects.select_for_update().get(pk=1)
        except ExportSource.DoesNotExist as error:
            raise ValidationError(
                "A origem de exportação ainda não foi preparada pela informática."
            ) from error
        now = timezone.now()
        if source.last_exported_at and now <= source.last_exported_at:
            raise ValidationError("O relógio do servidor recuou. Corrija-o antes de exportar.")
        # ONE SELECT at READ COMMITTED gives all rows/fields the same PostgreSQL
        # statement snapshot. Concurrent stock transactions are visible wholly or not.
        rows = list(
            Reference.objects.filter(active=True)
            .order_by("pk")
            .values("id", "code", "name", "current_stock", "box_capacity")
        )
        if len(rows) > 10000:
            raise ValidationError("O catálogo excede o limite de 10 000 referências do formato.")
        if source.sequence >= 9007199254740991 or any(
            not row["name"].strip() or not row["code"].strip() for row in rows
        ):
            raise ValidationError(
                "A identidade ou o catálogo precisa de revisão antes de exportar."
            )
        source.sequence += 1
        payload = {
            "source_id": str(source.source_id),
            "update_id": str(uuid.uuid4()),
            "sequence": source.sequence,
            "exported_at": now.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "references": [
                {
                    "id": str(row["id"]),
                    "code": row["code"],
                    "name": row["name"],
                    "bottles": row["current_stock"],
                    "box_capacity": row["box_capacity"],
                }
                for row in rows
            ],
        }
        envelope = signed_snapshot(payload, key)
        if len(json.dumps(envelope, ensure_ascii=False).encode()) > 4 * 1024 * 1024:
            raise ValidationError("A exportação excede os 4 MiB suportados pelo formato.")
        source.last_exported_at = now
        source.save(update_fields=["sequence", "last_exported_at"])
        AuditEvent.objects.create(
            actor=actor,
            action="vertente.exported",
            details={
                "update_id": payload["update_id"],
                "sequence": source.sequence,
                "references": len(rows),
            },
        )
    return envelope
