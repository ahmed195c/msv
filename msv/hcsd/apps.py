from django.apps import AppConfig
from django.db.models.signals import post_migrate


def _create_default_groups(sender, **kwargs):
    from django.contrib.auth.models import Group

    Group.objects.get_or_create(name='Data Entry')
    Group.objects.get_or_create(name='Inspector')
    Group.objects.get_or_create(name='Administration')


class HcsdConfig(AppConfig):
    name = 'hcsd'

    def ready(self):
        post_migrate.connect(_create_default_groups, sender=self)
