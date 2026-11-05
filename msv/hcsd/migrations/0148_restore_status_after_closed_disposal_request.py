"""Data correction for 0147, which put every repaired permit at 'issued'. Each
one goes back to the status it had before its closed disposal request, as
recorded in the change log when that request's payment was confirmed."""
from django.db import migrations

REPAIR_NOTE_PREFIX = 'تصحيح تلقائي: طلب التخلص مغلق'
PAYMENT_NOTE_PREFIX = 'waste_disposal_payment_received:'
RESTORABLE_STATUSES = ('disposal_approved', 'disposal_rejected')


def restore(apps, schema_editor):
    PirmetChangeLog = apps.get_model('hcsd', 'PirmetChangeLog')

    repairs = PirmetChangeLog.objects.filter(
        notes__startswith=REPAIR_NOTE_PREFIX,
    ).select_related('pirmet')
    for repair in repairs:
        permit = repair.pirmet
        payment_log = PirmetChangeLog.objects.filter(
            pirmet=permit,
            notes__startswith=PAYMENT_NOTE_PREFIX,
            created_at__lt=repair.created_at,
        ).order_by('-created_at').first()
        if (
            permit.status != 'issued'
            or not payment_log
            or payment_log.old_status not in RESTORABLE_STATUSES
        ):
            continue
        permit.status = payment_log.old_status
        permit.save(update_fields=['status'])
        PirmetChangeLog.objects.create(
            pirmet=permit,
            change_type='status_change',
            old_status='issued',
            new_status=permit.status,
            notes='تصحيح تلقائي: أُعيد التصريح إلى حالته قبل طلب التخلص المغلق.',
        )


class Migration(migrations.Migration):

    dependencies = [
        ('hcsd', '0147_repair_waste_permits_left_in_inspection'),
    ]

    operations = [
        migrations.RunPython(restore, migrations.RunPython.noop),
    ]
