"""
Garden Follow-up — independent, standalone tracking of park/garden site
reviews (rodent activity around manholes, outside areas, and buildings).

URL prefix : /garden/
Templates  : hcsd/garden_*.html
"""

import io
import logging
import os
import re
import zipfile
from itertools import groupby
from urllib.parse import quote

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..models import (
    GARDEN_INFESTATION_TYPE_CHOICES, GardenAreaReview, GardenVisit,
    GardenVisitChangeLog, GardenVisitPhoto,
)
from .common import (
    _can_admin, _can_data_entry, _can_field_agent, _can_garden_monitor,
    _can_rodent_control_field_agent, _can_rodent_control_monitor, _get_lang,
)

logger = logging.getLogger(__name__)


def _safe_filename_part(text):
    text = (text or '').strip()
    text = re.sub(r'[\\/:*?"<>|]', '-', text)
    text = re.sub(r'\s+', '_', text)
    return text or 'بدون_اسم'


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


def _can_add_garden(user):
    """Adding a new visit is allowed for everyone who can manage, plus the
    field-agent roles, which can ONLY add — not edit, delete, or review."""
    return _can_manage(user) or _can_field_agent(user) or _can_rodent_control_field_agent(user)


def _log_garden_change(user, action, notes='', visit=None, area_name=''):
    GardenVisitChangeLog.objects.create(
        visit=visit,
        area_name=area_name or (visit.area_name if visit else ''),
        action=action,
        notes=notes,
        changed_by=user if user and user.is_authenticated else None,
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
        'can_add': _can_add_garden(request.user),
        'can_admin': _can_admin(request.user),
        'lang': _get_lang(request),
    })


