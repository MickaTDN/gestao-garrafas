import binascii
import json
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from consultation.devices import authorize_device
from consultation.private_files import output_path, write_json


class Command(BaseCommand):
    help = "Autoriza um dispositivo offline: executar apenas pela informática, com o papel de preparação da base."

    def add_arguments(self, parser):
        parser.add_argument("--request", required=True)
        parser.add_argument("--output", required=True)
        parser.add_argument("--role", choices=["owner", "employee"], required=True)
        parser.add_argument("--allow-import", action="store_true")
        parser.add_argument("--days", type=int, default=365)
        parser.add_argument("--confirmed-device-fingerprint", required=True)

    def handle(self, *args, **options):
        from consultation.devices import base64, hashlib

        try:
            path = Path(options["request"])
            if path.stat().st_size > 8192:
                raise ValueError("Pedido demasiado grande.")
            request = json.loads(path.read_text())
            fingerprint = hashlib.sha256(
                base64.urlsafe_b64decode(request["spki"] + "==")
            ).hexdigest()
            if options["confirmed_device_fingerprint"] != fingerprint:
                raise ValueError(
                    "O fingerprint tem de ser confirmado no próprio dispositivo por canal independente."
                )
            output = output_path(options["output"])
            envelope = authorize_device(
                request,
                role=options["role"],
                allow_import=options["allow_import"],
                days=options["days"],
            )
            write_json(output, envelope)
        except (ValidationError, ValueError, OSError, KeyError, TypeError, binascii.Error) as error:
            raise CommandError(str(error)) from error
        self.stdout.write(
            "Autorização criada. Transfira apenas este ficheiro para o dispositivo confirmado; nunca a chave privada da origem."
        )
