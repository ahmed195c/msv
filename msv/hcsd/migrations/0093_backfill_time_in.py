from django.db import migrations


def backfill_time_in(apps, schema_editor):
    from django.db.models import F
    FieldWorkOrder = apps.get_model('hcsd', 'FieldWorkOrder')
    FieldWorkOrder.objects.filter(
        time_in__isnull=True,
        location_saved_at__isnull=False,
    ).update(time_in=F('location_saved_at'))


class Migration(migrations.Migration):

    dependencies = [
        ('hcsd', '0092_field_work_time_in'),
    ]

    operations = [
        migrations.RunPython(backfill_time_in, migrations.RunPython.noop),
    ]
