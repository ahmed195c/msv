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

from ..models import FieldWorkOrder, FieldWorkPhoto, FieldWorkSupervisorArea
from .common import _can_admin, _can_data_entry, _can_fw_supervise, _fw_supervisor_users_qs

logger = logging.getLogger(__name__)

ALLOWED_PHOTO_EXTENSIONS = {'.jpg', '.jpeg', '.png'}

_FW_CLOSED_STATUSES = frozenset({
    'completed', 'other_municipal',
    'closed_private_building', 'closed_no_answer', 'closed_other_municipal',
    'closed_observation', 'closed_low_infestation', 'closed_moderate_infestation',
    'closed_high_infestation', 'closed_out_of_service', 'closed_customer_refused',
    'closed_mobile_off', 'closed_not_attending', 'closed_not_available',
    'closed_scheduled_client',
})


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

    # Supervisors see only their area orders + directly assigned/received
    if _can_fw_supervise(request.user) and not _can_admin(request.user) and not _can_data_entry(request.user):
        from django.db.models import Q as _Q
        my_areas = list(
            FieldWorkSupervisorArea.objects.filter(supervisor=request.user)
            .values_list('area', flat=True)
        )
        orders = orders.filter(
            _Q(area__in=my_areas)
            | _Q(assigned_supervisor=request.user)
            | _Q(received_by=request.user)
        ).distinct()

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
    order = get_object_or_404(
        FieldWorkOrder.objects.select_related(
            'created_by', 'assigned_supervisor', 'received_by'
        ), pk=pk
    )
    can_admin = _can_admin(request.user)
    can_data_entry = _can_data_entry(request.user)
    can_edit = can_admin or can_data_entry
    is_fw_supervisor = _can_fw_supervise(request.user)
    can_assign = can_admin or can_data_entry
    uid = request.user.id
    can_submit_report = can_admin or (
        is_fw_supervisor and (
            order.assigned_supervisor_id == uid or order.received_by_id == uid
        )
    )
    can_receive = (
        is_fw_supervisor
        and not can_submit_report
        and order.status not in _FW_CLOSED_STATUSES
    )

    photos_before = order.photos.filter(phase='before').order_by('uploaded_at')
    photos_during = order.photos.filter(phase='during').order_by('uploaded_at')
    photos_after  = order.photos.filter(phase='after').order_by('uploaded_at')

    errors = []
    success = None

    if request.method == 'POST':
        action = (request.POST.get('action') or '').strip()

        # ── Receive order ────────────────────────────────────────────────────
        if action == 'receive_order' and is_fw_supervisor and order.status != 'completed':
            order.received_by = request.user
            order.received_at = timezone.now()
            order.save(update_fields=['received_by', 'received_at'])
            success = 'تم استلام متابعة الأمر.'

        # ── Assign supervisor ────────────────────────────────────────────────
        elif action == 'assign_supervisor' and can_assign:
            sup_id = (request.POST.get('supervisor_id') or '').strip()
            if sup_id == '':
                order.assigned_supervisor = None
                order.assigned_at = None
                order.save(update_fields=['assigned_supervisor', 'assigned_at'])
                success = 'تم إلغاء تعيين المراقب.'
            else:
                try:
                    from django.contrib.auth.models import User as _User
                    sup_user = _fw_supervisor_users_qs().get(pk=int(sup_id))
                    order.assigned_supervisor = sup_user
                    order.assigned_at = timezone.now()
                    order.save(update_fields=['assigned_supervisor', 'assigned_at'])
                    success = f'تم تعيين {sup_user.get_full_name() or sup_user.username} مراقباً للأمر.'
                except (ValueError, Exception):
                    errors.append('المراقب المختار غير صالح.')

        elif not can_edit and not can_submit_report:
            errors.append('ليس لديك صلاحية لتنفيذ هذا الإجراء.')

        # ── Update work details ──────────────────────────────────────────────
        elif action == 'update_details' and can_edit:
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
        elif action == 'update_status' and can_edit:
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
        elif action == 'upload_photos' and can_edit:
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
                    photos_before = order.photos.filter(phase='before').order_by('uploaded_at')
                    photos_during = order.photos.filter(phase='during').order_by('uploaded_at')
                    photos_after  = order.photos.filter(phase='after').order_by('uploaded_at')

        # ── Save GPS location ────────────────────────────────────────────────
        elif action == 'save_location' and can_submit_report:
            try:
                lat = float(request.POST.get('lat', ''))
                lng = float(request.POST.get('lng', ''))
            except (ValueError, TypeError):
                errors.append('إحداثيات غير صالحة.')
            else:
                order.gps_lat = lat
                order.gps_lng = lng
                order.location_saved_at = timezone.now()
                order.location_saved_by = request.user
                update_f = ['gps_lat', 'gps_lng', 'location_saved_at', 'location_saved_by']
                if not order.time_in:
                    order.time_in = timezone.now()
                    update_f.append('time_in')
                order.save(update_fields=update_f)
                success = 'تم حفظ الموقع.'

        # ── Supervisor report ────────────────────────────────────────────────
        elif action == 'supervisor_report' and can_submit_report:
            import json as _json
            workers_raw    = (request.POST.get('workers_count') or '').strip()
            vehicles_raw   = (request.POST.get('vehicles_count') or '').strip()
            building_type  = (request.POST.get('building_type') or '').strip()
            sup_notes      = (request.POST.get('supervisor_notes') or '').strip()
            client_sig     = (request.POST.get('client_signature') or '').strip()
            supervisor_sig = (request.POST.get('supervisor_signature') or '').strip()

            try:
                spray_entries = _json.loads(request.POST.get('spray_entries_json') or '[]')
                if not isinstance(spray_entries, list):
                    spray_entries = []
            except (ValueError, TypeError):
                spray_entries = []

            _SIG_PREFIX = 'data:image/png;base64,'
            if client_sig and not client_sig.startswith(_SIG_PREFIX):
                client_sig = ''
            if supervisor_sig and not supervisor_sig.startswith(_SIG_PREFIX):
                supervisor_sig = ''

            def _to_int(val):
                try:
                    v = int(val)
                    return v if v >= 0 else None
                except (ValueError, TypeError):
                    return None

            order.status              = 'completed'
            order.workers_count       = _to_int(workers_raw)
            order.vehicles_count      = _to_int(vehicles_raw)
            order.building_type       = building_type
            order.spray_entries       = spray_entries
            order.supervisor_notes    = sup_notes
            order.report_submitted_by = request.user
            order.report_submitted_at = timezone.now()
            if client_sig:
                order.client_signature = client_sig
            if supervisor_sig:
                order.supervisor_signature = supervisor_sig
            order.save(update_fields=[
                'status', 'workers_count', 'vehicles_count',
                'building_type', 'spray_entries', 'supervisor_notes',
                'report_submitted_by', 'report_submitted_at',
                'client_signature', 'supervisor_signature',
            ])
            success = 'تم حفظ تقرير المراقب — الحالة: تم إنجاز الخدمة.'

        elif action == 'postpone_order' and can_submit_report:
            from datetime import date as _date
            postponed_until_raw = (request.POST.get('postponed_until') or '').strip()
            postpone_notes      = (request.POST.get('postpone_notes') or '').strip()
            try:
                postponed_until = _date.fromisoformat(postponed_until_raw)
                if postponed_until <= _date.today():
                    errors.append('يرجى اختيار تاريخ مستقبلي.')
            except ValueError:
                postponed_until = None
                errors.append('يرجى تحديد تاريخ التأجيل.')
            if not errors:
                order.status         = 'postponed_client'
                order.postponed_until = postponed_until
                if postpone_notes:
                    order.supervisor_notes = postpone_notes
                order.save(update_fields=['status', 'postponed_until', 'supervisor_notes'])
                success = f'تم تأجيل الموعد إلى {postponed_until.strftime("%d/%m/%Y")}.'

        # ── Close request ───────────────────────────────────────────────────
        elif action == 'close_request' and (can_submit_report or can_edit):
            close_reason = (request.POST.get('close_reason') or '').strip()
            proof = request.FILES.get('closure_proof')
            valid_close_reasons = {
                'closed_private_building', 'closed_no_answer', 'closed_other_municipal',
                'closed_observation', 'closed_low_infestation', 'closed_moderate_infestation',
                'closed_high_infestation', 'closed_out_of_service', 'closed_customer_refused',
                'closed_mobile_off', 'closed_not_attending', 'closed_not_available',
                'closed_scheduled_client',
            }
            if order.status in _FW_CLOSED_STATUSES:
                errors.append('الطلب مغلق بالفعل.')
            elif close_reason not in valid_close_reasons:
                errors.append('يرجى اختيار سبب الإغلاق.')
            elif not proof:
                errors.append('يرجى رفع صورة إثبات.')
            else:
                ext = os.path.splitext(proof.name)[1].lower()
                if ext not in ALLOWED_PHOTO_EXTENSIONS:
                    errors.append('يُسمح فقط بصور JPG أو PNG.')
                else:
                    order.status = close_reason
                    order.close_date = timezone.now().date()
                    order.no_answer_screenshot = proof
                    order.report_submitted_by = request.user
                    order.report_submitted_at = timezone.now()
                    order.save(update_fields=[
                        'status', 'close_date', 'no_answer_screenshot',
                        'report_submitted_by', 'report_submitted_at',
                    ])
                    success = 'تم إغلاق الطلب بنجاح.'

        # ── Delete photo ─────────────────────────────────────────────────────
        elif action == 'delete_photo' and can_edit:
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

    fw_supervisor_users = _fw_supervisor_users_qs() if can_assign else []
    is_closed = order.status in _FW_CLOSED_STATUSES
    can_close = (can_submit_report or can_edit) and not is_closed
    from datetime import date as _date
    _BUILDING_TYPE_CHOICES = [
        'Villa', 'Government Facility', 'School', 'Public Park',
        'Mosque', 'Palace', 'Labor Accommodation', 'Vip Villa',
    ]
    return render(request, 'hcsd/field_work_detail.html', {
        'order': order,
        'can_edit': can_edit,
        'can_admin': can_admin,
        'can_assign': can_assign,
        'can_submit_report': can_submit_report,
        'can_receive': can_receive,
        'can_close': can_close,
        'is_closed': is_closed,
        'fw_supervisor_users': fw_supervisor_users,
        'photos_before': photos_before,
        'photos_during': photos_during,
        'photos_after': photos_after,
        'errors': errors,
        'success': success,
        'building_type_choices': _BUILDING_TYPE_CHOICES,
        'today_date': _date.today().isoformat(),
    })


