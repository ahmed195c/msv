from django.db import migrations
from django.db.models import F

# Historical rows store the rodenticide name/qty as free text in
# rodenticide_type (from the old Park RBS report seed). Map the known
# product-name prefixes onto the named quantity fields the new export
# reads, so historical months show real data instead of blank columns.
RODENTICIDE_PREFIX_TO_FIELD = {
    'SUREFIRE ALL WEATHER WB': 'rodenticide_surefire_qty',
    'SUREFIRE ALL WEATHER.': 'rodenticide_surefire_qty',
    'VERTOX Okta Blocks': 'rodenticide_vertox_qty',
    'VERTOX OCTA BLOCK': 'rodenticide_vertox_qty',
    'STELLIOX D50': 'rodenticide_sellioxid_qty',
    'VICTOR V FAST KILL': 'rodenticide_victor_qty',
    'NOCURAT WAX BLOCK': 'rodenticide_nocurat_qty',
}


def backfill(apps, schema_editor):
    RodentControlBuilding = apps.get_model('hcsd', 'RodentControlBuilding')
    RodentControlVisit = apps.get_model('hcsd', 'RodentControlVisit')

    # The Park RBS report seed stored its "Area Name" column (which is
    # really each site's identity, e.g. "Al Nahda") into building.name and
    # never set building.area — leaving the new report's Area Name column
    # blank for every seeded building. Recover it from name.
    RodentControlBuilding.objects.filter(area='').update(area=F('name'))

    for v in RodentControlVisit.objects.exclude(rodenticide_type='').exclude(rodenticide_type__isnull=True):
        prefix = v.rodenticide_type.split(':')[0].strip()
        field_name = RODENTICIDE_PREFIX_TO_FIELD.get(prefix)
        if not field_name or getattr(v, field_name) is not None:
            continue
        setattr(v, field_name, v.rodenticide_quantity)
        v.save(update_fields=[field_name])


def reverse_noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('hcsd', '0127_rodentcontrolvisit_bldg_villa_infested_count_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill, reverse_noop),
    ]
