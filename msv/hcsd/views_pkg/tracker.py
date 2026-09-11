"""
Unified request tracker — combines weed-removal and container-transfer
requests into a single searchable/filterable list.

URL prefix : /all-requests/
Template   : hcsd/complaints/all_requests.html
"""

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..models import (
    ContainerTransferInspection, ContainerTransferRequest,
    WeedRemovalInspection, WeedRemovalRequest, WeedRemovalSupervisorTask,
)
from .common import _can_admin, _can_data_entry, _get_lang
from .weed_removal import _weed_inspector_users_qs, _weed_supervisor_users_qs


def _can_manage(user):
    return _can_admin(user) or _can_data_entry(user)


@login_required
def all_requests(request):
    lang = _get_lang(request)
    type_filter   = (request.GET.get('type') or 'all').strip()
    status_filter = (request.GET.get('status') or 'all').strip()
    search        = (request.GET.get('q') or '').strip()

    items = []

    if type_filter in ('all', 'weed'):
        qs = WeedRemovalRequest.objects.select_related('created_by').order_by('-created_at')
        if status_filter != 'all':
            qs = qs.filter(status=status_filter)
        if search:
            qs = qs.filter(complaint_number__icontains=search) | qs.filter(complainant_name__icontains=search) | qs.filter(area__icontains=search)
        for c in qs:
            items.append({
                'kind':        'weed',
                'kind_label':  'حشائش',
                'pk':          c.pk,
                'item_key':    f'weed:{c.pk}',
                'number':      c.complaint_number,
                'name':        c.complainant_name,
                'area':        c.area,
                'status':      c.status,
                'created_at':  c.created_at,
                'created_by':  c.created_by,
                'detail_url':  f'/weed-removal/{c.pk}/',
            })

    if type_filter in ('all', 'container'):
        qs = ContainerTransferRequest.objects.select_related('created_by').order_by('-created_at')
        if status_filter != 'all':
            qs = qs.filter(status=status_filter)
        if search:
            qs = qs.filter(complaint_number__icontains=search) | qs.filter(complainant_name__icontains=search) | qs.filter(area__icontains=search)
        for c in qs:
            items.append({
                'kind':        'container',
                'kind_label':  'حاوية',
                'pk':          c.pk,
                'item_key':    f'container:{c.pk}',
                'number':      c.complaint_number,
                'name':        c.complainant_name,
                'area':        c.area,
                'status':      c.status,
                'created_at':  c.created_at,
                'created_by':  c.created_by,
                'detail_url':  f'/container-transfers/{c.pk}/',
            })

    items.sort(key=lambda x: x['created_at'], reverse=True)

    weed_statuses      = WeedRemovalRequest.STATUS_CHOICES
    container_statuses = ContainerTransferRequest.STATUS_CHOICES

    can_manage = _can_manage(request.user)
    assigned_count = request.GET.get('assigned')

    def _user_options(qs):
        return [{'id': u.pk, 'label': u.get_full_name() or u.username} for u in qs]

    return render(request, 'hcsd/complaints/all_requests.html', {
        'lang':               lang,
        'items':              items,
        'type_filter':        type_filter,
        'status_filter':      status_filter,
        'search':             search,
        'weed_statuses':      weed_statuses,
        'container_statuses': container_statuses,
        'can_manage':         can_manage,
        'assigned_count':     assigned_count,
        'weed_inspectors':    _user_options(_weed_inspector_users_qs()) if can_manage else [],
        'weed_supervisors':   _user_options(_weed_supervisor_users_qs()) if can_manage else [],
        'container_inspectors': _user_options(User.objects.filter(is_active=True).order_by('first_name', 'username')) if can_manage else [],
    })


@login_required
@require_POST
def bulk_assign_requests(request):
    if not _can_manage(request.user):
        return redirect('all_requests')

    role      = (request.POST.get('role') or '').strip()
    person_id = (request.POST.get('person_id') or '').strip()
    item_keys = request.POST.getlist('items')

    if role not in ('inspector', 'supervisor') or not person_id or not item_keys:
        return redirect('all_requests')

    person = get_object_or_404(User, pk=person_id, is_active=True)

    assigned_count = 0
    for key in item_keys:
        kind, _, raw_pk = key.partition(':')
        if not raw_pk.isdigit():
            continue
        pk = int(raw_pk)

        if kind == 'weed':
            obj = WeedRemovalRequest.objects.filter(pk=pk).first()
            if not obj:
                continue
            if role == 'inspector':
                inspection, created = WeedRemovalInspection.objects.get_or_create(
                    request=obj, defaults={'inspector': person, 'assigned_by': request.user},
                )
                if not created:
                    inspection.inspector   = person
                    inspection.assigned_by = request.user
                    inspection.save(update_fields=['inspector', 'assigned_by'])
                obj.status = 'inspector_assigned'
            else:
                task, created = WeedRemovalSupervisorTask.objects.get_or_create(
                    request=obj, defaults={'supervisor': person, 'assigned_by': request.user},
                )
                if not created:
                    task.supervisor  = person
                    task.assigned_by = request.user
                    task.save(update_fields=['supervisor', 'assigned_by'])
                obj.status = 'supervisor_assigned'
            obj.save(update_fields=['status', 'updated_at'])
            assigned_count += 1

        elif kind == 'container' and role == 'inspector':
            obj = ContainerTransferRequest.objects.filter(pk=pk).first()
            if not obj:
                continue
            inspection, created = ContainerTransferInspection.objects.get_or_create(
                request=obj, defaults={'inspector': person, 'assigned_by': request.user},
            )
            if not created:
                inspection.inspector   = person
                inspection.assigned_by = request.user
                inspection.save(update_fields=['inspector', 'assigned_by'])
            obj.status = 'assigned'
            obj.save(update_fields=['status', 'updated_at'])
            assigned_count += 1

    return redirect(f'/all-requests/?assigned={assigned_count}')
