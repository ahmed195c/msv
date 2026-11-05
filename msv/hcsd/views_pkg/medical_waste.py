"""
Medical Waste Inspection — fills, prints and archives the municipality's
"نموذج التفتيش على المنشآت الطبية".

URL prefix : /medical-waste/
Templates  : hcsd/medical_waste_*.html
"""

import csv
import io

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.http import FileResponse, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..forms import MedicalWasteInspectionForm
from ..medical_waste_pdf import (
    FOOTER_IMAGE, HEADER_IMAGE, SHEET_CSS, pdf_filename, save_report_pdf,
)
from ..models import MedicalWasteInspection
from .common import _can_admin, _can_data_entry, _can_inspector, _display_user_name, _parse_date

ARCHIVE_PAGE_SIZE = 25
EXPORT_HEADERS = [
    'رقم التقرير', 'تاريخ التفتيش', 'اسم المفتش', 'اسم المنشأة', 'رقم الرخصة', 'العنوان', 'رقم الهاتف',
    'نوع التفتيش', 'نوع الزيارة', 'نقطة 1', 'نقطة 2', 'نقطة 3', 'نقطة 4', 'الإجراء المتخذ',
    'مدة الإخطار (أيام)', 'نوع النفايات', 'الوزن التقديري', 'تاريخ الحفظ',
]
_SPREADSHEET_FORMULA_PREFIXES = ('=', '+', '-', '@', '\t', '\r')


def _can_write(user):
    return _can_admin(user) or _can_inspector(user) or _can_data_entry(user)


def _filtered_reports(request):
    """The archive queryset for the request's filters, plus the raw filters."""
    filters = {
        'facility': (request.GET.get('facility') or '').strip(),
        'inspector': (request.GET.get('inspector') or '').strip(),
        'date_from': (request.GET.get('date_from') or '').strip(),
        'date_to': (request.GET.get('date_to') or '').strip(),
        'type': (request.GET.get('type') or '').strip(),
    }
    reports = MedicalWasteInspection.objects.all()
    if filters['facility']:
        reports = reports.filter(facility_name__icontains=filters['facility'])
    if filters['inspector']:
        reports = reports.filter(inspector_name__icontains=filters['inspector'])
    date_from, date_to = _parse_date(filters['date_from']), _parse_date(filters['date_to'])
    if date_from:
        reports = reports.filter(inspection_date__gte=date_from)
    if date_to:
        reports = reports.filter(inspection_date__lte=date_to)
    if filters['type'] in dict(MedicalWasteInspection.TYPE_CHOICES):
        reports = reports.filter(inspection_type=filters['type'])
    return reports, filters


@login_required
def medical_waste_home(request):
    """The archive of saved reports."""
    reports, filters = _filtered_reports(request)
    page = Paginator(reports, ARCHIVE_PAGE_SIZE).get_page(request.GET.get('page'))
    query = request.GET.copy()
    query.pop('page', None)
    return render(request, 'hcsd/medical_waste_home.html', {
        'page': page,
        'filters': filters,
        'filter_query': query.urlencode(),
        'type_choices': MedicalWasteInspection.TYPE_CHOICES,
        'can_write': _can_write(request.user),
        'can_delete': _can_admin(request.user),
    })


def _delete_replaced_files(old_names, report):
    """Remove uploaded files that an edit replaced or cleared."""
    for field_name, old_name in old_names.items():
        field = getattr(report, field_name)
        if old_name and field.name != old_name:
            field.storage.delete(old_name)


def _form_view(request, report):
    is_new = report is None
    if not _can_write(request.user):
        return HttpResponseForbidden('ليس لديك صلاحية لتعبئة تقارير التفتيش.')
    if request.method == 'POST':
        file_fields = ('inspector_signature', 'representative_signature', 'notice_attachment')
        old_names = {name: getattr(report, name).name for name in file_fields} if report else {}
        form = MedicalWasteInspectionForm(request.POST, request.FILES, instance=report)
        if form.is_valid():
            with transaction.atomic():
                saved = form.save(commit=False)
                if is_new:
                    saved.created_by = request.user
                saved.save()
            _delete_replaced_files(old_names, saved)
            if not save_report_pdf(saved):
                messages.warning(request, 'تم حفظ التقرير، لكن تعذّر إنشاء نسخة PDF. يمكنك طباعته أو إعادة المحاولة لاحقاً.')
            else:
                messages.success(request, f'تم حفظ التقرير رقم {saved.pk} ونسخة PDF منه.')
            if request.POST.get('submit_action') == 'save_print':
                return redirect(f"{reverse('medical_waste_print', args=[saved.pk])}?autoprint=1")
            return redirect('medical_waste_detail', pk=saved.pk)
    elif is_new:
        form = MedicalWasteInspectionForm(initial={
            'inspector_name': _display_user_name(request.user),
            'inspection_date': timezone.localdate().isoformat(),
            'letter_action': True,
            'site_report_action': True,
        })
    else:
        form = MedicalWasteInspectionForm(instance=report)
    return render(request, 'hcsd/medical_waste_form.html', {
        'form': form,
        'report': report,
        'model': MedicalWasteInspection,
        'points': MedicalWasteInspection.INSPECTION_POINTS,
    })


