"""
Field Work Orders views.

URL prefix : /field-work/
Templates  : hcsd/field_work_*.html
"""

import io
import logging
import os

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from ..models import FieldWorkOrder, FieldWorkPhoto
from .common import _can_admin, _can_data_entry

logger = logging.getLogger(__name__)

ALLOWED_PHOTO_EXTENSIONS = {'.jpg', '.jpeg', '.png'}


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

@login_required
def field_work_list(request):
    from django.core.paginator import Paginator
    from django.db.models import Q

    can_admin     = _can_admin(request.user)
    can_data_entry = _can_data_entry(request.user)

    status_filter = (request.GET.get('status') or 'all').strip()
    source_filter = (request.GET.get('source') or 'all').strip()
    search        = (request.GET.get('q')      or '').strip()

    orders = FieldWorkOrder.objects.select_related('created_by').all()

    if status_filter != 'all':
        orders = orders.filter(status=status_filter)
    if source_filter != 'all':
        orders = orders.filter(source=source_filter)
    if search:
        orders = orders.filter(
            Q(order_number__icontains=search)
            | Q(customer_name__icontains=search)
            | Q(area__icontains=search)
            | Q(supervisor_name__icontains=search)
            | Q(work_type__icontains=search)
            | Q(site_name__icontains=search)
        )

    paginator = Paginator(orders, 50)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    status_options = [('all', 'كل الحالات')] + list(FieldWorkOrder.STATUS_CHOICES)

    return render(request, 'hcsd/field_work_list.html', {
        'page_obj':      page_obj,
        'can_admin':     can_admin,
        'can_data_entry': can_data_entry,
        'status_filter': status_filter,
        'source_filter': source_filter,
        'search':        search,
        'status_options': status_options,
        'total_count':   orders.count(),
    })


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

@login_required
def field_work_create(request):
    if not (_can_admin(request.user) or _can_data_entry(request.user)):
        return redirect('field_work_list')

    errors = []

    if request.method == 'POST':
        site_name = (request.POST.get('site_name') or '').strip()
        work_type = (request.POST.get('work_type') or '').strip()
        location = (request.POST.get('location') or '').strip()
        description = (request.POST.get('description') or '').strip()
        work_date = (request.POST.get('work_date') or '').strip() or None
        notes = (request.POST.get('notes') or '').strip()

        if not work_type:
            errors.append('يرجى إدخال نوع العمل.')

        if not errors:
            order = FieldWorkOrder.objects.create(
                site_name=site_name,
                work_type=work_type,
                location=location,
                description=description,
                work_date=work_date,
                notes=notes,
                created_by=request.user,
            )
            return redirect('field_work_detail', pk=order.pk)

    return render(request, 'hcsd/field_work_create.html', {
        'errors': errors,
        'post': request.POST,
    })


# ---------------------------------------------------------------------------
# Detail
# ---------------------------------------------------------------------------

