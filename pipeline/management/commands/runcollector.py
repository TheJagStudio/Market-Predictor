from django.core.management.base import BaseCommand

from pipeline.ingest.supervisor import run_collector


class Command(BaseCommand):
    help = "Run the 24/7 free-data collector (WebSockets + REST)."

    def handle(self, *args, **options):
        self.stdout.write("Starting collector…")
        run_collector()
