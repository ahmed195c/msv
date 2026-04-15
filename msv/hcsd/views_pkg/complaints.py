"""
Complaints system views.

URL prefix : /complaints/
Template dir: hcsd/complaints/
Language    : session key 'complaints_lang' → 'ar' (default) | 'en'

Workflow
--------
new → assigned_inspector → inspection_done → assigned_supervisor → in_progress → resolved → closed

Roles (re-use existing permit-system groups)
 - Admin/Data-Entry : assign inspector, assign supervisor, close
 - Any logged-in    : inspector fills inspection; supervisor fills resolution
   (assignment determines who can act on each phase)
"""

import logging
import os

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..models import (
    Complaint, ComplaintInspection, ComplaintMaterial, ComplaintPhoto,
    ComplaintResolution, ComplaintVehicle,
)
from .common import _can_admin, _can_data_entry

logger = logging.getLogger(__name__)

ALLOWED_PDF_EXTENSION = '.pdf'
ALLOWED_PHOTO_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}
LANG_AR = 'ar'
LANG_EN = 'en'


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_lang(request):
    lang = request.session.get('complaints_lang', LANG_AR)
    return lang if lang in (LANG_AR, LANG_EN) else LANG_AR


def _can_manage(user):
    """Admin or data-entry can assign and manage workflow."""
    return _can_admin(user) or _can_data_entry(user)


def _is_valid_pdf(file):
    _, ext = os.path.splitext(file.name)
    return ext.lower() == ALLOWED_PDF_EXTENSION


def _is_valid_photo(file):
    _, ext = os.path.splitext(file.name)
    return ext.lower() in ALLOWED_PHOTO_EXTENSIONS


# ── Language switch ───────────────────────────────────────────────────────────

@require_POST
def set_complaints_language(request):
    lang = (request.POST.get('lang') or LANG_AR).strip()
    if lang not in (LANG_AR, LANG_EN):
        lang = LANG_AR
    request.session['complaints_lang'] = lang
    next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or 'complaints_dashboard'
    if next_url.startswith('/'):
        from django.http import HttpResponseRedirect
        return HttpResponseRedirect(next_url)
    return redirect(next_url)


# ── Dashboard / List ──────────────────────────────────────────────────────────

@login_required
def complaints_dashboard(request):
    lang = _get_lang(request)
    status_filter = (request.GET.get('status') or 'all').strip()
    complaints = Complaint.objects.select_related('created_by').all()
    if status_filter != 'all':
        complaints = complaints.filter(status=status_filter)

    return render(request, 'hcsd/complaints/dashboard.html', {
        'complaints': complaints,
        'status_filter': status_filter,
        'status_choices': Complaint.STATUS_CHOICES,
        'lang': lang,
        'can_manage': _can_manage(request.user),
    })


# ── Submit ────────────────────────────────────────────────────────────────────

@login_required
def complaint_submit(request):
    lang = _get_lang(request)

    if request.method == 'POST':
        complaint_number = (request.POST.get('complaint_number') or '').strip()
        pdf_file = request.FILES.get('pdf_file')
        notes = (request.POST.get('notes') or '').strip()
        complainant_name = (request.POST.get('complainant_name') or '').strip()
        complainant_mobile = (request.POST.get('complainant_mobile') or '').strip()
        area = (request.POST.get('area') or '').strip()
        street_number = (request.POST.get('street_number') or '').strip()
        house_number = (request.POST.get('house_number') or '').strip()
        pest_types = ','.join(
            p for p in request.POST.getlist('pest_types')
            if p in {k for k, _ in Complaint.PEST_CHOICES}
        )

        errors = {}
        if not complaint_number:
            errors['complaint_number'] = (
                'Complaint number is required.' if lang == LANG_EN else 'رقم الشكوى مطلوب.'
            )
        if pdf_file and not _is_valid_pdf(pdf_file):
            errors['pdf_file'] = (
                'Only PDF files are accepted.' if lang == LANG_EN else 'يجب أن يكون الملف بصيغة PDF فقط.'
            )

        if not errors:
            complaint = Complaint.objects.create(
                complaint_number=complaint_number,
                pdf_file=pdf_file or None,
                notes=notes,
                complainant_name=complainant_name,
                complainant_mobile=complainant_mobile,
                area=area,
                street_number=street_number,
                house_number=house_number,
                pest_types=pest_types,
                created_by=request.user,
            )
            logger.info('Complaint %s created by %s', complaint.complaint_number, request.user)
            return redirect('complaint_detail', pk=complaint.pk)

        return render(request, 'hcsd/complaints/submit.html', {
            'errors': errors,
            'form_data': {
                'complaint_number': complaint_number, 'notes': notes,
                'complainant_name': complainant_name, 'complainant_mobile': complainant_mobile,
                'area': area, 'street_number': street_number, 'house_number': house_number,
                'pest_types': pest_types.split(','),
            },
            'lang': lang,
            'pest_choices': Complaint.PEST_CHOICES,
        })

    return render(request, 'hcsd/complaints/submit.html', {
        'errors': {}, 'form_data': {}, 'lang': lang,
        'pest_choices': Complaint.PEST_CHOICES,
    })


