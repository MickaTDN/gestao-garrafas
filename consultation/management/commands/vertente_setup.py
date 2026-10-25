import json
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from consultation.models import ExportSource
from consultation.signing import public_key


class Command(BaseCommand):
    help = "Prepara identidade e uma NOVA chave de exportação, sem tocar no stock."

    def add_arguments(self, parser):
        parser.add_argument("--directory", required=True)

    def handle(self, *args, **options):
        configured = Path(options["directory"]).expanduser()
        root = configured.resolve()
        if not configured.is_absolute() or root.is_relative_to(Path(settings.BASE_DIR).resolve()):
            raise CommandError("Use um diretório privado absoluto fora do código.")
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        paths = [root / "signing.pem", root / "origin.vatrust.json"]
        if any(path.exists() for path in paths):
            raise CommandError(
                "Não se substituem chaves/ficheiros existentes. Para rotação use outro diretório."
            )
        key = ec.generate_private_key(ec.SECP256R1())
        created = []
        try:
            with transaction.atomic():
                source, _ = ExportSource.objects.get_or_create(pk=1)
                trust = {
                    "format": "vertente-trust",
                    "version": 1,
                    "source_id": str(source.source_id),
                    "keys": [public_key(key)],
                }
                values = [
                    key.private_bytes(
                        serialization.Encoding.PEM,
                        serialization.PrivateFormat.PKCS8,
                        serialization.NoEncryption(),
                    ),
                    json.dumps(trust).encode(),
                ]
                for path, value in zip(paths, values, strict=True):
                    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    created.append(path)
                    with os.fdopen(fd, "wb") as stream:
                        stream.write(value)
        except Exception:
            for path in created:
                path.unlink(missing_ok=True)
            raise
        self.stdout.write("Origem: " + str(source.source_id))
        self.stdout.write("Fingerprint SHA-256: " + trust["keys"][0]["key_id"])
        self.stdout.write(
            "Chave privada apenas no escritório. Transfira só origin.vatrust.json e confirme o fingerprint por canal independente."
        )
