"""Runs the two daily management commands that the Linux deployment drives
via crontab (generate_recurring_field_work_orders, auto_unassign_field_work_supervisors).
There's no crontab in the desktop model, so whichever instance is the
elected host runs them itself, once every 24h, for as long as it stays host.

Only ever started by the elected host (see launcher.py) — never by a
client — since only the host should touch the database.
"""
import logging
import threading
import time

logger = logging.getLogger('msv.desktop.scheduler')

DAILY_COMMANDS = (
    'generate_recurring_field_work_orders',
    'auto_unassign_field_work_supervisors',
)

INTERVAL_SECONDS = 24 * 60 * 60


def _run_once():
    from django.core.management import call_command
    for name in DAILY_COMMANDS:
        try:
            call_command(name)
        except Exception:
            logger.exception('Desktop scheduler: command %r failed', name)


def start(stop_event: threading.Event, interval_seconds: float = INTERVAL_SECONDS) -> threading.Thread:
    """Runs the commands once immediately (matching "run on launch" semantics
    useful right after an update), then again every `interval_seconds` until
    `stop_event` is set."""
    def _loop():
        _run_once()
        while not stop_event.wait(timeout=interval_seconds):
            _run_once()

    t = threading.Thread(target=_loop, name='desktop-scheduler', daemon=True)
    t.start()
    return t
