"""
Weed Removal views.

URL prefix : /weed-removal/
Templates  : hcsd/weed_removal/

Workflow
--------
new → inspector_assigned → inspection_done → supervisor_assigned
    → work_in_progress → work_done → closed
    (rejected at any active step by inspector or admin)
"""

import logging
import os
import re

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.files.storage import default_storage
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..models import (
    WeedRemovalRequest, WeedRemovalInspection,
    WeedRemovalSupervisorTask, WeedRemovalVehicle, WeedRemovalPhoto,
    WeedRemovalWorkSession, WeedRemovalSessionVehicle,
)
from .common import _can_admin, _can_data_entry
from .complaints import _get_lang, _fix_rtl_pdf_text, _arabic_digits_to_western

logger = logging.getLogger(__name__)

ALLOWED_PHOTO_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}
ALLOWED_PDF_EXTENSION = '.pdf'
_PDF_IMPORT_SESSION_KEY = 'weed_pdf_import'


def _can_manage(user):
    return _can_admin(user) or _can_data_entry(user)


def _is_valid_photo(file):
    _, ext = os.path.splitext(file.name)
    return ext.lower() in ALLOWED_PHOTO_EXTENSIONS


# ── List ──────────────────────────────────────────────────────────────────────

@login_required
def weed_list(request):
    from django.db.models import Q, Count
    lang = _get_lang(request)
    status_filter = (request.GET.get('status') or 'all').strip()
    search        = (request.GET.get('q') or '').strip()

    qs = WeedRemovalRequest.objects.select_related('created_by').all()

    status_counts = {s: 0 for s, _ in WeedRemovalRequest.STATUS_CHOICES}
    for row in qs.values('status').annotate(n=Count('id')):
        status_counts[row['status']] = row['n']
    total_count = sum(status_counts.values())

    if status_filter != 'all':
        qs = qs.filter(status=status_filter)
    if search:
        qs = qs.filter(
            Q(complaint_number__icontains=search)
            | Q(complainant_name__icontains=search)
            | Q(area__icontains=search)
        )

    return render(request, 'hcsd/weed_removal/list.html', {
        'requests': qs,
        'status_filter': status_filter,
        'status_choices': WeedRemovalRequest.STATUS_CHOICES,
        'status_counts': status_counts,
        'total_count': total_count,
        'search': search,
        'can_manage': _can_manage(request.user),
        'lang': lang,
    })


# ── Create ────────────────────────────────────────────────────────────────────

@login_required
def weed_create(request):
    if not _can_manage(request.user):
        return redirect('weed_list')
    lang = _get_lang(request)
    errors = {}

    if request.method == 'POST':
        complaint_number   = (request.POST.get('complaint_number') or '').strip()
        complainant_name   = (request.POST.get('complainant_name') or '').strip()
        complainant_mobile = (request.POST.get('complainant_mobile') or '').strip()
        area               = (request.POST.get('area') or '').strip()
        house_number       = (request.POST.get('house_number') or '').strip()
        notes              = (request.POST.get('notes') or '').strip()
        pdf_file           = request.FILES.get('pdf_file')

        if not complaint_number:
            errors['complaint_number'] = 'رقم الشكوى مطلوب.'

        if not errors:
            obj = WeedRemovalRequest.objects.create(
                complaint_number=complaint_number,
                complainant_name=complainant_name,
                complainant_mobile=complainant_mobile,
                area=area,
                house_number=house_number,
                notes=notes,
                created_by=request.user,
            )
            if pdf_file:
                obj.pdf_file = pdf_file
                obj.save(update_fields=['pdf_file'])
            return redirect('weed_detail', pk=obj.pk)

    return render(request, 'hcsd/weed_removal/create.html', {
        'errors': errors,
        'post': request.POST,
        'lang': lang,
    })


# ── Detail ────────────────────────────────────────────────────────────────────

