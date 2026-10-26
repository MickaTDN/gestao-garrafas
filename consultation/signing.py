"""P-256 signed full snapshots. The private key never enters an exported file."""

import base64
import hashlib
import json
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from django.core.exceptions import ValidationError


def b64(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def public_key(key):
    der = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return {"key_id": hashlib.sha256(der).hexdigest(), "spki": b64(der)}


def read_key(path):
    try:
        key = serialization.load_pem_private_key(Path(path).read_bytes(), password=None)
        if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(
            key.curve, ec.SECP256R1
        ):
            raise ValueError
        return key
    except (OSError, ValueError, TypeError) as error:
        raise ValidationError(
            "A assinatura de exportações não está configurada. Contacte a informática."
        ) from error


def signed_snapshot(payload, key, *, kind="vertente-stock", version=2):
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    context = f"{kind}-v{version}\0".encode()
    r, s = decode_dss_signature(key.sign(context + data, ec.ECDSA(hashes.SHA256())))
    return {
        "format": kind,
        "version": version,
        "algorithm": "ES256",
        "key_id": public_key(key)["key_id"],
        "payload": b64(data),
        "signature": b64(r.to_bytes(32, "big") + s.to_bytes(32, "big")),
    }
