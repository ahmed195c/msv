"""
Portal landing view — entry point that lets the user choose a system.
No login required; authentication is handled by each sub-system.
"""

from django.conf import settings
from django.shortcuts import render


def portal_landing(request):
    """Root page: choose a system. The desktop build offers only the
    Permits System."""
    return render(request, 'hcsd/portal_landing.html', {
        'permits_only': settings.DESKTOP_MODE,
    })
