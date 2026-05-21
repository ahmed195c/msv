import calendar
import datetime
import os

from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group, User
from django.utils import timezone
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from ..models import (
    Company, CompanyChangeLog, EngineerCertificateRequest, EngineerLeave,
    Enginer, EnginerStatusLog, InspectorReview, PesticideTransportPermit,
    PirmetChangeLog, PirmetClearance, PirmetDocument, PublicHealthExamRequest,
    PublicHealthExamRequestDocument, RequirementInsuranceRequest,
    WasteDisposalRequest, WasteDisposalRequestDocument,
)
from ..forms import StaffRegistrationForm
from .common import (
    ALLOWED_DOC_EXTENSIONS, PEST_ACTIVITY_ORDER, PEST_ACTIVITY_KEYS,
    PUBLIC_HEALTH_ACTIVITY_KEYS, GROUP_NAME_ALIASES, ROLE_CAPABILITIES,
    INSPECTION_REPORT_PHOTO_PREFIX, VEHICLE_INSPECTION_REPORT_PHOTO_PREFIX,
    _parse_int, _parse_int_list, _parse_date, _calculate_permit_expiry,
    _add_months, _expired_trade_license_notice, _activities_for_enginer,
    _restricted_activities_for_enginer, _has_any_group, _role_is_admin,
    _role_is_inspector, _role_is_data_entry, _role_is_head, _user_roles,
    _has_capability, _can_admin, _can_inspector, _can_data_entry, _can_head,
    _company_has_active_extension, _can_create_exam_request,
    _inspector_users_qs, _display_user_name, _inspector_review_name,
    _inspection_report_decision_from_note, _inspection_report_photo_count_from_note,
    _inspection_report_photo_docs_by_prefix, _inspection_report_photo_docs,
    _vehicle_inspection_report_photo_docs, _request_documents,
    _latest_expired_activity_permit_before, _delay_months_after_first_month,
    _initial_violation_reference_expiry, _violation_reference_expiry_date,
    _log_pirmet_change, _log_company_change, _split_activities,
    _activity_keys_for_company, _permit_label_ar, _permit_detail_url_name,
    _certificate_type_for_exam, _certificate_expiry, _enginer_has_passed_for_certificate,
    _is_effective_active_permit, _engineer_no_certificate_notice,
    _group_clearances_by_status, _validate_engineer_for_type,
)
@login_required
def register(request):
    if not _can_admin(request.user):
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden('ليس لديك صلاحية لإنشاء مستخدمين جدد.')
    if request.method == 'POST':
        form = StaffRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            data_entry_group = Group.objects.filter(
                name__in=GROUP_NAME_ALIASES['data_entry']
            ).first()
            if not data_entry_group:
                data_entry_group = Group.objects.create(name='Data Entry')
            if data_entry_group:
                user.groups.add(data_entry_group)
            return redirect('home')
    else:
        form = StaffRegistrationForm()

    return render(request, 'hcsd/register.html', {'form': form})


@login_required
def vehicle_permit_print(request, permit_id):
    pirmet = get_object_or_404(
        PirmetClearance.objects.select_related('company', 'transport_details'),
        id=permit_id,
        permit_type='pesticide_transport',
    )
    transport = getattr(pirmet, 'transport_details', None)
    return render(request, 'hcsd/vehicle_permit_print.html', {
        'pirmet': pirmet,
        'transport': transport,
        'permit_detail_path': reverse('vehicle_permit_detail', args=[pirmet.id]),
    })


@login_required
def waste_disposal_permit_print(request, permit_id):
    # Get the requested permit to identify the company
    base_permit = get_object_or_404(
        PirmetClearance.objects.select_related('company'),
        id=permit_id,
        permit_type='waste_disposal',
    )
    company = base_permit.company

    # Use the latest issued permit for this company as the active permit
    permit = (
        PirmetClearance.objects
        .select_related('company', 'waste_details')
        .filter(company=company, permit_type='waste_disposal', status__in=['issued', 'disposal_approved'])
        .order_by('-issue_date', '-id')
        .first()
    )
    # Fall back to the requested permit if no issued one exists
    if permit is None:
        permit = get_object_or_404(
            PirmetClearance.objects.select_related('company', 'waste_details'),
            id=permit_id,
            permit_type='waste_disposal',
            status__in=['issued'],
        )

    waste = getattr(permit, 'waste_details', None)
    return render(request, 'hcsd/waste_disposal_permit_print.html', {
        'permit': permit,
        'waste': waste,
        'permit_detail_path': reverse('waste_permit_detail', args=[permit.id]),
    })


@login_required
def printer(request, permit_id=None):
    requested_id = permit_id or _parse_int(request.GET.get('permit_id'))
    permits_qs = PirmetClearance.objects.select_related('company', 'company__enginer').filter(
        permit_type='pest_control',
        status__in=['issued'],
    )

    if requested_id:
        permit = get_object_or_404(permits_qs, id=requested_id)
        if not permit.payment_receipt:
            return redirect('pest_control_permit_detail', id=permit.id)
    else:
        permit = permits_qs.exclude(payment_receipt='').exclude(
            payment_receipt__isnull=True
        ).order_by('-issue_date', '-dateOfCreation').first()

    return render(
        request,
        'hcsd/printer.html',
        {
            'permit': permit,
            'allowed_activities': _split_activities(permit.allowed_activities) if permit else [],
            'restricted_activities': _split_activities(permit.restricted_activities) if permit else [],
        },
    )
