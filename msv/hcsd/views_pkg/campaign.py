"""
Campaign Follow-up — independent, standalone tracking.

URL prefix : /campaign/
Templates  : hcsd/campaign_*.html

A site is "جارية" (ongoing) until an inspector writes any note on it, at
which point it's "تم اتخاذ إجراء" (action taken). No separate status field —
the note itself is the whole status model.
"""

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..models import CampaignRequest
from .common import _can_admin, _can_data_entry


def _can_manage(user):
    return _can_admin(user) or _can_data_entry(user)


@login_required
def campaign_list(request):
    query = (request.GET.get('q') or '').strip()
    status_filter = (request.GET.get('status') or 'all').strip()

    requests_qs = CampaignRequest.objects.all()
    if query:
        requests_qs = requests_qs.filter(company_name__icontains=query)
    if status_filter == 'ongoing':
        requests_qs = requests_qs.filter(note='')
    elif status_filter == 'done':
        requests_qs = requests_qs.exclude(note='')

    requests_list = list(requests_qs)
    ongoing_count = CampaignRequest.objects.filter(note='').count()
    done_count = CampaignRequest.objects.exclude(note='').count()

    return render(request, 'hcsd/campaign_list.html', {
        'rows': requests_list,
        'query': query,
        'status_filter': status_filter,
        'ongoing_count': ongoing_count,
        'done_count': done_count,
        'total_count': ongoing_count + done_count,
        'can_manage': _can_manage(request.user),
    })


@login_required
def campaign_create(request):
    if not _can_manage(request.user):
        return redirect('campaign_list')

    errors = []
    if request.method == 'POST':
        company_name    = (request.POST.get('company_name') or '').strip()
        location        = (request.POST.get('location') or '').strip()
        building_number = (request.POST.get('building_number') or '').strip()
        area            = (request.POST.get('area') or '').strip()
        google_maps_url = (request.POST.get('google_maps_url') or '').strip()
        photo           = request.FILES.get('photo')

        if not company_name:
            errors.append('يرجى إدخال اسم الشركة.')

        if not errors:
            obj = CampaignRequest.objects.create(
                company_name=company_name, location=location,
                building_number=building_number, area=area,
                google_maps_url=google_maps_url, photo=photo,
                created_by=request.user,
            )
            return redirect('campaign_detail', pk=obj.pk)

    return render(request, 'hcsd/campaign_create.html', {
        'errors': errors,
        'post': request.POST,
    })


@login_required
def campaign_detail(request, pk):
    obj = get_object_or_404(CampaignRequest, pk=pk)
    can_manage = _can_manage(request.user)

    if request.method == 'POST' and can_manage:
        action = request.POST.get('action', 'note')
        if action == 'update_request':
            obj.company_name    = (request.POST.get('company_name') or obj.company_name).strip()
            obj.building_number = (request.POST.get('building_number') or '').strip()
            obj.area            = (request.POST.get('area') or '').strip()
            obj.location        = (request.POST.get('location') or '').strip()
            obj.google_maps_url = (request.POST.get('google_maps_url') or '').strip()
            update_fields = ['company_name', 'building_number', 'area', 'location', 'google_maps_url']
            new_photo = request.FILES.get('photo')
            if new_photo:
                obj.photo = new_photo
                update_fields.append('photo')
            obj.save(update_fields=update_fields)
        else:
            obj.note = (request.POST.get('note') or '').strip()
            obj.noted_by = request.user
            obj.noted_at = timezone.now()
            obj.save(update_fields=['note', 'noted_by', 'noted_at'])
        return redirect('campaign_detail', pk=pk)

    return render(request, 'hcsd/campaign_detail.html', {
        'obj': obj,
        'can_manage': can_manage,
        'can_admin': _can_admin(request.user),
    })


@login_required
@require_POST
def campaign_delete(request, pk):
    obj = get_object_or_404(CampaignRequest, pk=pk)
    if not _can_admin(request.user):
        return HttpResponseForbidden()

    obj.delete()
    return redirect('campaign_list')
