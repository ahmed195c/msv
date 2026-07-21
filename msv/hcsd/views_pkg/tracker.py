"""
Unified request tracker — combines weed-removal and container-transfer
requests into a single searchable/filterable list.

URL prefix : /all-requests/
Template   : hcsd/complaints/all_requests.html
"""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from ..models import ContainerTransferRequest, WeedRemovalRequest
from .common import _get_lang


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

    return render(request, 'hcsd/complaints/all_requests.html', {
        'lang':               lang,
        'items':              items,
        'type_filter':        type_filter,
        'status_filter':      status_filter,
        'search':             search,
        'weed_statuses':      weed_statuses,
        'container_statuses': container_statuses,
    })
