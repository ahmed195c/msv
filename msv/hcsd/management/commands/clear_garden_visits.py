"""
One-off cleanup: wipe all "متابعة المناطق" (garden/area follow-up) data —
every GardenVisit row and its associated GardenAreaReview status rows.

Safe to preview first with --dry-run.
"""
from django.core.management.base import BaseCommand

from hcsd.models import GardenAreaReview, GardenVisit


class Command(BaseCommand):
    help = 'Delete all GardenVisit and GardenAreaReview rows'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        visits_count = GardenVisit.objects.count()
        reviews_count = GardenAreaReview.objects.count()

        if options['dry_run']:
            self.stdout.write(self.style.WARNING(
                f'[dry-run] Would delete {visits_count} GardenVisit rows '
                f'and {reviews_count} GardenAreaReview rows.'
            ))
            return

        deleted_visits, _ = GardenVisit.objects.all().delete()
        deleted_reviews, _ = GardenAreaReview.objects.all().delete()
        self.stdout.write(self.style.SUCCESS(
            f'Deleted {visits_count} GardenVisit rows and {reviews_count} GardenAreaReview rows.'
        ))