# ---------------------------------------------------------------------------
# Print Report
# ---------------------------------------------------------------------------

_ACTIVE_INGREDIENTS = {
    "Actellic 50 EC": "Primiphos Methyl 50%",
    "ECOLARVACIDE EC": "Temephos 50%",
    "Starycide SC 480": "Triflumuron 48%",
    "DIFRON 25 SC": "Diflubenzuron 25%",
    "GRAYBATE 50 SG": "Temephos 50 g/kg",
    "BIOPREN 4 GR": "S-Methoprene 0.4%",
    "LAROXYFEN PLUS WT": "Pyriproxyfen 2%",
    "Aqua k-Othrine": "Deltamethrin 20 g/L",
    "Chirotox": "Tetramethrin 5% / Piperonyl Butoxide 5%",
    "TETRACON 50 EC": "Lambda-cyhalothrin 50 g/L / Tetramethrin 10 g/L / PBO 20 g/L",
    "KULCYPERIN 100/3 EC": "Cypermethrin 10% / Tetramethrin 0.5% / Piperonyl Butoxide 2.5%",
    "DEMON MAX INSECTICIDE": "Cypermethrin 25.3% (w/w)",
    "Solfac EC 50": "Cyfluthrin 5%",
    "CYMPERATOR 25 EC": "Cypermethrin 26%",
    "Bio Amplat": "Cypermethrin 93% min. / Tetramethrin 94% min. / Piperonyl Butoxide 94% min.",
    "ROTRYN 200": "Cypermethrin 20% w/w (200 g/L)",
    "GUADIN SE": "Dinotefuran 10%",
    "BAITFURAN SP": "Dinotefuran 12%",
    "Detral Super": "Deltamethrin 0.7 g / Esbiothrin 0.7 g / Piperonyl Butoxide 7 g",
    "K-Othrine Partix": "Deltamethrin 25 g/L",
    "PERMETHOR": "Permethrin 10 g/kg",
    "Temprid SC": "Imidacloprid 21% / Beta-Cyfluthrin 10.5%",
    "HYMENOPHTHOR GR": "Fipronil 0.1 g/kg",
    "Vertox Oktablok": "Brodifacoum 0.005%",
    "FACORAT PELLETS": "Brodifacoum 0.005 g",
    "VICTOR V FAST-KILL BRAND BLOCKS II": "Bromethalin 0.01%",
    "SUREFIRE ALL WEATHER BLOCKS": "Brodifacoum 0.05 g/kg",
    "PROTECT SENSATION 2IN1": "Bromadiolone 0.005% (0.05 g/kg)",
    "VERTOX PASTA BAIT": "Brodifacoum 0.005% (0.05 g/kg)",
    "STELLIOX D50": "Difenacoum 0.005% W/W",
    "TALON WB": "Brodifacoum 0.005%",
    "SUREFIRE BROMA BLOCKS RODENTICIDE": "Bromadiolone 0.05 g/kg",
    "NOCURAT PARAFFINATO": "Difenacoum",
    "BuyBlocker Snake Deter": "Cedar Oil 1.00% / Cinnamon Oil 0.60% / Clove Oil 0.40%",
    "BOOM": "Clove Oil / Peppermint Oil / Citronella Oil / Cedar Oil / Cinnamon Oil / Thyme Oil",
    "CYPFORCE 40 EC": "Cypermethrin 25% / Tetramethrin 5% / Piperonyl Butoxide 10%",
    "D-TETRASUPER EC": "D-Tetramethrin 10%",
    "TEMEPHOS 55EC": "Temephos 50%",
}

