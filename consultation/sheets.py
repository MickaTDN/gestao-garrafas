"""RFC7516 JWE and the existing Stage B ES256 envelope. No stock writes."""

import base64
import hashlib
import json
import uuid
from datetime import date
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from jwcrypto import jwe, jwk

from accounts.permissions import require_access
from inventory.models import AuditEvent, Reference

from .models import AuthorizedDevice, ExportSource, PendingSheet, SheetReceipt

MAX_BYTES = 1024 * 1024
ALGORITHMS = ["RSA-OAEP-256", "A256GCM"]


def strict_json(raw):
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate field")
            result[key] = value
        return result

    return json.loads(
        raw, object_pairs_hook=unique, parse_constant=lambda _: (_ for _ in ()).throw(ValueError())
    )


def key_path():
    configured = settings.VERTENTE_SIGNING_KEY_FILE
    if not configured:
        raise ValidationError("Receção não configurada pela informática.")
    return Path(configured).parent / "pending-reception.pem"


def integer(value, minimum=0):
    if type(value) is not int or not minimum <= value <= 2147483647:
        raise ValueError("integer")


def text(value, maximum):
    if not isinstance(value, str) or len(value) > maximum or "\x00" in value:
        raise ValueError("text")
    value.encode("utf-8")  # Reject unpaired JSON surrogate escapes before persistence.


def canonical_uuid(value):
    if str(uuid.UUID(value)) != value:
        raise ValueError("uuid")


def decode(raw):
    try:
        if not isinstance(raw, bytes) or not 1 <= len(raw) <= MAX_BYTES:
            raise ValueError
        key = jwk.JWK.from_pem(key_path().read_bytes())
        outer = strict_json(raw)
        if (
            set(outer) != {"format", "version", "jwe"}
            or outer["format"] != "vertente-pending-sheet"
            or type(outer["version"]) is not int
            or outer["version"] not in (1, 2)
        ):
            raise ValueError
        parts = outer["jwe"].split(".")
        if len(parts) != 5:
            raise ValueError
        protected = strict_json(base64.urlsafe_b64decode(parts[0] + "=="))
        if protected != {"alg": "RSA-OAEP-256", "enc": "A256GCM", "kid": key.thumbprint()}:
            raise ValueError
        message = jwe.JWE(algs=ALGORITHMS)
        message.deserialize(outer["jwe"], key=key)
        signed = strict_json(message.payload)
        if (
            set(signed) != {"format", "version", "algorithm", "key_id", "payload", "signature"}
            or signed["format"] != "vertente-sheet"
            or type(signed["version"]) is not int
            or signed["version"] != outer["version"]
            or signed["algorithm"] != "ES256"
        ):
            raise ValueError
        data = base64.urlsafe_b64decode(signed["payload"] + "==")
        payload = strict_json(data)
        if set(payload) != {
            "source_id",
            "device_id",
            "authorization_revision",
            "sheet_id",
            "revision",
            "kind",
            "physical_date",
            "person",
            "notes",
            "lines",
        }:
            raise ValueError
        for field in ("source_id", "device_id", "sheet_id"):
            canonical_uuid(payload[field])
        integer(payload["revision"], 1)
        integer(payload["authorization_revision"], 1)
        if (
            payload["kind"] not in ("entry", "exit")
            or date.fromisoformat(payload["physical_date"]).isoformat() != payload["physical_date"]
        ):
            raise ValueError
        text(payload["person"], 200)
        if not payload["person"].strip():
            raise ValueError
        text(payload["notes"], 4000)
        if not isinstance(payload["lines"], list) or not 1 <= len(payload["lines"]) <= 500:
            raise ValueError
        seen = set()
        for line in payload["lines"]:
            is_proposal = "proposal" in line
            if set(line) != {"reference_id", "boxes", "units", "box_capacity"} | (
                {"proposal"} if is_proposal else set()
            ):
                raise ValueError
            if is_proposal:
                from inventory.proposals import validate_line

                if outer["version"] != 2 or payload["kind"] != "entry":
                    raise ValueError
                validate_line(line)
            elif line.get("reference_id", "").startswith("proposal:"):
                raise ValueError
            text(line["reference_id"], 100)
            if not line["reference_id"] or line["reference_id"] in seen:
                raise ValueError
            seen.add(line["reference_id"])
            for field in ("boxes", "units"):
                if line[field] is not None:
                    integer(line[field])
            if line["box_capacity"] is not None:
                integer(line["box_capacity"], 1)
            if line["boxes"] and line["box_capacity"] is None:
                raise ValueError
            total = (line["boxes"] or 0) * (line["box_capacity"] or 0) + (line["units"] or 0)
            integer(total, 1)
        return signed, data, payload
    except Exception as error:
        raise ValidationError(
            "Ficheiro inválido, incompatível, alterado ou chave de receção indisponível."
        ) from error


