from django.core.management.base import BaseCommand

from pipeline.ingest.backfill import backfill_binance


class Command(BaseCommand):
    help = "Backfill free Binance klines into feature bars so training can start immediately."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=7)
        parser.add_argument("--interval", default="1m")

    def handle(self, *args, **options):
        result = backfill_binance(days=options["days"], interval=options["interval"])
        self.stdout.write(self.style.SUCCESS(str(result)))
