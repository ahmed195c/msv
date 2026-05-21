_ADMIN_GROUPS = {'admin', 'Administration'}


def nav_context(request):
    user = request.user
    if not user.is_authenticated:
        return {'nav_is_admin': False}
    if user.is_superuser:
        return {'nav_is_admin': True}
    is_admin = user.groups.filter(name__in=_ADMIN_GROUPS).exists()
    return {'nav_is_admin': is_admin}
