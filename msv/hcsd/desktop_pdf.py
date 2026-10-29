"""Desktop build only: when an activity (pest_control) permit is issued, save
a PDF of its print page — exactly what printing it would give — to
MEDIA_ROOT/تصريح النشاط/التصاريح/<YYYY-MM>/<company name>.pdf.

The PDF is rendered by Microsoft Edge in headless mode (always present on
Windows 10/11, and already what pywebview draws the app window with) against
the app's own print page on 127.0.0.1, in a background thread so issuing the
permit never waits on it. A failure is logged and never blocks issuance.
"""
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlsplit

from django.conf import settings
from django.db import connection, transaction
from django.urls import reverse
from django.utils import timezone

from .models import (
    ACTIVITY_PERMIT_FOLDER, ACTIVITY_PERMIT_PDFS_FOLDER, PirmetClearance,
    company_folder_name,
)

logger = logging.getLogger(__name__)

EDGE_TIMEOUT_SECONDS = 90
EDGE_CANDIDATES = (
    r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
    r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
)
CREATE_NO_WINDOW = 0x08000000


def _find_browser():
    for path in EDGE_CANDIDATES:
        if os.path.exists(path):
            return path
    # Dev/testing on Linux or a PC with Edge elsewhere on PATH.
    for name in ('msedge', 'microsoft-edge', 'google-chrome', 'chromium'):
        found = shutil.which(name)
        if found:
            return found
    return None


def _local_base_url():
    lan_origin = os.getenv('MSV_DESKTOP_LAN_ORIGIN', '')
    port = urlsplit(lan_origin).port if lan_origin else None
    return f'http://127.0.0.1:{port}' if port else None


def _output_path(permit):
    month = timezone.localdate().strftime('%Y-%m')
    folder = Path(settings.MEDIA_ROOT) / ACTIVITY_PERMIT_FOLDER / ACTIVITY_PERMIT_PDFS_FOLDER / month
    name = company_folder_name(permit.company)
    path = folder / f'{name}.pdf'
    if path.exists():
        # Same company issued twice in one month — keep both.
        path = folder / f'{name} - {permit.permit_no or permit.pk}.pdf'
    return path


def render_activity_permit_pdf(permit_id):
    """Render the permit's print page to PDF. Returns the output Path, or
    None if it couldn't be produced (the reason is logged)."""
    permit = PirmetClearance.objects.select_related('company').get(pk=permit_id)
    browser = _find_browser()
    base_url = _local_base_url()
    if not browser or not base_url:
        logger.error('Activity permit PDF %s skipped: browser=%s base_url=%s', permit_id, browser, base_url)
        return None

    out = _output_path(permit)
    out.parent.mkdir(parents=True, exist_ok=True)
    url = base_url + reverse('pest_control_permit_print', args=[permit.pk])
    with tempfile.TemporaryDirectory(prefix='msv_pdf_') as profile_dir:
        cmd = [
            browser, '--headless=new', '--disable-gpu', '--no-first-run',
            '--no-pdf-header-footer', f'--user-data-dir={profile_dir}',
            f'--print-to-pdf={out}', url,
        ]
        try:
            subprocess.run(
                cmd, check=True, capture_output=True, timeout=EDGE_TIMEOUT_SECONDS,
                creationflags=CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
            )
        except (OSError, subprocess.SubprocessError):
            logger.exception('Activity permit PDF %s failed', permit_id)
            return None
    if not out.exists():
        logger.error('Activity permit PDF %s: browser exited but wrote no file', permit_id)
        return None
    logger.info('Activity permit PDF %s saved to %s', permit_id, out)
    return out


def queue_activity_permit_pdf(permit):
    """Call right after an activity permit becomes 'issued'."""
    if not settings.DESKTOP_MODE or permit.permit_type != 'pest_control':
        return

    def _run():
        try:
            render_activity_permit_pdf(permit.pk)
        finally:
            connection.close()

    def _start():
        threading.Thread(
            target=_run,
            name=f'permit-pdf-{permit.pk}', daemon=True,
        ).start()

    transaction.on_commit(_start)
