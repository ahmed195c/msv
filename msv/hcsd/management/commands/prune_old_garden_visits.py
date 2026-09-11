"""
One-off cleanup: keep only one month of "متابعة المناطق" (garden/area
follow-up) visits, deleting everything else. Used after a fresh bulk
import from Excel when only the latest month's data should stay live.

Safe to preview first with --dry-run.
"""
from django.core.management.base import BaseCommand

from hcsd.models import GardenVisit


class Command(BaseCommand):
    help = 'Delete GardenVisit rows outside a given year/month (default: keep September 2026 only)'

    def add_arguments(self, parser):
        parser.add_argument('--keep-year', type=int, default=2026)
        parser.add_argument('--keep-month', type=int, default=9)
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        year = options['keep_year']
        month = options['keep_month']
        dry_run = options['dry_run']

        qs = GardenVisit.objects.exclude(visit_date__year=year, visit_date__month=month)
        total = GardenVisit.objects.count()
        to_delete = qs.count()

        if dry_run:
            self.stdout.write(self.style.WARNING(
                f'[dry-run] Would delete {to_delete} of {total} rows, '
                f'keeping {total - to_delete} rows from {year}-{month:02d}.'
            ))
            return

        deleted, _ = qs.delete()
        remaining = GardenVisit.objects.count()
        self.stdout.write(self.style.SUCCESS(
            f'Deleted {deleted} rows. Remaining: {remaining} (all from {year}-{month:02d}).'
        ))