@login_required
def medical_waste_create(request):
    return _form_view(request, None)


@login_required
def medical_waste_edit(request, pk):
    return _form_view(request, get_object_or_404(MedicalWasteInspection, pk=pk))


def _web_sheet_context(report):
    return {
        'report': report,
        'sheet_css_url': static(SHEET_CSS),
        'header_image_url': static(HEADER_IMAGE),
        'footer_image_url': static(FOOTER_IMAGE),
        'inspector_signature_url': report.inspector_signature.url if report.inspector_signature else '',
        'representative_signature_url': (
            report.representative_signature.url if report.representative_signature else ''
        ),
    }


@login_required
def medical_waste_detail(request, pk):
    report = get_object_or_404(MedicalWasteInspection, pk=pk)
    return render(request, 'hcsd/medical_waste_detail.html', {
        **_web_sheet_context(report),
        'can_write': _can_write(request.user),
        'can_delete': _can_admin(request.user),
    })


@login_required
def medical_waste_print(request, pk):
    report = get_object_or_404(MedicalWasteInspection, pk=pk)
    return render(request, 'hcsd/medical_waste_print.html', {
        **_web_sheet_context(report),
        'autoprint': request.GET.get('autoprint') == '1',
    })


@login_required
def medical_waste_pdf(request, pk):
    report = get_object_or_404(MedicalWasteInspection, pk=pk)
    has_pdf = bool(report.pdf_file) and report.pdf_file.storage.exists(report.pdf_file.name)
    if not has_pdf and not save_report_pdf(report):
        messages.error(request, 'تعذّر إنشاء نسخة PDF من التقرير. يمكنك طباعته من زر الطباعة.')
        return redirect('medical_waste_detail', pk=report.pk)
    return FileResponse(report.pdf_file.open('rb'), as_attachment=True, filename=pdf_filename(report))


@login_required
@require_POST
def medical_waste_delete(request, pk):
    if not _can_admin(request.user):
        return HttpResponseForbidden('ليس لديك صلاحية لحذف التقارير.')
    report = get_object_or_404(MedicalWasteInspection, pk=pk)
    report_id, files = report.pk, [field for field in report.uploaded_files if field]
    report.delete()
    for field in files:
        field.storage.delete(field.name)
    messages.success(request, f'تم حذف التقرير رقم {report_id}.')
    return redirect('medical_waste_home')


def _safe_cell(value):
    """Spreadsheets run text starting with these characters as a formula."""
    if isinstance(value, str) and value.startswith(_SPREADSHEET_FORMULA_PREFIXES):
        return "'" + value
    return value


def _answer_label(answer):
    return '' if answer is None else ('نعم' if answer else 'لا')


def _export_rows(reports):
    for report in reports:
        action = report.get_contract_action_display()
        if report.notice_days:
            action = f'{action} ({report.notice_days}) أيام'
        if report.letter_action:
            action = MedicalWasteInspection.LETTER_ACTION_LABEL
        if report.site_report_action:
            action = MedicalWasteInspection.SITE_REPORT_ACTION_LABEL
        row = [
            report.pk, report.inspection_date.strftime('%d/%m/%Y'), report.inspector_name,
            report.facility_name, report.license_number, report.address, report.phone,
            report.get_inspection_type_display(), report.get_visit_type_display(),
            _answer_label(report.point_1), _answer_label(report.point_2),
            _answer_label(report.point_3), _answer_label(report.point_4),
            action, report.notice_days or '', report.waste_types_display, report.estimated_weight,
            timezone.localtime(report.created_at).strftime('%d/%m/%Y %H:%M'),
        ]
        yield [_safe_cell(value) for value in row]


@login_required
def medical_waste_export_csv(request):
    reports, _ = _filtered_reports(request)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(EXPORT_HEADERS)
    writer.writerows(_export_rows(reports))
    # The BOM makes Excel read the Arabic as UTF-8.
    response = HttpResponse('﻿' + buffer.getvalue(), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="medical_waste_inspections.csv"'
    return response


@login_required
def medical_waste_export_excel(request):
    import openpyxl
    from openpyxl.styles import Font

    reports, _ = _filtered_reports(request)
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = 'تقارير التفتيش'
    sheet.sheet_view.rightToLeft = True
    sheet.append(EXPORT_HEADERS)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for row in _export_rows(reports):
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    response = HttpResponse(
        buffer.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = 'attachment; filename="medical_waste_inspections.xlsx"'
    return response
