from django.db import migrations


def backfill_profiles(apps, schema_editor):
    User = apps.get_model('auth', 'User')
    UserProfile = apps.get_model('hcsd', 'UserProfile')
    for user in User.objects.all():
        UserProfile.objects.get_or_create(
            user=user,
            defaults={'admin_number': user.username},
        )


class Migration(migrations.Migration):

    dependencies = [
        ('hcsd', '0103_user_profile'),
    ]

    operations = [
        migrations.RunPython(backfill_profiles, migrations.RunPython.noop),
    ]
