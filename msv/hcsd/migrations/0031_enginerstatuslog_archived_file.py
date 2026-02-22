from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('hcsd', '0030_merge_20260222_1548'),
    ]

    operations = [
        migrations.AddField(
            model_name='enginerstatuslog',
            name='archived_file',
            field=models.FileField(blank=True, null=True, upload_to='engineer_certificates/archive/'),
        ),
    ]