# ── Detail ────────────────────────────────────────────────────────────────────

@login_required
def complaint_detail(request, pk):
    lang = _get_lang(request)
    complaint = get_object_or_404(
        Complaint.objects.select_related('created_by')
        .prefetch_related('photos'),
        pk=pk,
    )
    inspection = getattr(complaint, 'inspection', None)
    resolution = getattr(complaint, 'resolution', None)
    vehicles = list(resolution.vehicles.all()) if resolution else []
    materials = list(resolution.materials.all()) if resolution else []
    staff_users = User.objects.filter(is_active=True).order_by('first_name', 'username')
    pest_label_map = dict(Complaint.PEST_CHOICES)
    complaint_pest_labels = [
        pest_label_map.get(p, p)
        for p in (complaint.pest_types or '').split(',')
        if p.strip()
    ]

    return render(request, 'hcsd/complaints/detail.html', {
        'complaint': complaint,
        'inspection': inspection,
        'resolution': resolution,
        'vehicles': vehicles,
        'materials': materials,
        'status_choices': Complaint.STATUS_CHOICES,
        'staff_users': staff_users,
        'lang': lang,
        'can_manage': _can_manage(request.user),
        'is_inspector': inspection and inspection.inspector_id == request.user.id,
        'is_supervisor': resolution and resolution.supervisor_id == request.user.id,
        'inspection_photos': complaint.photos.filter(phase='inspection'),
        'during_photos': complaint.photos.filter(phase='during_work'),
        'after_photos': complaint.photos.filter(phase='after_work'),
        'complaint_pest_labels': complaint_pest_labels,
        'closing_status_choices': ComplaintResolution.CLOSING_STATUS_CHOICES,
    })


# ── Assign inspector ──────────────────────────────────────────────────────────

@login_required
@require_POST
def complaint_assign_inspector(request, pk):
    complaint = get_object_or_404(Complaint, pk=pk)
    if not _can_manage(request.user):
        return redirect('complaint_detail', pk=pk)

    inspector_id = request.POST.get('inspector_id')
    if not inspector_id:
        return redirect('complaint_detail', pk=pk)

    inspector = get_object_or_404(User, pk=inspector_id, is_active=True)

    # Create or update inspection record
    inspection, _ = ComplaintInspection.objects.get_or_create(
        complaint=complaint,
        defaults={'inspector': inspector, 'assigned_by': request.user},
    )
    if not _:
        inspection.inspector = inspector
        inspection.assigned_by = request.user
        inspection.save(update_fields=['inspector', 'assigned_by'])

    complaint.status = 'assigned_inspector'
    complaint.save(update_fields=['status', 'updated_at'])
    logger.info('Complaint %s assigned to inspector %s by %s', complaint.pk, inspector, request.user)
    return redirect('complaint_detail', pk=pk)


# ── Inspector: save inspection data ──────────────────────────────────────────

@login_required
@require_POST
def complaint_inspection_save(request, pk):
    complaint = get_object_or_404(Complaint, pk=pk)
    inspection = get_object_or_404(ComplaintInspection, complaint=complaint)

    # Only assigned inspector or admin can update
    if inspection.inspector_id != request.user.id and not _can_manage(request.user):
        return redirect('complaint_detail', pk=pk)

    lat = (request.POST.get('latitude') or '').strip()
    lng = (request.POST.get('longitude') or '').strip()
    location_notes = (request.POST.get('location_notes') or '').strip()
    inspection_notes = (request.POST.get('inspection_notes') or '').strip()
    mark_done = request.POST.get('mark_done') == '1'

    update_fields = ['location_notes', 'inspection_notes']
    inspection.location_notes = location_notes
    inspection.inspection_notes = inspection_notes

    try:
        if lat:
            inspection.latitude = float(lat)
            update_fields.append('latitude')
        if lng:
            inspection.longitude = float(lng)
            update_fields.append('longitude')
    except ValueError:
        pass

    if mark_done and not inspection.completed_at:
        inspection.completed_at = timezone.now()
        update_fields.append('completed_at')
        complaint.status = 'inspection_done'
        complaint.save(update_fields=['status', 'updated_at'])

    inspection.save(update_fields=update_fields)

    # Upload inspection photos
    for photo_file in request.FILES.getlist('inspection_photos'):
        if _is_valid_photo(photo_file):
            ComplaintPhoto.objects.create(
                complaint=complaint,
                phase='inspection',
                file=photo_file,
                uploaded_by=request.user,
            )

    return redirect('complaint_detail', pk=pk)


# ── Assign supervisor ─────────────────────────────────────────────────────────