@transaction.atomic
def _receive_sheet(raw, *, actor, principal=None):
    _authorize_receiver(actor, principal)
    signed, data, payload = decode(raw)
    source = ExportSource.objects.select_for_update().filter(pk=1).first()
    device = (
        AuthorizedDevice.objects.select_for_update().filter(device_id=payload["device_id"]).first()
    )
    if (
        not source
        or str(source.source_id) != payload["source_id"]
        or not device
        or not device.sheets_allowed
        or device.revoked_at
        or not device.expires_at
        or device.expires_at <= timezone.now()
        or device.revision != payload["authorization_revision"]
        or not device.public_spki
        or (principal is not None and str(device.pk) != principal.device_id)
        or signed["key_id"] != device.public_key_id
    ):
        raise ValidationError(
            "Origem ou autorização do dispositivo inválida, expirada ou revogada."
        )
    try:
        der = base64.urlsafe_b64decode(device.public_spki + "==")
        if hashlib.sha256(der).hexdigest() != device.public_key_id:
            raise ValueError
        key = serialization.load_der_public_key(der)
        if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(
            key.curve, ec.SECP256R1
        ):
            raise ValueError
        sig = base64.urlsafe_b64decode(signed["signature"] + "==")
        if len(sig) != 64:
            raise ValueError
        key.verify(
            encode_dss_signature(int.from_bytes(sig[:32]), int.from_bytes(sig[32:])),
            f"vertente-sheet-v{signed['version']}\0".encode() + data,
            ec.ECDSA(hashes.SHA256()),
        )
    except Exception as error:
        raise ValidationError("Assinatura do dispositivo inválida.") from error
    content_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    sheet = PendingSheet.objects.filter(
        source_id=source.source_id, sheet_id=payload["sheet_id"]
    ).first()
    if sheet:
        outcome = "duplicate" if sheet.content_sha256 == content_hash else "conflict"
    else:
        sheet = PendingSheet.objects.create(
            source_id=source.source_id,
            sheet_id=payload["sheet_id"],
            device=device,
            revision=payload["revision"],
            content_sha256=content_hash,
            payload=payload,
        )
        outcome = "pending"
    receipt = SheetReceipt.objects.create(
        sheet=sheet,
        actor=actor,
        original=raw,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        outcome=outcome,
        authorization={
            "revision": device.revision,
            "role": device.role,
            "public_spki": device.public_spki,
            "public_key_id": device.public_key_id,
            "expires_at": device.expires_at.isoformat(),
            "sheets_allowed": True,
            "device_id": str(device.pk),
            "sheet_revision": payload["revision"],
            "transport": "wifi" if principal else "file",
            "certificate_sha256": principal.certificate_sha256 if principal else None,
        },
    )
    AuditEvent.objects.create(
        actor=actor,
        action="sheets." + outcome,
        details={
            "receipt_id": str(receipt.pk),
            "sheet_id": str(sheet.sheet_id),
            "file_sha256": receipt.file_sha256,
            "device_id": str(device.pk),
        },
    )
    return receipt


def _authorize_receiver(actor, principal):
    if principal is None:
        require_access(actor, "admin")
    else:
        from accounts.permissions import authorization_lock

        from .transport import DevicePrincipal

        if not isinstance(principal, DevicePrincipal) or actor is not None:
            raise PermissionDenied("Identidade de transporte inválida.")
        authorization_lock()


def receive_sheet(raw, *, actor=None, principal=None):
    _authorize_receiver(actor, principal)
    try:
        return _receive_sheet(raw, actor=actor, principal=principal)
    except ValidationError:
        with transaction.atomic():
            _authorize_receiver(actor, principal)
            AuditEvent.objects.create(
                actor=actor,
                action="sheets.rejected_file",
                details={
                    "file_sha256": hashlib.sha256(raw).hexdigest()
                    if isinstance(raw, bytes)
                    else None
                },
            )
        raise


@transaction.atomic
def revoke_device(device_id, *, actor):
    require_access(actor, "admin")
    device = AuthorizedDevice.objects.select_for_update().get(pk=device_id)
    device.revoked_at = timezone.now()
    device.save(update_fields=["revoked_at"])
    AuditEvent.objects.create(
        actor=actor, action="sheets.device_revoked", details={"device_id": str(device.pk)}
    )


def reference_warnings(sheet):
    known = {
        str(ref.pk): ref
        for ref in Reference.objects.filter(
            pk__in=[
                int(line["reference_id"])
                for line in sheet.payload["lines"]
                if line["reference_id"].isascii()
                and line["reference_id"].isdigit()
                and 0 < int(line["reference_id"]) <= 9223372036854775807
            ]
        )
    }
    result = []
    for line in sheet.payload["lines"]:
        ref = known.get(line["reference_id"])
        reason = (
            "Referência desconhecida"
            if ref is None
            else "Referência inativa"
            if not ref.active
            else "Capacidade alterada"
            if ref.box_capacity != line["box_capacity"]
            else None
        )
        if reason:
            result.append({"reference_id": line["reference_id"], "reason": reason})
    return result