@login_required
def weed_detail(request, pk):
    lang = _get_lang(request)
    obj  = get_object_or_404(WeedRemovalRequest.objects.select_related('created_by'), pk=pk)

    inspection      = getattr(obj, 'inspection', None)
    supervisor_task = getattr(obj, 'supervisor_task', None)
    staff_users     = User.objects.filter(is_active=True).order_by('first_name', 'username')

    can_manage    = _can_manage(request.user)
    is_inspector  = bool(inspection)  if can_manage else (inspection  and inspection.inspector_id       == request.user.id)
    is_supervisor = bool(supervisor_task) if can_manage else (supervisor_task and supervisor_task.supervisor_id == request.user.id)

    photos_before = obj.photos.filter(phase='before')
    photos_during = obj.photos.filter(phase='during')
    photos_after  = obj.photos.filter(phase='after')

    current_session = None
    work_sessions   = []
    session_summary = None
    if supervisor_task:
        all_sessions = list(
            supervisor_task.work_sessions
            .prefetch_related('vehicles', 'photos')
            .order_by('started_at')
        )
        current_session = next((s for s in all_sessions if s.ended_at is None), None)
        work_sessions   = [s for s in all_sessions if s.ended_at is not None]

        for s in work_sessions:
            _p = list(s.photos.all())
            s.photos_start  = [p for p in _p if p.phase == 'before']
            s.photos_during = [p for p in _p if p.phase == 'during']
            s.photos_end    = [p for p in _p if p.phase == 'after']

        if all_sessions:
            first_start = all_sessions[0].started_at
            closed = [s for s in all_sessions if s.ended_at is not None]
            if closed:
                last_end   = closed[-1].ended_at
                total_days = (last_end.date() - first_start.date()).days + 1
                work_dates = {s.started_at.date() for s in all_sessions}
                session_summary = {
                    'first_start': first_start,
                    'last_end':    last_end,
                    'total_days':  total_days,
                    'work_days':   len(work_dates),
                    'idle_days':   total_days - len(work_dates),
                }

    return render(request, 'hcsd/weed_removal/detail.html', {
        'obj': obj,
        'inspection': inspection,
        'supervisor_task': supervisor_task,
        'current_session': current_session,
        'work_sessions': work_sessions,
        'session_summary': session_summary,
        'staff_users': staff_users,
        'is_inspector': is_inspector,
        'is_supervisor': is_supervisor,
        'can_manage': can_manage,
        'photos_before': photos_before,
        'photos_during': photos_during,
        'photos_after': photos_after,
        'status_choices': WeedRemovalRequest.STATUS_CHOICES,
        'vehicle_type_choices': WeedRemovalSessionVehicle.VEHICLE_TYPE_CHOICES,
        'lang': lang,
    })


# ── Assign Inspector ──────────────────────────────────────────────────────────

@login_required
@require_POST
def weed_assign_inspector(request, pk):
    obj = get_object_or_404(WeedRemovalRequest, pk=pk)
    if not _can_manage(request.user):
        return redirect('weed_detail', pk=pk)

    inspector_id = request.POST.get('inspector_id')
    if not inspector_id:
        return redirect('weed_detail', pk=pk)

    inspector = get_object_or_404(User, pk=inspector_id, is_active=True)
    inspection, created = WeedRemovalInspection.objects.get_or_create(
        request=obj,
        defaults={'inspector': inspector, 'assigned_by': request.user},
    )
    if not created:
        inspection.inspector   = inspector
        inspection.assigned_by = request.user
        inspection.save(update_fields=['inspector', 'assigned_by'])

    obj.status = 'inspector_assigned'
    obj.save(update_fields=['status', 'updated_at'])
    return redirect('weed_detail', pk=pk)


# ── Inspector: complete inspection + upload before photos ─────────────────────

@login_required
@require_POST
def weed_inspector_done(request, pk):
    obj        = get_object_or_404(WeedRemovalRequest, pk=pk)
    inspection = get_object_or_404(WeedRemovalInspection, request=obj)

    if inspection.inspector_id != request.user.id and not _can_manage(request.user):
        return redirect('weed_detail', pk=pk)

    notes = (request.POST.get('inspection_notes') or '').strip()
    inspection.inspection_notes = notes
    update_fields = ['inspection_notes']

    if not inspection.completed_at:
        inspection.completed_at = timezone.now()
        update_fields.append('completed_at')
        obj.status = 'inspection_done'
        obj.save(update_fields=['status', 'updated_at'])

    inspection.save(update_fields=update_fields)

    for photo_file in request.FILES.getlist('before_photos'):
        if _is_valid_photo(photo_file):
            WeedRemovalPhoto.objects.create(
                request=obj, phase='before',
                file=photo_file, uploaded_by=request.user,
            )

    return redirect('weed_detail', pk=pk)


# ── Assign Supervisor ─────────────────────────────────────────────────────────

