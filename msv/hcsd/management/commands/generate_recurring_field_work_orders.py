"""
Create a new field work order from each active recurring-order template
whose scheduled weekday matches today. Intended to run once daily via cron
(the weekday check is done here in Python, not in the crontab schedule).
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from hcsd.models import FieldWorkRecurringOrder


class Command(BaseCommand):
    help = 'Generate field work orders from due recurring-order templates'

    def handle(self, *args, **options):
        today = timezone.localdate()
        weekday = today.weekday()

        due_templates = FieldWorkRecurringOrder.objects.filter(
            is_active=True, weekday=weekday,
        ).exclude(last_generated_on=today)

        count = 0
        for tmpl in due_templates:
            tmpl.generate_order(today)
            count += 1

        self.stdout.write(self.style.SUCCESS(f'Generated {count} recurring field work order(s) for {today}.'))
