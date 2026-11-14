"""Companies imported from Excel got the code 'pest_control' as their licence
activities, a placeholder rather than the licence's text; it showed raw in the
request forms. They now say to see the trade licence."""
from django.db import migrations

IMPORT_PLACEHOLDER = 'pest_control'
SEE_LICENSE = 'كما هو موضح في الرخصة التجارية'


def replace_placeholder(apps, schema_editor):
    Company = apps.get_model('hcsd', 'Company')
    Company.objects.filter(business_activity=IMPORT_PLACEHOLDER).update(business_activity=SEE_LICENSE)


class Migration(migrations.Migration):

    dependencies = [
        ('hcsd', '0157_remove_unused_disposal_models'),
    ]

    operations = [
        migrations.RunPython(replace_placeholder, migrations.RunPython.noop),
    ]