@login_required
@require_POST
def weed_assign_supervisor(request, pk):
    obj = get_object_or_404(WeedRemovalRequest, pk=pk)
    if not _can_manage(request.user):
        return redirect('weed_detail', pk=pk)

    supervisor_id = request.POST.get('supervisor_id')
    if not supervisor_id:
        return redirect('weed_detail', pk=pk)

    supervisor = get_object_or_404(User, pk=supervisor_id, is_active=True)
    task, created = WeedRemovalSupervisorTask.objects.get_or_create(
        request=obj,
        defaults={'supervisor': supervisor, 'assigned_by': request.user},
    )
    if not created:
        task.supervisor  = supervisor
        task.assigned_by = request.user
        task.save(update_fields=['supervisor', 'assigned_by'])

    obj.status = 'supervisor_assigned'
    obj.save(update_fields=['status', 'updated_at'])
    return redirect('weed_detail', pk=pk)


# ── Supervisor: start a work session ─────────────────────────────────────────

@login_required
@require_POST
def weed_work_start(request, pk):
    obj  = get_object_or_404(WeedRemovalRequest, pk=pk)
    task = get_object_or_404(WeedRemovalSupervisorTask, request=obj)

    if task.supervisor_id != request.user.id and not _can_manage(request.user):
        return redirect('weed_detail', pk=pk)

    already_open = task.work_sessions.filter(ended_at__isnull=True).exists()
    if obj.status not in ('supervisor_assigned', 'work_paused') or already_open:
        return redirect('weed_detail', pk=pk)

    # First session: save workers_count from form
    if obj.status == 'supervisor_assigned':
        workers_raw = (request.POST.get('workers_count') or '').strip()
        try:
            task.workers_count = int(workers_raw) if workers_raw else None
        except ValueError:
            task.workers_count = None
        task.save(update_fields=['workers_count'])

    started_at = timezone.now()
    time_raw = (request.POST.get('start_time') or '').strip()
    if time_raw:
        try:
            import datetime as dt
            h, m = map(int, time_raw.split(':'))
            local_now = timezone.localtime(started_at)
            started_at = started_at.replace(
                hour=h, minute=m, second=0, microsecond=0,
                tzinfo=local_now.tzinfo,
            )
        except (ValueError, AttributeError):
            pass

    WeedRemovalWorkSession.objects.create(task=task, started_at=started_at)
    obj.status = 'work_in_progress'
    obj.save(update_fields=['status', 'updated_at'])
    return redirect('weed_detail', pk=pk)


# ── Supervisor: submit daily report (postpone or complete) ───────────────────

_SESSION_VEHICLE_TYPES = ('pickup', 'bobcat', 'tractor', 'truck', 'loader', 'other')

@login_required
@require_POST
def weed_report_submit(request, pk):
    obj  = get_object_or_404(WeedRemovalRequest, pk=pk)
    task = get_object_or_404(WeedRemovalSupervisorTask, request=obj)

    if task.supervisor_id != request.user.id and not _can_manage(request.user):
        return redirect('weed_detail', pk=pk)

    if obj.status != 'work_in_progress':
        return redirect('weed_detail', pk=pk)

    session = task.work_sessions.filter(ended_at__isnull=True).last()
    if not session:
        # Legacy: request entered work_in_progress before session tracking existed — auto-open one
        session = WeedRemovalWorkSession.objects.create(task=task, started_at=timezone.now())

    # Save workers + notes to session
    workers_raw = (request.POST.get('workers_count') or '').strip()
    try:
        session.workers_count = int(workers_raw) if workers_raw else None
    except ValueError:
        session.workers_count = None
    session.notes = (request.POST.get('notes') or '').strip()

    # Save vehicles — replace existing for this session
    session.vehicles.all().delete()
    for vtype in _SESSION_VEHICLE_TYPES:
        if request.POST.get(f'{vtype}_checked'):
            try:
                count = max(1, min(99, int(request.POST.get(f'{vtype}_count', '1'))))
            except (ValueError, TypeError):
                count = 1
            WeedRemovalSessionVehicle.objects.create(
                session=session, vehicle_type=vtype, count=count,
            )

    # Save photos (start / during / end) linked to this session
    for phase, field in (('before', 'start_photos'), ('during', 'during_photos'), ('after', 'end_photos')):
        for photo_file in request.FILES.getlist(field):
            if _is_valid_photo(photo_file):
                WeedRemovalPhoto.objects.create(
                    request=obj, session=session, phase=phase,
                    file=photo_file, uploaded_by=request.user,
                )

    action = (request.POST.get('action') or '').strip()
    now = timezone.now()

    if action == 'postpone':
        session.ended_at = now
        session.end_type = 'postponed'
        session.save(update_fields=['workers_count', 'notes', 'ended_at', 'end_type'])
        obj.status = 'work_paused'
        obj.save(update_fields=['status', 'updated_at'])

    elif action == 'complete':
        session.ended_at = now
        session.end_type = 'completed'
        session.save(update_fields=['workers_count', 'notes', 'ended_at', 'end_type'])
        if not task.completed_at:
            task.completed_at = now
            task.save(update_fields=['completed_at'])
        obj.status = 'work_done'
        obj.save(update_fields=['status', 'updated_at'])

    else:
        session.save(update_fields=['workers_count', 'notes'])

    return redirect('weed_detail', pk=pk)


