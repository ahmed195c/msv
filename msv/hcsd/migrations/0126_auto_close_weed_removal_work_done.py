from django.db import migrations


def close_work_done_requests(apps, schema_editor):
    WeedRemovalRequest = apps.get_model('hcsd', 'WeedRemovalRequest')
    WeedRemovalRequest.objects.filter(status='work_done').update(status='closed')


def reverse_noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('hcsd', '0125_remove_campaignrequest_location'),
    ]

    operations = [
        migrations.RunPython(close_work_done_requests, reverse_noop),
    ]
