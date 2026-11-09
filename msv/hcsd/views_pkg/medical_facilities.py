"""
Medical facilities — the register of facilities inspected for medical waste.
Each facility's page lists its inspection reports and starts new ones.

URL prefix : /medical-waste/facilities/
Templates  : hcsd/medical_facility_*.html
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Max, Q
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..forms import MedicalFacilityForm
from ..models import MedicalFacility
from .common import _can_admin
from .medical_waste import _can_write

FACILITY_PAGE_SIZE = 25


@login_required
def medical_facility_list(request):
    query = (request.GET.get('q') or '').strip()
    facilities = MedicalFacility.objects.annotate(
        report_count=Count('inspections'), last_inspection=Max('inspections__inspection_date'),
    ).order_by('name', 'id')
    if query:
        facilities = facilities.filter(Q(name__icontains=query) | Q(license_number__icontains=query))
    page = Paginator(facilities, FACILITY_PAGE_SIZE).get_page(request.GET.get('page'))
    return render(request, 'hcsd/medical_facility_list.html', {
        'page': page,
        'query': query,
        'can_write': _can_write(request.user),
    })


def _facility_form_view(request, facility):
    if not _can_write(request.user):
        return HttpResponseForbidden('ليس لديك صلاحية لإدارة المنشآت.')
    form = MedicalFacilityForm(request.POST or None, instance=facility)
    if request.method == 'POST' and form.is_valid():
        saved = form.save(commit=False)
        if facility is None:
            saved.created_by = request.user
        saved.save()
        messages.success(request, f'تم حفظ بيانات المنشأة "{saved.name}".')
        return redirect('medical_facility_detail', pk=saved.pk)
    return render(request, 'hcsd/medical_facility_form.html', {'form': form, 'facility': facility})


@login_required
def medical_facility_create(request):
    return _facility_form_view(request, None)


@login_required
def medical_facility_edit(request, pk):
    return _facility_form_view(request, get_object_or_404(MedicalFacility, pk=pk))


@login_required
def medical_facility_detail(request, pk):
    facility = get_object_or_404(MedicalFacility, pk=pk)
    return render(request, 'hcsd/medical_facility_detail.html', {
        'facility': facility,
        'reports': facility.inspections.all(),
        'can_write': _can_write(request.user),
        'can_delete': _can_admin(request.user),
    })


@login_required
@require_POST
def medical_facility_delete(request, pk):
    if not _can_admin(request.user):
        return HttpResponseForbidden('ليس لديك صلاحية لحذف المنشآت.')
    facility = get_object_or_404(MedicalFacility, pk=pk)
    if facility.inspections.exists():
        messages.error(request, 'لا يمكن حذف منشأة لها تقارير تفتيش محفوظة.')
        return redirect('medical_facility_detail', pk=facility.pk)
    facility.delete()
    messages.success(request, f'تم حذف المنشأة "{facility.name}".')
    return redirect('medical_facility_list')
