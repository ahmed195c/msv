from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('hcsd', '0039_enginer_card_number'),
    ]

    operations = [
        migrations.AddField(
            model_name='company',
            name='location_area',
            field=models.CharField(blank=True, max_length=150, null=True),
        ),
        migrations.AddField(
            model_name='company',
            name='location_street',
            field=models.CharField(blank=True, max_length=180, null=True),
        ),
    ]
