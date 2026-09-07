"""
Rodent Control — building trap (RBS) monitoring.

URL prefix : /rodent-control/
Templates  : hcsd/rodent_control_*.html

One trap per building. A monthly visit record is auto-generated for every
active building on the 1st of each month (see
management/commands/generate_rodent_control_visits.py); staff fill it in
when the team actually visits.
"""

import datetime
import io

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..models import RodentControlBuilding, RodentControlVisit
from .common import _can_admin, _can_data_entry


def _can_manage(user):
    return _can_admin(user) or _can_data_entry(user)


def _current_period_start(today=None):
    today = today or timezone.localdate()
    return today.replace(day=1)


def _get_or_create_current_visit(building, today=None):
    period_start = _current_period_start(today)
    visit, _ = RodentControlVisit.objects.get_or_create(
        building=building, period_start=period_start,
    )
    return visit


@login_required
def rodent_control_list(request):
    query = (request.GET.get('q') or '').strip()

    buildings_qs = RodentControlBuilding.objects.filter(is_active=True)
    if query:
        buildings_qs = buildings_qs.filter(name__icontains=query)
    buildings = list(buildings_qs.order_by('name'))

    period_start = _current_period_start()
    current_visits = {
        v.building_id: v
        for v in RodentControlVisit.objects.filter(
            building__in=buildings, period_start=period_start,
        )
    }

    rows = []
    for b in buildings:
        visit = current_visits.get(b.id)
        rows.append({'building': b, 'visit': visit})

    return render(request, 'hcsd/rodent_control_list.html', {
        'rows': rows,
        'query': query,
        'period_start': period_start,
        'can_manage': _can_manage(request.user),
        'total_buildings': len(buildings),
    })


@login_required
def rodent_control_building_create(request):
    if not _can_manage(request.user):
        return redirect('rodent_control_list')

    errors = []
    if request.method == 'POST':
        name     = (request.POST.get('name') or '').strip()
        number   = (request.POST.get('number') or '').strip()
        area     = (request.POST.get('area') or '').strip()
        location = (request.POST.get('location') or '').strip()
        notes    = (request.POST.get('notes') or '').strip()

        if not name:
            errors.append('يرجى إدخال اسم البناية.')

        if not errors:
            building = RodentControlBuilding.objects.create(
                name=name, number=number, area=area, location=location,
                notes=notes, created_by=request.user,
            )
            _get_or_create_current_visit(building)
            return redirect('rodent_control_building_detail', pk=building.pk)

    return render(request, 'hcsd/rodent_control_building_create.html', {
        'errors': errors,
        'post': request.POST,
    })


