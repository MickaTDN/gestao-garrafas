from django.core.management.base import BaseCommand

from inventory.backups import create_backup


class Command(BaseCommand):
    help = "Cria backup privado PostgreSQL + documentos, com integridade, retenção e cifragem configurável."
    def add_arguments(self, parser):
        parser.add_argument("--synthetic", action="store_true", help="Recusa bases sem nome sintético e marca o backup como teste.")
    def handle(self, *args, **options):
        path, manifest = create_backup(synthetic=options["synthetic"])
        self.stdout.write(self.style.SUCCESS(f"Backup concluído: {path.name}; {len(manifest['documents'])} documentos verificados."))
