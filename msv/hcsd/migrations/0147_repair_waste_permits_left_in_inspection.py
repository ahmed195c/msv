"""Data repair: closing a waste disposal request administratively used to leave
its permit at 'inspection_pending', so the closed request kept showing on the
requests-tracking page as still waiting for / received by an inspector. Put
those permits back to 'issued' (the view now does this when closing)."""
from django.db import migrations

OPEN_REQUEST_STATUSES = ('payment_pending', 'inspection_pending')


def repair(apps, schema_editor):
    PirmetClearance = apps.get_model('hcsd', 'PirmetClearance')
    WasteDisposalRequest = apps.get_model('hcsd', 'WasteDisposalRequest')
    PirmetChangeLog = apps.get_model('hcsd', 'PirmetChangeLog')
    InspectorReview = apps.get_model('hcsd', 'InspectorReview')

    with_open_request = WasteDisposalRequest.objects.filter(
        status__in=OPEN_REQUEST_STATUSES,
    ).values_list('permit_id', flat=True)
    stuck = PirmetClearance.objects.filter(
        permit_type='waste_disposal',
        status='inspection_pending',
        issue_date__isnull=False,
        waste_disposal_requests__isnull=False,
    ).exclude(pk__in=with_open_request).distinct()

    for permit in stuck:
        permit.status = 'issued'
        permit.save(update_fields=['status'])
        InspectorReview.objects.filter(pirmet=permit).update(inspector_user=None)
        PirmetChangeLog.objects.create(
            pirmet=permit,
            change_type='status_change',
            old_status='inspection_pending',
            new_status='issued',
            notes='تصحيح تلقائي: طلب التخلص مغلق، فأُعيد التصريح إلى حالة صادر.',
        )


class Migration(migrations.Migration):

    dependencies = [
        ('hcsd', '0146_activity_permit_receipt_names'),
    ]

    operations = [
        migrations.RunPython(repair, migrations.RunPython.noop),
    ]
