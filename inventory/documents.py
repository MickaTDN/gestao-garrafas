"""Private document bytes in PostgreSQL: stock, signature and PDF commit together."""

import base64
import binascii
import hashlib
import io
import uuid
import warnings

from django.core.exceptions import ValidationError
from django.utils import timezone
from PIL import Image, ImageStat, UnidentifiedImageError

from .models import AuditEvent, Document, ReportFile

MAX_SIGNATURE_BYTES = 256 * 1024
MAX_DOCUMENT_BYTES = 8 * 1024 * 1024


class DocumentIntegrityError(Exception):
    pass


def validate_signature(value):
    """Accept only a bounded PNG, decode it, reject blank images, strip metadata."""
    prefix = "data:image/png;base64,"
    if (
        not isinstance(value, str)
        or len(value) > 4 * MAX_SIGNATURE_BYTES // 3 + 100
        or not value.startswith(prefix)
    ):
        raise ValidationError("Assinatura inválida ou demasiado grande (máximo 256 KiB).")
    try:
        raw = base64.b64decode(value[len(prefix) :], validate=True)
        if len(raw) > MAX_SIGNATURE_BYTES:
            raise ValueError
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                if (
                    image.format != "PNG"
                    or getattr(image, "n_frames", 1) != 1
                    or not (100 <= image.width <= 2048 and 40 <= image.height <= 1024)
                ):
                    raise ValueError
                image.verify()
            with Image.open(io.BytesIO(raw)) as image:
                rgba = image.convert("RGBA")
                white = Image.new("RGBA", rgba.size, "white")
                white.alpha_composite(rgba)
                grey = white.convert("L")
                histogram = grey.histogram()
                ink = sum(histogram[:220])
                if ink < 30 or ImageStat.Stat(grey).stddev[0] < 1:
                    raise ValueError
                output = io.BytesIO()
                white.convert("RGB").save(output, format="PNG", optimize=True)
                canonical = output.getvalue()
                if len(canonical) > MAX_SIGNATURE_BYTES:
                    raise ValueError
                return canonical
    except (
        binascii.Error,
        ValueError,
        OSError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as error:
        raise ValidationError(
            "Desenhe uma assinatura válida em PNG, dentro dos limites permitidos."
        ) from error


def store_document(movement, *, kind, payload, metadata=None):
    if not payload or len(payload) > MAX_DOCUMENT_BYTES:
        raise ValidationError("Não foi possível guardar o documento dentro dos limites permitidos.")
    extension = "pdf" if kind == "pdf" else "png"
    reproducible = kind == "pdf" and (metadata or {}).get("presentation") == 3
    document = Document.objects.create(
        movement=movement,
        kind=kind,
        storage_key=f"{uuid.uuid4()}.{extension}",
        payload=None if reproducible else payload,
        byte_size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        content_type="application/pdf" if kind == "pdf" else "image/png",
        metadata=metadata or {},
    )

    if reproducible:
        ReportFile.objects.create(document=document, payload=payload)

    AuditEvent.objects.create(
        actor=movement.confirmed_by or movement.created_by,
        movement=movement,
        action="document.created",
        details={"document_id": document.pk, "kind": kind, "byte_size": len(payload)},
    )
    return document


def verified_bytes(document):
    from .reporting import document_payload

    payload = document_payload(document)
    if (
        not payload
        or len(payload) != document.byte_size
        or hashlib.sha256(payload).hexdigest() != document.sha256
    ):
        raise DocumentIntegrityError("A verificação de integridade do documento falhou.")
    return payload


def report_snapshot(movement, *, actor):
    lines = []
    for line in movement.lines.select_related(
        "reference", "target_location", "target_sector"
    ).order_by("reference__code"):
        lines.append(
            {
                "code": line.reference.code,
                "name": line.reference_name,
                "capacity": line.box_capacity,
                "boxes": line.boxes,
                "units": line.units,
                "quantity": line.quantity,
                "counted": line.counted_quantity,
                "before": line.stock_before,
                "after": line.stock_after,
                "reason": line.reason or movement.reason,
                "location": line.target_location.name if line.target_location_id else None,
                "sector": line.target_sector.name if line.target_sector_id else None,
            }
        )
    changes = [
        {
            "code": change.reference.code,
            "name": change.reference.name,
            "before": change.before_snapshot,
            "after": change.after_snapshot,
            "reason": change.reason,
        }
        for change in movement.location_changes.select_related("reference")
    ]
    return {
        "schema": 1,
        "presentation": 3,
        "id": movement.pk,
        "kind": movement.kind,
        "label": movement.get_kind_display(),
        "date": movement.date.isoformat(),
        "confirmed_at": timezone.localtime(movement.occurred_at).isoformat(),
        "person": movement.person_name,
        "responsible": actor.username,
        "validation": movement.validation,
        "correction_of": movement.correction_of_id,
        "reason": movement.reason,
        "lines": lines,
        "changes": changes,
    }


def render_pdf(snapshot, signature=None):
    from .pdf_v3 import render_pdf as render

    return render(snapshot, signature)


def create_confirmation_documents(movement, *, actor, number, signature=None):
    from .reporting import template_key

    signature_document = (
        store_document(movement, kind="signature", payload=signature) if signature else None
    )
    if movement.kind in ("exit", "inventory") or movement.report_requested:
        snapshot = report_snapshot(movement, actor=actor)
        snapshot.update(
            {
                "report_number": f"Mov-{number}/{movement.date.year % 100:02}",
                "report_year": movement.date.year,
                "report_sequence": number,
                "template_key": template_key(),
                "signature_sha256": signature_document.sha256 if signature_document else None,
            }
        )
        document = store_document(
            movement, kind="pdf", payload=render_pdf(snapshot, signature), metadata=snapshot
        )
        return document
    return None
