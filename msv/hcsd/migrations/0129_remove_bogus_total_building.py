from django.db import migrations


def remove_total_building(apps, schema_editor):
    RodentControlBuilding = apps.get_model('hcsd', 'RodentControlBuilding')
    # The historical seed imported the source spreadsheet's own subtotal
    # row ("TOTAL ") as if it were a real site — delete it and its visits.
    RodentControlBuilding.objects.filter(name__iexact='TOTAL').delete()


def reverse_noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('hcsd', '0128_backfill_rodent_control_report_fields'),
    ]

    operations = [
        migrations.RunPython(remove_total_building, reverse_noop),
    ]
