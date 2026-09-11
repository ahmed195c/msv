"""
Garden Follow-up — independent, standalone tracking of park/garden site
reviews (rodent activity around manholes, outside areas, and buildings).

URL prefix : /garden/
Templates  : hcsd/garden_*.html
"""

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..models import GARDEN_INFESTATION_TYPE_CHOICES, GardenVisit
from .common import _can_admin, _can_data_entry, _can_garden_monitor

GARDEN_NOTE_CHOICES = [
    'إصابة خارجية / Outside Infestation',
    'منهول مصاب / Infested Manhole',
    'عدد المباني المصاب / Number of Infested Buildings',
]


def _infestation_type_from_post(request):
    valid_codes = {code for code, _ in GARDEN_INFESTATION_TYPE_CHOICES}
    selected = [code for code in request.POST.getlist('infestation_type') if code in valid_codes]
    return ','.join(selected)


def _can_manage(user):
    return _can_admin(user) or _can_data_entry(user) or _can_garden_monitor(user)


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
        area_name        = (request.POST.get('area_name') or '').strip()
        location_details = (request.POST.get('location_details') or '').strip()
        google_maps_url  = (request.POST.get('google_maps_url') or '').strip()

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

        if not area_name:
            errors.append('يرجى إدخال اسم المنطقة.')

        if not errors:
            obj = GardenVisit.objects.create(
                visit_date=timezone.localdate(),
                area_name=area_name,
                location_details=location_details,
                google_maps_url=google_maps_url,
                latitude=_float('latitude'),
                longitude=_float('longitude'),
                infested_manholes=_int('infested_manholes'),
                infested_outside=_int('infested_outside'),
                total_infested_bldg=_int('total_infested_bldg'),
                infestation_type=_infestation_type_from_post(request),
                created_by=request.user,
            )
            return redirect('garden_list')

    return render(request, 'hcsd/garden_create.html', {
        'errors': errors,
        'post': request.POST,
        'infestation_type_choices': GARDEN_INFESTATION_TYPE_CHOICES,
        'selected_infestation_types': request.POST.getlist('infestation_type'),
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

        def _float(name):
            raw = (request.POST.get(name) or '').strip()
            try:
                return float(raw) if raw else None
            except ValueError:
                return None

        if request.POST.get('action') == 'save_location':
            obj.latitude         = _float('latitude')
            obj.longitude        = _float('longitude')
            obj.google_maps_url  = (request.POST.get('google_maps_url') or '').strip()
            obj.location_details = (request.POST.get('location_details') or '').strip()
            obj.save(update_fields=['latitude', 'longitude', 'google_maps_url', 'location_details'])
        else:
            obj.infested_manholes    = _int('infested_manholes')
            obj.infested_outside     = _int('infested_outside')
            obj.total_infested_bldg  = _int('total_infested_bldg')
            obj.notes                = (request.POST.get('notes') or '').strip()
            obj.infestation_type     = _infestation_type_from_post(request)
            obj.save(update_fields=[
                'infested_manholes', 'infested_outside', 'total_infested_bldg',
                'notes', 'infestation_type',
            ])
        return redirect('garden_detail', pk=pk)

    return render(request, 'hcsd/garden_detail.html', {
        'obj': obj,
        'can_manage': can_manage,
        'can_admin': _can_admin(request.user),
        'note_choices': GARDEN_NOTE_CHOICES,
        'infestation_type_choices': GARDEN_INFESTATION_TYPE_CHOICES,
    })


@login_required
@require_POST
def garden_delete(request, pk):
    obj = get_object_or_404(GardenVisit, pk=pk)
    if not _can_admin(request.user):
        return HttpResponseForbidden()

    obj.delete()
    return redirect('garden_list')
