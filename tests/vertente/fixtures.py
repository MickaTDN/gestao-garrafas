import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from cryptography.hazmat.primitives.asymmetric import ec

from consultation.signing import public_key, signed_snapshot


def stamp(value=None):
    return (
        (value or datetime.now(timezone.utc))
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def fixture():
    key = ec.generate_private_key(ec.SECP256R1())
    return key, {
        "format": "vertente-trust",
        "version": 1,
        "source_id": str(uuid.uuid4()),
        "keys": [public_key(key)],
    }


def snapshot(key, trust, sequence=1, references=None, **changes):
    now = datetime.now(timezone.utc)
    payload = {
        "source_id": trust["source_id"],
        "sequence": sequence,
        "update_id": str(uuid.uuid4()),
        "exported_at": stamp(now),
        "coverage": {"from": stamp(now - timedelta(days=180)), "until": stamp(now)},
        "receipts": [],
        "references": references
        if references is not None
        else [
            {
                "id": "1",
                "name": "Água de Ensaio",
                "bottles": 18,
                "box_capacity": 6,
                "location": "Corredor Esquerdo",
                "sector": "Setor 2",
                "minimum": 24,
            },
            {
                "id": "2",
                "name": "Coração Zero",
                "bottles": 0,
                "box_capacity": None,
                "location": "Patamar Superior",
                "sector": None,
                "minimum": None,
            },
            {
                "id": "3",
                "name": "Tinto Fictício",
                "bottles": 30,
                "box_capacity": 12,
                "location": "Corredor Direito",
                "sector": "Setor 10",
                "minimum": 30,
            },
        ],
    }
    payload.update(changes)
    if "exported_at" in changes and "coverage" not in changes:
        payload["coverage"]["until"] = payload["exported_at"]
    return signed_snapshot(payload, key)


def grant(key, trust, request, *, role="owner", can_import=None, revision=1, now=None, days=365):
    import base64

    now = now or datetime.now(timezone.utc)
    payload = {
        "source_id": trust["source_id"],
        "device_id": request["device_id"],
        "device_key_id": hashlib.sha256(
            base64.urlsafe_b64decode(request["spki"] + "==")
        ).hexdigest(),
        "role": role,
        "can_import": role == "owner" if can_import is None else can_import,
        "revision": revision,
        "grant_id": str(uuid.uuid4()),
        "issued_at": stamp(now),
        "expires_at": stamp(now + timedelta(days=days)),
    }
    return signed_snapshot(payload, key, kind="vertente-device", version=1)


def receipt(
    id, *, reference_id="1", bottles=6, confirmed_at=None, boxes=None, units=None, capacity=6
):
    when = confirmed_at or datetime.now(timezone.utc)
    return {
        "id": str(id),
        "movement_id": str(id),
        "reference_id": reference_id,
        "name": "Água de Ensaio",
        "date": when.date().isoformat(),
        "confirmed_at": stamp(when),
        "bottles": bottles,
        "boxes": boxes,
        "units": bottles if units is None else units,
        "box_capacity": capacity,
    }
