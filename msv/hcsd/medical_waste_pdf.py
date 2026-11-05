"""Saves a medical-waste inspection report as a PDF: exactly its print page,
rendered by a headless Chromium-family browser from a temporary local file.
The page's own security policy blocks scripts during rendering. A failure is
logged and reported to the caller; the report itself is already saved and can
still be printed."""
import logging
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from django.contrib.staticfiles import finders
from django.core.files.base import ContentFile
from django.template.loader import render_to_string

from .desktop_pdf import CREATE_NO_WINDOW, _find_browser

logger = logging.getLogger(__name__)

BROWSER_TIMEOUT_SECONDS = 60
FACILITY_NAME_MAX_LEN = 40
_UNSAFE_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

SHEET_CSS = 'hcsd/medical_waste/sheet.css'
HEADER_IMAGE = 'hcsd/medical_waste/form_header.png'
FOOTER_IMAGE = 'hcsd/medical_waste/form_footer.png'


def pdf_filename(report):
    facility = _UNSAFE_NAME_CHARS.sub('', report.facility_name).strip()[:FACILITY_NAME_MAX_LEN].strip()
    return f'{report.inspection_date:%Y-%m-%d} - {facility or "منشأة"} - تقرير {report.pk}.pdf'


def _file_uri(static_path):
    return Path(finders.find(static_path)).as_uri()


def _signature_uri(signature):
    return Path(signature.path).as_uri() if signature else ''


def _print_html(report):
    return render_to_string('hcsd/medical_waste_print.html', {
        'report': report,
        'for_pdf': True,
        'sheet_css_url': _file_uri(SHEET_CSS),
        'header_image_url': _file_uri(HEADER_IMAGE),
        'footer_image_url': _file_uri(FOOTER_IMAGE),
        'inspector_signature_url': _signature_uri(report.inspector_signature),
        'representative_signature_url': _signature_uri(report.representative_signature),
    })


def _render_pdf_bytes(report, browser):
    with tempfile.TemporaryDirectory(prefix='msv_mw_pdf_') as tmp:
        tmp_dir = Path(tmp)
        page, out = tmp_dir / 'report.html', tmp_dir / 'report.pdf'
        page.write_text(_print_html(report), encoding='utf-8')
        subprocess.run(
            [
                browser, '--headless=new', '--disable-gpu', '--no-first-run',
                '--no-pdf-header-footer', '--allow-file-access-from-files',
                f'--user-data-dir={tmp_dir / "profile"}', f'--print-to-pdf={out}', page.as_uri(),
            ],
            check=True, capture_output=True, timeout=BROWSER_TIMEOUT_SECONDS,
            creationflags=CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
        )
        return out.read_bytes()


def save_report_pdf(report):
    """(Re)generate the report's PDF. Returns True on success. On failure the
    previous PDF is removed too: it would no longer match an edited report."""
    if report.pdf_file:
        report.pdf_file.delete(save=False)
    browser = _find_browser()
    try:
        if not browser:
            raise OSError('no Chromium-family browser found')
        content = _render_pdf_bytes(report, browser)
    except (OSError, ValueError, subprocess.SubprocessError):
        logger.exception('Medical waste report PDF %s failed', report.pk)
        report.pdf_file = ''
        report.save(update_fields=['pdf_file'])
        return False
    report.pdf_file.save(pdf_filename(report), ContentFile(content), save=False)
    report.save(update_fields=['pdf_file'])
    return True
