import uuid
from datetime import datetime, timezone

from cryptography.hazmat.primitives.asymmetric import ec

from consultation.signing import public_key, signed_snapshot


def fixture():
    key = ec.generate_private_key(ec.SECP256R1())
    source = str(uuid.uuid4())
    trust = {
        "format": "vertente-trust",
        "version": 1,
        "source_id": source,
        "keys": [public_key(key)],
    }
    return key, trust


def snapshot(key, trust, sequence=1, references=None, **changes):
    payload = {
        "source_id": trust["source_id"],
        "sequence": sequence,
        "update_id": str(uuid.uuid4()),
        "exported_at": datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z"),
        "references": references
        if references is not None
        else [
            {
                "id": "1",
                "code": "VA-001",
                "name": "Água de Ensaio",
                "bottles": 18,
                "box_capacity": 6,
            },
            {
                "id": "2",
                "code": "VA-002",
                "name": "Coração Zero",
                "bottles": 0,
                "box_capacity": None,
            },
            {
                "id": "3",
                "code": "VA-003",
                "name": "Tinto Fictício",
                "bottles": 30,
                "box_capacity": 12,
            },
        ],
    }
    payload.update(changes)
    return signed_snapshot(payload, key)
