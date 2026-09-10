"""
Garden Follow-up — independent, standalone tracking of park/garden site
reviews (rodent activity around manholes, outside areas, and buildings).

URL prefix : /garden/
Templates  : hcsd/garden_*.html
"""

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..models import GardenVisit
from .common import _can_admin, _can_data_entry


def _can_manage(user):
    return _can_admin(user) or _can_data_entry(user)


@login_required
def garden_list(request):
    query = (request.GET.get('q') or '').strip()

    visits_qs = GardenVisit.objects.all()
    if query:
        visits_qs = visits_qs.filter(area_name__icontains=query)

    return render(request, 'hcsd/garden_list.html', {
        'rows': list(visits_qs),
        'query': query,
        'total_count': GardenVisit.objects.count(),
        'can_manage': _can_manage(request.user),
        'can_admin': _can_admin(request.user),
    })


@login_required
def garden_create(request):
    if not _can_manage(request.user):
        return redirect('garden_list')

    errors = []
    if request.method == 'POST':
        import datetime as _dt

        raw_date = (request.POST.get('visit_date') or '').strip()
        try:
            visit_date = _dt.date.fromisoformat(raw_date)
        except ValueError:
            visit_date = None
        area_name       = (request.POST.get('area_name') or '').strip()
        google_maps_url = (request.POST.get('google_maps_url') or '').strip()
        notes           = (request.POST.get('notes') or '').strip()

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

        if not visit_date:
            errors.append('يرجى إدخال تاريخ صحيح.')
        if not area_name:
            errors.append('يرجى إدخال اسم المنطقة.')

        if not errors:
            obj = GardenVisit.objects.create(
                visit_date=visit_date,
                area_name=area_name,
                google_maps_url=google_maps_url,
                latitude=_float('latitude'),
                longitude=_float('longitude'),
                infested_manholes=_int('infested_manholes'),
                infested_outside=_int('infested_outside'),
                total_infested_bldg=_int('total_infested_bldg'),
                notes=notes,
                created_by=request.user,
            )
            return redirect('garden_list')

    return render(request, 'hcsd/garden_create.html', {
        'errors': errors,
        'post': request.POST,
    })


@login_required
def garden_detail(request, pk):
    obj = get_object_or_404(GardenVisit, pk=pk)
    can_manage = _can_manage(request.user)

    if request.method == 'POST':
        if not can_manage:
            return HttpResponseForbidden()

        def _int(name):
            raw = (request.POST.get(name) or '').strip()
            try:
                return int(raw) if raw else None
            except ValueError:
                return None

        obj.infested_manholes    = _int('infested_manholes')
        obj.infested_outside     = _int('infested_outside')
        obj.total_infested_bldg  = _int('total_infested_bldg')
        obj.notes                = (request.POST.get('notes') or '').strip()
        obj.save(update_fields=['infested_manholes', 'infested_outside', 'total_infested_bldg', 'notes'])
        return redirect('garden_detail', pk=pk)

    return render(request, 'hcsd/garden_detail.html', {
        'obj': obj,
        'can_manage': can_manage,
        'can_admin': _can_admin(request.user),
    })


@login_required
@require_POST
def garden_delete(request, pk):
    obj = get_object_or_404(GardenVisit, pk=pk)
    if not _can_admin(request.user):
        return HttpResponseForbidden()

    obj.delete()
    return redirect('garden_list')
