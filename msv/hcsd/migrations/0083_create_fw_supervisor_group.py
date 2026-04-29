from django.db import migrations


def create_fw_supervisor_group(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Group.objects.get_or_create(name='fw_supervisor')


def delete_fw_supervisor_group(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Group.objects.filter(name='fw_supervisor').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('hcsd', '0082_field_work_assigned_supervisor'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.RunPython(create_fw_supervisor_group, delete_fw_supervisor_group),
    ]
