from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('hcsd', '0009_add_permit_types'),
    ]

    operations = [
        migrations.AddField(
            model_name='pirmetclearance',
            name='payment_link',
            field=models.CharField(blank=True, max_length=500, null=True),
        ),
    ]
