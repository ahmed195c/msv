"""
Container Transfer Request views.

URL prefix : /container-transfers/
Template dir: hcsd/container/

Workflow
--------
new → assigned → location_saved → biaa_contacted → biaa_transferred → report_submitted → closed
"""

import logging
import os
import re
from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.files.storage import default_storage
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..models import (
    ContainerTransferRequest,
    ContainerTransferInspection,
    ContainerTransferPhoto,
)
from .common import _can_admin, _can_data_entry
from .complaints import _fix_rtl_pdf_text, _arabic_digits_to_western, _get_lang

logger = logging.getLogger(__name__)

ALLOWED_PDF_EXTENSION  = '.pdf'
ALLOWED_PHOTO_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}
_SESSION_KEY = 'container_pdf_import'


# ── Helpers ───────────────────────────────────────────────────────────────────

def _can_manage(user):
    return _can_admin(user) or _can_data_entry(user)


def _is_valid_pdf(file):
    _, ext = os.path.splitext(file.name)
    return ext.lower() == ALLOWED_PDF_EXTENSION


def _is_valid_photo(file):
    _, ext = os.path.splitext(file.name)
    return ext.lower() in ALLOWED_PHOTO_EXTENSIONS


def _extract_from_pdf(pdf_file):
    """Reuse complaint PDF extraction logic for container transfer PDFs."""
    try:
        import pdfplumber
    except ImportError:
        return {}

    data = {
        'complaint_number': '',
        'complainant_name': '',
        'complainant_mobile': '',
        'area': '',
        'house_number': '',
        'notes': '',
    }

    try:
        with pdfplumber.open(pdf_file) as pdf:
            raw = []
            for page in pdf.pages:
                raw.extend((page.extract_text(x_tolerance=3, y_tolerance=3) or '').splitlines())

        full = _fix_rtl_pdf_text('\n'.join(raw))

        patterns = [
            ('complaint_number',   [r'رقم الشكوى\s+([0-9]+']),
            ('complainant_name',   [r'(.+)\nاسم المشتكي', r'اسم المشتكي\s+(.+)']),
            ('complainant_mobile', [r'(?:متحرك|ثابت)\s+الرقم\s+([0-9]{7,15})',
                                    r'الرقم\s+([0-9]{7,15})']),
            ('area',               [r'موقع الشكوى\s+(.+)']),
            ('notes',              [r'تفاصيل الشكوى\s+(.+)']),
        ]

        for field, pats in patterns:
            for pat in pats:
                m = re.search(pat, full, re.MULTILINE)
                if m:
                    data[field] = m.group(1).strip()
                    break

        if data['notes']:
            m = re.search(r'منزل\s+([0-9]+)', data['notes'])
            if m:
                data['house_number'] = m.group(1)

    except Exception:
        logger.warning('Container PDF extraction error', exc_info=True)

    return data


# ── Manual Create ─────────────────────────────────────────────────────────────

@login_required
def container_create(request):
    lang = _get_lang(request)
    if not _can_manage(request.user):
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden()

    errors = {}
    post = {}

    if request.method == 'POST':
        post = request.POST
        complaint_number   = (post.get('complaint_number') or '').strip()
        complainant_name   = (post.get('complainant_name') or '').strip()
        complainant_mobile = (post.get('complainant_mobile') or '').strip()
        area               = (post.get('area') or '').strip()
        house_number       = (post.get('house_number') or '').strip()
        notes              = (post.get('notes') or '').strip()
        pdf_file           = request.FILES.get('pdf_file')

        if not complaint_number:
            errors['complaint_number'] = 'رقم الشكوى مطلوب.'

        if not errors:
            obj = ContainerTransferRequest.objects.create(
                complaint_number=complaint_number,
                complainant_name=complainant_name,
                complainant_mobile=complainant_mobile,
                area=area,
                house_number=house_number,
                notes=notes,
                created_by=request.user,
            )
            if pdf_file and _is_valid_pdf(pdf_file):
                saved = default_storage.save(
                    f'container_requests/pdfs/{pdf_file.name}', pdf_file
                )
                ContainerTransferRequest.objects.filter(pk=obj.pk).update(pdf_file=saved)

            logger.info('ContainerTransferRequest %s created manually by %s', obj.complaint_number, request.user)
            return redirect('container_detail', pk=obj.pk)

    return render(request, 'hcsd/container/create.html', {
        'errors': errors,
        'post': post,
        'lang': lang,
    })


