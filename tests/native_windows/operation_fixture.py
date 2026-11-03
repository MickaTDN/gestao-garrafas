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


def pending_fixture():
    import json
    import uuid
    from datetime import timedelta

    from cryptography.hazmat.primitives.asymmetric import ec
    from django.utils import timezone
    from jwcrypto import jwe, jwk

    from consultation.models import AuthorizedDevice, ExportSource
    from consultation.review import confirm_sheet, correct_sheet, review_sheet
    from consultation.sheets import key_path, receive_sheet
    from consultation.signing import public_key, signed_snapshot

    key = ec.generate_private_key(ec.SECP256R1())
    public = public_key(key)
    device = AuthorizedDevice.objects.create(
        device_id=uuid.uuid4(),
        public_key_id=public["key_id"],
        public_spki=public["spki"],
        role="employee",
        revision=1,
        sheets_allowed=True,
        expires_at=timezone.now() + timedelta(days=1),
    )
    source = ExportSource.objects.get(pk=1)
    payload = {
        "source_id": str(source.source_id),
        "device_id": str(device.pk),
        "authorization_revision": 1,
        "sheet_id": str(uuid.uuid4()),
        "revision": 1,
        "kind": "entry",
        "physical_date": "2026-01-02",
        "person": "Pessoa fictícia pendente",
        "notes": "Folha de ensaio sem efeito no stock",
        "lines": [{"reference_id": str(ref.pk), "boxes": 1, "units": 2, "box_capacity": 6}],
    }
    signed = signed_snapshot(payload, key, kind="vertente-sheet", version=1)
    recipient = jwk.JWK.from_pem(key_path().read_bytes())
    envelope = jwe.JWE(
        json.dumps(signed).encode(),
        protected={"alg": "RSA-OAEP-256", "enc": "A256GCM", "kid": recipient.thumbprint()},
        recipient=recipient.public(),
    )
    raw = json.dumps(
        {"format": "vertente-pending-sheet", "version": 1, "jwe": envelope.serialize(compact=True)}
    ).encode()
    receipt = receive_sheet(raw, actor=actor)
    assert receipt.outcome == "pending"
    assert receive_sheet(raw, actor=actor).outcome == "duplicate"
    # Confirm a pending entry and exit through the same reviewed production services.
    # Net zero preserves the pre-existing native smoke balance while exercising
    # numbering without entry PDF, mandatory signed exit PDF and recovery evidence.
    for kind in ("entry", "exit"):
        payload = {
            **payload,
            "sheet_id": str(uuid.uuid4()),
            "kind": kind,
            "lines": [
                {
                    "reference_id": str(ref.pk),
                    "boxes": None,
                    "units": 1,
                    "box_capacity": ref.box_capacity,
                }
            ],
        }
        signed = signed_snapshot(payload, key, kind="vertente-sheet", version=1)
        envelope = jwe.JWE(
            json.dumps(signed).encode(),
            protected={"alg": "RSA-OAEP-256", "enc": "A256GCM", "kid": recipient.thumbprint()},
            recipient=recipient.public(),
        )
        wire = json.dumps(
            {
                "format": "vertente-pending-sheet",
                "version": 1,
                "jwe": envelope.serialize(compact=True),
            }
        ).encode()
        sheet = receive_sheet(wire, actor=actor).sheet
        sequence = 0
        if kind == "entry":
            values = {k: payload[k] for k in ("person", "physical_date", "notes", "lines")}
            values["person"] = "Pessoa sintética conferida no Windows"
            sequence = correct_sheet(
                sheet.pk,
                actor=actor,
                sequence=0,
                values=values,
                reason="Correção de ensaio auditada",
            ).sequence
        review, _ = review_sheet(sheet.pk, actor=actor, sequence=sequence)
        result = confirm_sheet(
            sheet.pk,
            actor=actor,
            sequence=review.sequence,
            token=review.data["token"],
            confirmed=True,
            report_requested=False,
            validation="signed" if kind == "exit" else None,
            signature_data=signature if kind == "exit" else None,
        )
        assert result.status == "confirmed"
        assert (
            confirm_sheet(
                sheet.pk,
                actor=actor,
                sequence=review.sequence,
                token=review.data["token"],
                confirmed=True,
                report_requested=False,
            ).pk
            == result.pk
        )

    # Version-two proposal: receipt creates nothing; approval/confirmation creates
    # the real identity. A compensating ordinary exit keeps the synthetic sum 33.
    proposal_id = "proposal:" + str(uuid.uuid4())
    proposed = {
        **payload,
        "sheet_id": str(uuid.uuid4()),
        "kind": "entry",
        "lines": [
            {
                "reference_id": proposal_id,
                "proposal": {"name": "Nova referência sintética portátil"},
                "boxes": None,
                "units": 1,
                "box_capacity": 6,
            }
        ],
    }

    def packet(value, version):
        signed = signed_snapshot(value, key, kind="vertente-sheet", version=version)
        encrypted = jwe.JWE(
            json.dumps(signed).encode(),
            protected={"alg": "RSA-OAEP-256", "enc": "A256GCM", "kid": recipient.thumbprint()},
            recipient=recipient.public(),
        )
        return json.dumps(
            {
                "format": "vertente-pending-sheet",
                "version": version,
                "jwe": encrypted.serialize(compact=True),
            }
        ).encode()

    wire = packet(proposed, 2)
    sheet = receive_sheet(wire, actor=actor).sheet
    assert not Reference.objects.filter(name="Nova referência sintética portátil").exists()
    values = {k: proposed[k] for k in ("person", "physical_date", "notes", "lines")}
    values["lines"] = [
        {
            **proposed["lines"][0],
            "proposal": {
                "name": "Nova referência sintética portátil",
                "location_id": ref.location_id,
                "sector_id": None,
            },
        }
    ]
    corrected = correct_sheet(
        sheet.pk, actor=actor, sequence=0, values=values, reason="Proposta conferida no Windows"
    )
    review, _ = review_sheet(sheet.pk, actor=actor, sequence=corrected.sequence)
    official = confirm_sheet(
        sheet.pk,
        actor=actor,
        sequence=review.sequence,
        token=review.data["token"],
        confirmed=True,
        report_requested=True,
    )
    assert receive_sheet(wire, actor=actor).outcome == "duplicate"
    created = Reference.objects.get(
        pk=official.source_metadata["proposal_reference_ids"][proposal_id]
    )
    assert created.current_stock == 1 and created.code.startswith("GAR-")
    outgoing = {
        **proposed,
        "sheet_id": str(uuid.uuid4()),
        "kind": "exit",
        "lines": [{"reference_id": str(created.pk), "boxes": None, "units": 1, "box_capacity": 6}],
    }
    sheet = receive_sheet(packet(outgoing, 1), actor=actor).sheet
    review, _ = review_sheet(sheet.pk, actor=actor, sequence=0)
    confirm_sheet(
        sheet.pk,
        actor=actor,
        sequence=review.sequence,
        token=review.data["token"],
        confirmed=True,
        validation="signed",
        signature_data=signature,
    )
    created.refresh_from_db()
    assert created.current_stock == 0

    # An unfinished direct-entry proposal is persistent too, without a catalogue row.
    from inventory.proposals import add_to_entry

    draft = operations.create_draft(actor=actor, kind="entry")
    add_to_entry(
        draft.pk,
        actor=actor,
        revision=0,
        data={
            "name": "Proposta direta por aprovar",
            "box_capacity": None,
            "boxes": None,
            "units": 3,
            "location": ref.location,
        },
    )
    assert not Reference.objects.filter(name="Proposta direta por aprovar").exists()


pending_fixture()
