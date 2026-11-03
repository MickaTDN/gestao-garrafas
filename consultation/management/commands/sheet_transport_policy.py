from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.permissions import authorization_lock
from consultation.models import ExportSource
from consultation.private_files import output_path, write_json
from consultation.signing import read_key, signed_snapshot
from inventory.models import AuditEvent
from native_windows.receiver_policy import origin


class Command(BaseCommand):
    help = (
        "Exporta a política pública assinada do transporte, sem ativar rede ou conceder permissões."
    )

    def add_arguments(self, parser):
        for name in ("receiver-origin", "stock-origin", "output"):
            parser.add_argument("--" + name, required=True)

    @transaction.atomic
    def handle(self, *args, **options):
        authorization_lock()
        target = output_path(options["output"])
        receiver, stock = origin(options["receiver_origin"]), origin(options["stock_origin"])
        if receiver == stock:
            from django.core.management.base import CommandError

            raise CommandError("Receção e publicador Stock exigem origens distintas.")
        data = {
            "source_id": str(ExportSource.objects.get(pk=1).source_id),
            "receiver_origin": receiver,
            "stock_origin": stock,
        }
        write_json(
            target,
            signed_snapshot(
                data,
                read_key(settings.VERTENTE_SIGNING_KEY_FILE),
                kind="vertente-sheet-transport",
                version=1,
            ),
        )
        AuditEvent.objects.create(action="sheets.transport_policy_exported", details=data)
        self.stdout.write(
            "Política pública assinada criada. A rede continua dependente de aprovação explícita."
        )
