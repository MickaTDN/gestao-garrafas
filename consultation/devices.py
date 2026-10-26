"""Physical provisioning: signed, device-bound capabilities. No self-selected roles."""

import base64
import hashlib
import uuid
from datetime import timedelta

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from inventory.models import AuditEvent

from .exports import instant
from .models import AuthorizedDevice, ExportSource
from .signing import read_key, signed_snapshot


def authorize_device(request, *, role, allow_import=False, days=365):
    try:
        if (
            set(request) != {"format", "version", "device_id", "spki", "signature"}
            or request["format"] != "vertente-device-request"
            or request["version"] != 1
        ):
            raise ValueError
        device_id = str(uuid.UUID(request["device_id"]))
        if (
            device_id != request["device_id"]
            or role not in ["owner", "employee"]
            or not 1 <= days <= 365
        ):
            raise ValueError
        der = base64.urlsafe_b64decode(request["spki"] + "==")
        key = serialization.load_der_public_key(der)
        if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(
            key.curve, ec.SECP256R1
        ):
            raise ValueError
        signature = base64.urlsafe_b64decode(request["signature"] + "==")
        if len(signature) != 64:
            raise ValueError
        key.verify(
            encode_dss_signature(int.from_bytes(signature[:32]), int.from_bytes(signature[32:])),
            ("vertente-device-request-v1\0" + device_id).encode(),
            ec.ECDSA(hashes.SHA256()),
        )
    except Exception as error:
        raise ValidationError(
            "Pedido de dispositivo inválido. Confirme o fingerprint presencialmente."
        ) from error
    fingerprint = hashlib.sha256(der).hexdigest()
    signing = read_key(settings.VERTENTE_SIGNING_KEY_FILE)
    from accounts.permissions import authorization_lock

    with transaction.atomic():
        authorization_lock()
        source = ExportSource.objects.get(pk=1)
        device, _ = AuthorizedDevice.objects.select_for_update().get_or_create(
            device_id=device_id, defaults={"public_key_id": fingerprint, "role": role}
        )
        if device.public_key_id != fingerprint or device.role != role:
            raise ValidationError(
                "A identidade/perfil está fixado. Utilize outro perfil de navegador/dispositivo, sem misturar dados privados."
            )
        device.revision += 1
        device.save(update_fields=["revision"])
        now = timezone.now()
        payload = {
            "source_id": str(source.source_id),
            "device_id": device_id,
            "device_key_id": fingerprint,
            "role": role,
            "can_import": role == "owner" or bool(allow_import),
            "revision": device.revision,
            "grant_id": str(uuid.uuid4()),
            "issued_at": instant(now),
            "expires_at": instant(now + timedelta(days=days)),
        }
        envelope = signed_snapshot(payload, signing, kind="vertente-device", version=1)
        AuditEvent.objects.create(
            action="vertente.device_authorized",
            details={
                "device_id": device_id,
                "role": role,
                "revision": device.revision,
                "can_import": payload["can_import"],
            },
        )
        return envelope
