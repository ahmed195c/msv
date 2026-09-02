"""
Create this month's trap-monitoring visit record for every active
rodent-control building. Intended to run daily via cron — idempotent per
(building, month) via the unique_together constraint, so a missed day (e.g.
the server was down on the 1st) self-heals whenever it next runs.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from hcsd.models import RodentControlBuilding, RodentControlVisit


class Command(BaseCommand):
    help = 'Generate this month\'s rodent-control visit record for every active building'

    def handle(self, *args, **options):
        period_start = timezone.localdate().replace(day=1)

        count = 0
        for building in RodentControlBuilding.objects.filter(is_active=True):
            _, created = RodentControlVisit.objects.get_or_create(
                building=building, period_start=period_start,
            )
            if created:
                count += 1

        self.stdout.write(self.style.SUCCESS(
            f'Generated {count} rodent-control visit record(s) for {period_start:%Y-%m}.'
        ))
