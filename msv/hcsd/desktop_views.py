"""Tiny unauthenticated endpoint used only by the desktop build's elected-host
protocol (desktop/hostlock.py) for liveness checks over the LAN. Harmless if
ever hit on the server deployment — it reveals no data, just this process's
own pid/epoch/start time.
"""
import os

from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth import views as auth_views
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.db import transaction
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET

LOCAL_ADDRS = {'127.0.0.1', '::1'}


def _first_run_allowed(request):
    """A fresh desktop install has an empty database and no Python/shell to
    run createsuperuser with, so the first admin is created in-app — but
    only while no user exists at all, and only from the host PC's own
    window, never from another machine on the LAN."""
    return (
        settings.DESKTOP_MODE
        and request.META.get('REMOTE_ADDR') in LOCAL_ADDRS
        and not User.objects.exists()
    )


class DesktopAwareLoginView(auth_views.LoginView):
    template_name = 'registration/login.html'

    def dispatch(self, request, *args, **kwargs):
        if _first_run_allowed(request):
            return redirect('desktop_first_run')
        return super().dispatch(request, *args, **kwargs)


def desktop_first_run(request):
    if not _first_run_allowed(request):
        raise Http404
    form = UserCreationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            if User.objects.select_for_update().exists():
                return redirect('login')
            user = form.save(commit=False)
            user.is_staff = True
            user.is_superuser = True
            user.save()
        login(request, user)
        return redirect(settings.LOGIN_REDIRECT_URL)
    return render(request, 'registration/desktop_first_run.html', {'form': form})


@csrf_exempt
@require_GET
def desktop_ping(request):
    return JsonResponse({
        'pid': os.getpid(),
        'epoch': int(os.getenv('MSV_DESKTOP_EPOCH', '0')),
        'started_at': os.getenv('MSV_DESKTOP_STARTED_AT', ''),
    })