@login_required
def garden_create(request):
    if not _can_add_garden(request.user):
        return redirect('garden_list')

    lang = _get_lang(request)
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
            errors.append('Please enter the area name.' if lang == 'en' else 'يرجى إدخال اسم المنطقة.')

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
            _log_garden_change(request.user, 'created', notes='تمت إضافة موقع جديد.', visit=obj)

            # Each "spot_photos_<N>" / "spot_description_<N>" pair is one
            # infestation spot — a visit can have several, each with its
            # own set of photos and an optional shared description.
            spot_indices = set()
            for key in request.POST:
                if key.startswith('spot_description_'):
                    spot_indices.add(key[len('spot_description_'):])
            for key in request.FILES:
                if key.startswith('spot_photos_'):
                    spot_indices.add(key[len('spot_photos_'):])

            for idx in spot_indices:
                try:
                    spot_number = int(idx)
                except ValueError:
                    continue
                description = (request.POST.get(f'spot_description_{idx}') or '').strip()
                for photo in request.FILES.getlist(f'spot_photos_{idx}'):
                    GardenVisitPhoto.objects.create(
                        garden_visit=obj, spot_number=spot_number,
                        description=description, file=photo, uploaded_by=request.user,
                    )
            return redirect('garden_list')

    return render(request, 'hcsd/garden_create.html', {
        'errors': errors,
        'post': request.POST,
        'infestation_type_choices': GARDEN_INFESTATION_TYPE_CHOICES,
        'selected_infestation_types': request.POST.getlist('infestation_type'),
        'lang': lang,
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
            old_lat, old_lng = obj.latitude, obj.longitude
            old_url, old_details = obj.google_maps_url, obj.location_details

            obj.latitude         = _float('latitude')
            obj.longitude        = _float('longitude')
            obj.google_maps_url  = (request.POST.get('google_maps_url') or '').strip()
            obj.location_details = (request.POST.get('location_details') or '').strip()
            obj.save(update_fields=['latitude', 'longitude', 'google_maps_url', 'location_details'])

            changed_parts = []
            if (old_lat, old_lng) != (obj.latitude, obj.longitude):
                changed_parts.append('الإحداثيات')
            if old_url != obj.google_maps_url:
                changed_parts.append('رابط خرائط قوقل')
            if old_details != obj.location_details:
                changed_parts.append('تفاصيل الموقع')
            if changed_parts:
                _log_garden_change(
                    request.user, 'location_updated', visit=obj,
                    notes='تم تحديث: ' + '، '.join(changed_parts),
                )
        else:
            old_manholes, old_outside, old_bldg = (
                obj.infested_manholes, obj.infested_outside, obj.total_infested_bldg,
            )
            old_notes, old_type = obj.notes, obj.infestation_type

            obj.infested_manholes    = _int('infested_manholes')
            obj.infested_outside     = _int('infested_outside')
            obj.total_infested_bldg  = _int('total_infested_bldg')
            obj.notes                = (request.POST.get('notes') or '').strip()
            obj.infestation_type     = _infestation_type_from_post(request)
            obj.save(update_fields=[
                'infested_manholes', 'infested_outside', 'total_infested_bldg',
                'notes', 'infestation_type',
            ])

            def _fmt(value):
                return '—' if value is None else str(value)

            diff_parts = []
            if old_manholes != obj.infested_manholes:
                diff_parts.append(f'مناهيل مصابة: {_fmt(old_manholes)} ← {_fmt(obj.infested_manholes)}')
            if old_outside != obj.infested_outside:
                diff_parts.append(f'إصابة خارجية: {_fmt(old_outside)} ← {_fmt(obj.infested_outside)}')
            if old_bldg != obj.total_infested_bldg:
                diff_parts.append(f'إجمالي مباني مصابة: {_fmt(old_bldg)} ← {_fmt(obj.total_infested_bldg)}')
            if old_notes != obj.notes:
                diff_parts.append('تم تعديل الملاحظات')
            if old_type != obj.infestation_type:
                diff_parts.append('تم تعديل نوع الإصابة')
            if diff_parts:
                _log_garden_change(request.user, 'updated', visit=obj, notes='، '.join(diff_parts))

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

    photo_spots = []
    for spot_number, group in groupby(obj.photos.all(), key=lambda p: p.spot_number):
        group = list(group)
        photo_spots.append({
            'spot_number': spot_number,
            'description': group[0].description,
            'photos': group,
        })

    can_admin = _can_admin(request.user)
    change_logs = (
        list(obj.change_logs.select_related('changed_by').order_by('-created_at'))
        if can_admin else []
    )

    return render(request, 'hcsd/garden_detail.html', {
        'obj': obj,
        'can_manage': can_manage,
        'can_admin': can_admin,
        'note_choices': GARDEN_NOTE_CHOICES,
        'infestation_type_choices': GARDEN_INFESTATION_TYPE_CHOICES,
        'photo_spots': photo_spots,
        'change_logs': change_logs,
        'lang': _get_lang(request),
    })


@login_required
def garden_visit_report(request, pk):
    """Download a ZIP archive with a visit's full details as a plain text
    file plus every infestation-spot photo — for archiving one request."""
    obj = get_object_or_404(GardenVisit, pk=pk)

    lines = [
        'تقرير زيارة متابعة المناطق',
        '=' * 30,
        f'اسم المنطقة: {obj.area_name or "—"}',
        f'تفاصيل الموقع: {obj.location_details or "—"}',
        f'تاريخ الزيارة: {obj.visit_date.strftime("%d/%m/%Y") if obj.visit_date else "—"}',
    ]
    if obj.latitude is not None and obj.longitude is not None:
        lines.append(f'الإحداثيات: {obj.latitude}, {obj.longitude}')
        maps_url = obj.google_maps_url or f'https://www.google.com/maps?q={obj.latitude},{obj.longitude}'
        lines.append(f'رابط خرائط قوقل: {maps_url}')
    elif obj.google_maps_url:
        lines.append(f'رابط خرائط قوقل: {obj.google_maps_url}')

    lines += [
        '',
        'بيانات الإصابة',
        '-' * 20,
        f'مناهيل مصابة: {obj.infested_manholes if obj.infested_manholes is not None else "—"}',
        f'إصابة خارجية: {obj.infested_outside if obj.infested_outside is not None else "—"}',
        f'إجمالي مباني مصابة: {obj.total_infested_bldg if obj.total_infested_bldg is not None else "—"}',
    ]
    if obj.infestation_type:
        lines.append(f'نوع الإصابة: {obj.infestation_type_display}')
    if obj.notes:
        lines.append(f'ملاحظات: {obj.notes}')

    photos_qs = obj.photos.all()
    spots = []
    if photos_qs:
        lines += ['', 'أماكن الإصابة', '-' * 20]
        for spot_number, group in groupby(photos_qs, key=lambda p: p.spot_number):
            group = list(group)
            spots.append((spot_number, group))
            desc = group[0].description or 'بدون وصف'
            lines.append(f'مكان الإصابة {spot_number}: {desc} ({len(group)} صورة)')

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('تفاصيل_الطلب.txt', ('\n'.join(lines)).encode('utf-8-sig'))
        for spot_number, group in spots:
            for i, photo in enumerate(group, start=1):
                try:
                    if not photo.file or not os.path.exists(photo.file.path):
                        continue
                    ext = os.path.splitext(photo.file.name)[1] or '.jpg'
                    zf.write(photo.file.path, f'مكان الإصابة {spot_number}/صورة_{i}{ext}')
                except Exception:
                    logger.exception('Failed to add photo %s to garden visit archive', photo.pk)
    buffer.seek(0)

    area_part = _safe_filename_part(obj.area_name)
    date_part = obj.visit_date.strftime('%Y-%m-%d') if obj.visit_date else 'بدون_تاريخ'
    filename = f'{area_part}_{date_part}_{obj.pk}.zip'
    ascii_fallback = filename.encode('ascii', 'ignore').decode('ascii') or f'garden_visit_{obj.pk}.zip'
    response = HttpResponse(buffer.getvalue(), content_type='application/zip')
    response['Content-Disposition'] = (
        f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(filename)}"
    )
    return response


@login_required
@require_POST
def garden_delete(request, pk):
    obj = get_object_or_404(GardenVisit, pk=pk)
    if not _can_admin(request.user):
        return HttpResponseForbidden()

    _log_garden_change(request.user, 'deleted', notes='تم حذف الموقع.', visit=obj)
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

    _log_garden_change(
        request.user, 'review_toggled', area_name=review.area_name,
        notes='تمت مراجعة المنطقة.' if review.is_reviewed else 'تم إلغاء تعليم المراجعة.',
    )

    next_url = request.POST.get('next') or ''
    if next_url.startswith('/garden/'):
        return redirect(next_url)
    return redirect('garden_list')


@login_required
def garden_change_log(request):
    if not _can_admin(request.user):
        return redirect('garden_list')

    logs_qs = GardenVisitChangeLog.objects.select_related('changed_by', 'visit').order_by('-created_at')
    paginator = Paginator(logs_qs, 50)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'hcsd/garden_change_log.html', {
        'page_obj': page_obj,
        'lang': _get_lang(request),
    })
