"""Synthetic operation helpers, never copied from the workbook."""

import base64
import io

from PIL import Image, ImageDraw

from inventory import operations
from inventory.services import confirm_movement


def signature_png(*, blank=False, size=(600, 200)):
    image = Image.new("RGB", size, "white")
    if not blank:
        draw = ImageDraw.Draw(image)
        draw.line(
            [(25, 120), (80, 35), (130, 140), (185, 50), (240, 125), (330, 80), (450, 115)],
            fill="black",
            width=4,
        )
    output = io.BytesIO()
    image.save(output, format="PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode()


def confirmed_operation(
    actor, reference, *, kind="exit", units=2, report=False, signed=False, location=None
):
    draft = operations.create_draft(actor=actor, kind=kind, references=[reference])
    line = draft.lines.get()
    draft = operations.save_draft(
        draft.pk,
        actor=actor,
        revision=0,
        header={"person_name": "Pessoa documental sintética"},
        rows=[
            {
                "id": line.pk,
                "boxes": None,
                "units": units,
                "reason": "Contagem documental sintética",
                "target_location": location or reference.location,
            }
        ],
    )
    reviewed, _ = operations.review_draft(draft.pk, actor=actor, revision=draft.revision)
    return confirm_movement(
        draft.pk,
        actor=actor,
        review_token=reviewed.review_token,
        report_requested=report,
        validation="signed" if signed else "simple" if kind == "exit" else None,
        signature_data=signature_png() if signed else None,
    )
