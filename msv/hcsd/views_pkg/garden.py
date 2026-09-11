"""
Garden Follow-up — independent, standalone tracking of park/garden site
reviews (rodent activity around manholes, outside areas, and buildings).

URL prefix : /garden/
Templates  : hcsd/garden_*.html
"""

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..models import GARDEN_INFESTATION_TYPE_CHOICES, GardenAreaReview, GardenVisit
from .common import _can_admin, _can_data_entry, _can_garden_monitor, _can_rodent_control_monitor

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
    return (
        _can_admin(user) or _can_data_entry(user)
        or _can_garden_monitor(user) or _can_rodent_control_monitor(user)
    )


def _current_period_start():
    return timezone.localdate().replace(day=1)


def _garden_area_reviews_map(area_names, period_start):
    """Return {area_name: GardenAreaReview} for this month, creating any
    missing rows (defaulting to not-reviewed) so every area always has one."""
    reviews = {
        r.area_name: r
        for r in GardenAreaReview.objects.filter(area_name__in=area_names, period_start=period_start)
    }
    for name in area_names:
        if name not in reviews:
            reviews[name], _ = GardenAreaReview.objects.get_or_create(
                area_name=name, period_start=period_start,
            )
    return reviews


@login_required
def garden_list(request):
    query = (request.GET.get('q') or '').strip()
    show_reviewed = request.GET.get('reviewed') == '1'
    page_number = request.GET.get('page') or 1

    # Ordered to match the source Excel sheet's row order (its "No" column),
    # not the model's default newest-first ordering.
    visits_qs = GardenVisit.objects.order_by('id')
    if query:
        visits_qs = visits_qs.filter(area_name__icontains=query)

    period_start = _current_period_start()
    area_names = list(visits_qs.values_list('area_name', flat=True).distinct())
    area_reviews = _garden_area_reviews_map(area_names, period_start)

    reviewed_areas = {name for name, r in area_reviews.items() if r.is_reviewed}
    pending_count  = len(area_reviews) - len(reviewed_areas)

    if show_reviewed:
        visits_qs = visits_qs.filter(area_name__in=reviewed_areas)
    else:
        visits_qs = visits_qs.exclude(area_name__in=reviewed_areas)

    paginator = Paginator(visits_qs, 20)
    page_obj = paginator.get_page(page_number)
    for row in page_obj:
        row.review = area_reviews.get(row.area_name)

    return render(request, 'hcsd/garden_list.html', {
        'rows': page_obj,
        'page_obj': page_obj,
        'query': query,
        'show_reviewed': show_reviewed,
        'pending_count': pending_count,
        'reviewed_count': len(reviewed_areas),
        'total_count': paginator.count,
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

            # Updating the infestation data for an area counts as reviewing
            # it for this month — no need for a separate manual step.
            review, _created = GardenAreaReview.objects.get_or_create(
                area_name=obj.area_name, period_start=_current_period_start(),
            )
            if not review.is_reviewed:
                review.is_reviewed = True
                review.reviewed_by = request.user
                review.reviewed_at = timezone.now()
                review.save(update_fields=['is_reviewed', 'reviewed_by', 'reviewed_at'])
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


@login_required
@require_POST
def garden_area_review_toggle(request, pk):
    review = get_object_or_404(GardenAreaReview, pk=pk)
    if not _can_manage(request.user):
        return HttpResponseForbidden()

    review.is_reviewed = not review.is_reviewed
    review.reviewed_by = request.user if review.is_reviewed else None
    review.reviewed_at = timezone.now() if review.is_reviewed else None
    review.save(update_fields=['is_reviewed', 'reviewed_by', 'reviewed_at'])

    next_url = request.POST.get('next') or ''
    if next_url.startswith('/garden/'):
        return redirect(next_url)
    return redirect('garden_list')
