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

from django.contrib.auth.decorators import login_required
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
            visit_date_raw = (request.POST.get('visit_date') or '').strip()
            try:
                visit_date = datetime.date.fromisoformat(visit_date_raw)
            except ValueError:
                visit_date = timezone.localdate()

            current_visit.visit_date = visit_date
            current_visit.visited_by = request.user
            current_visit.inspected = bool(request.POST.get('inspected'))
            current_visit.infested = bool(request.POST.get('infested'))
            current_visit.damaged = bool(request.POST.get('damaged'))
            current_visit.newly_installed = bool(request.POST.get('newly_installed'))
            current_visit.replenished = bool(request.POST.get('replenished'))
            current_visit.rodenticide_type = (request.POST.get('rodenticide_type') or '').strip()
            rq_raw = (request.POST.get('rodenticide_quantity') or '').strip()
            try:
                current_visit.rodenticide_quantity = float(rq_raw) if rq_raw else None
            except ValueError:
                current_visit.rodenticide_quantity = None
            current_visit.notes = (request.POST.get('notes') or '').strip()
            current_visit.save(update_fields=[
                'visit_date', 'visited_by', 'inspected', 'infested', 'damaged',
                'newly_installed', 'replenished', 'rodenticide_type',
                'rodenticide_quantity', 'notes',
            ])
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
