from uuid import UUID

from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from imports.management.commands.inspect_stock_excel import private_report_path
from imports.reconciliation import publish_preview
from imports.reports import write_private_report


class Command(BaseCommand):
    help = "Publica apenas uma prévia previamente revista, com confirmação explícita do seu token."

    def add_arguments(self, parser):
        parser.add_argument("preview_id", type=UUID)
        parser.add_argument("--actor", required=True)
        parser.add_argument("--confirmation", type=UUID, required=True,
                            help="Token da prévia privada que foi revista.")
        parser.add_argument("--report", required=True)

    def handle(self, *args, **options):
        destination = private_report_path(options["report"])
        try:
            actor = get_user_model().objects.get(username=options["actor"])
            with transaction.atomic():
                result = publish_preview(options["preview_id"], actor=actor,
                                         confirmation_token=options["confirmation"])
                write_private_report(destination, {"kind": "publication_validation", **result})
        except (ObjectDoesNotExist, PermissionDenied, ValidationError, OSError,
                ValueError, TypeError) as exc:
            raise CommandError("Publicação recusada. Verifique a conta, a confirmação, "
                               "a validade da prévia e o destino privado.") from exc
        self.stdout.write(self.style.SUCCESS("Publicação validada. Relatório privado guardado."))
