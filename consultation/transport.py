"""Device transport only. No operational permissions or administrator impersonation."""

import re
import uuid
from dataclasses import dataclass

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction

from inventory.models import AuditEvent

from .exports import instant
from .signing import read_key, signed_snapshot


@dataclass(frozen=True)
class DevicePrincipal:
    device_id: str
    certificate_sha256: str

    def __post_init__(self):
        if str(uuid.UUID(self.device_id)) != self.device_id or not re.fullmatch(
            r"[a-f0-9]{64}", self.certificate_sha256
        ):
            raise ValueError("Invalid device principal")


@transaction.atomic
def _accept(raw, principal, request_id):
    from .sheets import receive_sheet

    if str(uuid.UUID(request_id)) != request_id:
        raise ValidationError("Identificador da tentativa inválido.")
    receipt = receive_sheet(raw, principal=principal)
    # A conflicting upload can belong to another authorized device; bind the ACK
    # to the actual sender and file, never the first sheet's mutable device row.
    data = {
        "source_id": str(receipt.sheet.source_id),
        "device_id": principal.device_id,
        "sheet_id": str(receipt.sheet.sheet_id),
        "revision": receipt.authorization["sheet_revision"],
        "file_sha256": receipt.file_sha256,
        "receipt_id": str(receipt.pk),
        "outcome": receipt.outcome,
        "received_at": instant(receipt.created_at),
        "request_id": request_id,
    }
    # Failure signing rolls back reception too. No ACK before the outer commit.
    return signed_snapshot(
        data, read_key(settings.VERTENTE_SIGNING_KEY_FILE), kind="vertente-sheet-receipt", version=1
    )


def accept_upload(raw, *, principal, request_id):
    try:
        return _accept(raw, principal, request_id)
    except Exception as error:
        # No body, people, certificate PEM, signatures or credentials in diagnostics.
        AuditEvent.objects.create(
            action="sheets.transport_failed",
            details={
                "device_id": principal.device_id,
                "category": type(error).__name__,
            },
        )
        raise
