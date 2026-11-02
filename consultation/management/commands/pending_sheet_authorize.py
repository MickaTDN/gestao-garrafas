"""Separate signed capability; the Stage B consultation grant stays unchanged."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.permissions import authorization_lock
from consultation.exports import instant
from consultation.models import AuthorizedDevice, ExportSource
from consultation.private_files import output_path, write_json
from consultation.signing import read_key, signed_snapshot
from inventory.models import AuditEvent


class Command(BaseCommand):
    help = "Exporta a permissão de folhas de um dispositivo já autorizado explicitamente pela informática."

    def add_arguments(self, parser):
        parser.add_argument("--device", required=True)
        parser.add_argument("--output", required=True)

    @transaction.atomic
    def handle(self, *args, **options):
        authorization_lock()
        try:
            output = output_path(options["output"])
            device = AuthorizedDevice.objects.select_for_update().get(pk=options["device"])
            if (
                not device.sheets_allowed
                or device.revoked_at
                or not device.public_spki
                or not device.expires_at
                or device.expires_at <= timezone.now()
            ):
                raise ValueError(
                    "Dispositivo sem permissão de folhas válida; use a autorização presencial existente."
                )
            source = ExportSource.objects.get(pk=1)
            payload = {
                "source_id": str(source.source_id),
                "device_id": str(device.pk),
                "device_key_id": device.public_key_id,
                "authorization_revision": device.revision,
                "expires_at": instant(device.expires_at),
                "sheets_allowed": True,
            }
            envelope = signed_snapshot(
                payload,
                read_key(settings.VERTENTE_SIGNING_KEY_FILE),
                kind="vertente-sheet-authorization",
                version=1,
            )
            write_json(output, envelope)
            AuditEvent.objects.create(
                action="sheets.permission_exported",
                details={
                    "device_id": str(device.pk),
                    "revision": device.revision,
                },
            )
        except (ValidationError, ValueError, OSError, AuthorizedDevice.DoesNotExist) as error:
            raise CommandError(
                "Não foi possível exportar a permissão; verifique dispositivo, validade e destino privado."
            ) from error
        self.stdout.write("Permissão assinada preparada, sem chaves privadas.")
