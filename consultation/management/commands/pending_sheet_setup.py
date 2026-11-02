import json
import os
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from jwcrypto import jwk

from consultation.models import ExportSource
from consultation.sheets import key_path
from consultation.signing import read_key, signed_snapshot


class Command(BaseCommand):
    help = "Prepara uma chave RSA de receção separada e a chave pública autenticada pela origem."

    def handle(self, *args, **options):
        path = key_path()
        if (
            not path.is_absolute()
            or path.is_relative_to(Path(settings.BASE_DIR).resolve())
            or path.is_symlink()
        ):
            raise CommandError("Use o diretório privado de assinatura, fora do código.")
        public = path.with_suffix(".public.json")
        if path.exists() or public.exists():
            raise CommandError("Não se substituem chaves existentes; conserve-as com os backups.")
        source = ExportSource.objects.get(pk=1)
        signing = read_key(settings.VERTENTE_SIGNING_KEY_FILE)
        key = jwk.JWK.generate(kty="RSA", size=3072)
        payload = {
            "source_id": str(source.source_id),
            "jwk": json.loads(key.export_public()),
            "key_id": key.thumbprint(),
        }
        # Existing signed Stage B envelope; no new trust root or private key export.
        signed = signed_snapshot(payload, signing, kind="vertente-sheet-recipient", version=1)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as out:
            out.write(key.export_to_pem(private_key=True, password=None))
        with public.open("x") as out:
            json.dump(signed, out)
        self.stdout.write(
            "Chave de receção preparada. Distribua apenas o ficheiro público assinado."
        )
