"""
Campaign Follow-up — independent, standalone tracking.

URL prefix : /campaign/
Templates  : hcsd/campaign_*.html

A site is "جارية" (ongoing) until an inspector writes any note on it, at
which point it's "تم اتخاذ إجراء" (action taken). No separate status field —
the note itself is the whole status model.
"""

import io

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..models import CampaignActionLog, CampaignRequest
from .common import _can_admin, _can_data_entry, _can_inspector


def _can_manage(user):
    return _can_admin(user) or _can_data_entry(user) or _can_inspector(user)


@login_required
def campaign_list(request):
    query = (request.GET.get('q') or '').strip()
    status_filter = (request.GET.get('status') or 'ongoing').strip()

    requests_qs = CampaignRequest.objects.all()
    if query:
        requests_qs = requests_qs.filter(company_name__icontains=query)
    if status_filter == 'ongoing':
        requests_qs = requests_qs.filter(note='', action_type='')
    elif status_filter in ('violation', 'followup'):
        requests_qs = requests_qs.filter(action_type=status_filter)

    requests_list = list(requests_qs)
    all_qs = CampaignRequest.objects.all()
    ongoing_count   = all_qs.filter(note='', action_type='').count()
    violation_count = all_qs.filter(action_type='violation').count()
    followup_count  = all_qs.filter(action_type='followup').count()
    total_count     = all_qs.count()

    return render(request, 'hcsd/campaign_list.html', {
        'rows': requests_list,
        'query': query,
        'status_filter': status_filter,
        'ongoing_count': ongoing_count,
        'violation_count': violation_count,
        'followup_count': followup_count,
        'total_count': total_count,
        'can_manage': _can_manage(request.user),
    })


@login_required
def campaign_create(request):
    if not _can_manage(request.user):
        return redirect('campaign_list')

    errors = []
    if request.method == 'POST':
        company_name    = (request.POST.get('company_name') or '').strip()
        building_number = (request.POST.get('building_number') or '').strip()
        area            = (request.POST.get('area') or '').strip()
        infestation_location = (request.POST.get('infestation_location') or '').strip()
        google_maps_url = (request.POST.get('google_maps_url') or '').strip()
        photo           = request.FILES.get('photo')

        if not company_name:
            errors.append('يرجى إدخال اسم الشركة.')

        if not errors:
            obj = CampaignRequest.objects.create(
                company_name=company_name,
                building_number=building_number, area=area,
                infestation_location=infestation_location,
                google_maps_url=google_maps_url, photo=photo,
                created_by=request.user,
            )
            return redirect('campaign_detail', pk=obj.pk)

    return render(request, 'hcsd/campaign_create.html', {
        'errors': errors,
        'post': request.POST,
    })


def _is_assigned_to(user, obj):
    return obj.assigned_inspector_id == user.id


@login_required
def campaign_detail(request, pk):
    obj = get_object_or_404(CampaignRequest, pk=pk)
    can_manage = _can_manage(request.user)
    can_admin = _can_admin(request.user)
    is_owner = _is_assigned_to(request.user, obj)
    can_act = can_admin or (obj.assigned_inspector_id is None) or is_owner

    if request.method == 'POST' and can_manage:
        action = request.POST.get('action', 'note')
        if action == 'claim':
            if obj.assigned_inspector_id is None:
                obj.assigned_inspector = request.user
                obj.assigned_at = timezone.now()
                obj.save(update_fields=['assigned_inspector', 'assigned_at'])
        elif action == 'release':
            if can_admin or is_owner:
                obj.assigned_inspector = None
                obj.assigned_at = None
                obj.save(update_fields=['assigned_inspector', 'assigned_at'])
        elif action == 'update_request':
            obj.company_name    = (request.POST.get('company_name') or obj.company_name).strip()
            obj.building_number = (request.POST.get('building_number') or '').strip()
            obj.area            = (request.POST.get('area') or '').strip()
            obj.infestation_location = (request.POST.get('infestation_location') or '').strip()
            obj.google_maps_url = (request.POST.get('google_maps_url') or '').strip()
            update_fields = ['company_name', 'building_number', 'area', 'infestation_location', 'google_maps_url']
            new_photo = request.FILES.get('photo')
            if new_photo:
                obj.photo = new_photo
                update_fields.append('photo')
            obj.save(update_fields=update_fields)
        elif can_act:
            note = (request.POST.get('note') or '').strip()
            obj.note = note
            if 'action_type' in request.POST:
                action_type = (request.POST.get('action_type') or '').strip()
                valid_types = {c for c, _ in CampaignRequest.ACTION_TYPE_CHOICES}
                if action_type in valid_types:
                    obj.action_type = action_type
            obj.noted_by = request.user
            obj.noted_at = timezone.now()
            obj.save(update_fields=['note', 'action_type', 'noted_by', 'noted_at'])

            CampaignActionLog.objects.create(
                request=obj, action_type=obj.action_type, note=note,
                created_by=request.user,
            )
        return redirect('campaign_detail', pk=pk)

    return render(request, 'hcsd/campaign_detail.html', {
        'obj': obj,
        'can_manage': can_manage,
        'can_admin': can_admin,
        'is_owner': is_owner,
        'can_act': can_act,
        'action_logs': obj.action_logs.select_related('created_by').all(),
    })


@login_required
def campaign_report_excel(request):
    """Excel report of every logged action: company, action taken, note,
    inspector, and date — one row per action, so the same company can
    appear more than once if it was acted on more than once."""
    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    logs = (
        CampaignActionLog.objects
        .select_related('request', 'created_by')
        .order_by('request__company_name', 'created_at')
    )

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'تقرير متابعة الحملة'
    ws.sheet_view.rightToLeft = True

    thin = Side(style='thin', color='999999')
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    header_fill = PatternFill('solid', fgColor='4338ca')

    headers = ['اسم الشركة', 'المنطقة', 'رقم البناية', 'الحالة', 'الملاحظة', 'اسم المفتش', 'التاريخ والوقت']
    widths = [30, 16, 12, 14, 40, 20, 18]
    for col, (hdr, w) in enumerate(zip(headers, widths), start=1):
        c = ws.cell(row=1, column=col, value=hdr)
        c.font = Font(name='Arial', bold=True, color='FFFFFF', size=11)
        c.fill = header_fill
        c.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        c.border = border
    ws.row_dimensions[1].height = 26

    for row_idx, log in enumerate(logs, start=2):
        inspector = log.created_by.get_full_name() or log.created_by.username if log.created_by else ''
        values = [
            log.request.company_name,
            log.request.area,
            log.request.building_number,
            log.get_action_type_display() or 'ملاحظة',
            log.note,
            inspector,
            timezone.localtime(log.created_at).strftime('%d/%m/%Y %H:%M'),
        ]
        for col, val in enumerate(values, start=1):
            c = ws.cell(row=row_idx, column=col, value=val)
            c.font = Font(name='Arial', size=10.5)
            c.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
            c.border = border

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    response = HttpResponse(
        output.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = 'attachment; filename="campaign_report.xlsx"'
    return response


@login_required
@require_POST
def campaign_delete(request, pk):
    obj = get_object_or_404(CampaignRequest, pk=pk)
    if not _can_admin(request.user):
        return HttpResponseForbidden()

    obj.delete()
    return redirect('campaign_list')