# ── Add photos (after completion) ─────────────────────────────────────────────

@login_required
@require_POST
def weed_add_photos(request, pk):
    obj  = get_object_or_404(WeedRemovalRequest, pk=pk)
    task = getattr(obj, 'supervisor_task', None)

    if not _can_manage(request.user) and (not task or task.supervisor_id != request.user.id):
        return redirect('weed_detail', pk=pk)

    phase = request.POST.get('phase', 'after')
    if phase not in ('before', 'during', 'after'):
        phase = 'after'

    last_session = task.work_sessions.order_by('-started_at').first() if task else None

    for photo_file in request.FILES.getlist('photos'):
        if _is_valid_photo(photo_file):
            WeedRemovalPhoto.objects.create(
                request=obj, phase=phase,
                session=last_session,
                file=photo_file, uploaded_by=request.user,
            )

    return redirect('weed_detail', pk=pk)


# ── Reject ────────────────────────────────────────────────────────────────────

@login_required
@require_POST
def weed_reject(request, pk):
    obj        = get_object_or_404(WeedRemovalRequest, pk=pk)
    inspection = get_object_or_404(WeedRemovalInspection, request=obj)

    if inspection.inspector_id != request.user.id and not _can_manage(request.user):
        return redirect('weed_detail', pk=pk)

    if obj.status in ('closed', 'rejected'):
        return redirect('weed_detail', pk=pk)

    reason = (request.POST.get('rejection_reason') or '').strip()
    if not reason:
        return redirect('weed_detail', pk=pk)

    inspection.rejection_reason = reason
    inspection.rejected_by      = request.user
    inspection.rejected_at      = timezone.now()
    inspection.save(update_fields=['rejection_reason', 'rejected_by', 'rejected_at'])

    obj.status = 'rejected'
    obj.save(update_fields=['status', 'updated_at'])
    logger.info('WeedRemoval %s rejected by %s', pk, request.user)
    return redirect('weed_detail', pk=pk)


# ── Close ─────────────────────────────────────────────────────────────────────

@login_required
@require_POST
def weed_close(request, pk):
    obj = get_object_or_404(WeedRemovalRequest, pk=pk)
    if not _can_manage(request.user):
        return redirect('weed_detail', pk=pk)
    obj.status = 'closed'
    obj.save(update_fields=['status', 'updated_at'])
    return redirect('weed_detail', pk=pk)


# ── Delete photo ──────────────────────────────────────────────────────────────

@login_required
@require_POST
def weed_photo_delete(request, pk, ppk):
    obj   = get_object_or_404(WeedRemovalRequest, pk=pk)
    photo = get_object_or_404(WeedRemovalPhoto, pk=ppk, request=obj)
    if _can_manage(request.user) or photo.uploaded_by_id == request.user.id:
        photo.file.delete(save=False)
        photo.delete()
    return redirect('weed_detail', pk=pk)


# ── Save location ─────────────────────────────────────────────────────────────

@login_required
@require_POST
def weed_save_location(request, pk):
    obj        = get_object_or_404(WeedRemovalRequest, pk=pk)
    inspection = get_object_or_404(WeedRemovalInspection, request=obj)

    if inspection.inspector_id != request.user.id and not _can_manage(request.user):
        return redirect('weed_detail', pk=pk)

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

    inspection.save(update_fields=update_fields)
    return redirect('weed_detail', pk=pk)


# ── PDF Import ─────────────────────────────────────────────────────────────────

def _is_valid_pdf(file):
    _, ext = os.path.splitext(file.name)
    return ext.lower() == ALLOWED_PDF_EXTENSION


