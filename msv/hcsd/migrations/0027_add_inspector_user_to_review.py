from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('hcsd', '0026_alter_company_business_activity'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='inspectorreview',
            name='inspector_user',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.deletion.SET_NULL,
                related_name='inspector_reviews',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
