from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('hcsd', '0010_add_payment_link'),
    ]

    operations = [
        migrations.AddField(
            model_name='company',
            name='pest_control_type',
            field=models.CharField(
                blank=True,
                choices=[
                    ('public_health_pest_control', 'Public Health Pest Control'),
                    ('termite_control', 'Termite Control'),
                    ('grain_pests', 'Grain Pests Control'),
                ],
                max_length=30,
                null=True,
            ),
        ),
    ]
