from django.core.management.base import BaseCommand, CommandError

from inventory.backups import restore_synthetic


class Command(BaseCommand):
    help = "Restaura apenas backups sintéticos para uma base NOVA garrafas_restore_...; nunca substitui destinos."
    def add_arguments(self, parser):
        parser.add_argument("archive")
        parser.add_argument("--database", required=True)
        parser.add_argument("--confirm-isolated", action="store_true")
    def handle(self, *args, **options):
        if not options["confirm_isolated"]:
            raise CommandError("Confirme o destino isolado com --confirm-isolated.")
        manifest = restore_synthetic(options["archive"], database=options["database"])
        self.stdout.write(self.style.SUCCESS(f"Restauro sintético concluído; {len(manifest['documents'])} documentos verificados. Base isolada conservada para revisão."))