# ── List ──────────────────────────────────────────────────────────────────────

@login_required
def container_list(request):
    lang = _get_lang(request)
    status_filter = (request.GET.get('status') or 'all').strip()
    requests_qs = ContainerTransferRequest.objects.select_related('created_by').all()
    if status_filter != 'all':
        requests_qs = requests_qs.filter(status=status_filter)

    return render(request, 'hcsd/container/list.html', {
        'requests': requests_qs,
        'status_filter': status_filter,
        'status_choices': ContainerTransferRequest.STATUS_CHOICES,
        'can_manage': _can_manage(request.user),
        'lang': lang,
    })


# ── PDF Import ────────────────────────────────────────────────────────────────

@login_required
def container_pdf_import(request):
    lang = _get_lang(request)
    error = None

    if request.method == 'POST':
        pdf_file = request.FILES.get('pdf_file')
        if not pdf_file:
            error = 'يرجى اختيار ملف PDF.'
        elif not _is_valid_pdf(pdf_file):
            error = 'يجب أن يكون الملف بصيغة PDF فقط.'
        else:
            extracted = _extract_from_pdf(pdf_file)
            pdf_file.seek(0)
            saved_name = default_storage.save(f'container_requests/pdfs/{pdf_file.name}', pdf_file)
            request.session[_SESSION_KEY] = {
                **extracted,
                'pdf_saved_name': saved_name,
                'pdf_original_name': pdf_file.name,
            }
            return redirect('container_pdf_review')

    return render(request, 'hcsd/container/pdf_import.html', {'error': error, 'lang': lang})


@login_required
def container_pdf_review(request):
    lang = _get_lang(request)
    session_data = request.session.get(_SESSION_KEY)
    if not session_data:
        return redirect('container_pdf_import')

    if request.method == 'POST':
        complaint_number   = (request.POST.get('complaint_number') or '').strip()
        complainant_name   = (request.POST.get('complainant_name') or '').strip()
        complainant_mobile = (request.POST.get('complainant_mobile') or '').strip()
        area               = (request.POST.get('area') or '').strip()
        house_number       = (request.POST.get('house_number') or '').strip()
        notes              = (request.POST.get('notes') or '').strip()

        if not complaint_number:
            return render(request, 'hcsd/container/pdf_review.html', {
                'form_data': request.POST,
                'pdf_original_name': session_data.get('pdf_original_name', ''),
                'errors': {'complaint_number': 'رقم الشكوى مطلوب.'},
                'lang': lang,
            })

        obj = ContainerTransferRequest.objects.create(
            complaint_number=complaint_number,
            complainant_name=complainant_name,
            complainant_mobile=complainant_mobile,
            area=area,
            house_number=house_number,
            notes=notes,
            created_by=request.user,
        )

        pdf_saved = session_data.get('pdf_saved_name', '')
        if pdf_saved and default_storage.exists(pdf_saved):
            ContainerTransferRequest.objects.filter(pk=obj.pk).update(pdf_file=pdf_saved)

        del request.session[_SESSION_KEY]
        logger.info('ContainerTransferRequest %s created by %s', obj.complaint_number, request.user)
        return redirect('container_detail', pk=obj.pk)

    form_data = {
        'complaint_number':   session_data.get('complaint_number', ''),
        'complainant_name':   session_data.get('complainant_name', ''),
        'complainant_mobile': session_data.get('complainant_mobile', ''),
        'area':               session_data.get('area', ''),
        'house_number':       session_data.get('house_number', ''),
        'notes':              session_data.get('notes', ''),
    }
    return render(request, 'hcsd/container/pdf_review.html', {
        'form_data': form_data,
        'pdf_original_name': session_data.get('pdf_original_name', ''),
        'errors': {},
        'lang': lang,
    })


