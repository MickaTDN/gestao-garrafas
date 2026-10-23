"""Provision a named user; password comes from a terminal or an injected variable."""

import getpass
import os

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from accounts.models import User


class Command(BaseCommand):
    help = "Cria um utilizador sem password predefinida nem registo público."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--role", choices=User.Role.values, default=User.Role.VIEWER)
        parser.add_argument("--password-env", help="Nome da variável injetada com a password.")

    def handle(self, *args, **options):
        if User.objects.filter(username=options["username"]).exists():
            raise CommandError("O utilizador já existe; nenhuma alteração efetuada.")
        if options["password_env"]:
            password = os.getenv(options["password_env"], "")
        else:
            password = getpass.getpass("Password (mínimo 12 caracteres): ")
            if password != getpass.getpass("Confirmar password: "):
                raise CommandError("As passwords não coincidem.")
        user = User(username=options["username"], role=options["role"])
        try:
            validate_password(password, user)
        except ValidationError as exc:
            raise CommandError(" ".join(exc.messages)) from exc
        user.set_password(password)
        user.save()
        self.stdout.write(self.style.SUCCESS("Utilizador criado."))
