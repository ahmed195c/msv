from django.shortcuts import redirect

from .views_pkg.common import _is_garden_monitor_only

# Paths a garden_monitor-only account may reach besides the garden section
# itself — logout/language-switch/static/media, nothing that exposes other
# business sections.
ALLOWED_PATH_PREFIXES = ('/garden/', '/logout/', '/set-language/', '/static/', '/media/')


class GardenMonitorAccessMiddleware:
    """Confines accounts whose only role is 'مراقب القوارض' (garden_monitor) to
    the garden follow-up section (/garden/...) — they must not be able to
    view or act on any other part of the system, even by typing the URL."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        if (
            user is not None
            and _is_garden_monitor_only(user)
            and not request.path.startswith(ALLOWED_PATH_PREFIXES)
        ):
            return redirect('garden_list')
        return self.get_response(request)