def _extract_weed_from_pdf(pdf_file):
    """Read a Sharjah Municipality weed removal PDF and return a dict of fields."""
    try:
        import pdfplumber
    except ImportError:
        logger.warning('pdfplumber not installed; PDF extraction skipped')
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
            raw_lines = []
            for page in pdf.pages:
                page_text = page.extract_text(x_tolerance=3, y_tolerance=3) or ''
                raw_lines.extend(page_text.splitlines())

        full = _fix_rtl_pdf_text('\n'.join(raw_lines))

        field_patterns = [
            ('complaint_number',   [r'رقم الشكوى\s+([0-9]+)']),
            ('complainant_name',   [r'(.+)\nاسم المشتكي', r'اسم المشتكي\s+(.+)']),
            ('complainant_mobile', [r'(?:متحرك|ثابت)\s+الرقم\s+([0-9]{7,15})',
                                    r'الرقم\s+([0-9]{7,15})']),
            ('area',               [r'موقع الشكوى\s+(.+)']),
            ('notes',              [r'تفاصيل الشكوى\s+(.+)']),
        ]

        for field, patterns in field_patterns:
            for pat in patterns:
                m = re.search(pat, full, re.MULTILINE)
                if m:
                    data[field] = m.group(1).strip()
                    break

        if data['notes']:
            m = re.search(r'منزل\s+([0-9]+)', data['notes'])
            if m:
                data['house_number'] = m.group(1)

        m_notes_extra = re.search(r'ملاحظات\s+(.+)', full)
        if m_notes_extra and not data['notes']:
            data['notes'] = m_notes_extra.group(1).strip()

    except Exception:
        logger.warning('Weed PDF extraction error', exc_info=True)

    return data


@login_required
def weed_pdf_import(request):
    if not _can_manage(request.user):
        return redirect('weed_list')
    lang = _get_lang(request)
    error = None

    if request.method == 'POST':
        pdf_file = request.FILES.get('pdf_file')
        if not pdf_file:
            error = 'يرجى اختيار ملف PDF.'
        elif not _is_valid_pdf(pdf_file):
            error = 'يجب أن يكون الملف بصيغة PDF فقط.'
        else:
            extracted = _extract_weed_from_pdf(pdf_file)
            pdf_file.seek(0)
            saved_name = default_storage.save(f'weed_removal/pdfs/{pdf_file.name}', pdf_file)
            request.session[_PDF_IMPORT_SESSION_KEY] = {
                **extracted,
                'pdf_saved_name': saved_name,
                'pdf_original_name': pdf_file.name,
            }
            return redirect('weed_pdf_review')

    return render(request, 'hcsd/weed_removal/pdf_import.html', {
        'lang': lang,
        'error': error,
    })


@login_required
def weed_pdf_review(request):
    if not _can_manage(request.user):
        return redirect('weed_list')
    lang = _get_lang(request)
    session_data = request.session.get(_PDF_IMPORT_SESSION_KEY)

    if not session_data:
        return redirect('weed_pdf_import')

    if request.method == 'POST':
        complaint_number   = (request.POST.get('complaint_number') or '').strip()
        complainant_name   = (request.POST.get('complainant_name') or '').strip()
        complainant_mobile = (request.POST.get('complainant_mobile') or '').strip()
        area               = (request.POST.get('area') or '').strip()
        house_number       = (request.POST.get('house_number') or '').strip()
        notes              = (request.POST.get('notes') or '').strip()

        if not complaint_number:
            return render(request, 'hcsd/weed_removal/pdf_review.html', {
                'lang': lang,
                'form_data': request.POST,
                'pdf_original_name': session_data.get('pdf_original_name', ''),
                'errors': {'complaint_number': 'رقم الشكوى مطلوب.'},
            })

        obj = WeedRemovalRequest.objects.create(
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
            WeedRemovalRequest.objects.filter(pk=obj.pk).update(pdf_file=pdf_saved)

        del request.session[_PDF_IMPORT_SESSION_KEY]
        logger.info('WeedRemovalRequest %s created via PDF import by %s', obj.complaint_number, request.user)
        return redirect('weed_detail', pk=obj.pk)

    form_data = {
        'complaint_number':   session_data.get('complaint_number', ''),
        'complainant_name':   session_data.get('complainant_name', ''),
        'complainant_mobile': session_data.get('complainant_mobile', ''),
        'area':               session_data.get('area', ''),
        'house_number':       session_data.get('house_number', ''),
        'notes':              session_data.get('notes', ''),
    }
    return render(request, 'hcsd/weed_removal/pdf_review.html', {
        'lang': lang,
        'form_data': form_data,
        'pdf_original_name': session_data.get('pdf_original_name', ''),
        'errors': {},
    })
