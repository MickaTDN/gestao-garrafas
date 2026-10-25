"""Version 3 PDF renderer. Preserve this version for byte-identical reproductions."""

import base64
import hashlib
import io
import json
from datetime import date, datetime
from pathlib import Path
from xml.sax.saxutils import escape

import reportlab
from django.core.exceptions import ValidationError
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image as PDFImage
from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from web.branding import APP_NAME, LOGO, original_asset

from .presentation import entered_quantity, stock_quantity


def rendering_assets():
    fonts = Path(reportlab.__file__).parent / "fonts"
    logo = original_asset(LOGO)
    return {
        "reportlab": reportlab.Version,
        "app_name": APP_NAME,
        "company_name": "Vertente Aveludada",
        "layout": 3,
        "renderer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "regular": base64.b64encode((fonts / "Vera.ttf").read_bytes()).decode(),
        "bold": base64.b64encode((fonts / "VeraBd.ttf").read_bytes()).decode(),
        "logo": base64.b64encode(logo.read_bytes()).decode() if logo else None,
    }


def asset_key(assets):
    return hashlib.sha256(json.dumps(assets, sort_keys=True).encode()).hexdigest()


def render_pdf(snapshot, signature=None):
    """A4 report generated once from immutable confirmation snapshots."""
    if snapshot.get("template_key"):
        from .models import ReportTemplate

        assets = ReportTemplate.objects.get(pk=snapshot["template_key"]).assets
    else:
        assets = rendering_assets()
    if assets["reportlab"] != reportlab.Version:
        raise ValidationError(
            "A reprodução fiel exige a versão original do motor PDF. Conserve o exemplar existente."
        )
    app_name = assets.get("app_name", APP_NAME)
    key = asset_key(assets)
    regular, bold = "GG-" + key, "GG-Bold-" + key
    if regular not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(regular, io.BytesIO(base64.b64decode(assets["regular"]))))
        pdfmetrics.registerFont(TTFont(bold, io.BytesIO(base64.b64decode(assets["bold"]))))
    number = snapshot.get("report_number") or f"MOV-{snapshot['id']}"
    modern = snapshot["kind"] in ("entry", "exit")
    body = ParagraphStyle(
        "GGBody", fontName=regular, fontSize=8, leading=12, alignment=TA_LEFT, spaceAfter=5
    )
    title = ParagraphStyle(
        "GGTitle",
        parent=body,
        fontName=bold,
        fontSize=19,
        leading=24,
        textColor=colors.HexColor("#126650"),
    )
    header = ParagraphStyle(
        "GGHeader", parent=body, fontName=bold, fontSize=7, leading=10, textColor=colors.white
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
        title=f"{app_name} · {number}",
        author=app_name,
        invariant=1,
    )
    story = [
        p(f"{snapshot['label']} · {number}", title),
        p(
            f"Data: {date.fromisoformat(snapshot['date']).strftime('%d/%m/%Y')}"
            if modern
            else f"Data: {date.fromisoformat(snapshot['date']).strftime('%d/%m/%Y')} · Confirmado: {datetime.fromisoformat(snapshot['confirmed_at']).strftime('%d/%m/%Y %H:%M:%S %z')}"
        ),
        p(f"Responsável pela confirmação: {snapshot['responsible']}"),
        p(f"{'Cliente' if modern else 'Pessoa'}: {snapshot['person'] or 'Não aplicável'}"),
    ]
    image = ""
    if assets["logo"]:
        image = PDFImage(io.BytesIO(base64.b64decode(assets["logo"])))
        scale = min(65 * mm / image.imageWidth, 25 * mm / image.imageHeight)
        image.drawWidth, image.drawHeight = image.imageWidth * scale, image.imageHeight * scale
        image.hAlign = "LEFT"
    if modern:
        company = ParagraphStyle("Company", parent=title, alignment=TA_RIGHT, fontSize=16)
        heading = Table(
            [[image, p(assets.get("company_name", "Vertente Aveludada"), company)]],
            colWidths=[88 * mm, 88 * mm],
        )
        heading.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ]
            )
        )
        story[0:0] = [heading, Spacer(1, 5 * mm)]
    else:
        story[0:0] = ([image, Spacer(1, 4 * mm)] if image else []) + [p(app_name, title)]
    if snapshot["correction_of"]:
        story.append(
            p(f"Correção relacionada com MOV-{snapshot['correction_of']} · {snapshot['reason']}")
        )
    elif snapshot["reason"]:
        story.append(p(snapshot["reason"]))
    inventory = snapshot["kind"] == "inventory"
    if inventory:
        headings = [
            "Referência",
            "Caixas",
            "Soltas",
            "Contagem",
            "Stock antes",
            "Diferença",
            "Stock final",
        ]
        widths = [61, 14, 14, 20, 21, 22, 24]
    else:
        headings = [
            "Referência",
            "Quantidade movimentada",
            "Stock final",
        ]
        widths = [80, 48, 48]
    rows = [[p(label, header) for label in headings]]
    for line in snapshot["lines"]:
        if inventory:
            rows.append(
                [
                    p(line["name"]),
                    p(line["boxes"]),
                    p(line["units"]),
                    p(line["counted"]),
                    p(line["before"]),
                    p(line["quantity"]),
                    p(line["after"]),
                ]
            )
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
        else:
            rows.append(
                [
                    p(line["name"]),
                    p(
                        entered_quantity(
                            line["boxes"], line["units"], line["quantity"], line["capacity"]
                        )
                    ),
                    p(stock_quantity(line["after"], line["capacity"])),
                ]
            )
    table = LongTable(rows, colWidths=[width * mm for width in widths], repeatRows=1, hAlign="LEFT")
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
    for change in snapshot["changes"]:
        story.append(
            p(
                f"Transferência {change.get('name') or change['code']}: {change['before'].get('location')} / {change['before'].get('sector') or 'sem setor'} → {change['after'].get('location')} / {change['after'].get('sector') or 'sem setor'} · {change['reason']}"
            )
        )
    if signature:
        story.extend(
            [
                p("Validação com assinatura."),
                PDFImage(io.BytesIO(signature), width=90 * mm, height=30 * mm, kind="proportional"),
            ]
        )
    elif snapshot["kind"] == "exit":
        story.append(p("Validação: confirmação simples, sem assinatura."))
    if inventory:
        story.append(
            p(
                "Caixas e garrafas soltas preservam os valores introduzidos; — identifica informação não fornecida."
            )
        )

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(regular, 8)
        canvas.setFillColor(colors.HexColor("#71817c"))
        canvas.drawString(17 * mm, 12 * mm, f"{app_name} · {number} · Documento histórico")
        canvas.drawRightString(193 * mm, 12 * mm, f"Página {doc.page}")
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
