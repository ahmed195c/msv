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
def home(request):
    permits_qs = PirmetClearance.objects.filter(
        permit_type__in=['pest_control', 'pesticide_transport', 'waste_disposal']
    )
    total_permits = permits_qs.count()
    issued_permits = permits_qs.filter(status='issued').count()
    pending_permits = (
        permits_qs.filter(
            status__in=[
                'order_received',
                'inspection_payment_pending',
                'inspection_pending',
                'review_pending',
                'payment_pending',
                'disposal_approved',
                'head_approved',
                'inspection_completed',
            ]
        )
        .exclude(
            status='inspection_completed',
            unapprovedReason__isnull=False,
        )
        .exclude(
            status='inspection_completed',
            unapprovedReason='',
        )
        .count()
    )
    needs_completion_permits = permits_qs.filter(
        Q(status__in=['needs_completion', 'rejected', 'disposal_rejected', 'closed_requirements_pending'])
        | (Q(status='inspection_completed') & ~Q(unapprovedReason__isnull=True) & ~Q(unapprovedReason=''))
    ).count()

    status_label_map = {
        'order_received': 'بانتظار اصدار رابط دفع التفتيش',
        'inspection_payment_pending': 'بانتظار دفع التفتيش',
        'inspection_pending': 'جاهز للاستلام',
        'review_pending': 'بانتظار المراجعة',
        'approved': 'معتمد من المفتش',
        'needs_completion': 'غير معتمد',
        'payment_pending': 'بانتظار دفع التصريح',
        'violation_payment_link_pending': 'بانتظار إرسال رابط دفع المخالفة',
        'violation_payment_pending': 'بانتظار دفع المخالفة',
        'issued': 'تم إصدار التصريح',
        'head_approved': 'تم الاعتماد النهائي',
        'closed_requirements_pending': 'مغلق - اشتراطات واجبة الاستيفاء',
        'cancelled_admin': 'مغلق',
        'disposal_approved': 'إتلاف معتمد',
        'disposal_rejected': 'إتلاف مرفوض',
    }
    status_breakdown = [
        {
            'key': row['status'],
            'label': status_label_map.get(row['status'], row['status']),
            'total': row['total'],
        }
        for row in permits_qs.values('status').annotate(total=Count('id')).order_by('-total')[:6]
    ]
    permit_type_breakdown = [
        {
            'key': row['permit_type'],
            'label': _permit_label_ar(row['permit_type']),
            'total': row['total'],
        }
        for row in permits_qs.values('permit_type').annotate(total=Count('id')).order_by('-total')
    ]
    today = timezone.localdate()
    active_extension_companies = (
        CompanyChangeLog.objects.filter(
            action='extension_requested',
        )
        .filter(
            Q(extension_end_date__isnull=True) | Q(extension_end_date__gte=today)
        )
        .values('company_id')
        .distinct()
        .count()
    )

    engineers_on_leave = EngineerLeave.objects.filter(actual_return_date__isnull=True).count()

    # ── Permits expiring within 7 days ──────────────────────────────────────
    week_ahead = today + datetime.timedelta(days=7)
    expiring_soon_qs = (
        PirmetClearance.objects.filter(
            permit_type__in=['pest_control', 'pesticide_transport', 'waste_disposal'],
            status='issued',
            dateOfExpiry__gte=today,
            dateOfExpiry__lte=week_ahead,
        )
        .select_related('company')
        .order_by('dateOfExpiry')
    )
    expiring_soon = []
    for p in expiring_soon_qs:
        days_left = (p.dateOfExpiry - today).days
        expiring_soon.append({
            'permit': p,
            'days_left': days_left,
            'label': _permit_label_ar(p.permit_type),
        })

    return render(
        request,
        'hcsd/home.html',
        {
            'total_companies': Company.objects.count(),
            'total_engineers': Enginer.objects.count(),
            'total_permits': total_permits,
            'issued_permits': issued_permits,
            'pending_permits': pending_permits,
            'needs_completion_permits': needs_completion_permits,
            'active_extension_companies': active_extension_companies,
            'engineers_on_leave': engineers_on_leave,
            'status_breakdown': status_breakdown,
            'permit_type_breakdown': permit_type_breakdown,
            'expiring_soon': expiring_soon,
        },
    )


