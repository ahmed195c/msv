from django.shortcuts import redirect

from .views_pkg.common import CONFINED_ROLE_HOME_URL, CONFINED_ROLE_PATH_PREFIXES, _confined_role_for

# Paths every confined-monitor account may reach besides its own section —
# logout/language-switch/static/media, nothing that exposes other sections.
SHARED_ALLOWED_PREFIXES = ('/logout/', '/set-language/', '/static/', '/media/')


class ConfinedRoleAccessMiddleware:
    """Confines accounts whose *only* role is one of the section-scoped
    "monitor" roles (e.g. 'مراقب القوارض' for /garden/, 'مراقب المصائد' for
    /rodent-control/) to that one section — they must not be able to view
    or act on any other part of the system, even by typing the URL."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        role = _confined_role_for(user) if user is not None else None
        if role:
            allowed = CONFINED_ROLE_PATH_PREFIXES[role] + SHARED_ALLOWED_PREFIXES
            if not request.path.startswith(allowed):
                return redirect(CONFINED_ROLE_HOME_URL[role])
        return self.get_response(request)
