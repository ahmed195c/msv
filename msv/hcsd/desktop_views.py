"""Tiny unauthenticated endpoint used only by the desktop build's elected-host
protocol (desktop/hostlock.py) for liveness checks over the LAN. Harmless if
ever hit on the server deployment — it reveals no data, just this process's
own pid/epoch/start time.
"""
import os

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET


@csrf_exempt
@require_GET
def desktop_ping(request):
    return JsonResponse({
        'pid': os.getpid(),
        'epoch': int(os.getenv('MSV_DESKTOP_EPOCH', '0')),
        'started_at': os.getenv('MSV_DESKTOP_STARTED_AT', ''),
    })