# ── Detail ────────────────────────────────────────────────────────────────────

@login_required
def container_detail(request, pk):
    lang = _get_lang(request)
    obj = get_object_or_404(
        ContainerTransferRequest.objects.select_related('created_by'),
        pk=pk,
    )
    inspection    = getattr(obj, 'inspection', None)
    staff_users   = User.objects.filter(is_active=True).order_by('first_name', 'username')
    before_photos = obj.photos.filter(phase='before')
    after_photos  = obj.photos.filter(phase='after')
    is_inspector  = inspection and inspection.inspector_id == request.user.id

    return render(request, 'hcsd/container/detail.html', {
        'obj': obj,
        'inspection': inspection,
        'staff_users': staff_users,
        'before_photos': before_photos,
        'after_photos': after_photos,
        'can_manage': _can_manage(request.user),
        'is_inspector': is_inspector,
        'status_choices': ContainerTransferRequest.STATUS_CHOICES,
        'lang': lang,
    })


# ── Assign inspector ──────────────────────────────────────────────────────────

@login_required
@require_POST
def container_assign_inspector(request, pk):
    obj = get_object_or_404(ContainerTransferRequest, pk=pk)
    if not _can_manage(request.user):
        return redirect('container_detail', pk=pk)

    inspector_id = request.POST.get('inspector_id')
    if not inspector_id:
        return redirect('container_detail', pk=pk)

    inspector = get_object_or_404(User, pk=inspector_id, is_active=True)
    inspection, created = ContainerTransferInspection.objects.get_or_create(
        request=obj,
        defaults={'inspector': inspector, 'assigned_by': request.user},
    )
    if not created:
        inspection.inspector   = inspector
        inspection.assigned_by = request.user
        inspection.save(update_fields=['inspector', 'assigned_by'])

    obj.status = 'assigned'
    obj.save(update_fields=['status', 'updated_at'])
    logger.info('Container %s assigned to inspector %s by %s', pk, inspector, request.user)
    return redirect('container_detail', pk=pk)


# ── Inspector: save location + before photos ──────────────────────────────────

@login_required
@require_POST
def container_save_location(request, pk):
    obj        = get_object_or_404(ContainerTransferRequest, pk=pk)
    inspection = get_object_or_404(ContainerTransferInspection, request=obj)

    if inspection.inspector_id != request.user.id and not _can_manage(request.user):
        return redirect('container_detail', pk=pk)

    lat            = (request.POST.get('latitude') or '').strip()
    lng            = (request.POST.get('longitude') or '').strip()
    location_notes = (request.POST.get('location_notes') or '').strip()

    update_fields = ['location_notes']
    inspection.location_notes = location_notes

    try:
        if lat:
            inspection.latitude = float(lat)
            update_fields.append('latitude')
        if lng:
            inspection.longitude = float(lng)
            update_fields.append('longitude')
    except ValueError:
        pass

    if not inspection.location_saved_at:
        inspection.location_saved_at = timezone.now()
        update_fields.append('location_saved_at')
        obj.status = 'location_saved'
        obj.save(update_fields=['status', 'updated_at'])

    inspection.save(update_fields=update_fields)

    for photo_file in request.FILES.getlist('before_photos'):
        if _is_valid_photo(photo_file):
            ContainerTransferPhoto.objects.create(
                request=obj, phase='before',
                file=photo_file, uploaded_by=request.user,
            )

    return redirect('container_detail', pk=pk)


# ── Inspector: mark Bee'ah contacted ─────────────────────────────────────────

@login_required
@require_POST
def container_contact_biaa(request, pk):
    obj        = get_object_or_404(ContainerTransferRequest, pk=pk)
    inspection = get_object_or_404(ContainerTransferInspection, request=obj)

    if inspection.inspector_id != request.user.id and not _can_manage(request.user):
        return redirect('container_detail', pk=pk)

    notes = (request.POST.get('biaa_contact_notes') or '').strip()
    inspection.biaa_contact_notes = notes
    update_fields = ['biaa_contact_notes']

    if not inspection.biaa_contacted_at:
        inspection.biaa_contacted_at = timezone.now()
        update_fields.append('biaa_contacted_at')
        obj.status = 'biaa_contacted'
        obj.save(update_fields=['status', 'updated_at'])

    inspection.save(update_fields=update_fields)
    return redirect('container_detail', pk=pk)