@login_required
def field_work_detail(request, pk):
    order = get_object_or_404(FieldWorkOrder.objects.select_related('created_by'), pk=pk)
    can_admin = _can_admin(request.user)
    can_data_entry = _can_data_entry(request.user)
    can_edit = can_admin or can_data_entry

    photos_before = order.photos.filter(phase='before').order_by('uploaded_at')
    photos_during = order.photos.filter(phase='during').order_by('uploaded_at')
    photos_after  = order.photos.filter(phase='after').order_by('uploaded_at')

    errors = []
    success = None

    if request.method == 'POST' and can_edit:
        action = (request.POST.get('action') or '').strip()

        # ── Update work details ──────────────────────────────────────────────
        if action == 'update_details':
            site_name   = (request.POST.get('site_name') or '').strip()
            work_type   = (request.POST.get('work_type') or '').strip()
            location    = (request.POST.get('location') or '').strip()
            description = (request.POST.get('description') or '').strip()
            work_date   = (request.POST.get('work_date') or '').strip() or None
            notes       = (request.POST.get('notes') or '').strip()
            workers_count_raw = (request.POST.get('workers_count') or '').strip()
            equipment   = (request.POST.get('equipment_used') or '').strip()

            if not work_type:
                errors.append('يرجى إدخال نوع العمل.')
            workers_count = None
            if workers_count_raw:
                try:
                    workers_count = int(workers_count_raw)
                    if workers_count < 0:
                        raise ValueError
                except ValueError:
                    errors.append('عدد العمال يجب أن يكون رقماً صحيحاً.')

            if not errors:
                order.site_name = site_name
                order.work_type = work_type
                order.location = location
                order.description = description
                order.work_date = work_date
                order.notes = notes
                order.workers_count = workers_count
                order.equipment_used = equipment
                order.save(update_fields=[
                    'site_name', 'work_type', 'location', 'description',
                    'work_date', 'notes', 'workers_count', 'equipment_used',
                ])
                success = 'تم حفظ التفاصيل.'

        # ── Update status ────────────────────────────────────────────────────
        elif action == 'update_status':
            new_status = (request.POST.get('status') or '').strip()
            work_completed_raw = request.POST.get('work_completed')
            valid_statuses = {s for s, _ in FieldWorkOrder.STATUS_CHOICES}
            if new_status not in valid_statuses:
                errors.append('حالة غير صحيحة.')
            else:
                order.status = new_status
                if new_status in ('completed', 'incomplete'):
                    order.work_completed = (new_status == 'completed')
                order.save(update_fields=['status', 'work_completed'])
                success = 'تم تحديث الحالة.'

        # ── Upload photos ────────────────────────────────────────────────────
        elif action == 'upload_photos':
            phase = (request.POST.get('phase') or '').strip()
            photos = request.FILES.getlist('photos')
            valid_phases = {'before', 'during', 'after'}
            if phase not in valid_phases:
                errors.append('يرجى اختيار مرحلة الصور.')
            elif not photos:
                errors.append('يرجى اختيار صورة واحدة على الأقل.')
            else:
                invalid = [
                    p.name for p in photos
                    if os.path.splitext(p.name)[1].lower() not in ALLOWED_PHOTO_EXTENSIONS
                ]
                if invalid:
                    errors.append('يُسمح فقط بصور JPG/PNG.')
                else:
                    for photo in photos:
                        FieldWorkPhoto.objects.create(
                            work_order=order,
                            phase=phase,
                            file=photo,
                            uploaded_by=request.user,
                        )
                    success = 'تم رفع الصور.'
                    # Refresh photo querysets
                    photos_before = order.photos.filter(phase='before').order_by('uploaded_at')
                    photos_during = order.photos.filter(phase='during').order_by('uploaded_at')
                    photos_after  = order.photos.filter(phase='after').order_by('uploaded_at')

        # ── Supervisor report ────────────────────────────────────────────────
        elif action == 'supervisor_report':
            new_status      = (request.POST.get('status') or '').strip()
            workers_raw     = (request.POST.get('workers_count') or '').strip()
            vehicles_raw    = (request.POST.get('vehicles_count') or '').strip()
            pesticides      = (request.POST.get('pesticides_used') or '').strip()
            sup_notes       = (request.POST.get('supervisor_notes') or '').strip()

            valid_statuses = {s for s, _ in FieldWorkOrder.STATUS_CHOICES}
            if new_status not in valid_statuses:
                errors.append('يرجى اختيار الحالة.')
            else:
                def _to_int(val):
                    try:
                        v = int(val)
                        return v if v >= 0 else None
                    except (ValueError, TypeError):
                        return None

                order.status           = new_status
                order.workers_count    = _to_int(workers_raw)
                order.vehicles_count   = _to_int(vehicles_raw)
                order.pesticides_used  = pesticides
                order.supervisor_notes = sup_notes
                order.report_submitted_by = request.user
                order.report_submitted_at = timezone.now()
                order.save(update_fields=[
                    'status', 'workers_count', 'vehicles_count',
                    'pesticides_used', 'supervisor_notes',
                    'report_submitted_by', 'report_submitted_at',
                ])
                success = 'تم حفظ تقرير المراقب.'

        # ── Delete photo ─────────────────────────────────────────────────────
        elif action == 'delete_photo':
            photo_id = (request.POST.get('photo_id') or '').strip()
            try:
                photo = FieldWorkPhoto.objects.get(id=photo_id, work_order=order)
                photo.file.delete(save=False)
                photo.delete()
                success = 'تم حذف الصورة.'
                photos_before = order.photos.filter(phase='before').order_by('uploaded_at')
                photos_during = order.photos.filter(phase='during').order_by('uploaded_at')
                photos_after  = order.photos.filter(phase='after').order_by('uploaded_at')
            except FieldWorkPhoto.DoesNotExist:
                errors.append('الصورة غير موجودة.')

        if not errors:
            return redirect('field_work_detail', pk=order.pk)

    return render(request, 'hcsd/field_work_detail.html', {
        'order': order,
        'can_edit': can_edit,
        'can_admin': can_admin,
        'photos_before': photos_before,
        'photos_during': photos_during,
        'photos_after': photos_after,
        'errors': errors,
        'success': success,
    })


