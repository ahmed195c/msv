_ADMIN_GROUPS = {'admin', 'Administration'}
_RODENT_SIDEBAR_PREFIXES = ('/rodent-control/', '/garden/')


def nav_context(request):
    user = request.user
    if not user.is_authenticated:
        return {'nav_is_admin': False}
    if user.is_superuser:
        ctx = {'nav_is_admin': True}
    else:
        ctx = {'nav_is_admin': user.groups.filter(name__in=_ADMIN_GROUPS).exists()}

    if request.path.startswith(_RODENT_SIDEBAR_PREFIXES):
        from .models import GardenVisit, RodentControlBuilding
        from .views_pkg.common import _confined_role_for
        ctx['nav_building_count'] = RodentControlBuilding.objects.count()
        ctx['nav_area_count'] = GardenVisit.objects.count()
        ctx['nav_confined_role'] = _confined_role_for(user)

    return ctx
