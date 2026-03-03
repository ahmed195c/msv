from django.db import migrations, models


def backfill_primary_engineer(apps, schema_editor):
    Company = apps.get_model('hcsd', 'Company')
    for company in Company.objects.exclude(enginer__isnull=True).iterator():
        company.engineers.add(company.enginer)


class Migration(migrations.Migration):
    dependencies = [
        ('hcsd', '0037_company_location_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='company',
            name='engineers',
            field=models.ManyToManyField(blank=True, related_name='companies', to='hcsd.enginer'),
        ),
        migrations.RunPython(backfill_primary_engineer, migrations.RunPython.noop),
    ]
