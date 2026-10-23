import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from imports.management.commands.inspect_stock_excel import private_report_path
from imports.reconciliation import build_preview
from imports.reports import write_private_report


class Command(BaseCommand):
    help = "Cria uma pré-visualização reconciliada; não publica referências nem stock."

    def add_arguments(self, parser):
        parser.add_argument("batch_id", type=int)
        parser.add_argument("--decisions", type=Path, required=True)
        parser.add_argument("--actor", required=True, help="Conta administrativa existente.")
        parser.add_argument("--report", required=True, help="Caminho privado fora do Git.")

    def handle(self, *args, **options):
        destination = private_report_path(options["report"])
        try:
            actor = get_user_model().objects.get(username=options["actor"])
            decisions = json.loads(options["decisions"].read_text(encoding="utf-8"))
            with transaction.atomic():
                preview = build_preview(options["batch_id"], decisions, actor=actor)
                write_private_report(destination, {
                    "kind": "reconciliation_preview",
                    "published": False,
                    "preview_id": str(preview.pk),
                    "confirmation_token": str(preview.confirmation_token),
                    "reconciliation_digest": preview.reconciliation_digest,
                    "decisions": preview.decisions,
                    "summary": preview.summary,
                    "rows": preview.rows,
                })
        except (ObjectDoesNotExist, OSError, ValueError, TypeError,
                PermissionDenied, ValidationError) as exc:
            raise CommandError("Não foi possível preparar a prévia. Verifique a conta administrativa, "
                               "o lote, as decisões e o destino privado.") from exc
        self.stdout.write(
            f"Prévia {preview.pk}: {preview.summary['reference_count']} referências; "
            f"total {preview.summary['total_stock']} garrafas. Nenhum stock publicado."
        )
        if not preview.summary["ready"]:
            raise CommandError("A prévia contém impedimentos; consulte o relatório privado.")
