from django.core.management.base import BaseCommand

from pipeline.ingest.backfill import backfill_binance


class Command(BaseCommand):
    help = "Backfill free Binance klines for every enabled coin and timeframe."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=7)
        parser.add_argument("--interval", default="all", help="1m, 5m, 15m, 1h, or all")
        parser.add_argument("--assets", default="", help="Comma-separated coins, e.g. BTC,ETH,XRP")

    def handle(self, *args, **options):
        assets = [part.strip() for part in str(options["assets"]).split(",") if part.strip()] or None
        interval = options["interval"]
        intervals = None if interval in {"all", "*", ""} else [interval]
        result = backfill_binance(days=options["days"], interval=interval, intervals=intervals, assets=assets)
        self.stdout.write(self.style.SUCCESS(str(result)))
