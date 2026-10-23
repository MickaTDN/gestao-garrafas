"""Private, read-only reconciliation report and optional unpublished staging."""

import json
import os
from pathlib import Path
from zipfile import BadZipFile

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from openpyxl.utils.exceptions import InvalidFileException

from imports.excel import inspect_stock_workbook


def private_report_path(value):
    path = Path(value).expanduser().resolve()
    # Ignored directories inside a checkout still live in the repository tree.
    # Keep reports entirely outside every checkout, including linked worktrees.
    if path == settings.BASE_DIR or path.is_relative_to(settings.BASE_DIR):
        raise CommandError("O relatório deve ficar fora do repositório, numa pasta privada.")
    if any(
        (parent / ".git").is_file() or (parent / ".git" / "HEAD").is_file()
        for parent in (path.parent, *path.parents)
    ):
        raise CommandError("O relatório não pode ficar dentro de um checkout Git.")
    if path.exists():
        raise CommandError(
            "O relatório já existe; indique um novo caminho para preservar o anterior."
        )
    return path


class Command(BaseCommand):
    help = "Inspeciona Stock sem publicar dados. --stage guarda apenas um lote em análise."

    def add_arguments(self, parser):
        parser.add_argument("path", type=Path)
        parser.add_argument(
            "--report", required=True, help="JSON privado, fora de qualquer checkout Git."
        )
        parser.add_argument(
            "--stage", action="store_true", help="Guarda proveniência; não altera stock."
        )

    def handle(self, *args, **options):
        destination = private_report_path(options["report"])
        try:
            inspection = inspect_stock_workbook(options["path"])
        except (OSError, ValueError, BadZipFile, InvalidFileException) as exc:
            raise CommandError(
                "Não foi possível ler o Excel; confirme o caminho e o formato .xlsx."
            ) from exc
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(destination, flags, 0o600)
        except OSError as exc:
            raise CommandError(
                "Não foi possível criar um relatório privado sem sobrescrever ficheiros."
            ) from exc
        with os.fdopen(descriptor, "w", encoding="utf-8") as report:
            json.dump(inspection.as_report(), report, ensure_ascii=False, indent=2, allow_nan=False)
            report.write("\n")
        if options["stage"]:
            from inventory.models import ImportBatch, LegacyRow

            with transaction.atomic():
                batch, created = ImportBatch.objects.get_or_create(
                    sha256=inspection.sha256,
                    defaults={
                        "source_name": inspection.source_name[:250],
                        "status": ImportBatch.Status.STAGED,
                        "summary": {
                            **inspection.summary,
                            "source_headers": inspection.headers,
                        },
                    },
                )
                if created:
                    LegacyRow.objects.bulk_create(
                        [
                            LegacyRow(
                                import_batch=batch,
                                sheet="Stock",
                                row_number=row.row_number,
                                reference=None,
                                raw_data=row.raw_data,
                                opening_stock=row.opening_stock,
                                reported_stock=row.reported_stock,
                                reconciled_stock=row.reconciled_stock,
                            )
                            for row in inspection.rows
                        ]
                    )
            self.stdout.write(
                "Lote em análise criado." if created else "Lote já existente; sem duplicação."
            )
        summary = inspection.summary
        self.stdout.write(
            "Inspeção concluída: "
            f"{summary['references']} linhas; "
            f"{summary['errors']} erros; {summary['warnings']} avisos. "
            "Relatório privado criado. Nenhum saldo ou movimento publicado."
        )
        if summary["errors"]:
            raise CommandError(
                "Existem exceções no relatório; o lote exige reconciliação antes da importação."
            )
