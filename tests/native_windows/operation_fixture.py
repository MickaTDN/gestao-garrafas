"""Executed by the installed Django shell ONLY in the new synthetic native DB."""

import base64
import io

from django.conf import settings
from PIL import Image, ImageDraw

from accounts.models import User
from inventory import operations
from inventory.models import ImportBatch, Reference
from inventory.services import confirm_movement

if settings.DATABASES["default"]["NAME"] != "gva_native_synthetic" or ImportBatch.objects.exists():
    raise RuntimeError("Synthetic native fixture refuses another database")
actor = User.objects.get(username="synthetic-ci-admin")
ref = Reference.objects.get(code="SYN-C-1")
image = Image.new("RGB", (600, 200), "white")
ImageDraw.Draw(image).line(
    [(20, 120), (80, 35), (135, 140), (190, 50), (250, 125), (330, 80), (460, 115)],
    fill="black",
    width=4,
)
output = io.BytesIO()
image.save(output, format="PNG")
signature = "data:image/png;base64," + base64.b64encode(output.getvalue()).decode()
for kind in ("entry", "exit"):
    draft = operations.create_draft(actor=actor, kind=kind, references=[ref])
    line = draft.lines.get()
    draft = operations.save_draft(
        draft.pk,
        actor=actor,
        revision=0,
        header={"person_name": "Pessoa exclusivamente fictícia"},
        rows=[
            {
                "id": line.pk,
                "boxes": None,
                "units": 2,
                "reason": "",
                "target_location": ref.location,
            }
        ],
    )
    reviewed, _ = operations.review_draft(draft.pk, actor=actor, revision=draft.revision)
    confirm_movement(
        draft.pk,
        actor=actor,
        review_token=reviewed.review_token,
        report_requested=True,
        validation="signed" if kind == "exit" else None,
        signature_data=signature if kind == "exit" else None,
    )
