"""Fill the inspection payment date of earlier requests from their change log:
the day the inspection payment was first recorded."""
from django.db import migrations
from django.utils import timezone

INSPECTION_PAID_NOTES = ('Inspection payment received.', 'Inspection receipt uploaded.')


def fill_dates(apps, schema_editor):
    Permit = apps.get_model('hcsd', 'PirmetClearance')
    ChangeLog = apps.get_model('hcsd', 'PirmetChangeLog')
    first_paid = {}
    logs = ChangeLog.objects.filter(notes__in=INSPECTION_PAID_NOTES).order_by('created_at')
    for permit_id, created_at in logs.values_list('pirmet_id', 'created_at'):
        first_paid.setdefault(permit_id, timezone.localtime(created_at).date())
    for permit in Permit.objects.filter(pk__in=first_paid, inspection_payment_date__isnull=True):
        permit.inspection_payment_date = first_paid[permit.pk]
        permit.save(update_fields=['inspection_payment_date'])


class Migration(migrations.Migration):

    dependencies = [
        ('hcsd', '0155_permit_inspection_payment_date'),
    ]

    operations = [
        migrations.RunPython(fill_dates, migrations.RunPython.noop),
    ]