# ---------------------------------------------------------------------------
# Word Report
# ---------------------------------------------------------------------------

@login_required
def field_work_report(request, pk):
    order = get_object_or_404(FieldWorkOrder.objects.select_related('created_by'), pk=pk)

    try:
        from docx import Document
        from docx.shared import Inches, Pt, RGBColor
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.oxml.ns import qn
        from docx.oxml import OxmlElement
    except ImportError:
        return HttpResponse('مكتبة python-docx غير مثبتة.', status=500)

    doc = Document()

    # ── Page setup: A4, Arabic RTL ──────────────────────────────────────────
    section = doc.sections[0]
    section.page_width  = int(8.27 * 914400)
    section.page_height = int(11.69 * 914400)
    section.left_margin = section.right_margin = int(1 * 914400)
    section.top_margin  = section.bottom_margin = int(1 * 914400)

    def set_rtl(paragraph):
        pPr = paragraph._p.get_or_add_pPr()
        bidi = OxmlElement('w:bidi')
        pPr.append(bidi)
        paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT

    def add_heading(text, level=1):
        p = doc.add_paragraph()
        set_rtl(p)
        run = p.add_run(text)
        run.bold = True
        run.font.size = Pt(16 if level == 1 else 13)
        run.font.color.rgb = RGBColor(0x1a, 0x3a, 0x5c)
        return p

    def add_field(label, value):
        p = doc.add_paragraph()
        set_rtl(p)
        lbl = p.add_run(f'{label}: ')
        lbl.bold = True
        lbl.font.size = Pt(11)
        val = p.add_run(str(value) if value else '—')
        val.font.size = Pt(11)

    def add_section_title(text):
        p = doc.add_paragraph()
        set_rtl(p)
        run = p.add_run(text)
        run.bold = True
        run.font.size = Pt(12)
        run.font.color.rgb = RGBColor(0x2a, 0x6a, 0x9a)
        doc.add_paragraph()

    # ── Title ───────────────────────────────────────────────────────────────
    title = doc.add_paragraph()
    set_rtl(title)
    t = title.add_run('تقرير أمر العمل الميداني')
    t.bold = True
    t.font.size = Pt(20)
    t.font.color.rgb = RGBColor(0x1a, 0x3a, 0x5c)
    doc.add_paragraph()

    # ── Basic info ──────────────────────────────────────────────────────────
    add_heading('معلومات الطلب', level=1)
    add_field('رقم الأمر', f'#{order.pk}')
    add_field('نوع العمل', order.work_type)
    add_field('اسم الموقع', order.site_name or None)
    add_field('العنوان', order.location or None)
    add_field('تاريخ التنفيذ', order.work_date.strftime('%d/%m/%Y') if order.work_date else None)
    add_field('تاريخ الإنشاء', order.created_at.strftime('%d/%m/%Y'))
    add_field('الحالة', order.get_status_display())
    doc.add_paragraph()

    # ── Work details ────────────────────────────────────────────────────────
    add_heading('تفاصيل العمل', level=1)
    add_field('عدد العمال', order.workers_count)
    add_field('المعدات المستخدمة', order.equipment_used or None)
    add_field('اكتملت العملية', 'نعم' if order.work_completed is True else ('لا' if order.work_completed is False else None))
    if order.description:
        add_field('وصف العمل', order.description)
    if order.notes:
        add_field('ملاحظات', order.notes)
    doc.add_paragraph()

    # ── Photos ──────────────────────────────────────────────────────────────
    phases = [
        ('before', 'صور قبل العمل'),
        ('during', 'صور أثناء العمل'),
        ('after',  'صور بعد العمل'),
    ]
    for phase_key, phase_label in phases:
        phase_photos = list(order.photos.filter(phase=phase_key).order_by('uploaded_at'))
        if not phase_photos:
            continue
        add_section_title(phase_label)
        for photo in phase_photos:
            try:
                photo_path = photo.file.path
                if os.path.exists(photo_path):
                    doc.add_picture(photo_path, width=Inches(4.5))
                    if photo.caption:
                        cap = doc.add_paragraph(photo.caption)
                        set_rtl(cap)
                    doc.add_paragraph()
            except Exception:
                logger.exception('Failed to add photo %s to Word report', photo.pk)

    # ── Output ──────────────────────────────────────────────────────────────
    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)

    filename = f'field_work_{order.pk}.docx'
    response = HttpResponse(
        buffer.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