_INSECT_IDS  = {'نمل', 'صراصير', 'بعوض', 'ذباب'}
_RODENT_IDS  = {'فئران'}
_REPTILE_IDS = {'ثعبان'}

def _pest_category(pests):
    cats = []
    if any(p in _INSECT_IDS for p in pests):
        cats.append('Insects')
    if any(p in _RODENT_IDS for p in pests):
        cats.append('Rodents')
    if any(p in _REPTILE_IDS for p in pests):
        cats.append('Reptiles')
    return ' / '.join(cats) if cats else ''


@login_required
def field_work_report_print(request, pk):
    order = get_object_or_404(
        FieldWorkOrder.objects.select_related('report_submitted_by'),
        pk=pk,
    )
    materials = []
    observations = []
    for entry in (order.spray_entries or []):
        loc = entry.get('location', '')
        pests = entry.get('pests', [])
        pesticides = entry.get('pesticides', [])
        for p in pesticides:
            materials.append({
                'product': p.get('name', ''),
                'qty': f"{p.get('qty', '')} {p.get('unit', '')}".strip(),
                'active_ingredient': _ACTIVE_INGREDIENTS.get(p.get('name', ''), ''),
                'location': loc,
            })
        observations.append({
            'building_type': order.building_type or '',
            'observation': order.supervisor_notes or '',
            'pest_category': _pest_category(pests),
            'pest_found': ', '.join(pests),
            'location': loc,
            'action': entry.get('action', ''),
        })
    time_in_dt = order.time_in or order.location_saved_at
    return render(request, 'hcsd/field_work_report_print.html', {
        'order': order,
        'materials': materials,
        'observations': observations,
        'time_in_dt': time_in_dt,
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
        to_create = []
        for i in range(row_count):
            include = request.POST.get(f'row_{i}_include')
            if not include:
                continue
            order_number = (request.POST.get(f'row_{i}_order_number') or '').strip()
            if mode == 'new_only' and order_number in existing:
                continue
            to_create.append(FieldWorkOrder(
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
            ))
        FieldWorkOrder.objects.bulk_create(to_create, batch_size=500)
        created = len(to_create)
        del request.session[_EXCEL_SESSION_KEY]
        return redirect(reverse('field_work_list') + f'?imported={created}')

    return render(request, 'hcsd/field_work_excel_review.html', {
        'rows':      enriched,
        'total':     len(rows),
        'new_count': new_count,
        'dup_count': dup_count,
    })


# ---------------------------------------------------------------------------
# Supervisors Management
# ---------------------------------------------------------------------------

@login_required
def field_work_supervisors(request):
    if not (_can_admin(request.user) or _can_data_entry(request.user)):
        return redirect('field_work_list')

    from django.contrib.auth.models import User
    from django.db.models import Count, Q

    supervisors = (
        _fw_supervisor_users_qs()
        .prefetch_related('fw_supervisor_areas')
        .annotate(
            active_count=Count(
                'field_work_assigned',
                filter=~Q(field_work_assigned__status='completed'),
                distinct=True,
            ) + Count(
                'field_work_received',
                filter=~Q(field_work_received__status='completed'),
                distinct=True,
            ),
        )
    )

    # Collect all distinct areas from existing orders for the area dropdown
    existing_areas = (
        FieldWorkOrder.objects.exclude(area='')
        .values_list('area', flat=True)
        .distinct()
        .order_by('area')
    )

    error = ''
    success = ''

    if request.method == 'POST':
        if not _can_admin(request.user):
            return redirect('field_work_supervisors')

        action = request.POST.get('action', '')

        if action == 'add_area':
            sup_id = (request.POST.get('supervisor_id') or '').strip()
            area = (request.POST.get('area') or '').strip()
            if not sup_id or not area:
                error = 'يرجى اختيار مراقب ومنطقة.'
            else:
                try:
                    sup = User.objects.get(pk=int(sup_id), groups__name__in=['fw_supervisor', 'Field Work Supervisor'])
                    _, created = FieldWorkSupervisorArea.objects.get_or_create(
                        supervisor=sup, area=area,
                        defaults={'assigned_by': request.user},
                    )
                    success = f'تمت إضافة منطقة "{area}" للمراقب {sup.get_full_name() or sup.username}.' if created else 'المنطقة مضافة مسبقاً.'
                except (ValueError, User.DoesNotExist):
                    error = 'المراقب غير صالح.'

        elif action == 'remove_area':
            area_id = (request.POST.get('area_id') or '').strip()
            try:
                FieldWorkSupervisorArea.objects.filter(pk=int(area_id)).delete()
                success = 'تم حذف المنطقة.'
            except (ValueError, Exception):
                error = 'تعذّر الحذف.'

        if not error:
            return redirect('field_work_supervisors')

    return render(request, 'hcsd/field_work_supervisors.html', {
        'supervisors': supervisors,
        'existing_areas': existing_areas,
        'fw_supervisor_users': _fw_supervisor_users_qs(),
        'error': error,
        'success': success,
    })
