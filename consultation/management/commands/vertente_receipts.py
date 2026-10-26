
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.utils.dateparse import parse_datetime

from consultation.exports import recovery_receipts
from consultation.private_files import output_path, write_json


class Command(BaseCommand):
    help = "Recupera uma janela completa de Entradas confirmadas, assinada e sem stock/pessoas."

    def add_arguments(self, parser):
        parser.add_argument("--from", dest="start", required=True)
        parser.add_argument("--until", required=True)
        parser.add_argument("--output", required=True)

    def handle(self, *args, **options):
        try:
            start, end = parse_datetime(options["start"]), parse_datetime(options["until"])
            if not start or not end:
                raise ValueError("Instantes ISO 8601 obrigatórios.")
            output = output_path(options["output"])
            data = recovery_receipts(start=start, end=end)
            write_json(output, data)
        except (ValidationError, ValueError, OSError) as error:
            raise CommandError(str(error)) from error
        self.stdout.write(
            "Janela completa criada. Pode sobrepor janelas: os IDs impedem duplicações. Se exceder o limite, divida o período; não descarte Entradas."
        )
