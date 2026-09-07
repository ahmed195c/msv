"""
Create this month's trap-monitoring visit record for every active
rodent-control building that doesn't already have one. Intended to run
daily via cron — a missed day (e.g. the server was down on the 1st)
self-heals whenever it next runs.

A building can have several visits in the same month (imported historical
data, or more than one real field visit), so this only fills in the gap
for buildings with zero visits this month — it never adds a second one.
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
            if RodentControlVisit.objects.filter(building=building, period_start=period_start).exists():
                continue
            RodentControlVisit.objects.create(building=building, period_start=period_start)
            count += 1

        self.stdout.write(self.style.SUCCESS(
            f'Generated {count} rodent-control visit record(s) for {period_start:%Y-%m}.'
        ))
