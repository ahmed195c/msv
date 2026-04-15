"""
Portal landing view — entry point that lets the user choose a system.
No login required; authentication is handled by each sub-system.
"""

from django.shortcuts import render


def portal_landing(request):
    """Root page: choose between Permits System and Complaints System."""
    return render(request, 'hcsd/portal_landing.html')