# ── Inspector: mark container transferred ────────────────────────────────────

@login_required
@require_POST
def container_mark_transferred(request, pk):
    obj        = get_object_or_404(ContainerTransferRequest, pk=pk)
    inspection = get_object_or_404(ContainerTransferInspection, request=obj)

    if inspection.inspector_id != request.user.id and not _can_manage(request.user):
        return redirect('container_detail', pk=pk)

    if not inspection.biaa_transferred_at:
        inspection.biaa_transferred_at = timezone.now()
        inspection.save(update_fields=['biaa_transferred_at'])
        obj.status = 'biaa_transferred'
        obj.save(update_fields=['status', 'updated_at'])

    return redirect('container_detail', pk=pk)


# ── Inspector: submit final report + after photos ────────────────────────────

@login_required
@require_POST
def container_submit_report(request, pk):
    obj        = get_object_or_404(ContainerTransferRequest, pk=pk)
    inspection = get_object_or_404(ContainerTransferInspection, request=obj)

    if inspection.inspector_id != request.user.id and not _can_manage(request.user):
        return redirect('container_detail', pk=pk)

    report_notes = (request.POST.get('report_notes') or '').strip()
    inspection.report_notes = report_notes
    update_fields = ['report_notes']

    if not inspection.completed_at:
        inspection.completed_at = timezone.now()
        update_fields.append('completed_at')
        obj.status = 'report_submitted'
        obj.save(update_fields=['status', 'updated_at'])

    inspection.save(update_fields=update_fields)

    for photo_file in request.FILES.getlist('after_photos'):
        if _is_valid_photo(photo_file):
            ContainerTransferPhoto.objects.create(
                request=obj, phase='after',
                file=photo_file, uploaded_by=request.user,
            )

    return redirect('container_detail', pk=pk)


# ── Inspector: reject request ────────────────────────────────────────────────

@login_required
@require_POST
def container_reject(request, pk):
    obj        = get_object_or_404(ContainerTransferRequest, pk=pk)
    inspection = get_object_or_404(ContainerTransferInspection, request=obj)

    if inspection.inspector_id != request.user.id and not _can_manage(request.user):
        return redirect('container_detail', pk=pk)

    if obj.status in ('closed', 'rejected'):
        return redirect('container_detail', pk=pk)

    reason = (request.POST.get('rejection_reason') or '').strip()
    if not reason:
        return redirect('container_detail', pk=pk)

    inspection.rejection_reason = reason
    inspection.rejected_by      = request.user
    inspection.rejected_at      = timezone.now()
    inspection.save(update_fields=['rejection_reason', 'rejected_by', 'rejected_at'])

    obj.status = 'rejected'
    obj.save(update_fields=['status', 'updated_at'])
    logger.info('Container request %s rejected by %s — reason: %s', pk, request.user, reason)
    return redirect('container_detail', pk=pk)


# ── Admin: close request ──────────────────────────────────────────────────────

@login_required
@require_POST
def container_close(request, pk):
    obj = get_object_or_404(ContainerTransferRequest, pk=pk)
    if not _can_manage(request.user):
        return redirect('container_detail', pk=pk)

    obj.status = 'closed'
    obj.save(update_fields=['status', 'updated_at'])
    logger.info('Container request %s closed by %s', pk, request.user)
    return redirect('container_detail', pk=pk)


# ── Photo delete ──────────────────────────────────────────────────────────────

@login_required
@require_POST
def container_photo_delete(request, pk, photo_pk):
    obj   = get_object_or_404(ContainerTransferRequest, pk=pk)
    photo = get_object_or_404(ContainerTransferPhoto, pk=photo_pk, request=obj)
    if _can_manage(request.user) or photo.uploaded_by_id == request.user.id:
        photo.file.delete(save=False)
        photo.delete()
    return redirect('container_detail', pk=pk)
