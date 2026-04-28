"""
Field Work Orders views.

URL prefix : /field-work/
Templates  : hcsd/field_work_*.html
"""

import datetime as _dt
import io
import logging
import os

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
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


# ---------------------------------------------------------------------------
# Excel Import
# ---------------------------------------------------------------------------

_EXCEL_SESSION_KEY    = 'fw_excel_import'
_MAX_EXCEL_ROWS       = 2000
_ALLOWED_EXCEL_EXTS   = {'.xlsx', '.xls'}

_COL_MAP = {
    'رقم الطلب': 'order_number',    'رقم الامر': 'order_number',
    'رقم الأمر': 'order_number',    'order no': 'order_number',
    'order number': 'order_number', 'order_no': 'order_number',
    'تاريخ الطلب': 'request_date',  'request date': 'request_date',
    'تاريخ الإغلاق': 'close_date',  'تاريخ الاغلاق': 'close_date',
    'close date': 'close_date',
    'اسم المتعامل': 'customer_name','اسم العميل': 'customer_name',
    'المتعامل': 'customer_name',    'customer': 'customer_name',
    'customer name': 'customer_name',
    'الموبايل': 'mobile',           'الجوال': 'mobile',
    'رقم الهاتف': 'mobile',         'mobile': 'mobile',
    'phone': 'mobile',
    'المنطقة': 'area',              'area': 'area',
    'رقم الشارع': 'street_number',  'الشارع': 'street_number',
    'street': 'street_number',      'street no': 'street_number',
    'رقم المنزل': 'house_number',   'house': 'house_number',
    'house no': 'house_number',
    'نوع الحشرات': 'pest_types',    'الحشرات': 'pest_types',
    'pest': 'pest_types',           'pest type': 'pest_types',
    'المشرف المعالج': 'supervisor_name', 'المشرف': 'supervisor_name',
    'supervisor': 'supervisor_name',
    'العامل': 'worker_name',        'worker': 'worker_name',
    'حالة الطلب': 'excel_status',   'الحالة': 'excel_status',
    'status': 'excel_status',
    'ملاحظة الحالة': 'excel_status_note', 'ملاحظة': 'excel_status_note',
    'note': 'excel_status_note',    'notes': 'excel_status_note',
    'الشهر': 'month_sheet',         'month': 'month_sheet',
}


def _norm_header(h):
    return ' '.join(str(h or '').strip().lower().split())


def _parse_xl_date(val):
    if val is None:
        return ''
    if isinstance(val, (_dt.datetime, _dt.date)):
        d = val.date() if isinstance(val, _dt.datetime) else val
        return d.isoformat()
    s = str(val).strip()
    for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y', '%m/%d/%Y'):
        try:
            return _dt.datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    return s


def _to_date(s):
    if not s:
        return None
    try:
        return _dt.date.fromisoformat(s)
    except ValueError:
        return None


def _str_val(v):
    return '' if v is None else str(v).strip()


def _extract_excel_rows(file_obj):
    """Return (rows, error_message). rows = list[dict]."""
    try:
        import openpyxl
        wb = openpyxl.load_workbook(file_obj, read_only=True, data_only=True)
    except Exception:
        return [], 'تعذّر قراءة الملف — تأكد أنه ملف Excel صالح (.xlsx).'

    ws = wb.active
    it = ws.iter_rows(values_only=True)

    header_row = None
    for row in it:
        if any(c is not None for c in row):
            header_row = row
            break
    if header_row is None:
        return [], 'الملف فارغ أو لا يحتوي على بيانات.'

    col_map = {}
    for idx, cell in enumerate(header_row):
        field = _COL_MAP.get(_norm_header(cell))
        if field:
            col_map[idx] = field

    if not col_map:
        return [], 'لم يتم التعرف على أعمدة الملف. تأكد أن الصف الأول يحتوي على عناوين الأعمدة.'

    rows = []
    for row in it:
        if not any(c is not None for c in row):
            continue
        rec = {}
        for idx, field in col_map.items():
            val = row[idx] if idx < len(row) else None
            rec[field] = _parse_xl_date(val) if field in ('request_date', 'close_date') else _str_val(val)
        if not any(v for v in rec.values()):
            continue
        rows.append(rec)
        if len(rows) >= _MAX_EXCEL_ROWS:
            break

    return rows, ''


