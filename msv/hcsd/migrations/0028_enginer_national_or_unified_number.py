from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('hcsd', '0027_add_inspector_user_to_review'),
    ]

    operations = [
        migrations.AddField(
            model_name='enginer',
            name='national_or_unified_number',
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
    ]