@login_required
def rodent_control_building_detail(request, pk):
    building = get_object_or_404(RodentControlBuilding, pk=pk)
    can_manage = _can_manage(request.user)

    current_visit = _get_or_create_current_visit(building)
    history = list(
        building.visits.exclude(pk=current_visit.pk).order_by('-period_start')
    )

    if request.method == 'POST':
        if not can_manage:
            return redirect('rodent_control_building_detail', pk=pk)

        action = request.POST.get('action', '')

        if action == 'record_visit':
            def _int(name):
                raw = (request.POST.get(name) or '').strip()
                try:
                    return int(raw) if raw else None
                except ValueError:
                    return None

            def _float(name):
                raw = (request.POST.get(name) or '').strip()
                try:
                    return float(raw) if raw else None
                except ValueError:
                    return None

            def _time(name):
                raw = (request.POST.get(name) or '').strip()
                try:
                    return datetime.time.fromisoformat(raw) if raw else None
                except ValueError:
                    return None

            visit_date_raw = (request.POST.get('visit_date') or '').strip()
            try:
                visit_date = datetime.date.fromisoformat(visit_date_raw)
            except ValueError:
                visit_date = timezone.localdate()

            current_visit.visit_date = visit_date
            current_visit.visited_by = request.user

            current_visit.team_leader_name = (request.POST.get('team_leader_name') or '').strip()
            current_visit.team_leader_id = (request.POST.get('team_leader_id') or '').strip()
            current_visit.time_in = _time('time_in')
            current_visit.time_out = _time('time_out')

            current_visit.rbs_inspected_count = _int('rbs_inspected_count')
            current_visit.rbs_lock_ok = 'rbs_lock_ok' in request.POST
            current_visit.rbs_infested_count = _int('rbs_infested_count')
            current_visit.rbs_damaged_count = _int('rbs_damaged_count')
            current_visit.rbs_new_installed_count = _int('rbs_new_installed_count')
            current_visit.stick_change_ok = 'stick_change_ok' in request.POST
            current_visit.rbs_replenished_count = _int('rbs_replenished_count')

            current_visit.manholes_inspected_count = _int('manholes_inspected_count')
            current_visit.manholes_treated_count = _int('manholes_treated_count')
            current_visit.manholes_treated_qty = _float('manholes_treated_qty')
            current_visit.manholes_infested_count = _int('manholes_infested_count')

            current_visit.burrows_outside_count = _int('burrows_outside_count')
            current_visit.burrows_infested_count = _int('burrows_infested_count')

            current_visit.trees_inspected_count = _int('trees_inspected_count')
            current_visit.trees_treated_count = _int('trees_treated_count')
            current_visit.trees_infested_count = _int('trees_infested_count')

            current_visit.rodenticide_type = (request.POST.get('rodenticide_type') or '').strip()
            current_visit.rodenticide_quantity = _float('rodenticide_quantity')

            current_visit.technicians_count = _int('technicians_count')

            current_visit.bldg_villa_inspected_count = _int('bldg_villa_inspected_count')
            current_visit.bldg_villa_infested_count = _int('bldg_villa_infested_count')

            current_visit.construction_inspected_count = _int('construction_inspected_count')
            current_visit.construction_infested_count = _int('construction_infested_count')

            current_visit.masjed_inspected_count = _int('masjed_inspected_count')
            current_visit.masjed_infested_count = _int('masjed_infested_count')

            current_visit.electrical_inspected_count = _int('electrical_inspected_count')
            current_visit.electrical_infested_count = _int('electrical_infested_count')

            current_visit.gov_offices_count = _int('gov_offices_count')

            current_visit.rodenticide_surefire_qty = _float('rodenticide_surefire_qty')
            current_visit.rodenticide_facorat_qty = _float('rodenticide_facorat_qty')
            current_visit.rodenticide_vertox_qty = _float('rodenticide_vertox_qty')
            current_visit.rodenticide_sellioxid_qty = _float('rodenticide_sellioxid_qty')
            current_visit.rodenticide_victor_qty = _float('rodenticide_victor_qty')
            current_visit.rodenticide_protect_qty = _float('rodenticide_protect_qty')
            current_visit.rodenticide_nocurat_qty = _float('rodenticide_nocurat_qty')

            current_visit.notes = (request.POST.get('notes') or '').strip()

            # Auto-derive the summary flags (used by the list-page badge and
            # by the historical import) from the actual counts just entered.
            current_visit.inspected = bool(current_visit.rbs_inspected_count)
            current_visit.infested = bool(current_visit.rbs_infested_count) or bool(current_visit.manholes_infested_count) or bool(current_visit.burrows_infested_count) or bool(current_visit.trees_infested_count)
            current_visit.damaged = bool(current_visit.rbs_damaged_count) or not current_visit.rbs_lock_ok
            current_visit.newly_installed = bool(current_visit.rbs_new_installed_count)
            current_visit.replenished = bool(current_visit.rbs_replenished_count)

            current_visit.save()
            return redirect('rodent_control_building_detail', pk=pk)

        elif action == 'update_building':
            building.name     = (request.POST.get('name') or building.name).strip()
            building.number   = (request.POST.get('number') or '').strip()
            building.area     = (request.POST.get('area') or '').strip()
            building.location = (request.POST.get('location') or '').strip()
            building.notes    = (request.POST.get('notes') or '').strip()
            building.save(update_fields=['name', 'number', 'area', 'location', 'notes'])
            return redirect('rodent_control_building_detail', pk=pk)

        elif action == 'toggle_active':
            building.is_active = not building.is_active
            building.save(update_fields=['is_active'])
            return redirect('rodent_control_building_detail', pk=pk)

    return render(request, 'hcsd/rodent_control_building_detail.html', {
        'building': building,
        'current_visit': current_visit,
        'history': history,
        'can_manage': can_manage,
    })


