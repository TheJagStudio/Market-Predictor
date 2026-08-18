from django.core.management.base import BaseCommand

from pipeline.ml.train import run_training_job


class Command(BaseCommand):
    help = "Train selected model architectures for a job id."

    def add_arguments(self, parser):
        parser.add_argument("job_id", type=int)

    def handle(self, *args, **options):
        job_id = options["job_id"]
        self.stdout.write(f"Training job {job_id}…")
        run_training_job(job_id)
        self.stdout.write(self.style.SUCCESS("done"))
