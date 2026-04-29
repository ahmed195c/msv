from django.db import migrations


def clear_violation_ref_for_new_companies(apps, schema_editor):
    """
    Clear violation_reference_expiry for permits that belong to companies
    with no previously-issued pest control permit.  These were incorrectly
    set from the trade-licence expiry date during permit creation, making
    new companies appear to have overdue violations.
    """
    PirmetClearance = apps.get_model('hcsd', 'PirmetClearance')

    affected = (
        PirmetClearance.objects
        .filter(
            permit_type='pest_control',
            violation_reference_expiry__isnull=False,
            # Only fix permits whose violation order/receipt are both empty
            # (i.e. no actual violation payment has been processed)
            violation_payment_order_number__isnull=True,
            violation_payment_receipt='',
        )
    )

    fixed = 0
    for pirmet in affected:
        # Check whether there is any OTHER issued pest control permit for
        # the same company that expired before this one was created.
        has_previous_permit = PirmetClearance.objects.filter(
            company=pirmet.company,
            permit_type='pest_control',
            status='issued',
            dateOfExpiry__isnull=False,
        ).exclude(id=pirmet.id).exists()

        if not has_previous_permit:
            pirmet.violation_reference_expiry = None
            pirmet.save(update_fields=['violation_reference_expiry'])
            fixed += 1

    print(f'\n  Fixed violation_reference_expiry for {fixed} permit(s).')


class Migration(migrations.Migration):

    dependencies = [
        ('hcsd', '0085_field_work_supervisor_area'),
    ]

    operations = [
        migrations.RunPython(
            clear_violation_ref_for_new_companies,
            migrations.RunPython.noop,
        ),
    ]