@login_required
def rodent_control_monthly_excel(request):
    """Excel export of visit records for a date range, matching the exact
    column layout of the real "Rodent Team Report" spreadsheet (see
    hcsd/static/hcsd/excl/buldings/MONTHLY REPORT RODENT CONTROL 2026.xlsx)
    so this export is a drop-in replacement for it — header text and column
    order are copied verbatim from that file, quirks included."""
    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    today = timezone.localdate()
    raw_from = (request.GET.get('date_from') or '').strip()
    raw_to = (request.GET.get('date_to') or '').strip()
    try:
        date_from = datetime.date.fromisoformat(raw_from)
    except ValueError:
        date_from = today.replace(day=1)
    try:
        date_to = datetime.date.fromisoformat(raw_to)
    except ValueError:
        date_to = today
    if date_from > date_to:
        date_from, date_to = date_to, date_from

    visits = list(
        RodentControlVisit.objects.filter(
            period_start__gte=date_from.replace(day=1),
            period_start__lte=date_to,
        )
        .select_related('building', 'visited_by')
        .order_by('building__area', 'period_start')
    )

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Rodent Team Report'
    ws.sheet_view.rightToLeft = False

    thin = Side(style='thin', color='999999')
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    header_fill = PatternFill('solid', fgColor='0e7490')

    # Verbatim from the real spreadsheet's header row — do not edit the text.
    headers = [
        'Team Leader',
        'Date',
        'Area Name',
        'No of Technicians',
        'Time In',
        'Total number of Inspecteted Bldg/ Villa',
        'Number of Infested Bldg/ Villa',
        'Total Number of  Manholes',
        'Number of Insp & Treated Manholes',
        ' Number of Infested Manholes',
        'Total number of Inspected Burrows',
        'Number of Infested Burrows',
        'Total Inspected Construction',
        ' Infested Construction',
        'Totol InspectedMasjed',
        ' InfestedMasjed',
        'Total Inspected Trees',
        ' Insfested Trees',
        'Total Inspected Electrical Rooms',
        ' Insfested Electrical Rooms',
        'Gov Offices',
        'Rodenticide 1 {SUREFIRE ALL WEATHER.}  Qyt',
        'Rodenticide 2 {FACORAT PELLETS}Qyt',
        'Rodenticide 3 {VERTOX Okta Blocks}Qyt',
        'Rodenticide 4 {SELLIOX D}Qyt',
        'Rodenticide 5 VICTOR V FAST KILL',
        'Rodenticide 6 Protect Sensation 2in1',
        'Rodenticide 6 NOCURAT PARAFFINATO',
        'Time Out:',
    ]
    widths = [16, 12, 16, 9, 9, 14, 14, 12, 14, 14, 14, 14, 12, 12, 12, 12, 12, 12, 14, 14, 10, 14, 14, 14, 14, 14, 14, 14, 9]
    for col, (hdr, w) in enumerate(zip(headers, widths), start=1):
        c = ws.cell(row=1, column=col, value=hdr)
        c.font = Font(name='Arial', bold=True, color='FFFFFF', size=10)
        c.fill = header_fill
        c.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        c.border = border
        ws.column_dimensions[get_column_letter(col)].width = w
    ws.row_dimensions[1].height = 30

    for row_idx, v in enumerate(visits, start=2):
        team_leader = v.team_leader_name or (
            (v.visited_by.get_full_name() or v.visited_by.username) if v.visited_by else ''
        )
        values = [
            team_leader,
            v.visit_date.strftime('%d/%m/%Y') if v.visit_date else '',
            v.building.area or '',
            v.technicians_count,
            v.time_in.strftime('%H:%M') if v.time_in else '',
            v.bldg_villa_inspected_count,
            v.bldg_villa_infested_count,
            v.manholes_inspected_count,
            v.manholes_treated_count,
            v.manholes_infested_count,
            v.burrows_outside_count,
            v.burrows_infested_count,
            v.construction_inspected_count,
            v.construction_infested_count,
            v.masjed_inspected_count,
            v.masjed_infested_count,
            v.trees_inspected_count,
            v.trees_infested_count,
            v.electrical_inspected_count,
            v.electrical_infested_count,
            v.gov_offices_count,
            v.rodenticide_surefire_qty,
            v.rodenticide_facorat_qty,
            v.rodenticide_vertox_qty,
            v.rodenticide_sellioxid_qty,
            v.rodenticide_victor_qty,
            v.rodenticide_protect_qty,
            v.rodenticide_nocurat_qty,
            v.time_out.strftime('%H:%M') if v.time_out else '',
        ]
        for col, val in enumerate(values, start=1):
            c = ws.cell(row=row_idx, column=col, value=val)
            c.font = Font(name='Arial', size=10)
            c.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
            c.border = border

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    filename = f'rodent_control_{date_from:%Y-%m}_{date_to:%Y-%m}.xlsx'
    response = HttpResponse(
        output.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
