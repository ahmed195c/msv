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

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..models import (
    WeedRemovalRequest, WeedRemovalInspection,
    WeedRemovalSupervisorTask, WeedRemovalVehicle, WeedRemovalPhoto,
)
from .common import _can_admin, _can_data_entry
from .complaints import _get_lang

logger = logging.getLogger(__name__)

ALLOWED_PHOTO_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}


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

    is_inspector  = inspection and inspection.inspector_id == request.user.id
    is_supervisor = supervisor_task and supervisor_task.supervisor_id == request.user.id

    photos_before = obj.photos.filter(phase='before')
    photos_during = obj.photos.filter(phase='during')
    photos_after  = obj.photos.filter(phase='after')

    vehicles = supervisor_task.vehicles.all() if supervisor_task else []

    return render(request, 'hcsd/weed_removal/detail.html', {
        'obj': obj,
        'inspection': inspection,
        'supervisor_task': supervisor_task,
        'vehicles': vehicles,
        'staff_users': staff_users,
        'is_inspector': is_inspector,
        'is_supervisor': is_supervisor,
        'can_manage': _can_manage(request.user),
        'photos_before': photos_before,
        'photos_during': photos_during,
        'photos_after': photos_after,
        'status_choices': WeedRemovalRequest.STATUS_CHOICES,
        'vehicle_type_choices': WeedRemovalVehicle.VEHICLE_TYPE_CHOICES,
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


# ── Supervisor: save workers + start work ─────────────────────────────────────

@login_required
@require_POST
def weed_supervisor_start(request, pk):
    obj  = get_object_or_404(WeedRemovalRequest, pk=pk)
    task = get_object_or_404(WeedRemovalSupervisorTask, request=obj)

    if task.supervisor_id != request.user.id and not _can_manage(request.user):
        return redirect('weed_detail', pk=pk)

    workers_raw = (request.POST.get('workers_count') or '').strip()
    try:
        task.workers_count = int(workers_raw) if workers_raw else None
    except ValueError:
        task.workers_count = None
    task.save(update_fields=['workers_count'])

    if obj.status == 'supervisor_assigned':
        obj.status = 'work_in_progress'
        obj.save(update_fields=['status', 'updated_at'])

    return redirect('weed_detail', pk=pk)


# ── Supervisor: add vehicle ───────────────────────────────────────────────────

@login_required
@require_POST
def weed_add_vehicle(request, pk):
    obj  = get_object_or_404(WeedRemovalRequest, pk=pk)
    task = get_object_or_404(WeedRemovalSupervisorTask, request=obj)

    if task.supervisor_id != request.user.id and not _can_manage(request.user):
        return redirect('weed_detail', pk=pk)

    vehicle_type = (request.POST.get('vehicle_type') or '').strip()
    notes        = (request.POST.get('vehicle_notes') or '').strip()
    valid_types  = {k for k, _ in WeedRemovalVehicle.VEHICLE_TYPE_CHOICES}

    if vehicle_type in valid_types:
        count_raw = (request.POST.get('vehicle_count') or '1').strip()
        try:
            count = max(1, int(count_raw))
        except ValueError:
            count = 1
        WeedRemovalVehicle.objects.create(task=task, vehicle_type=vehicle_type, count=count, notes=notes)

    return redirect('weed_detail', pk=pk)


# ── Supervisor: delete vehicle ────────────────────────────────────────────────

@login_required
@require_POST
def weed_delete_vehicle(request, pk, vpk):
    obj     = get_object_or_404(WeedRemovalRequest, pk=pk)
    task    = get_object_or_404(WeedRemovalSupervisorTask, request=obj)
    vehicle = get_object_or_404(WeedRemovalVehicle, pk=vpk, task=task)

    if task.supervisor_id == request.user.id or _can_manage(request.user):
        vehicle.delete()

    return redirect('weed_detail', pk=pk)


# ── Supervisor: upload photos ─────────────────────────────────────────────────

@login_required
@require_POST
def weed_upload_photos(request, pk):
    obj  = get_object_or_404(WeedRemovalRequest, pk=pk)
    task = getattr(obj, 'supervisor_task', None)

    is_supervisor = task and task.supervisor_id == request.user.id
    if not is_supervisor and not _can_manage(request.user):
        return redirect('weed_detail', pk=pk)

    phase       = (request.POST.get('phase') or '').strip()
    valid_phases = {'during', 'after'}
    if phase not in valid_phases:
        return redirect('weed_detail', pk=pk)

    for photo_file in request.FILES.getlist('photos'):
        if _is_valid_photo(photo_file):
            WeedRemovalPhoto.objects.create(
                request=obj, phase=phase,
                file=photo_file, uploaded_by=request.user,
            )

    return redirect('weed_detail', pk=pk)


# ── Supervisor: submit final report ──────────────────────────────────────────

@login_required
@require_POST
def weed_supervisor_done(request, pk):
    obj  = get_object_or_404(WeedRemovalRequest, pk=pk)
    task = get_object_or_404(WeedRemovalSupervisorTask, request=obj)

    if task.supervisor_id != request.user.id and not _can_manage(request.user):
        return redirect('weed_detail', pk=pk)

    report_notes = (request.POST.get('report_notes') or '').strip()
    task.report_notes = report_notes
    update_fields = ['report_notes']

    if not task.completed_at:
        task.completed_at = timezone.now()
        update_fields.append('completed_at')
        obj.status = 'work_done'
        obj.save(update_fields=['status', 'updated_at'])

    task.save(update_fields=update_fields)
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