@login_required
def field_work_excel_import(request):
    if not (_can_admin(request.user) or _can_data_entry(request.user)):
        return redirect('field_work_list')

    error = ''
    if request.method == 'POST':
        f = request.FILES.get('excel_file')
        if not f:
            error = 'يرجى اختيار ملف Excel.'
        elif os.path.splitext(f.name)[1].lower() not in _ALLOWED_EXCEL_EXTS:
            error = 'يُسمح فقط بملفات .xlsx أو .xls'
        else:
            rows, err = _extract_excel_rows(f)
            if err:
                error = err
            elif not rows:
                error = 'لم يتم العثور على صفوف بيانات في الملف.'
            else:
                request.session[_EXCEL_SESSION_KEY] = rows
                return redirect('field_work_excel_review')

    return render(request, 'hcsd/field_work_excel_import.html', {'error': error})


@login_required
def field_work_excel_review(request):
    if not (_can_admin(request.user) or _can_data_entry(request.user)):
        return redirect('field_work_list')

    rows = request.session.get(_EXCEL_SESSION_KEY)
    if not rows:
        return redirect('field_work_excel_import')

    order_numbers = {r.get('order_number', '') for r in rows if r.get('order_number')}
    existing = set(
        FieldWorkOrder.objects.filter(order_number__in=order_numbers)
        .values_list('order_number', flat=True)
    )

    enriched = [{**r, 'is_dup': r.get('order_number', '') in existing} for r in rows]
    new_count = sum(1 for r in enriched if not r['is_dup'])
    dup_count = len(rows) - new_count

    if request.method == 'POST':
        mode = request.POST.get('import_mode', 'new_only')
        row_count = len(rows)
        created = 0
        for i in range(row_count):
            include = request.POST.get(f'row_{i}_include')
            if not include:
                continue
            order_number = (request.POST.get(f'row_{i}_order_number') or '').strip()
            if mode == 'new_only' and order_number in existing:
                continue
            FieldWorkOrder.objects.create(
                order_number    = order_number,
                request_date    = _to_date((request.POST.get(f'row_{i}_request_date') or '').strip()),
                customer_name   = (request.POST.get(f'row_{i}_customer_name') or '').strip(),
                mobile          = (request.POST.get(f'row_{i}_mobile') or '').strip(),
                area            = (request.POST.get(f'row_{i}_area') or '').strip(),
                house_number    = (request.POST.get(f'row_{i}_house_number') or '').strip(),
                pest_types      = (request.POST.get(f'row_{i}_pest_types') or '').strip(),
                supervisor_name = (request.POST.get(f'row_{i}_supervisor_name') or '').strip(),
                worker_name     = (request.POST.get(f'row_{i}_worker_name') or '').strip(),
                excel_status    = (request.POST.get(f'row_{i}_excel_status') or '').strip(),
                street_number   = rows[i].get('street_number', ''),
                close_date      = _to_date(rows[i].get('close_date', '')),
                excel_status_note = rows[i].get('excel_status_note', ''),
                month_sheet     = rows[i].get('month_sheet', ''),
                source          = 'excel',
                created_by      = request.user,
            )
            created += 1
        del request.session[_EXCEL_SESSION_KEY]
        return redirect(reverse('field_work_list') + f'?imported={created}')

    return render(request, 'hcsd/field_work_excel_review.html', {
        'rows':      enriched,
        'total':     len(rows),
        'new_count': new_count,
        'dup_count': dup_count,
    })
