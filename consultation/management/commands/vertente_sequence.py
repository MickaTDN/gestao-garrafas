"""Explicit export-counter recovery AFTER official stock has been reconciled."""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from consultation.models import ExportSource
from inventory.models import AuditEvent


class Command(BaseCommand):
    help = "Recupera só a sequência de exportação, sem modificar stock; exige revisão prévia."

    def add_arguments(self, parser):
        parser.add_argument("--source", required=True)
        parser.add_argument("--after", required=True, type=int)
        parser.add_argument("--reason", required=True)
        parser.add_argument("--confirm-reconciled", action="store_true")

    def handle(self, *args, **options):
        target = options["after"]
        if (
            not options["confirm_reconciled"]
            or not 0 <= target < 9007199254740991
            or len(options["reason"].strip()) < 10
        ):
            raise CommandError("Exige confirmação de reconciliação, motivo e sequência válida.")
        with transaction.atomic():
            try:
                source = ExportSource.objects.select_for_update().get(pk=1)
            except ExportSource.DoesNotExist as error:
                raise CommandError("Recupere primeiro a identidade de origem correta.") from error
            if str(source.source_id) != options["source"] or target < source.sequence:
                raise CommandError(
                    "Origem incorreta ou tentativa de recuar a sequência. Não foi alterada."
                )
            old = source.sequence
            source.sequence = target
            source.save(update_fields=["sequence"])
            AuditEvent.objects.create(
                action="vertente.sequence_recovered",
                details={"before": old, "after": target, "reason": options["reason"].strip()},
            )
        self.stdout.write("Sequência recuperada. Não foi alterada qualquer quantidade de stock.")
