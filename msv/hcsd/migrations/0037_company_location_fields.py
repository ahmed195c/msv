from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('hcsd', '0036_alter_company_id_alter_companychangelog_id_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='company',
            name='latitude',
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True),
        ),
        migrations.AddField(
            model_name='company',
            name='longitude',
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True),
        ),
    ]
