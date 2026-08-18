from django.core.management.base import BaseCommand

from pipeline.ml.loop import run_inference_loop


class Command(BaseCommand):
    help = "Run live inference + optional Polymarket order loop."

    def handle(self, *args, **options):
        self.stdout.write("Starting inference loop…")
        run_inference_loop()
