"""
Create a new field work order from each active recurring-order template
whose scheduled weekday matches today. Intended to run once daily via cron
(the weekday check is done here in Python, not in the crontab schedule).
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from hcsd.models import FieldWorkOrder, FieldWorkRecurringOrder


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
            FieldWorkOrder.objects.create(
                site_name=tmpl.site_name,
                customer_name=tmpl.customer_name,
                mobile=tmpl.mobile,
                area=tmpl.area,
                street_number=tmpl.street_number,
                house_number=tmpl.house_number,
                location=tmpl.location,
                pest_types=tmpl.pest_types,
                complaint_source=tmpl.complaint_source,
                notes=tmpl.notes,
                request_date=today,
                status='new',
                source='recurring',
                created_by=tmpl.created_by,
                recurring_template=tmpl,
            )
            tmpl.last_generated_on = today
            tmpl.save(update_fields=['last_generated_on'])
            count += 1

        self.stdout.write(self.style.SUCCESS(f'Generated {count} recurring field work order(s) for {today}.'))