@login_required
@require_POST
def complaint_assign_supervisor(request, pk):
    complaint = get_object_or_404(Complaint, pk=pk)
    if not _can_manage(request.user):
        return redirect('complaint_detail', pk=pk)

    supervisor_id = request.POST.get('supervisor_id')
    if not supervisor_id:
        return redirect('complaint_detail', pk=pk)

    supervisor = get_object_or_404(User, pk=supervisor_id, is_active=True)

    resolution, _ = ComplaintResolution.objects.get_or_create(
        complaint=complaint,
        defaults={'supervisor': supervisor, 'assigned_by': request.user},
    )
    if not _:
        resolution.supervisor = supervisor
        resolution.assigned_by = request.user
        resolution.save(update_fields=['supervisor', 'assigned_by'])

    complaint.status = 'assigned_supervisor'
    complaint.save(update_fields=['status', 'updated_at'])
    logger.info('Complaint %s assigned to supervisor %s by %s', complaint.pk, supervisor, request.user)
    return redirect('complaint_detail', pk=pk)


# ── Supervisor: save resolution data ─────────────────────────────────────────

@login_required
@require_POST
def complaint_resolution_save(request, pk):
    complaint = get_object_or_404(Complaint, pk=pk)
    resolution = get_object_or_404(ComplaintResolution, complaint=complaint)

    if resolution.supervisor_id != request.user.id and not _can_manage(request.user):
        return redirect('complaint_detail', pk=pk)

    # Basic fields
    work_notes = (request.POST.get('work_notes') or '').strip()
    mark_done = request.POST.get('mark_done') == '1'
    closing_status = (request.POST.get('closing_status') or '').strip()
    valid_closing = {k for k, _ in ComplaintResolution.CLOSING_STATUS_CHOICES}
    update_fields = ['work_notes', 'closing_status']
    resolution.work_notes = work_notes
    resolution.closing_status = closing_status if closing_status in valid_closing else ''

    try:
        num_workers = int(request.POST.get('num_workers') or 0)
        if num_workers >= 0:
            resolution.num_workers = num_workers or None
            update_fields.append('num_workers')
    except ValueError:
        pass

    # Vehicles: replace all with submitted list
    plate_numbers = request.POST.getlist('plate_number')
    vehicle_types = request.POST.getlist('vehicle_type')
    resolution.vehicles.all().delete()
    for plate, vtype in zip(plate_numbers, vehicle_types):
        plate = plate.strip()
        if plate:
            ComplaintVehicle.objects.create(
                resolution=resolution,
                plate_number=plate,
                vehicle_type=vtype.strip(),
            )

    # Materials: replace all with submitted list
    mat_names = request.POST.getlist('material_name')
    mat_qtys = request.POST.getlist('material_qty')
    resolution.materials.all().delete()
    for name, qty in zip(mat_names, mat_qtys):
        name = name.strip()
        if name:
            ComplaintMaterial.objects.create(
                resolution=resolution,
                material_name=name,
                quantity=qty.strip(),
            )

    if mark_done and not resolution.completed_at:
        resolution.completed_at = timezone.now()
        update_fields.append('completed_at')
        # Auto-calculate days from inspector assignment to supervisor completion
        try:
            inspection = complaint.inspection
            delta = resolution.completed_at - inspection.assigned_at
            resolution.num_days = max(1, delta.days + (1 if delta.seconds > 0 else 0))
            update_fields.append('num_days')
        except ComplaintInspection.DoesNotExist:
            pass
        complaint.status = 'resolved'
        complaint.save(update_fields=['status', 'updated_at'])
    elif not resolution.completed_at:
        complaint.status = 'in_progress'
        complaint.save(update_fields=['status', 'updated_at'])

    resolution.save(update_fields=update_fields)

    # Upload work photos
    for phase in ('during_work', 'after_work'):
        for photo_file in request.FILES.getlist(f'{phase}_photos'):
            if _is_valid_photo(photo_file):
                ComplaintPhoto.objects.create(
                    complaint=complaint,
                    phase=phase,
                    file=photo_file,
                    uploaded_by=request.user,
                )

    return redirect('complaint_detail', pk=pk)


# ── Add photos (always allowed regardless of complaint status) ────────────────

@login_required
@require_POST
def complaint_add_photos(request, pk):
    """Upload photos to a complaint phase — allowed at any status."""
    complaint = get_object_or_404(Complaint, pk=pk)
    phase = (request.POST.get('phase') or '').strip()
    valid_phases = {p for p, _ in ComplaintPhoto.PHASE_CHOICES}
    if phase not in valid_phases:
        return redirect('complaint_detail', pk=pk)

    for photo_file in request.FILES.getlist('photos'):
        if _is_valid_photo(photo_file):
            ComplaintPhoto.objects.create(
                complaint=complaint,
                phase=phase,
                file=photo_file,
                uploaded_by=request.user,
            )
    return redirect('complaint_detail', pk=pk)


# ── Delete photo ──────────────────────────────────────────────────────────────

@login_required
@require_POST
def complaint_photo_delete(request, pk, photo_pk):
    complaint = get_object_or_404(Complaint, pk=pk)
    photo = get_object_or_404(ComplaintPhoto, pk=photo_pk, complaint=complaint)
    if _can_manage(request.user) or photo.uploaded_by_id == request.user.id:
        photo.file.delete(save=False)
        photo.delete()
    return redirect('complaint_detail', pk=pk)
