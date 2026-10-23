"""Private document bytes in PostgreSQL: stock, signature and PDF commit together."""

import base64
import binascii
import hashlib
import io
import uuid
import warnings
from datetime import date, datetime
from pathlib import Path
from xml.sax.saxutils import escape

import reportlab
from django.core.exceptions import ValidationError
from django.utils import timezone
from PIL import Image, ImageStat, UnidentifiedImageError
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image as PDFImage
from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle

from .models import AuditEvent, Document

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
    document = Document.objects.create(
        movement=movement,
        kind=kind,
        storage_key=f"{uuid.uuid4()}.{extension}",
        payload=payload,
        byte_size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        content_type="application/pdf" if kind == "pdf" else "image/png",
        metadata=metadata or {},
    )

    AuditEvent.objects.create(
        actor=movement.confirmed_by or movement.created_by,
        movement=movement,
        action="document.created",
        details={"document_id": document.pk, "kind": kind, "byte_size": len(payload)},
    )
    return document


def verified_bytes(document):
    payload = bytes(document.payload or b"")
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
            "before": change.before_snapshot,
            "after": change.after_snapshot,
            "reason": change.reason,
        }
        for change in movement.location_changes.select_related("reference")
    ]
    return {
        "schema": 1,
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
    """A4 report generated once from immutable confirmation snapshots."""
    fonts = Path(reportlab.__file__).parent / "fonts"
    if "GG" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("GG", str(fonts / "Vera.ttf")))
        pdfmetrics.registerFont(TTFont("GG-Bold", str(fonts / "VeraBd.ttf")))
    body = ParagraphStyle(
        "GGBody", fontName="GG", fontSize=8, leading=12, alignment=TA_LEFT, spaceAfter=5
    )
    title = ParagraphStyle(
        "GGTitle",
        parent=body,
        fontName="GG-Bold",
        fontSize=19,
        leading=24,
        textColor=colors.HexColor("#126650"),
    )
    header = ParagraphStyle(
        "GGHeader", parent=body, fontName="GG-Bold", fontSize=7, leading=10, textColor=colors.white
    )

    def p(value, style=body):
        return Paragraph(escape("—" if value is None else str(value)).replace("\n", "<br/>"), style)

    output = io.BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=17 * mm,
        leftMargin=17 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        title=f"Gestão de Garrafas · MOV-{snapshot['id']}",
        author="Gestão de Garrafas",
    )
    story = [
        p("GESTÃO DE GARRAFAS", title),
        Spacer(1, 5 * mm),
        p(f"{snapshot['label']} · MOV-{snapshot['id']}", title),
        p(
            f"Data: {date.fromisoformat(snapshot['date']).strftime('%d/%m/%Y')} · Confirmado: {datetime.fromisoformat(snapshot['confirmed_at']).strftime('%d/%m/%Y %H:%M:%S %z')}"
        ),
        p(f"Responsável pela confirmação: {snapshot['responsible']}"),
        p(f"Pessoa: {snapshot['person'] or 'Não aplicável'}"),
    ]
    if snapshot["correction_of"]:
        story.append(
            p(f"Correção relacionada com MOV-{snapshot['correction_of']} · {snapshot['reason']}")
        )
    elif snapshot["reason"]:
        story.append(p(snapshot["reason"]))
    inventory = snapshot["kind"] == "inventory"
    headings = [
        "Referência / capacidade",
        "Caixas",
        "Soltas",
        "Contagem" if inventory else "Total",
        "Stock antes",
        "Diferença" if inventory else "Variação",
        "Stock final",
    ]
    rows = [[p(label, header) for label in headings]]
    for line in snapshot["lines"]:
        rows.append(
            [
                p(
                    f"{line['code']} · {line['name']}\nCaixa: {line['capacity'] if line['capacity'] is not None else 'por definir'}"
                ),
                p(line["boxes"]),
                p(line["units"]),
                p(line["counted"] if inventory else abs(line["quantity"])),
                p(line["before"]),
                p(line["quantity"]),
                p(line["after"]),
            ]
        )
        if inventory:
            rows.append(
                [
                    p(
                        f"Motivo: {line['reason'] or 'Sem diferença quantitativa'}\nLocalização final: {line['location'] or 'por definir'} · Setor: {line['sector'] or 'por definir'}"
                    ),
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                ]
            )
    table = LongTable(
        rows,
        colWidths=[61 * mm, 14 * mm, 14 * mm, 20 * mm, 21 * mm, 22 * mm, 24 * mm],
        repeatRows=1,
        hAlign="LEFT",
    )
    commands = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#126650")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 1), (-1, -1), 0.3, colors.HexColor("#e0e8e4")),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]
    if inventory:
        commands.extend(("SPAN", (0, index), (-1, index)) for index in range(2, len(rows), 2))
    table.setStyle(TableStyle(commands))
    story.extend([Spacer(1, 4 * mm), table, Spacer(1, 4 * mm)])
    if not inventory:
        story.append(
            p(f"Total de garrafas: {sum(abs(line['quantity']) for line in snapshot['lines'])}")
        )
    for change in snapshot["changes"]:
        story.append(
            p(
                f"Transferência {change['code']}: {change['before'].get('location')} / {change['before'].get('sector') or 'sem setor'} → {change['after'].get('location')} / {change['after'].get('sector') or 'sem setor'} · {change['reason']}"
            )
        )
    if signature:
        story.extend(
            [
                p(
                    "Validação com assinatura desenhada — não constitui assinatura digital qualificada."
                ),
                PDFImage(io.BytesIO(signature), width=90 * mm, height=30 * mm, kind="proportional"),
            ]
        )
    elif snapshot["kind"] == "exit":
        story.append(p("Validação: confirmação simples, sem assinatura."))
    story.append(
        p(
            "Caixas e garrafas soltas preservam os valores introduzidos; — identifica informação não fornecida."
        )
    )

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("GG", 8)
        canvas.setFillColor(colors.HexColor("#71817c"))
        canvas.drawString(
            17 * mm, 12 * mm, f"Gestão de Garrafas · MOV-{snapshot['id']} · Documento histórico"
        )
        canvas.drawRightString(193 * mm, 12 * mm, f"Página {doc.page}")
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()


def create_confirmation_documents(movement, *, actor, signature=None):
    if signature:
        store_document(movement, kind="signature", payload=signature)
    if movement.kind in ("exit", "inventory") or movement.report_requested:
        snapshot = report_snapshot(movement, actor=actor)
        store_document(
            movement, kind="pdf", payload=render_pdf(snapshot, signature), metadata=snapshot
        )
