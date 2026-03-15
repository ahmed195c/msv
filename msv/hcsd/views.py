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

from .models import (
    Company,
    CompanyChangeLog,
    EngineerCertificateRequest,
    EngineerLeave,
    Enginer,
    EnginerStatusLog,
    InspectorReview,
    PesticideTransportPermit,
    PirmetChangeLog,
    PirmetClearance,
    PirmetDocument,
    PublicHealthExamRequest,
    RequirementInsuranceRequest,
    WasteDisposalRequest,
    WasteDisposalRequestDocument,
)
from .forms import StaffRegistrationForm

ALLOWED_DOC_EXTENSIONS = {'.pdf', '.png', '.jpg', '.jpeg'}
PEST_ACTIVITY_ORDER = [
    'public_health_pest_control',
    'termite_control',
    'grain_pests',
]
PEST_ACTIVITY_KEYS = set(PEST_ACTIVITY_ORDER)
PUBLIC_HEALTH_ACTIVITY_KEYS = [
    'public_health_pest_control',
    'grain_pests',
]
GROUP_NAME_ALIASES = {
    'admin': ['admin', 'Administration'],
    'inspector': ['inspector', 'Inspector'],
    'data_entry': ['data_entry', 'Data Entry'],
    'head': ['head', 'Head'],
}
ROLE_CAPABILITIES = {
    # Admin keeps full operational capabilities.
    'admin': {'admin', 'inspect', 'data_entry', 'head_approve'},
    # Inspector handles inspection intake/reports only.
    'inspector': {'inspect'},
    # Data entry handles data-entry workflows.
    'data_entry': {'data_entry'},
    # Head of section performs final permit approval.
    'head': {'head_approve'},
}
INSPECTION_REPORT_PHOTO_PREFIX = 'inspection_report_photo_'
VEHICLE_INSPECTION_REPORT_PHOTO_PREFIX = 'vehicle_inspection_report_photo_'


def _parse_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_int_list(values):
    ids = []
    for value in values or []:
        parsed = _parse_int(value)
        if parsed:
            ids.append(parsed)
    return list(dict.fromkeys(ids))


def _validate_engineer_for_type(enginer, pest_control_type):
    if not enginer:
        return None
    if pest_control_type == 'termite_control' and not enginer.termite_cert:
        return f'المهندس "{enginer.name}" لا يملك شهادة النمل الأبيض.'
    if pest_control_type == 'public_health_pest_control' and not enginer.public_health_cert:
        return f'المهندس "{enginer.name}" لا يملك شهادة صحة عامة.'
    return None


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        for date_format in ('%d/%m/%Y', '%d-%m-%Y'):
            try:
                return datetime.datetime.strptime(value, date_format).date()
            except ValueError:
                continue
        return None


def _calculate_permit_expiry(trade_license_exp):
    if not trade_license_exp:
        return None
    try:
        return trade_license_exp.replace(year=trade_license_exp.year + 1)
    except ValueError:
        # Handle Feb 29 when adding one year.
        return trade_license_exp.replace(year=trade_license_exp.year + 1, day=28)


def _add_months(value, months):
    if not value:
        return None
    month = value.month - 1 + months
    year = value.year + month // 12
    month = month % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return datetime.date(year, month, day)


def _expired_trade_license_notice(trade_license_exp):
    if not trade_license_exp:
        return ''
    today = datetime.date.today()
    if trade_license_exp >= today:
        return ''
    delta_days = (today - trade_license_exp).days
    months = delta_days // 30
    if months >= 1:
        return f'تنبيه: الرخصة التجارية منتهية منذ {months} شهر.'
    return f'تنبيه: الرخصة التجارية منتهية منذ {delta_days} يوم.'


def _activities_for_enginer(enginer):
    # Temporary rollout rule:
    # if the engineer/certificates are not entered yet, do not block or empty out
    # the permit activities. Keep the request flowing and show a warning instead.
    if not enginer:
        return list(PEST_ACTIVITY_ORDER)
    activities = []
    if enginer.public_health_cert:
        for item in PUBLIC_HEALTH_ACTIVITY_KEYS:
            if item not in activities:
                activities.append(item)
    if enginer.termite_cert and 'termite_control' not in activities:
        activities.append('termite_control')
    if not activities:
        return list(PEST_ACTIVITY_ORDER)
    return activities


def _restricted_activities_for_enginer(enginer):
    allowed = set(_activities_for_enginer(enginer))
    if not allowed:
        return []
    return [item for item in PEST_ACTIVITY_ORDER if item not in allowed]


def _has_any_group(user, names):
    if not user.is_authenticated:
        return False
    return user.groups.filter(name__in=names).exists()


def _role_is_admin(user):
    return user.is_authenticated and (
        user.is_superuser
        or _has_any_group(user, GROUP_NAME_ALIASES['admin'])
    )


def _role_is_inspector(user):
    return user.is_authenticated and _has_any_group(user, GROUP_NAME_ALIASES['inspector'])


def _role_is_data_entry(user):
    return user.is_authenticated and _has_any_group(user, GROUP_NAME_ALIASES['data_entry'])


def _role_is_head(user):
    return user.is_authenticated and _has_any_group(user, GROUP_NAME_ALIASES['head'])


def _user_roles(user):
    if not getattr(user, 'is_authenticated', False):
        return set()
    cached_roles = getattr(user, '_hcsd_roles_cache', None)
    if cached_roles is not None:
        return cached_roles
    roles = set()
    if _role_is_admin(user):
        roles.add('admin')
    if _role_is_inspector(user):
        roles.add('inspector')
    if _role_is_data_entry(user):
        roles.add('data_entry')
    if _role_is_head(user):
        roles.add('head')
    setattr(user, '_hcsd_roles_cache', roles)
    return roles


def _has_capability(user, capability):
    for role in _user_roles(user):
        if capability in ROLE_CAPABILITIES.get(role, set()):
            return True
    return False


def _can_admin(user):
    return _has_capability(user, 'admin')


def _can_inspector(user):
    return _has_capability(user, 'inspect')


def _can_data_entry(user):
    return _has_capability(user, 'data_entry')


def _can_head(user):
    return _has_capability(user, 'head_approve')


def _company_has_active_extension(company):
    """Return True if the company has an open extension that hasn't been closed yet."""
    requested = company.change_logs.filter(action='extension_requested').count()
    closed = company.change_logs.filter(action='extension_closed').count()
    return requested > closed


def _can_create_exam_request(user):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    # Keep this stricter by design: staff alone does not grant this action.
    if _has_any_group(user, GROUP_NAME_ALIASES['admin']):
        return True
    if _has_any_group(user, GROUP_NAME_ALIASES['data_entry']):
        return True
    # Staff inspectors must not create exam requests unless they also have an allowed group.
    return False


def _inspector_users_qs():
    return (
        User.objects.filter(is_active=True, groups__name__in=GROUP_NAME_ALIASES['inspector'])
        .distinct()
        .order_by('first_name', 'last_name', 'username')
    )


def _display_user_name(user):
    if not user:
        return ''
    full_name = user.get_full_name().strip()
    return full_name or user.username


def _inspector_review_name(review):
    if not review:
        return None
    if getattr(review, 'inspector_user', None):
        return _display_user_name(review.inspector_user)
    if getattr(review, 'inspector', None):
        return review.inspector.name
    return None


def _inspection_report_decision_from_note(note):
    if not note or ':' not in note:
        return None
    decision = note.split(':', 1)[1].strip().lower()
    if decision in {'approved', 'rejected', 'requirements_required'}:
        return decision
    return None


def _inspection_report_photo_count_from_note(note, prefix='Inspection report photos uploaded:'):
    if not note or not note.startswith(prefix):
        return 0
    try:
        return int(note.split(':', 1)[1].strip())
    except (TypeError, ValueError):
        return 0


def _inspection_report_photo_docs_by_prefix(pirmet, prefix, log_prefix='Inspection report photos uploaded:'):
    # Prefer explicitly tagged photo filenames used by the current workflow.
    named_photos = list(
        PirmetDocument.objects.filter(
            pirmet=pirmet,
            file__icontains=prefix,
        ).order_by('uploadedAt')
    )
    if named_photos:
        return named_photos

    # Backward-compatible fallback for old records uploaded before tagging.
    latest_photo_log = (
        PirmetChangeLog.objects.filter(
            pirmet=pirmet,
            change_type='document_upload',
            notes__startswith=log_prefix,
        )
        .order_by('-created_at')
        .first()
    )
    if not latest_photo_log:
        return []

    expected_count = _inspection_report_photo_count_from_note(latest_photo_log.notes, prefix=log_prefix)
    if expected_count <= 0:
        return []

    candidates = (
        PirmetDocument.objects.filter(
            pirmet=pirmet,
            uploadedAt__lte=latest_photo_log.created_at + datetime.timedelta(seconds=30),
        )
        .order_by('-uploadedAt')
    )
    photos = []
    for doc in candidates:
        ext = os.path.splitext(doc.file.name)[1].lower()
        if ext not in {'.png', '.jpg', '.jpeg'}:
            continue
        photos.append(doc)
        if len(photos) >= expected_count:
            break
    photos.reverse()
    return photos


def _inspection_report_photo_docs(pirmet):
    return _inspection_report_photo_docs_by_prefix(
        pirmet,
        INSPECTION_REPORT_PHOTO_PREFIX,
        log_prefix='Inspection report photos uploaded:',
    )


def _vehicle_inspection_report_photo_docs(pirmet):
    return _inspection_report_photo_docs_by_prefix(
        pirmet,
        VEHICLE_INSPECTION_REPORT_PHOTO_PREFIX,
        log_prefix='Vehicle inspection report photos uploaded:',
    )


def _request_documents(pirmet):
    docs = PirmetDocument.objects.filter(pirmet=pirmet).order_by('uploadedAt')
    return [
        doc
        for doc in docs
        if INSPECTION_REPORT_PHOTO_PREFIX not in (doc.file.name or '')
        and VEHICLE_INSPECTION_REPORT_PHOTO_PREFIX not in (doc.file.name or '')
    ]


def _latest_expired_activity_permit_before(pirmet, reference_date):
    official_expired = (
        PirmetClearance.objects.filter(
            company=pirmet.company,
            permit_type='pest_control',
            status__in={'issued', 'payment_completed'},
            dateOfExpiry__isnull=False,
            dateOfExpiry__lt=reference_date,
        )
        .exclude(id=pirmet.id)
        .order_by('-dateOfExpiry', '-id')
        .first()
    )
    if official_expired:
        return official_expired

    # Fallback for legacy records where historical permits may not be marked as issued.
    return (
        PirmetClearance.objects.filter(
            company=pirmet.company,
            permit_type='pest_control',
            dateOfExpiry__isnull=False,
            dateOfExpiry__lt=reference_date,
        )
        .exclude(id=pirmet.id)
        .order_by('-dateOfExpiry', '-id')
        .first()
    )


def _delay_months_after_first_month(expiry_date, reference_date):
    if not expiry_date or not reference_date or reference_date <= expiry_date:
        return 0
    grace_end = _add_months(expiry_date, 1)
    if not grace_end or reference_date <= grace_end:
        return 0

    months = 0
    cursor = grace_end
    while cursor and cursor < reference_date:
        months += 1
        cursor = _add_months(cursor, 1)
    return months


def _initial_violation_reference_expiry(existing_company_trade_license_expiry, submitted_trade_license_expiry):
    # Freeze the reference at request creation time using the company's
    # previously stored trade license expiry (before any in-form edits).
    if existing_company_trade_license_expiry:
        return existing_company_trade_license_expiry
    if submitted_trade_license_expiry:
        return submitted_trade_license_expiry
    return None


def _violation_reference_expiry_date(pirmet, reference_date):
    if pirmet.violation_reference_expiry:
        return pirmet.violation_reference_expiry

    previous_permit = _latest_expired_activity_permit_before(pirmet, reference_date)
    if previous_permit and previous_permit.dateOfExpiry:
        return previous_permit.dateOfExpiry

    # Legacy fallback: if this request itself carries an old expiry date,
    # treat it as the overdue renewal baseline.
    if pirmet.dateOfExpiry and pirmet.dateOfExpiry < reference_date:
        return pirmet.dateOfExpiry

    return None


def _log_pirmet_change(pirmet, change_type, user, old_status=None, new_status=None, notes=''):
    PirmetChangeLog.objects.create(
        pirmet=pirmet,
        change_type=change_type,
        old_status=old_status,
        new_status=new_status,
        notes=notes,
        changed_by=user if user and user.is_authenticated else None,
    )


def _log_company_change(company, action, user, notes='', attachment=None, **extra_fields):
    CompanyChangeLog.objects.create(
        company=company,
        action=action,
        notes=notes,
        changed_by=user if user and user.is_authenticated else None,
        attachment=attachment,
        **extra_fields,
    )


def _split_activities(value):
    if not value:
        return []
    return [item.strip() for item in value.split(',') if item.strip()]


def _activity_keys_for_company(company, permit):
    keys = []
    if permit and permit.allowed_activities:
        keys = [item for item in _split_activities(permit.allowed_activities) if item in PEST_ACTIVITY_KEYS]
    elif company and company.pest_control_type:
        keys = [company.pest_control_type]
    if 'termite_control' in keys and 'public_health_pest_control' not in keys:
        keys = ['public_health_pest_control'] + keys
    return keys


def _permit_label_ar(permit_type):
    labels = {
        'pest_control': 'تصريح مزاولة نشاط مكافحة آفات الصحة العامة',
        'pesticide_transport': 'تصريح المركبة',
        'waste_disposal': 'تصريح التخلص من النفايات',
    }
    return labels.get(permit_type, permit_type)


def _permit_detail_url_name(permit_type):
    mapping = {
        'pest_control': 'pest_control_permit_detail',
        'pesticide_transport': 'vehicle_permit_detail',
        'waste_disposal': 'waste_permit_detail',
    }
    return mapping.get(permit_type, 'pest_control_permit_detail')


def _certificate_type_for_exam(exam_type):
    exam_type_value = (exam_type or '').strip()
    if 'نمل' in exam_type_value:
        return 'termite'
    return 'public_health'


def _certificate_expiry(issue_date):
    if not issue_date:
        return None, False
    expiry_date = _add_months(issue_date, 3)
    if not expiry_date:
        return None, False
    return expiry_date, expiry_date < timezone.localdate()


def _enginer_has_passed_for_certificate(enginer, certificate_type):
    if not enginer:
        return False
    cert_type = (certificate_type or '').strip()
    if cert_type == 'termite' and enginer.termite_cert:
        return True
    if cert_type == 'public_health' and enginer.public_health_cert:
        return True

    successful_exam_requests = PublicHealthExamRequest.objects.filter(
        enginer=enginer,
        status='completed',
        exam_result='ناجح',
    )
    for exam_request in successful_exam_requests:
        if _certificate_type_for_exam(exam_request.exam_type) == cert_type:
            return True
    return False


def _is_effective_active_permit(permit, today):
    """Returns True if the permit is currently active and valid."""
    if permit.status == 'cancelled_admin':
        return False
    if permit.dateOfExpiry and permit.dateOfExpiry < today:
        return False
    if permit.issue_date:
        return True
    return (
        permit.status in {'issued', 'payment_completed'}
        and bool(permit.dateOfExpiry)
        and permit.dateOfExpiry >= today
    )


def _engineer_no_certificate_notice(enginer_obj):
    if not enginer_obj:
        return ''
    if enginer_obj.public_health_cert or enginer_obj.termite_cert:
        return ''
    return 'تنبيه: المهندس المختار لا يملك حالياً شهادات لمن يهمه الأمر. تم السماح بتقديم الطلب مع ضرورة استكمال الشهادات لاحقاً.'


def _group_clearances_by_status(items, status_order, status_section_label_map):
    grouped = []
    by_status = {}
    for item in items:
        status_key = getattr(item, 'status_key', item.status)
        by_status.setdefault(status_key, []).append(item)

    for status_key in status_order:
        status_items = by_status.pop(status_key, [])
        if not status_items:
            continue
        grouped.append(
            {
                'status': status_key,
                'label': status_section_label_map.get(status_key, status_key),
                'items': status_items,
            }
        )

    for status_key, status_items in by_status.items():
        grouped.append(
            {
                'status': status_key,
                'label': status_section_label_map.get(status_key, status_key),
                'items': status_items,
            }
        )
    return grouped


@login_required
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
                'payment_completed',
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
        'payment_completed': 'تم استلام الدفع',
        'issued': 'تم إصدار التصريح',
        'head_approved': 'الاعتماد النهائي',
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


@login_required
def company_list(request):
    query = (request.GET.get('q') or '').strip()
    status_filter = (request.GET.get('status') or 'all').strip()
    today = datetime.date.today()

    companies_qs = Company.objects.all()
    if query:
        companies_qs = companies_qs.filter(Q(name__icontains=query) | Q(number__icontains=query))
    companies = list(companies_qs)
    company_ids = [c.id for c in companies]

    # Batch all per-company queries to avoid N+1.
    latest_issued_permit_map = {}
    for permit in PirmetClearance.objects.filter(
        company_id__in=company_ids,
        permit_type='pest_control',
        status__in=['issued', 'payment_completed'],
    ).order_by('company_id', '-dateOfCreation', '-id'):
        if permit.company_id not in latest_issued_permit_map:
            latest_issued_permit_map[permit.company_id] = permit

    latest_permit_any_map = {}
    for permit in PirmetClearance.objects.filter(
        company_id__in=company_ids,
        permit_type='pest_control',
    ).order_by('company_id', '-dateOfCreation', '-id'):
        if permit.company_id not in latest_permit_any_map:
            latest_permit_any_map[permit.company_id] = permit

    expired_company_ids = set(
        PirmetClearance.objects.filter(
            company_id__in=company_ids,
            permit_type__in=['pest_control', 'pesticide_transport'],
            status__in=['issued', 'payment_completed'],
            dateOfExpiry__isnull=False,
            dateOfExpiry__lt=today,
        ).values_list('company_id', flat=True).distinct()
    )

    latest_extension_map = {}
    for log in CompanyChangeLog.objects.filter(
        company_id__in=company_ids,
        action='extension_requested',
    ).order_by('company_id', '-created_at'):
        if log.company_id not in latest_extension_map:
            latest_extension_map[log.company_id] = log

    rows = []
    for company in companies:
        latest_issued_permit = latest_issued_permit_map.get(company.id)
        latest_permit_any = latest_permit_any_map.get(company.id)
        has_expired_permit = company.id in expired_company_ids
        activity_keys = _activity_keys_for_company(company, latest_issued_permit)

        latest_extension = latest_extension_map.get(company.id)
        has_active_extension = bool(
            latest_extension
            and latest_extension.extension_end_date
            and (not latest_extension.extension_start_date or latest_extension.extension_start_date <= today)
            and latest_extension.extension_end_date >= today
        )
        is_suspended = bool(latest_permit_any and latest_permit_any.status == 'cancelled_admin')

        activity_expiry = latest_issued_permit.dateOfExpiry if latest_issued_permit else None
        trade_expiry = company.trade_license_exp
        effective_expiry = activity_expiry or trade_expiry

        rows.append(
            {
                'company': company,
                'activity_keys': activity_keys,
                'activity_expiry': activity_expiry,
                'trade_expiry': trade_expiry,
                'effective_expiry': effective_expiry,
                'has_active_extension': has_active_extension,
                'is_suspended': is_suspended,
                'has_expired_permit': has_expired_permit,
            }
        )

    if status_filter == 'extension':
        rows = [row for row in rows if row['has_active_extension']]
    elif status_filter == 'suspended':
        rows = [row for row in rows if row['is_suspended']]
    elif status_filter == 'expired_permits':
        rows = [row for row in rows if row['has_expired_permit']]

    # Default ordering: latest trade license expiry first (newest to oldest).
    rows.sort(
        key=lambda row: (
            row['trade_expiry'] is None,
            -(row['trade_expiry'].toordinal() if row['trade_expiry'] else 0),
            row['company'].name or '',
        )
    )

    paginator = Paginator(rows, 30)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(
        request,
        'hcsd/company_list.html',
        {
            'company_rows': page_obj.object_list,
            'page_obj': page_obj,
            'total_companies': len(rows),
            'query': query,
            'status_filter': status_filter,
            'can_add_company': _can_data_entry(request.user),
        },
    )


@login_required
def extension_followup(request):
    if not _can_data_entry(request.user):
        return redirect('company_list')

    today = datetime.date.today()
    logs = (
        CompanyChangeLog.objects.filter(action='extension_requested')
        .select_related('company', 'changed_by')
        .order_by('extension_end_date', '-created_at')
    )

    rows = []
    for log in logs:
        end_date = log.extension_end_date
        start_date = log.extension_start_date
        days_left = None
        if end_date:
            days_left = (end_date - today).days
        rows.append(
            {
                'log': log,
                'company': log.company,
                'start_date': start_date,
                'end_date': end_date,
                'days_left': days_left,
                'days_overdue': abs(days_left) if days_left is not None and days_left < 0 else None,
            }
        )

    rows.sort(
        key=lambda row: (
            row['end_date'] is None,
            row['end_date'] or datetime.date.max,
            row['company'].name or '',
        )
    )

    return render(
        request,
        'hcsd/extension_followup.html',
        {
            'extension_rows': rows,
            'today': today,
        },
    )


@login_required
def add_company(request):
    engineers = Enginer.objects.all().order_by('name')
    form_data = {}
    error = ''

    if request.method == 'POST':
        name = (request.POST.get('name') or '').strip()
        number = (request.POST.get('number') or '').strip()
        trade_license_exp_value = (request.POST.get('trade_license_exp') or '').strip()
        address = (request.POST.get('address') or '').strip()
        landline = (request.POST.get('landline') or '').strip()
        owner_phone = (request.POST.get('owner_phone') or '').strip()
        email = (request.POST.get('email') or '').strip()
        business_activity_text = (request.POST.get('business_activity') or '').strip()
        pest_control_type = (request.POST.get('pest_control_type') or '').strip()
        enginer_id = _parse_int(request.POST.get('enginer'))
        enginer_ids = _parse_int_list(request.POST.getlist('enginers'))
        if enginer_id and enginer_id not in enginer_ids:
            enginer_ids.insert(0, enginer_id)

        form_data = {
            'name': name,
            'number': number,
            'trade_license_exp': trade_license_exp_value,
            'address': address,
            'landline': landline,
            'owner_phone': owner_phone,
            'email': email,
            'business_activity': business_activity_text,
            'enginer_id': str(enginer_id) if enginer_id else '',
            'enginer_ids': [str(i) for i in enginer_ids],
        }

        if not _can_data_entry(request.user):
            error = 'ليس لديك صلاحية لإضافة الشركات.'
        elif not name or not number or not address:
            error = 'يرجى إدخال اسم الشركة ورقم الرخصة والعنوان.'
        elif not pest_control_type:
            error = 'يرجى اختيار نوع المكافحة.'

        trade_license_exp = _parse_date(trade_license_exp_value)
        if trade_license_exp_value and not trade_license_exp:
            error = 'تاريخ انتهاء الرخصة التجارية غير صالح.'

        enginer = None
        if enginer_id:
            enginer = Enginer.objects.filter(id=enginer_id).first()
            if not enginer:
                error = 'يرجى اختيار مهندس صحيح.'

        selected_engineers = []
        if enginer_ids:
            selected_engineers = list(Enginer.objects.filter(id__in=enginer_ids))
            if len(selected_engineers) != len(enginer_ids):
                error = 'يرجى اختيار مهندسين صحيحين.'
        if not error and enginer:
            error = _validate_engineer_for_type(enginer, pest_control_type) or ''
        if not error:
            for engineer_item in selected_engineers:
                validation_error = _validate_engineer_for_type(engineer_item, pest_control_type)
                if validation_error:
                    error = validation_error
                    break

        if not error:
            company = Company.objects.create(
                name=name,
                number=number,
                trade_license_exp=trade_license_exp,
                address=address,
                landline=landline or None,
                owner_phone=owner_phone or None,
                email=email or None,
                business_activity=business_activity_text or None,
                pest_control_type=pest_control_type,
                enginer=enginer,
            )
            if selected_engineers:
                company.engineers.set(selected_engineers)
            create_notes = 'Company created.'
            if not enginer:
                create_notes = 'Company created without engineer (new company pending inspection/setup).'
            _log_company_change(company, 'created', request.user, notes=create_notes)
            return redirect('company_detail', id=company.id)

    return render(
        request,
        'hcsd/add_company.html',
        {
            'engineers': engineers,
            'form_data': form_data,
            'selected_pest_control_type': request.POST.get('pest_control_type') or '',
            'error': error,
        },
    )


@login_required
def company_detail(request, id):
    company = get_object_or_404(Company, id=id)
    engineers = Enginer.objects.all().order_by('name')
    can_edit_company = _can_admin(request.user)
    can_request_extension = _can_data_entry(request.user)
    can_manage_requirement_insurance = _can_admin(request.user)

    error = ''
    extension_error = ''
    extension_notice = ''
    form_data = {
        'name': company.name,
        'number': company.number,
        'trade_license_exp': company.trade_license_exp.isoformat() if company.trade_license_exp else '',
        'address': company.address,
        'landline': company.landline or '',
        'owner_phone': company.owner_phone or '',
        'email': company.email or '',
        'business_activity': company.business_activity or '',
        'enginer_id': str(company.enginer_id) if company.enginer_id else '',
        'enginer_ids': [str(i) for i in company.engineers.values_list('id', flat=True)],
    }
    selected_pest_control_type = company.pest_control_type or ''

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'close_extension':
            if not _can_admin(request.user):
                extension_error = 'إغلاق المهلة متاح للإدارة فقط.'
            elif not _company_has_active_extension(company):
                extension_error = 'لا توجد مهلة نشطة لإغلاقها.'
            else:
                close_notes = (request.POST.get('close_notes') or '').strip()
                _log_company_change(
                    company,
                    'extension_closed',
                    request.user,
                    notes=close_notes or 'تم إغلاق المهلة واستيفاء الشروط.',
                )
                return redirect('company_detail', id=company.id)
        elif action == 'request_extension':
            if not can_request_extension:
                extension_error = 'ليس لديك صلاحية لطلب المهلة.'
            else:
                extension_type = (request.POST.get('extension_type') or '').strip()
                extension_document = request.FILES.get('extension_document')
                extension_start_date = _parse_date(request.POST.get('extension_start_date'))
                extension_end_date = _parse_date(request.POST.get('extension_end_date'))
                extension_start_date_raw = (request.POST.get('extension_start_date') or '').strip()
                extension_end_date_raw = (request.POST.get('extension_end_date') or '').strip()
                if not extension_type:
                    extension_error = 'يرجى إدخال نوع المهلة.'
                elif not extension_start_date_raw or not extension_end_date_raw:
                    extension_error = 'يرجى إدخال تاريخ بداية ونهاية المهلة.'
                elif not extension_start_date or not extension_end_date:
                    extension_error = 'تواريخ المهلة غير صالحة.'
                elif extension_end_date < extension_start_date:
                    extension_error = 'تاريخ نهاية المهلة يجب أن يكون بعد أو يساوي تاريخ البداية.'
                elif not extension_document:
                    extension_error = 'يرجى إرفاق مستند المهلة.'
                else:
                    _log_company_change(
                        company,
                        'extension_requested',
                        request.user,
                        notes=extension_type,
                        attachment=extension_document,
                        extension_start_date=extension_start_date,
                        extension_end_date=extension_end_date,
                    )
                    return redirect('company_detail', id=company.id)
        else:
            if not can_edit_company:
                error = 'التعديل متاح للإدارة فقط.'
            else:
                name = (request.POST.get('name') or '').strip()
                number = (request.POST.get('number') or '').strip()
                trade_license_exp_value = (request.POST.get('trade_license_exp') or '').strip()
                address = (request.POST.get('address') or '').strip()
                landline = (request.POST.get('landline') or '').strip()
                owner_phone = (request.POST.get('owner_phone') or '').strip()
                email = (request.POST.get('email') or '').strip()
                business_activity_text = (request.POST.get('business_activity') or '').strip()
                pest_control_type = (request.POST.get('pest_control_type') or '').strip()
                enginer_id = _parse_int(request.POST.get('enginer'))
                enginer_ids = _parse_int_list(request.POST.getlist('enginers'))
                if enginer_id and enginer_id not in enginer_ids:
                    enginer_ids.insert(0, enginer_id)

                form_data.update(
                    {
                        'name': name,
                        'number': number,
                        'trade_license_exp': trade_license_exp_value,
                        'address': address,
                        'landline': landline,
                        'owner_phone': owner_phone,
                        'email': email,
                        'business_activity': business_activity_text,
                        'enginer_id': str(enginer_id) if enginer_id else '',
                        'enginer_ids': [str(i) for i in enginer_ids],
                    }
                )
                selected_pest_control_type = pest_control_type

                if not name or not number or not address:
                    error = 'يرجى إدخال الاسم ورقم الرخصة والعنوان.'
                elif not pest_control_type:
                    error = 'يرجى اختيار نوع المكافحة.'
                elif not enginer_id:
                    error = 'يرجى اختيار مهندس.'

                trade_license_exp = _parse_date(trade_license_exp_value)
                if trade_license_exp_value and not trade_license_exp:
                    error = 'تاريخ انتهاء الرخصة التجارية غير صالح.'

                enginer = None
                if enginer_id:
                    enginer = Enginer.objects.filter(id=enginer_id).first()
                    if not enginer:
                        error = 'يرجى اختيار مهندس صحيح.'

                selected_engineers = []
                if enginer_ids:
                    selected_engineers = list(Enginer.objects.filter(id__in=enginer_ids))
                    if len(selected_engineers) != len(enginer_ids):
                        error = 'يرجى اختيار مهندسين صحيحين.'

                if not error and enginer:
                    error = _validate_engineer_for_type(enginer, pest_control_type) or ''
                if not error:
                    for engineer_item in selected_engineers:
                        validation_error = _validate_engineer_for_type(engineer_item, pest_control_type)
                        if validation_error:
                            error = validation_error
                            break

                if not error:
                    changes = []
                    if company.enginer_id != enginer_id:
                        changes.append('engineer_changed')
                    company.name = name
                    company.number = number
                    company.trade_license_exp = trade_license_exp
                    company.address = address
                    company.landline = landline or None
                    company.owner_phone = owner_phone or None
                    company.email = email or None
                    company.business_activity = business_activity_text or None
                    company.pest_control_type = pest_control_type
                    company.enginer = enginer
                    company.save()
                    company.engineers.set(selected_engineers)

                    _log_company_change(company, 'updated', request.user, notes='Company updated.')
                    if 'engineer_changed' in changes:
                        _log_company_change(company, 'engineer_changed', request.user, notes='Engineer changed.')
                    return redirect('company_detail', id=company.id)

    permits_qs = (
        PirmetClearance.objects.filter(
            company=company,
            permit_type__in=['pest_control', 'pesticide_transport', 'waste_disposal'],
        )
        .order_by('-dateOfCreation', '-id')
    )
    permits = list(permits_qs)
    latest_permits = {}
    today = timezone.localdate()
    active_permits = {}
    latest_issued_permits = {}
    permit_status_labels = {
        'order_received': 'بانتظار اصدار رابط دفع التفتيش',
        'inspection_payment_pending': 'بانتظار دفع التفتيش',
        'review_pending': 'بانتظار مراجعة المفتش',
        'needs_completion': 'غير معتمد',
        'approved': 'تم الاعتماد من المفتش',
        'payment_pending': 'بانتظار دفع التصريح',
        'payment_completed': 'تم استلام الدفع',
        'issued': 'تم إصدار التصريح',
        'inspection_pending': 'جاهز للاستلام',
        'inspection_completed': 'تم إنهاء التفتيش',
        'head_approved': 'الاعتماد النهائي',
        'closed_requirements_pending': 'مغلق - اشتراطات واجبة الاستيفاء',
        'cancelled_admin': 'مغلق',
        'disposal_approved': 'إتلاف معتمد',
        'disposal_rejected': 'إتلاف مرفوض',
    }

    for permit in permits:
        permit.permit_label_ar = _permit_label_ar(permit.permit_type)
        permit.status_label_ar = permit_status_labels.get(permit.status, permit.get_status_display())
        permit.detail_url_name = _permit_detail_url_name(permit.permit_type)
        permit.is_issued_record = bool(permit.issue_date) or permit.status in {'issued', 'payment_completed'}
        permit.is_effective_active = _is_effective_active_permit(permit, today)

        if permit.status == 'cancelled_admin':
            permit.primary_action_label = None
            permit.primary_action_url = None
        elif permit.permit_type == 'pest_control' and permit.is_issued_record:
            permit.primary_action_label = 'عرض التصريح'
            permit.primary_action_url = reverse('pest_control_permit_view', kwargs={'id': permit.id})
        elif permit.is_issued_record:
            permit.primary_action_label = 'عرض التصريح'
            permit.primary_action_url = reverse(permit.detail_url_name, kwargs={'id': permit.id})
        else:
            permit.primary_action_label = 'متابعة الطلب'
            permit.primary_action_url = reverse(permit.detail_url_name, kwargs={'id': permit.id})

        if permit.permit_type not in latest_permits:
            latest_permits[permit.permit_type] = permit
        if permit.permit_type not in active_permits and permit.is_effective_active:
            active_permits[permit.permit_type] = permit
        if (
            permit.permit_type not in latest_issued_permits
            and permit.is_issued_record
            and permit.status != 'cancelled_admin'
        ):
            latest_issued_permits[permit.permit_type] = permit

    display_status_priority = {
        'issued': 0,
        'payment_completed': 0,
        'inspection_pending': 1,
        'order_received': 1,
        'inspection_payment_pending': 1,
        'review_pending': 1,
        'approved': 1,
        'payment_pending': 1,
        'inspection_completed': 1,
        'head_approved': 1,
        'disposal_approved': 1,
        'needs_completion': 2,
        'closed_requirements_pending': 2,
        'rejected': 2,
        'disposal_rejected': 2,
        'cancelled_admin': 3,
    }
    permits.sort(
        key=lambda permit: (
            display_status_priority.get(permit.status, 2),
            -(permit.dateOfCreation.toordinal() if permit.dateOfCreation else 0),
            -permit.id,
        )
    )

    issued_archive = [p for p in permits if p.is_issued_record]
    pending_permits_list = [
        p for p in permits
        if not p.is_issued_record and p.status not in {'cancelled_admin', 'inspection_completed', 'closed_requirements_pending'}
    ]
    extension_logs = list(
        company.change_logs.filter(action='extension_requested').order_by('-created_at')
    )
    for ext in extension_logs:
        ext.is_active = bool(ext.extension_end_date and ext.extension_end_date >= today)

    logs = company.change_logs.all().order_by('-created_at')
    requirement_insurance_requests = list(
        company.requirement_insurance_requests.select_related('related_permit', 'created_by')
    )
    company_blocked = _company_has_active_extension(company)
    # Engineer leave info for company's primary engineer
    engineer_active_leave = None
    if company.enginer_id:
        engineer_active_leave = EngineerLeave.objects.filter(
            engineer_id=company.enginer_id,
            actual_return_date__isnull=True,
        ).select_related('substitute').first()
    latest_extension = company.change_logs.filter(action='extension_requested').order_by('-created_at').first()
    if latest_extension and latest_extension.extension_end_date:
        days_left = (latest_extension.extension_end_date - datetime.date.today()).days
        if 0 <= days_left <= 7:
            extension_notice = f'تنبيه: تنتهي المهلة الحالية بتاريخ {latest_extension.extension_end_date:%d/%m/%Y} (بعد {days_left} يوم).'
        elif days_left < 0:
            extension_notice = f'تنبيه: انتهت المهلة الحالية بتاريخ {latest_extension.extension_end_date:%d/%m/%Y}.'

    return render(
        request,
        'hcsd/company_details.html',
        {
            'company': company,
            'engineers': engineers,
            'form_data': form_data,
            'selected_pest_control_type': selected_pest_control_type,
            'error': error,
            'extension_error': extension_error,
            'extension_notice': extension_notice,
            'can_edit_company': can_edit_company,
            'can_request_extension': can_request_extension,
            'can_manage_requirement_insurance': can_manage_requirement_insurance,
            'logs': logs,
            'requirement_insurance_requests': requirement_insurance_requests,
            'latest_pest_permit': latest_permits.get('pest_control'),
            'latest_vehicle_permit': latest_permits.get('pesticide_transport'),
            'latest_waste_permit': latest_permits.get('waste_disposal'),
            'active_pest_permit': active_permits.get('pest_control'),
            'active_vehicle_permit': active_permits.get('pesticide_transport'),
            'active_waste_permit': active_permits.get('waste_disposal'),
            'display_pest_permit': active_permits.get('pest_control') or latest_issued_permits.get('pest_control'),
            'display_vehicle_permit': active_permits.get('pesticide_transport') or latest_issued_permits.get('pesticide_transport'),
            'display_waste_permit': active_permits.get('waste_disposal') or latest_issued_permits.get('waste_disposal'),
            'company_permits': permits,
            'issued_archive': issued_archive,
            'pending_permits_list': pending_permits_list,
            'extension_logs': extension_logs,
            'company_blocked': company_blocked,
            'engineer_active_leave': engineer_active_leave,
        },
    )


@login_required
def requirement_insurance_request_detail(request, request_id):
    insurance_request = get_object_or_404(
        RequirementInsuranceRequest.objects.select_related(
            'company',
            'related_permit',
            'created_by',
        ),
        id=request_id,
    )
    can_manage = _can_admin(request.user)
    errors = []

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'save_payment_order':
            if not can_manage:
                errors.append('ليس لديك صلاحية لإدخال أمر دفع التأمين.')
            if insurance_request.status in {'refunded', 'cancelled'}:
                errors.append('لا يمكن تعديل هذا الطلب في حالته الحالية.')
            payment_order_number = (request.POST.get('payment_order_number') or '').strip()
            if not payment_order_number:
                errors.append('يرجى إدخال رقم أمر دفع التأمين.')
            if not errors:
                insurance_request.payment_order_number = payment_order_number
                insurance_request.status = 'payment_order_recorded'
                insurance_request.save(update_fields=['payment_order_number', 'status', 'updated_at'])
                _log_company_change(
                    insurance_request.company,
                    'updated',
                    request.user,
                    notes=f'تم إدخال أمر دفع تأمين استيفاء الشروط للطلب #{insurance_request.id}.',
                )
                return redirect('requirement_insurance_request_detail', request_id=insurance_request.id)

        if action == 'save_payment_receipt':
            if not can_manage:
                errors.append('ليس لديك صلاحية لتأكيد دفع التأمين.')
            if insurance_request.status in {'refunded', 'cancelled'}:
                errors.append('لا يمكن تعديل هذا الطلب في حالته الحالية.')
            if not (insurance_request.payment_order_number or '').strip():
                errors.append('يرجى إدخال أمر دفع التأمين أولاً.')
            receipt = request.FILES.get('payment_receipt')
            if not receipt:
                errors.append('يرجى إرفاق إيصال دفع التأمين.')
            else:
                ext = os.path.splitext(receipt.name)[1].lower()
                if ext not in ALLOWED_DOC_EXTENSIONS:
                    errors.append('يُسمح فقط بملفات PDF أو صور لإيصال التأمين.')
            if not errors:
                start_date = timezone.localdate()
                end_date = _add_months(start_date, insurance_request.duration_months)
                insurance_request.payment_receipt = receipt
                insurance_request.payment_received_at = timezone.now()
                insurance_request.start_date = start_date
                insurance_request.end_date = end_date
                insurance_request.status = 'active'
                insurance_request.save(
                    update_fields=[
                        'payment_receipt',
                        'payment_received_at',
                        'start_date',
                        'end_date',
                        'status',
                        'updated_at',
                    ]
                )
                _log_company_change(
                    insurance_request.company,
                    'requirements_insurance_paid',
                    request.user,
                    notes=(
                        f'تم دفع تأمين استيفاء الشروط للطلب #{insurance_request.id} '
                        f'وصار فعالاً حتى {end_date:%d/%m/%Y}.'
                    ),
                )
                return redirect('requirement_insurance_request_detail', request_id=insurance_request.id)

        if action == 'save_refund':
            if not can_manage:
                errors.append('ليس لديك صلاحية لتسجيل استرداد التأمين.')
            if insurance_request.status != 'active':
                errors.append('يمكن تسجيل الاسترداد فقط بعد تفعيل التأمين.')
            refund_reference_number = (request.POST.get('refund_reference_number') or '').strip()
            refund_receipt = request.FILES.get('refund_receipt')
            if not refund_receipt:
                errors.append('يرجى إرفاق مستند أو إيصال استرداد التأمين.')
            else:
                ext = os.path.splitext(refund_receipt.name)[1].lower()
                if ext not in ALLOWED_DOC_EXTENSIONS:
                    errors.append('يُسمح فقط بملفات PDF أو صور لمستند الاسترداد.')
            if not errors:
                insurance_request.refund_reference_number = refund_reference_number or None
                insurance_request.refund_receipt = refund_receipt
                insurance_request.refunded_at = timezone.now()
                insurance_request.status = 'refunded'
                insurance_request.save(
                    update_fields=[
                        'refund_reference_number',
                        'refund_receipt',
                        'refunded_at',
                        'status',
                        'updated_at',
                    ]
                )
                _log_company_change(
                    insurance_request.company,
                    'requirements_insurance_refunded',
                    request.user,
                    notes=f'تم استرداد تأمين استيفاء الشروط للطلب #{insurance_request.id}.',
                )
                return redirect('requirement_insurance_request_detail', request_id=insurance_request.id)

    return render(
        request,
        'hcsd/requirement_insurance_request_detail.html',
        {
            'insurance_request': insurance_request,
            'errors': errors,
            'can_manage': can_manage,
        },
    )


@login_required
def requirement_insurance_create(request):
    if not _can_data_entry(request.user):
        return redirect('company_list')

    companies = Company.objects.all().order_by('name')
    selected_company_id = _parse_int(request.GET.get('company_id'))
    back_company_id = selected_company_id
    form_data = {}
    form_errors = []

    if request.method == 'POST':
        company_id = _parse_int(request.POST.get('company_id'))
        duration_months = _parse_int(request.POST.get('duration_months'))
        requirements_notes = (request.POST.get('requirements_notes') or '').strip()

        company = None
        if not company_id:
            form_errors.append('يرجى اختيار شركة.')
        else:
            company = Company.objects.filter(id=company_id).first()
            if not company:
                form_errors.append('الشركة المختارة غير موجودة.')

        if duration_months not in {1, 3, 6}:
            form_errors.append('يرجى اختيار مدة صحيحة للتأمين.')

        back_company_id = company_id
        form_data = {
            'company_id': str(company_id or ''),
            'duration_months': str(duration_months or '1'),
            'requirements_notes': requirements_notes,
        }

        if not form_errors and company:
            related_permit = (
                PirmetClearance.objects.filter(
                    company=company,
                    permit_type='pest_control',
                    status='closed_requirements_pending',
                )
                .order_by('-dateOfCreation', '-id')
                .first()
            )
            insurance_request = RequirementInsuranceRequest.objects.create(
                company=company,
                related_permit=related_permit,
                duration_months=duration_months,
                requirements_notes=requirements_notes,
                created_by=request.user,
            )
            _log_company_change(
                company,
                'requirements_insurance_created',
                request.user,
                notes=(
                    f'تم إنشاء طلب تأمين لاستيفاء الشروط لمدة '
                    f'{insurance_request.get_duration_months_display()}.'
                ),
            )
            return redirect('requirement_insurance_request_detail', request_id=insurance_request.id)

    return render(
        request,
        'hcsd/requirement_insurance_create.html',
        {
            'companies': companies,
            'selected_company_id': selected_company_id,
            'back_company_id': back_company_id,
            'form_data': form_data,
            'form_errors': form_errors,
        },
    )


@login_required
def enginer_list(request):
    search_query = (request.GET.get('q') or '').strip()
    certification_filter = (request.GET.get('certification') or '').strip()

    engineers = Enginer.objects.all()

    if search_query:
        engineers = engineers.filter(
            Q(name__icontains=search_query) |
            Q(national_or_unified_number__icontains=search_query) |
            Q(card_number__icontains=search_query)
        )

    if certification_filter == 'public_health':
        engineers = engineers.exclude(public_health_cert='')
    elif certification_filter == 'termite':
        engineers = engineers.exclude(termite_cert='')

    engineers = list(engineers.order_by('name'))
    # Fetch all active leave records in one query for efficiency
    active_leave_map = {
        leave.engineer_id: leave
        for leave in EngineerLeave.objects.filter(
            actual_return_date__isnull=True,
            engineer_id__in=[e.id for e in engineers],
        ).select_related('substitute')
    }
    for engineer in engineers:
        ph_expiry_date, ph_is_expired = _certificate_expiry(engineer.public_health_cert_issue_date)
        termite_expiry_date, termite_is_expired = _certificate_expiry(engineer.termite_cert_issue_date)
        engineer.public_health_cert_expiry_date = ph_expiry_date
        engineer.public_health_cert_is_expired = ph_is_expired
        engineer.termite_cert_expiry_date = termite_expiry_date
        engineer.termite_cert_is_expired = termite_is_expired
        engineer.active_leave = active_leave_map.get(engineer.id)
    return render(
        request,
        'hcsd/enginer_list.html',
        {
            'engineers': engineers,
            'can_add_enginer': _can_data_entry(request.user),
            'can_create_exam_request': _can_create_exam_request(request.user),
            'can_view_exam_requests': _can_inspector(request.user) or _can_create_exam_request(request.user),
            'search_query': search_query,
            'certification_filter': certification_filter,
            'on_leave_count': len(active_leave_map),
        },
    )


@login_required
def enginer_add(request):
    error = ''
    form_data = {}

    if request.method == 'POST':
        if not _can_data_entry(request.user):
            error = 'ليس لديك صلاحية لإضافة مهندسين.'
        else:
            name = (request.POST.get('name') or '').strip()
            national_or_unified_number = (request.POST.get('national_or_unified_number') or '').strip()
            email = (request.POST.get('email') or '').strip()
            phone = (request.POST.get('phone') or '').strip()
            public_health_cert = request.FILES.get('public_health_cert')
            termite_cert = request.FILES.get('termite_cert')

            form_data = {
                'name': name,
                'national_or_unified_number': national_or_unified_number,
                'email': email,
                'phone': phone,
            }
            if not name or not national_or_unified_number or not email or not phone:
                error = 'يرجى إدخال بيانات المهندس كاملة.'

            if not error:
                enginer = Enginer.objects.create(
                    name=name,
                    national_or_unified_number=national_or_unified_number,
                    email=email,
                    phone=phone,
                    public_health_cert=public_health_cert,
                    termite_cert=termite_cert,
                )
                EnginerStatusLog.objects.create(
                    enginer=enginer,
                    action='created',
                    notes='Engineer created.',
                    changed_by=request.user,
                )
                if public_health_cert:
                    EnginerStatusLog.objects.create(
                        enginer=enginer,
                        action='public_health_cert_uploaded',
                        notes='Public health certificate uploaded.',
                        changed_by=request.user,
                    )
                if termite_cert:
                    EnginerStatusLog.objects.create(
                        enginer=enginer,
                        action='termite_cert_uploaded',
                        notes='Termite certificate uploaded.',
                        changed_by=request.user,
                    )
                return redirect('enginer_list')

    return render(
        request,
        'hcsd/enginer_add.html',
        {
            'error': error,
            'form_data': form_data,
            'can_add_enginer': _can_data_entry(request.user),
        },
    )


@login_required
def enginer_detail(request, id):
    enginer = get_object_or_404(Enginer, id=id)
    error = ''
    leave_error = ''
    all_engineers = Enginer.objects.exclude(id=enginer.id).order_by('name')
    active_leave = enginer.leaves.filter(actual_return_date__isnull=True).order_by('-created_at').first()

    if request.method == 'POST':
        action = request.POST.get('action', '')

        if action == 'record_leave':
            if not _can_admin(request.user):
                leave_error = 'تسجيل الإجازة متاح للإدارة فقط.'
            elif active_leave:
                leave_error = 'يوجد إجازة نشطة مسجلة بالفعل — أغلقها أولاً قبل تسجيل إجازة جديدة.'
            else:
                start_date = _parse_date(request.POST.get('start_date'))
                expected_return_date = _parse_date(request.POST.get('expected_return_date'))
                substitute_id = _parse_int(request.POST.get('substitute_id'))
                notes = (request.POST.get('notes') or '').strip()
                substitute = Enginer.objects.filter(id=substitute_id).first() if substitute_id else None
                if not start_date:
                    leave_error = 'يرجى إدخال تاريخ بداية الإجازة.'
                else:
                    EngineerLeave.objects.create(
                        engineer=enginer,
                        substitute=substitute,
                        start_date=start_date,
                        expected_return_date=expected_return_date,
                        notes=notes,
                        created_by=request.user,
                    )
                    return redirect('enginer_detail', id=enginer.id)

        elif action == 'close_leave':
            if not _can_admin(request.user):
                leave_error = 'إغلاق الإجازة متاح للإدارة فقط.'
            elif not active_leave:
                leave_error = 'لا توجد إجازة نشطة لإغلاقها.'
            else:
                actual_return = _parse_date(request.POST.get('actual_return_date')) or datetime.date.today()
                active_leave.actual_return_date = actual_return
                active_leave.closed_by = request.user
                active_leave.save(update_fields=['actual_return_date', 'closed_by'])
                return redirect('enginer_detail', id=enginer.id)

        elif not _can_data_entry(request.user):
            error = 'التحديث متاح لموظفي الإدخال أو الإدارة فقط.'
        else:
            updated = False
            public_health_cert = request.FILES.get('public_health_cert')
            termite_cert = request.FILES.get('termite_cert')
            if public_health_cert:
                previous_public_health_cert = enginer.public_health_cert.name if enginer.public_health_cert else None
                enginer.public_health_cert = public_health_cert
                EnginerStatusLog.objects.create(
                    enginer=enginer,
                    action='public_health_cert_uploaded',
                    notes='Public health certificate updated.',
                    changed_by=request.user,
                    archived_file=previous_public_health_cert or None,
                )
                updated = True
            if termite_cert:
                previous_termite_cert = enginer.termite_cert.name if enginer.termite_cert else None
                enginer.termite_cert = termite_cert
                EnginerStatusLog.objects.create(
                    enginer=enginer,
                    action='termite_cert_uploaded',
                    notes='Termite certificate updated.',
                    changed_by=request.user,
                    archived_file=previous_termite_cert or None,
                )
                updated = True
            if updated:
                enginer.save()
                return redirect('enginer_detail', id=enginer.id)
            error = 'يرجى إرفاق ملف واحد على الأقل.'

    # Re-fetch active leave after possible POST changes
    active_leave = enginer.leaves.filter(actual_return_date__isnull=True).order_by('-created_at').first()
    leave_history = enginer.leaves.select_related('substitute', 'created_by', 'closed_by').order_by('-created_at')
    logs = enginer.status_logs.select_related('changed_by').all().order_by('-created_at')
    archived_logs = [log for log in logs if getattr(log, 'archived_file', None)]
    public_health_expiry_date, public_health_is_expired = _certificate_expiry(enginer.public_health_cert_issue_date)
    termite_expiry_date, termite_is_expired = _certificate_expiry(enginer.termite_cert_issue_date)
    return render(
        request,
        'hcsd/enginer_detail.html',
        {
            'enginer': enginer,
            'can_update_enginer': _can_data_entry(request.user),
            'can_manage_leave': _can_admin(request.user),
            'can_create_exam_request': _can_create_exam_request(request.user),
            'error': error,
            'leave_error': leave_error,
            'active_leave': active_leave,
            'leave_history': leave_history,
            'all_engineers': all_engineers,
            'logs': logs,
            'archived_logs': archived_logs,
            'public_health_expiry_date': public_health_expiry_date,
            'public_health_is_expired': public_health_is_expired,
            'termite_expiry_date': termite_expiry_date,
            'termite_is_expired': termite_is_expired,
        },
    )


@login_required
def public_health_exam_request_list(request):
    prefilled_enginer_id = _parse_int(request.GET.get('enginer_id'))
    card_number_query = (request.GET.get('card_number') or '').strip()
    status_filter = (request.GET.get('status') or '').strip()
    form_error = ''
    can_create_exam_request = _can_create_exam_request(request.user)

    if request.method == 'POST':
        if not can_create_exam_request:
            form_error = 'ليس لديك صلاحية لإنشاء طلب جديد.'
        else:
            enginer_id = _parse_int(request.POST.get('enginer_id'))
            company_id = _parse_int(request.POST.get('company_id'))
            request_notes = (request.POST.get('request_notes') or '').strip()
            request_document = request.FILES.get('request_document')
            unified_identity_number = (request.POST.get('unified_identity_number') or '').strip()
            exam_language = (request.POST.get('exam_language') or '').strip()
            exam_type = (request.POST.get('exam_type') or '').strip()
            qualified_technician_name = (request.POST.get('qualified_technician_name') or '').strip()
            phone_number = (request.POST.get('phone_number') or '').strip()
            request_submission_date = _parse_date((request.POST.get('request_submission_date') or '').strip())
            enginer = Enginer.objects.filter(id=enginer_id).first()
            company = None
            if not enginer:
                form_error = 'يرجى اختيار مهندس صحيح.'
            if not form_error and company_id:
                company = Company.objects.filter(id=company_id).first()
                if not company:
                    form_error = 'الشركة المختارة غير صحيحة.'
            if not form_error and not request_document:
                form_error = 'يرجى إرفاق مستندات الطلب.'
            if not form_error:
                if not company:
                    company = (
                        Company.objects.filter(Q(engineers=enginer) | Q(enginer=enginer))
                        .distinct()
                        .order_by('name')
                        .first()
                    )
                attempt_number = PublicHealthExamRequest.next_attempt_number(enginer, exam_type=exam_type)
                exam_fee = PublicHealthExamRequest.fee_for_attempt(attempt_number)
                PublicHealthExamRequest.objects.create(
                    enginer=enginer,
                    company=company,
                    serial_number='',
                    attempt_number=attempt_number,
                    exam_fee=exam_fee,
                    request_submission_date=request_submission_date,
                    unified_number='',
                    identity_number=unified_identity_number,
                    exam_language=exam_language,
                    exam_type=exam_type,
                    qualified_technician_name=qualified_technician_name,
                    phone_number=phone_number or enginer.phone,
                    request_notes=request_notes,
                    request_document=request_document,
                    created_by=request.user,
                    status='submitted',
                )
                return redirect('public_health_exam_request_list')

    requests_qs = PublicHealthExamRequest.objects.select_related('enginer', 'reviewed_by')
    if card_number_query:
        requests_qs = requests_qs.filter(enginer__card_number__icontains=card_number_query)
    if status_filter:
        requests_qs = requests_qs.filter(status=status_filter)

    engineers = Enginer.objects.order_by('name')
    _EXAM_TYPES = ['اختبار عام', 'نمل أبيض']
    per_type_counts = {}
    for row in PublicHealthExamRequest.objects.values('enginer_id', 'exam_type').annotate(total=Count('id')):
        eng_id = row['enginer_id']
        et = row['exam_type'] or ''
        per_type_counts.setdefault(eng_id, {})[et] = row['total']
    engineer_attempt_map = {}
    engineer_fee_map = {}
    engineer_data_map = {}
    for eng in engineers:
        counts_for_eng = per_type_counts.get(eng.id, {})
        engineer_attempt_map[eng.id] = {}
        engineer_fee_map[eng.id] = {}
        for et in _EXAM_TYPES:
            next_att = counts_for_eng.get(et, 0) + 1
            engineer_attempt_map[eng.id][et] = next_att
            engineer_fee_map[eng.id][et] = PublicHealthExamRequest.fee_for_attempt(next_att)
        engineer_data_map[eng.id] = {
            'national_number': eng.national_or_unified_number or '',
            'phone': eng.phone or '',
        }

    companies = Company.objects.all().prefetch_related('engineers').order_by('name')
    engineer_company_map = {}
    for company in companies:
        if company.enginer_id and company.enginer_id not in engineer_company_map:
            engineer_company_map[company.enginer_id] = company.id
        for engineer_id in company.engineers.values_list('id', flat=True):
            if engineer_id not in engineer_company_map:
                engineer_company_map[engineer_id] = company.id

    return render(
        request,
        'hcsd/public_health_exam_request_list.html',
        {
            'requests': requests_qs,
            'engineers': engineers,
            'companies': companies,
            'form_error': form_error,
            'card_number_query': card_number_query,
            'status_filter': status_filter,
            'can_create': can_create_exam_request,
            'can_inspector_review': _can_inspector(request.user),
            'prefilled_enginer_id': prefilled_enginer_id,
            'engineer_company_map': engineer_company_map,
            'engineer_attempt_map': engineer_attempt_map,
            'engineer_fee_map': engineer_fee_map,
            'engineer_data_map': engineer_data_map,
        },
    )


@login_required
def public_health_exam_request_detail(request, request_id):
    exam_request = get_object_or_404(
        PublicHealthExamRequest.objects.select_related('enginer', 'reviewed_by'),
        id=request_id,
    )
    error = ''
    can_inspector_review = _can_inspector(request.user)
    can_manage_payment = _can_create_exam_request(request.user)
    exam_date_passed = False
    if exam_request.exam_datetime:
        exam_date_passed = timezone.localdate() >= exam_request.exam_datetime.date()
    suggested_certificate_type = _certificate_type_for_exam(exam_request.exam_type)

    if request.method == 'POST':
        action = (request.POST.get('action') or '').strip()

        if action == 'inspector_review':
            if not can_inspector_review:
                error = 'ليس لديك صلاحية لمراجعة الطلب.'
            elif exam_request.status not in {'submitted'}:
                error = 'لا يمكن مراجعة الطلب في حالته الحالية.'
            else:
                decision = (request.POST.get('decision') or '').strip()
                notes = (request.POST.get('review_notes') or '').strip()
                if decision not in {'approve', 'reject'}:
                    error = 'يرجى اختيار قرار المراجعة.'
                elif decision == 'reject' and not notes:
                    error = 'يرجى كتابة سبب الرفض.'
                else:
                    exam_request.reviewed_by = request.user
                    exam_request.review_notes = notes
                    exam_request.recommendation = (request.POST.get('recommendation') or '').strip()
                    exam_request.status = 'inspector_approved' if decision == 'approve' else 'rejected'
                    exam_request.save()
                    return redirect('public_health_exam_request_detail', request_id=exam_request.id)

        elif action == 'set_payment_order_number':
            if not can_manage_payment:
                error = 'ليس لديك صلاحية لإدخال بيانات الدفع.'
            elif exam_request.status not in {'inspector_approved', 'payment_pending'}:
                error = 'لا يمكن إدخال رقم أمر الدفع في حالة الطلب الحالية.'
            else:
                payment_reference = (request.POST.get('payment_reference') or '').strip()
                if not payment_reference:
                    error = 'يرجى إدخال رقم أمر الدفع.'
                else:
                    exam_request.payment_reference = payment_reference
                    exam_request.status = 'payment_pending'
                    exam_request.save(update_fields=['payment_reference', 'status', 'updated_at'])
                    return redirect('public_health_exam_request_detail', request_id=exam_request.id)

        elif action == 'record_payment':
            if not can_manage_payment:
                error = 'ليس لديك صلاحية لتسجيل الدفع.'
            elif exam_request.status != 'payment_pending':
                error = 'لا يمكن تسجيل الدفع في حالة الطلب الحالية.'
            elif not exam_request.payment_reference:
                error = 'يرجى إدخال رقم أمر الدفع أولاً.'
            else:
                receipt = request.FILES.get('payment_receipt')
                if not receipt:
                    error = 'يرجى إرفاق إيصال الدفع.'
                else:
                    exam_request.payment_receipt = receipt
                    exam_request.payment_receipt_number = None
                    exam_request.payment_receipt_date = None
                    exam_request.payment_received_at = timezone.now()
                    exam_request.save()
                    return redirect('public_health_exam_request_detail', request_id=exam_request.id)

        elif action == 'schedule_exam':
            if not can_manage_payment:
                error = 'ليس لديك صلاحية لحجز موعد الاختبار.'
            elif exam_request.status != 'payment_pending':
                error = 'لا يمكن حجز موعد قبل تسجيل الدفع.'
            elif not exam_request.payment_receipt:
                error = 'يرجى تسجيل إيصال الدفع أولاً.'
            else:
                exam_date_raw = (request.POST.get('exam_date') or '').strip()
                if not exam_date_raw:
                    error = 'يرجى إدخال تاريخ موعد الاختبار.'
                else:
                    exam_date = _parse_date(exam_date_raw)
                    if not exam_date:
                        error = 'صيغة تاريخ الموعد غير صحيحة.'
                    else:
                        exam_request.exam_datetime = datetime.datetime.combine(exam_date, datetime.time.min)
                        exam_request.exam_location = None
                        exam_request.status = 'scheduled'
                        exam_request.save()
                        return redirect('public_health_exam_request_detail', request_id=exam_request.id)

        elif action == 'record_exam_result':
            if not can_inspector_review:
                error = 'ليس لديك صلاحية لتسجيل نتيجة الاختبار.'
            elif exam_request.status != 'scheduled':
                error = 'لا يمكن تسجيل النتيجة قبل حجز الموعد.'
            elif not exam_date_passed:
                error = 'لا يمكن تسجيل النتيجة قبل تاريخ موعد الاختبار.'
            else:
                exam_result = (request.POST.get('exam_result') or '').strip()
                if exam_result not in {'ناجح', 'غير ناجح'}:
                    error = 'يرجى اختيار نتيجة صحيحة.'
                else:
                    exam_request.exam_result = exam_result
                    exam_request.status = 'completed'
                    exam_request.save(update_fields=['exam_result', 'status', 'updated_at'])
                    return redirect('public_health_exam_request_detail', request_id=exam_request.id)

    return render(
        request,
        'hcsd/public_health_exam_request_detail.html',
        {
            'exam_request': exam_request,
            'error': error,
            'can_inspector_review': can_inspector_review,
            'can_manage_payment': can_manage_payment,
            'can_record_result': can_inspector_review and exam_request.status == 'scheduled' and exam_date_passed,
            'can_create_certificate_request': (
                can_manage_payment
                and exam_request.status == 'completed'
                and exam_request.exam_result == 'ناجح'
            ),
            'suggested_certificate_type': suggested_certificate_type,
        },
    )


@login_required
def engineer_certificate_request_list(request):
    prefilled_enginer_id = _parse_int(request.GET.get('enginer_id'))
    prefilled_certificate_type = (request.GET.get('certificate_type') or '').strip()
    prefilled_source_exam_request_id = _parse_int(request.GET.get('source_exam_request_id'))
    card_number_query = (request.GET.get('card_number') or '').strip()
    status_filter = (request.GET.get('status') or '').strip()
    certificate_type_filter = (request.GET.get('certificate_type_filter') or '').strip()
    form_error = ''
    can_manage_certificate_requests = _can_create_exam_request(request.user)

    if request.method == 'POST':
        if not can_manage_certificate_requests:
            form_error = 'ليس لديك صلاحية لتقديم طلب شهادة جديد.'
        else:
            enginer_id = _parse_int(request.POST.get('enginer_id'))
            certificate_type = (request.POST.get('certificate_type') or '').strip()
            source_exam_request_id = _parse_int(request.POST.get('source_exam_request_id'))

            enginer = Enginer.objects.filter(id=enginer_id).first()
            if not enginer:
                form_error = 'يرجى اختيار مهندس صحيح.'
            elif certificate_type not in {'public_health', 'termite'}:
                form_error = 'يرجى اختيار نوع الشهادة.'
            else:
                active_request_exists = EngineerCertificateRequest.objects.filter(
                    enginer=enginer,
                    certificate_type=certificate_type,
                    status__in={'submitted', 'payment_pending', 'payment_received'},
                ).exists()
                if active_request_exists:
                    form_error = 'يوجد طلب شهادة مفتوح لنفس المهندس ونفس النوع.'

            if not form_error:
                exam_request = None
                if source_exam_request_id:
                    exam_request = PublicHealthExamRequest.objects.filter(
                        id=source_exam_request_id,
                        enginer=enginer,
                        status='completed',
                        exam_result='ناجح',
                    ).first()
                    if exam_request and _certificate_type_for_exam(exam_request.exam_type) != certificate_type:
                        exam_request = None

                EngineerCertificateRequest.objects.create(
                    enginer=enginer,
                    exam_request=exam_request,
                    certificate_type=certificate_type,
                    status='submitted',
                    created_by=request.user,
                )
                return redirect('engineer_certificate_request_list')

    certificate_requests = EngineerCertificateRequest.objects.select_related(
        'enginer',
        'issued_by',
        'exam_request',
    )
    if card_number_query:
        certificate_requests = certificate_requests.filter(enginer__card_number__icontains=card_number_query)
    if status_filter:
        certificate_requests = certificate_requests.filter(status=status_filter)
    if certificate_type_filter:
        certificate_requests = certificate_requests.filter(certificate_type=certificate_type_filter)

    engineers = Enginer.objects.order_by('name')
    return render(
        request,
        'hcsd/engineer_certificate_request_list.html',
        {
            'requests': certificate_requests,
            'engineers': engineers,
            'form_error': form_error,
            'card_number_query': card_number_query,
            'status_filter': status_filter,
            'certificate_type_filter': certificate_type_filter,
            'prefilled_enginer_id': prefilled_enginer_id,
            'prefilled_certificate_type': prefilled_certificate_type,
            'prefilled_source_exam_request_id': prefilled_source_exam_request_id,
            'can_manage_certificate_requests': can_manage_certificate_requests,
        },
    )


@login_required
def engineer_certificate_request_detail(request, request_id):
    certificate_request = get_object_or_404(
        EngineerCertificateRequest.objects.select_related('enginer', 'issued_by', 'exam_request'),
        id=request_id,
    )
    can_manage_certificate_requests = _can_create_exam_request(request.user)
    error = ''

    if request.method == 'POST':
        action = (request.POST.get('action') or '').strip()

        if action == 'set_payment_order_number':
            if not can_manage_certificate_requests:
                error = 'ليس لديك صلاحية لإدخال بيانات دفع الشهادة.'
            elif certificate_request.status not in {'submitted', 'payment_pending'}:
                error = 'لا يمكن تعديل بيانات الدفع في الحالة الحالية.'
            else:
                payment_order_number = (request.POST.get('payment_order_number') or '').strip()
                if not payment_order_number:
                    error = 'يرجى إدخال رقم أمر الدفع.'
                else:
                    certificate_request.payment_order_number = payment_order_number
                    certificate_request.status = 'payment_pending'
                    certificate_request.save(update_fields=['payment_order_number', 'status', 'updated_at'])
                    return redirect('engineer_certificate_request_detail', request_id=certificate_request.id)

        elif action == 'record_payment':
            if not can_manage_certificate_requests:
                error = 'ليس لديك صلاحية لتسجيل دفع الشهادة.'
            elif certificate_request.status != 'payment_pending':
                error = 'لا يمكن تسجيل الدفع في الحالة الحالية.'
            elif not certificate_request.payment_order_number:
                error = 'يرجى إدخال رقم أمر الدفع أولاً.'
            else:
                payment_receipt = request.FILES.get('payment_receipt')
                emirates_id_document = request.FILES.get('emirates_id_document')
                if not payment_receipt or not emirates_id_document:
                    error = 'يرجى إرفاق إيصال الدفع والهوية الإماراتية.'
                else:
                    certificate_request.payment_receipt = payment_receipt
                    certificate_request.emirates_id_document = emirates_id_document
                    certificate_request.payment_received_at = timezone.now()
                    certificate_request.status = 'payment_received'
                    certificate_request.save(
                        update_fields=[
                            'payment_receipt',
                            'emirates_id_document',
                            'payment_received_at',
                            'status',
                            'updated_at',
                        ]
                    )
                    return redirect('engineer_certificate_request_detail', request_id=certificate_request.id)

        elif action == 'issue_certificate':
            if not can_manage_certificate_requests:
                error = 'ليس لديك صلاحية إصدار الشهادة.'
            elif certificate_request.status != 'payment_received':
                error = 'لا يمكن إصدار الشهادة قبل استلام متطلبات الدفع.'
            else:
                issued_certificate = request.FILES.get('issued_certificate')
                certificate_issue_date_raw = (request.POST.get('certificate_issue_date') or '').strip()
                certificate_issue_date = None
                if certificate_issue_date_raw:
                    certificate_issue_date = _parse_date(certificate_issue_date_raw)
                    if not certificate_issue_date:
                        error = 'صيغة تاريخ إصدار الشهادة غير صحيحة.'
                if not error and not issued_certificate:
                    error = 'يرجى إرفاق ملف الشهادة الصادرة.'
                if not error:
                    certificate_issue_date = certificate_issue_date or timezone.localdate()
                    with transaction.atomic():
                        certificate_request.issued_certificate = issued_certificate
                        certificate_request.certificate_issue_date = certificate_issue_date
                        certificate_request.issued_by = request.user
                        certificate_request.issued_at = timezone.now()
                        certificate_request.status = 'issued'
                        certificate_request.save(
                            update_fields=[
                                'issued_certificate',
                                'certificate_issue_date',
                                'issued_by',
                                'issued_at',
                                'status',
                                'updated_at',
                            ]
                        )

                        enginer = certificate_request.enginer
                        if certificate_request.certificate_type == 'termite':
                            previous_file = enginer.termite_cert.name if enginer.termite_cert else None
                            enginer.termite_cert = certificate_request.issued_certificate
                            enginer.termite_cert_issue_date = certificate_issue_date
                            enginer.save(update_fields=['termite_cert', 'termite_cert_issue_date'])
                            EnginerStatusLog.objects.create(
                                enginer=enginer,
                                action='termite_cert_uploaded',
                                notes='Termite certificate issued from standalone certificate request.',
                                changed_by=request.user,
                                archived_file=previous_file or None,
                            )
                        else:
                            previous_file = enginer.public_health_cert.name if enginer.public_health_cert else None
                            enginer.public_health_cert = certificate_request.issued_certificate
                            enginer.public_health_cert_issue_date = certificate_issue_date
                            enginer.save(update_fields=['public_health_cert', 'public_health_cert_issue_date'])
                            EnginerStatusLog.objects.create(
                                enginer=enginer,
                                action='public_health_cert_uploaded',
                                notes='Public health certificate issued from standalone certificate request.',
                                changed_by=request.user,
                                archived_file=previous_file or None,
                            )
                    return redirect('engineer_certificate_request_detail', request_id=certificate_request.id)

    can_set_payment_order_number = (
        can_manage_certificate_requests
        and certificate_request.status in {'submitted', 'payment_pending'}
        and not certificate_request.payment_order_number
    )
    can_record_certificate_payment = (
        can_manage_certificate_requests
        and certificate_request.status == 'payment_pending'
        and not certificate_request.payment_receipt
    )
    can_issue_certificate = (
        can_manage_certificate_requests
        and certificate_request.status == 'payment_received'
    )
    no_pass_warning = (
        can_issue_certificate
        and not _enginer_has_passed_for_certificate(
            certificate_request.enginer,
            certificate_request.certificate_type,
        )
    )
    certificate_expiry_date, certificate_is_expired = _certificate_expiry(certificate_request.certificate_issue_date)

    return render(
        request,
        'hcsd/engineer_certificate_request_detail.html',
        {
            'certificate_request': certificate_request,
            'error': error,
            'can_manage_certificate_requests': can_manage_certificate_requests,
            'can_set_payment_order_number': can_set_payment_order_number,
            'can_record_certificate_payment': can_record_certificate_payment,
            'can_issue_certificate': can_issue_certificate,
            'no_pass_warning': no_pass_warning,
            'certificate_expiry_date': certificate_expiry_date,
            'certificate_is_expired': certificate_is_expired,
        },
    )


@login_required
def clearance_list(request):
    search_query = (request.GET.get('q') or '').strip()
    clearances_qs = (
        PirmetClearance.objects.filter(permit_type__in=['pest_control', 'pesticide_transport', 'waste_disposal'])
        .select_related('company', 'company__enginer')
        .order_by('-dateOfCreation')
    )
    if search_query:
        clearances_qs = clearances_qs.filter(
            Q(company__name__icontains=search_query)
            | Q(company__number__icontains=search_query)
        )
    reviews = InspectorReview.objects.filter(pirmet__in=clearances_qs).select_related('inspector', 'inspector_user')
    review_map = {review.pirmet_id: review for review in reviews}
    inspection_receive_changes = (
        PirmetChangeLog.objects.filter(
            pirmet__in=clearances_qs,
            change_type='details_update',
            notes__startswith='inspection_received_by:',
        )
        .order_by('pirmet_id', '-created_at')
    )
    inspection_report_changes = (
        PirmetChangeLog.objects.filter(
            pirmet__in=clearances_qs,
            change_type='details_update',
            notes__startswith='inspection_report:',
        )
        .select_related('changed_by')
        .order_by('pirmet_id', '-created_at')
    )
    inspection_receive_map = {}
    for change in inspection_receive_changes:
        if change.pirmet_id not in inspection_receive_map:
            inspection_receive_map[change.pirmet_id] = change
    inspection_report_map = {}
    for change in inspection_report_changes:
        if change.pirmet_id not in inspection_report_map:
            inspection_report_map[change.pirmet_id] = change
    clearances = list(clearances_qs)
    waste_requests_qs = (
        WasteDisposalRequest.objects.filter(permit__in=clearances_qs)
        .select_related('inspected_by')
        .order_by('permit_id', '-created_at', '-id')
    )
    latest_waste_request_map = {}
    latest_active_waste_request_map = {}
    for waste_request in waste_requests_qs:
        if waste_request.permit_id not in latest_waste_request_map:
            latest_waste_request_map[waste_request.permit_id] = waste_request
        if (
            waste_request.status in {'payment_pending', 'inspection_pending'}
            and waste_request.permit_id not in latest_active_waste_request_map
        ):
            latest_active_waste_request_map[waste_request.permit_id] = waste_request

    for clearance in clearances:
        clearance.permit_label_ar = _permit_label_ar(clearance.permit_type)
        clearance.detail_url_name = _permit_detail_url_name(clearance.permit_type)
        clearance.detail_url = reverse(clearance.detail_url_name, kwargs={'id': clearance.id})
        if clearance.permit_type == 'waste_disposal':
            latest_waste_request = (
                latest_active_waste_request_map.get(clearance.id)
                or latest_waste_request_map.get(clearance.id)
            )
            if latest_waste_request and clearance.status in {
                'inspection_pending',
                'disposal_approved',
                'disposal_rejected',
            }:
                clearance.permit_label_ar = 'طلب التخلص من النفايات'
                clearance.detail_url = reverse(
                    'waste_disposal_request_detail',
                    kwargs={'permit_id': clearance.id, 'request_id': latest_waste_request.id},
                )
        company = clearance.company
        engineer = company.enginer if company else None
        engineer_phone = (engineer.phone or '').strip() if engineer else ''
        landline_phone = (company.landline or '').strip() if company else ''
        company_phone = (company.owner_phone or '').strip() if company else ''
        clearance.contact_number = engineer_phone or landline_phone or company_phone or None
        clearance.company_location = (company.address or '').strip() if company and company.address else '-'
        review = review_map.get(clearance.id)
        clearance.inspector_name = _inspector_review_name(review)
        clearance.inspection_assigned_user_id = review.inspector_user_id if review and review.inspector_user_id else None
        if (
            not clearance.inspection_assigned_user_id
            and clearance.permit_type == 'waste_disposal'
        ):
            pending_waste_request = latest_active_waste_request_map.get(clearance.id)
            if (
                pending_waste_request
                and pending_waste_request.status == 'inspection_pending'
                and pending_waste_request.inspected_by_id
            ):
                clearance.inspection_assigned_user_id = pending_waste_request.inspected_by_id
        request_docs = _request_documents(clearance)
        clearance.request_documents_count = len(request_docs)
        clearance.has_request_documents = bool(
            clearance.request_documents_bundle
            or clearance.request_documents_count
        )
        receive_change = inspection_receive_map.get(clearance.id)
        clearance.inspection_receiver_name = None
        if receive_change and ':' in receive_change.notes:
            clearance.inspection_receiver_name = receive_change.notes.split(':', 1)[1].strip()
        if (
            not clearance.inspection_receiver_name
            and clearance.permit_type == 'waste_disposal'
        ):
            pending_waste_request = latest_active_waste_request_map.get(clearance.id)
            if pending_waste_request and pending_waste_request.inspected_by:
                clearance.inspection_receiver_name = _display_user_name(
                    pending_waste_request.inspected_by
                )
        clearance.status_key = clearance.status
        if (
            clearance.status == 'inspection_pending'
            and clearance.inspection_receiver_name
        ):
            clearance.status_key = 'inspection_received'
        report_change = inspection_report_map.get(clearance.id)
        clearance.inspection_report_decision = (
            _inspection_report_decision_from_note(report_change.notes)
            if report_change
            else None
        )
        if not clearance.inspection_report_decision and clearance.permit_type == 'waste_disposal':
            if clearance.status == 'disposal_approved':
                clearance.inspection_report_decision = 'approved'
            elif clearance.status == 'disposal_rejected':
                clearance.inspection_report_decision = 'rejected'

    finished_statuses = {
        'issued',
        'closed_requirements_pending',
        'cancelled_admin',
        'disposal_approved',
        'disposal_rejected',
    }
    active_clearances = []
    finished_clearances = []
    for _item in clearances:
        if _item.status in finished_statuses:
            finished_clearances.append(_item)
        elif (
            _item.status == 'inspection_completed'
            and _item.inspection_report_decision != 'approved'
        ):
            finished_clearances.append(_item)
        else:
            active_clearances.append(_item)
    inspector_scope_only = _can_inspector(request.user) and not _can_admin(request.user)
    if inspector_scope_only:
        inspector_visible_statuses = {'inspection_pending', 'inspection_received'}
        active_clearances = [
            item
            for item in active_clearances
            if getattr(item, 'status_key', item.status) in inspector_visible_statuses
        ]
        finished_clearances = []

    if _can_inspector(request.user):
        current_user_id = request.user.id

        def _active_inspector_sort_key(item):
            item_status = getattr(item, 'status_key', item.status)
            is_ready_to_receive = item_status == 'inspection_pending'
            is_received = item_status == 'inspection_received'
            assigned_to_current = bool(
                is_received
                and item.inspection_assigned_user_id
                and item.inspection_assigned_user_id == current_user_id
            )
            if is_ready_to_receive:
                priority = 0
            elif assigned_to_current:
                priority = 1
            elif is_received:
                priority = 2
            else:
                priority = 3
            created_ordinal = item.dateOfCreation.toordinal() if item.dateOfCreation else 0
            return (priority, -created_ordinal, -item.id)

        active_clearances.sort(key=_active_inspector_sort_key)
    else:
        active_clearances.sort(
            key=lambda item: (
                -(item.dateOfCreation.toordinal() if item.dateOfCreation else 0),
                -item.id,
            )
        )

    finished_clearances.sort(
        key=lambda item: (
            -(item.dateOfCreation.toordinal() if item.dateOfCreation else 0),
            -item.id,
        )
    )

    status_filter_label_map = {
        'inspection_received': 'تم استلام الطلب للتفتيش',
        'inspection_pending': 'جاهز للاستلام',
        'order_received': 'بانتظار اصدار رابط دفع التفتيش',
        'inspection_payment_pending': 'بانتظار دفع التفتيش',
        'review_pending': 'بانتظار مراجعة المفتش',
        'approved': 'معتمد من المفتش',
        'needs_completion': 'غير معتمد',
        'rejected': 'مرفوض',
        'payment_pending': 'بانتظار دفع التصريح',
        'payment_completed': 'تم استلام الدفع',
        'issued': 'تم إصدار التصريح',
        'inspection_completed': 'اكتمل التفتيش',
        'closed_requirements_pending': 'مغلق - اشتراطات واجبة الاستيفاء',
        'cancelled_admin': 'مغلق',
        'disposal_approved': 'إتلاف معتمد',
        'disposal_rejected': 'إتلاف مرفوض',
    }
    status_section_label_map = {
        'inspection_received': 'طلبات تم استلامها للتفتيش',
        'inspection_pending': 'طلبات جاهزة للاستلام',
        'order_received': 'بانتظار اصدار رابط دفع التفتيش',
        'inspection_payment_pending': 'طلبات بانتظار دفع التفتيش',
        'review_pending': 'طلبات بانتظار مراجعة المفتش',
        'approved': 'طلبات معتمدة من المفتش',
        'needs_completion': 'طلبات غير معتمدة',
        'rejected': 'طلبات مرفوضة',
        'payment_pending': 'طلبات بانتظار دفع التصريح',
        'payment_completed': 'طلبات تم استلام دفعها',
        'issued': 'طلبات صادرة',
        'inspection_completed': 'طلبات اكتمل تفتيشها',
        'closed_requirements_pending': 'طلبات مغلقة - اشتراطات واجبة الاستيفاء',
        'cancelled_admin': 'طلبات مغلقة',
        'disposal_approved': 'طلبات إتلاف معتمدة',
        'disposal_rejected': 'طلبات إتلاف مرفوضة',
    }
    active_status_order = [
        'inspection_pending',
        'inspection_received',
        'order_received',
        'inspection_payment_pending',
        'review_pending',
        'approved',
        'needs_completion',
        'rejected',
        'payment_pending',
        'payment_completed',
    ]
    finished_status_order = [
        'issued',
        'inspection_completed',
        'closed_requirements_pending',
        'cancelled_admin',
        'disposal_approved',
        'disposal_rejected',
    ]
    if inspector_scope_only:
        active_status_order = ['inspection_pending', 'inspection_received']
        finished_status_order = []
    all_status_order = active_status_order + finished_status_order

    status_filter = (request.GET.get('status') or 'all').strip()
    if status_filter != 'all' and status_filter not in status_filter_label_map:
        status_filter = 'all'

    if status_filter != 'all':
        active_clearances = [
            item for item in active_clearances
            if getattr(item, 'status_key', item.status) == status_filter
        ]
        finished_clearances = [
            item for item in finished_clearances
            if getattr(item, 'status_key', item.status) == status_filter
        ]

    status_filter_options = [
        {'value': 'all', 'label': 'كل الحالات'},
        *[
            {'value': status_key, 'label': status_filter_label_map.get(status_key, status_key)}
            for status_key in all_status_order
        ],
    ]
    status_filter_label = (
        status_filter_label_map.get(status_filter, 'كل الحالات')
        if status_filter != 'all'
        else 'كل الحالات'
    )

    active_clearance_groups = _group_clearances_by_status(active_clearances, active_status_order, status_section_label_map)
    finished_clearance_groups = _group_clearances_by_status(finished_clearances, finished_status_order, status_section_label_map)

    return render(
        request,
        'hcsd/clearance_list.html',
        {
            'clearances': active_clearances,
            'active_clearances': active_clearances,
            'finished_clearances': finished_clearances,
            'active_clearance_groups': active_clearance_groups,
            'finished_clearance_groups': finished_clearance_groups,
            'query': search_query,
            'status_filter': status_filter,
            'status_filter_label': status_filter_label,
            'status_filter_options': status_filter_options,
            'show_finished_section': not inspector_scope_only,
            'can_create_pirmet': _can_data_entry(request.user),
            'form_errors': [],
        },
    )


@login_required
def permit_types(request):
    return render(
        request,
        'hcsd/permit_types.html',
        {
            'can_create_pirmet': _can_data_entry(request.user),
        },
    )


@login_required
def vehicle_permit(request):
    if not _can_data_entry(request.user):
        return redirect('clearance_list')

    companies = Company.objects.select_related('enginer').all().order_by('name')
    selected_company_id = _parse_int(request.GET.get('company_id') or request.POST.get('company_id'))
    selected_company = (
        Company.objects.select_related('enginer').filter(id=selected_company_id).first()
        if selected_company_id
        else None
    )

    form_data = {
        'request_email': '',
        'vehicle_type': '',
        'vehicle_number': '',
        'vehicle_color': '',
        'issue_authority': '',
        'vehicle_license_expiry': '',
    }
    form_errors = []
    invalid_docs = []

    if request.method == 'POST':
        company_id = _parse_int(request.POST.get('company_id'))
        company = (
            Company.objects.select_related('enginer').filter(id=company_id).first()
            if company_id
            else None
        )
        if not company:
            form_errors.append('company_select_invalid')
        elif _company_has_active_extension(company):
            form_errors.append('company_has_active_extension')

        form_data.update(
            {
                'request_email': (request.POST.get('request_email') or '').strip(),
                'vehicle_type': (request.POST.get('vehicle_type') or '').strip(),
                'vehicle_number': (request.POST.get('vehicle_number') or '').strip(),
                'vehicle_color': (request.POST.get('vehicle_color') or '').strip(),
                'issue_authority': (request.POST.get('issue_authority') or '').strip(),
                'vehicle_license_expiry': (request.POST.get('vehicle_license_expiry') or '').strip(),
            }
        )

        if not form_data['request_email']:
            form_errors.append('request_email_required')
        if not form_data['vehicle_type']:
            form_errors.append('vehicle_type_required')
        if not form_data['vehicle_number']:
            form_errors.append('vehicle_number_required')
        if not form_data['vehicle_color']:
            form_errors.append('vehicle_color_required')
        if not form_data['issue_authority']:
            form_errors.append('issue_authority_required')
        if not form_data['vehicle_license_expiry']:
            form_errors.append('vehicle_license_expiry_required')

        vehicle_license_expiry = _parse_date(form_data['vehicle_license_expiry'])
        if form_data['vehicle_license_expiry'] and not vehicle_license_expiry:
            form_errors.append('vehicle_license_expiry_invalid')

        documents = request.FILES.getlist('documents')
        if not documents:
            form_errors.append('documents_required')
        else:
            for doc in documents:
                ext = os.path.splitext(doc.name)[1].lower()
                if ext not in ALLOWED_DOC_EXTENSIONS:
                    invalid_docs.append(doc.name)
            if invalid_docs:
                form_errors.append('documents_invalid')

        if not form_errors:
            permit = PirmetClearance.objects.create(
                company=company,
                permit_type='pesticide_transport',
                status='inspection_pending',
                request_email=form_data['request_email'] or None,
            )
            PesticideTransportPermit.objects.create(
                pirmet=permit,
                contact_number=company.owner_phone or company.landline or None,
                vehicle_type=form_data['vehicle_type'],
                vehicle_number=form_data['vehicle_number'],
                vehicle_color=form_data['vehicle_color'],
                issue_authority=form_data['issue_authority'],
                vehicle_license_expiry=vehicle_license_expiry,
            )
            for doc in documents:
                PirmetDocument.objects.create(pirmet=permit, file=doc)
            _log_pirmet_change(permit, 'created', request.user, new_status=permit.status, notes='Vehicle permit request created.')
            _log_pirmet_change(
                permit,
                'document_upload',
                request.user,
                notes=f'Documents uploaded: {len(documents)}',
            )
            return redirect('vehicle_permit_detail', id=permit.id)

    context = {
        'companies': companies,
        'selected_company_id': selected_company_id,
        'selected_company': selected_company,
        'form_data': form_data,
        'form_errors': form_errors,
    }
    if invalid_docs:
        context['invalid_docs'] = invalid_docs
    return render(request, 'hcsd/vehicle_permit.html', context)


@login_required
def vehicle_permit_detail(request, id):
    pirmet = get_object_or_404(
        PirmetClearance.objects.select_related('company', 'transport_details').prefetch_related('documents'),
        id=id,
        permit_type='pesticide_transport',
    )
    transport = getattr(pirmet, 'transport_details', None)
    review_errors = []

    assigned_review = InspectorReview.objects.filter(pirmet=pirmet).select_related('inspector_user').first()
    assigned_inspector_user = assigned_review.inspector_user if assigned_review else None
    assigned_inspector_name = (
        _display_user_name(assigned_inspector_user)
        if assigned_inspector_user
        else None
    )
    can_receive_inspection_request = (
        _can_inspector(request.user)
        and pirmet.status == 'inspection_pending'
        and not assigned_inspector_user
    )
    can_reassign_inspector = (
        _can_admin(request.user)
        and pirmet.status == 'inspection_pending'
        and assigned_inspector_user
    )
    can_submit_inspection_report = (
        _can_inspector(request.user)
        and pirmet.status == 'inspection_pending'
        and assigned_inspector_user
        and assigned_inspector_user.id == request.user.id
    )

    latest_inspection_receive = (
        PirmetChangeLog.objects.filter(
            pirmet=pirmet,
            change_type='details_update',
            notes__startswith='inspection_received_by:',
        )
        .order_by('-created_at')
        .first()
    )
    inspection_receiver_name = None
    if latest_inspection_receive and ':' in latest_inspection_receive.notes:
        inspection_receiver_name = latest_inspection_receive.notes.split(':', 1)[1].strip()
    if assigned_inspector_name:
        inspection_receiver_name = assigned_inspector_name

    latest_inspection_report = (
        PirmetChangeLog.objects.filter(
            pirmet=pirmet,
            change_type='details_update',
            notes__startswith='inspection_report:',
        )
        .select_related('changed_by')
        .order_by('-created_at')
        .first()
    )
    inspection_report_decision = (
        _inspection_report_decision_from_note(latest_inspection_report.notes)
        if latest_inspection_report
        else None
    )
    inspection_report_date = (
        latest_inspection_report.created_at if latest_inspection_report else None
    )

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'receive_for_inspection':
            if not (_can_inspector(request.user) or _can_admin(request.user)):
                review_errors.append('ليس لديك صلاحية لاستلام الطلب للتفتيش.')
            if pirmet.status != 'inspection_pending':
                review_errors.append('هذا الطلب ليس في مرحلة التفتيش.')

            inspector_user = None
            inspector_id = _parse_int(request.POST.get('inspector_id'))
            if inspector_id and _can_admin(request.user):
                inspector_user = _inspector_users_qs().filter(id=inspector_id).first()
                if not inspector_user:
                    review_errors.append('يرجى اختيار مفتش صحيح.')
            elif _can_inspector(request.user):
                inspector_user = request.user
            elif _can_admin(request.user):
                review_errors.append('يرجى اختيار مفتش صحيح.')

            if not review_errors:
                with transaction.atomic():
                    locked_pirmet = (
                        PirmetClearance.objects.select_for_update()
                        .filter(id=pirmet.id, permit_type='pesticide_transport')
                        .first()
                    )
                    if not locked_pirmet:
                        review_errors.append('تعذر العثور على الطلب.')
                    elif locked_pirmet.status != 'inspection_pending':
                        review_errors.append('هذا الطلب لم يعد بانتظار الاستلام للتفتيش.')
                    else:
                        locked_review = (
                            InspectorReview.objects.select_for_update()
                            .filter(pirmet=locked_pirmet)
                            .only('id', 'inspector_user_id')
                            .first()
                        )
                        locked_inspector_user_id = locked_review.inspector_user_id if locked_review else None
                        if (
                            _can_inspector(request.user)
                            and not _can_admin(request.user)
                            and locked_inspector_user_id
                            and locked_inspector_user_id != request.user.id
                        ):
                            review_errors.append('تم استلام الطلب بواسطة مفتش آخر.')
                        else:
                            InspectorReview.objects.update_or_create(
                                pirmet=locked_pirmet,
                                defaults={
                                    'inspector': None,
                                    'inspector_user': inspector_user,
                                    'isApproved': False,
                                    'comments': 'تم استلام الطلب للتفتيش.',
                                },
                            )
                            _log_pirmet_change(
                                locked_pirmet,
                                'details_update',
                                request.user,
                                notes=f'inspection_received_by:{_display_user_name(inspector_user)}',
                            )
                if not review_errors:
                    return redirect('vehicle_permit_detail', id=pirmet.id)

        if action == 'submit_inspection_report':
            if not can_submit_inspection_report:
                review_errors.append('ليس لديك صلاحية لإضافة تقرير التفتيش.')
            if pirmet.status != 'inspection_pending':
                review_errors.append('هذا الطلب ليس في مرحلة إدخال تقرير التفتيش.')

            decision = (request.POST.get('inspection_decision') or '').strip().lower()
            report_notes = (request.POST.get('inspection_report_notes') or '').strip()
            photos = request.FILES.getlist('inspection_report_photos')
            if decision not in {'approved', 'rejected'}:
                review_errors.append('يرجى اختيار نتيجة التقرير.')
            if decision == 'rejected' and not report_notes:
                review_errors.append('يرجى كتابة ملاحظات سبب عدم الاعتماد.')
            invalid_photos = []
            for photo in photos:
                ext = os.path.splitext(photo.name)[1].lower()
                if ext not in {'.png', '.jpg', '.jpeg'}:
                    invalid_photos.append(photo.name)
            if invalid_photos:
                review_errors.append('يُسمح فقط برفع صور JPG/PNG لتقرير التفتيش.')

            if not review_errors:
                old_status = pirmet.status
                if decision == 'approved':
                    pirmet.status = 'inspection_completed'
                    if pirmet.unapprovedReason:
                        pirmet.unapprovedReason = None
                    pirmet.save(update_fields=['status', 'unapprovedReason'])
                else:
                    pirmet.status = 'inspection_completed'
                    pirmet.unapprovedReason = report_notes or 'Inspection rejected.'
                    pirmet.save(update_fields=['status', 'unapprovedReason'])
                _log_pirmet_change(
                    pirmet,
                    'status_change',
                    request.user,
                    old_status=old_status,
                    new_status=pirmet.status,
                    notes='Vehicle inspection report submitted.',
                )
                _log_pirmet_change(
                    pirmet,
                    'details_update',
                    request.user,
                    notes=f'inspection_report:{decision}',
                )
                if report_notes:
                    _log_pirmet_change(
                        pirmet,
                        'details_update',
                        request.user,
                        notes=f'inspection_report_notes:{report_notes}',
                    )
                if photos:
                    timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S%f')
                    for index, photo in enumerate(photos, start=1):
                        ext = os.path.splitext(photo.name)[1].lower() or '.jpg'
                        photo.name = (
                            f'{VEHICLE_INSPECTION_REPORT_PHOTO_PREFIX}'
                            f'{pirmet.id}_{timestamp}_{index}{ext}'
                        )
                        PirmetDocument.objects.create(pirmet=pirmet, file=photo)
                    _log_pirmet_change(
                        pirmet,
                        'document_upload',
                        request.user,
                        notes=f'Vehicle inspection report photos uploaded: {len(photos)}',
                    )
                return redirect('vehicle_permit_detail', id=pirmet.id)

        if action == 'send_payment_link':
            if not _can_admin(request.user):
                review_errors.append('ليس لديك صلاحية لإدخال رقم الدفع.')
            if pirmet.status != 'inspection_completed':
                review_errors.append('هذا الطلب ليس بانتظار إدخال رقم دفع التصريح.')
            payment_number = (request.POST.get('payment_number') or '').strip()
            if not payment_number:
                review_errors.append('يرجى إدخال رقم أمر دفع تصريح المركبة.')

            if not review_errors:
                old_status = pirmet.status
                pirmet.PaymentNumber = payment_number
                pirmet.status = 'payment_pending'
                pirmet.save(update_fields=['PaymentNumber', 'status'])
                _log_pirmet_change(
                    pirmet,
                    'status_change',
                    request.user,
                    old_status=old_status,
                    new_status=pirmet.status,
                    notes='Vehicle permit payment number entered.',
                )
                _log_pirmet_change(
                    pirmet,
                    'details_update',
                    request.user,
                    notes='Vehicle permit payment reference recorded.',
                )
                return redirect('vehicle_permit_detail', id=pirmet.id)

        if action == 'payment':
            if not _can_admin(request.user):
                review_errors.append('ليس لديك صلاحية لتأكيد الدفع.')
            if pirmet.status != 'payment_pending':
                review_errors.append('هذا الطلب ليس بانتظار الدفع.')
            if not (pirmet.PaymentNumber or '').strip():
                review_errors.append('يرجى إدخال رقم أمر الدفع أولاً.')

            receipt = (
                request.FILES.get('payment_receipt_camera')
                or request.FILES.get('payment_receipt')
            )
            if not receipt:
                review_errors.append('يرجى إرفاق إيصال الدفع.')
            else:
                ext = os.path.splitext(receipt.name)[1].lower()
                if ext not in ALLOWED_DOC_EXTENSIONS:
                    review_errors.append('يُسمح فقط بملفات PDF أو صور للإيصال.')

            if not review_errors:
                old_status = pirmet.status
                pirmet.payment_receipt = receipt
                pirmet.payment_date = datetime.date.today()
                issue_date = datetime.date.today()
                expiry_date = _calculate_permit_expiry(issue_date)
                pirmet.issue_date = issue_date
                pirmet.dateOfExpiry = expiry_date
                # New flow: after permit payment proof, issue the permit directly.
                pirmet.status = 'issued'
                pirmet.save()
                _log_pirmet_change(
                    pirmet,
                    'status_change',
                    request.user,
                    old_status=old_status,
                    new_status=pirmet.status,
                    notes='Vehicle permit payment received and permit issued.',
                )
                return redirect('vehicle_permit_detail', id=pirmet.id)

        if action == 'issue':
            if not _can_admin(request.user):
                review_errors.append('ليس لديك صلاحية لإصدار التصريح.')
            if pirmet.status != 'payment_completed':
                review_errors.append('لا يمكن إصدار التصريح قبل تأكيد دفع التصريح.')

            if not review_errors:
                old_status = pirmet.status
                issue_date = datetime.date.today()
                expiry_date = _calculate_permit_expiry(issue_date)
                pirmet.issue_date = issue_date
                pirmet.dateOfExpiry = expiry_date
                pirmet.status = 'issued'
                pirmet.save(update_fields=['issue_date', 'dateOfExpiry', 'status'])
                _log_pirmet_change(
                    pirmet,
                    'status_change',
                    request.user,
                    old_status=old_status,
                    new_status=pirmet.status,
                    notes='Vehicle permit issued.',
                )
                return redirect('vehicle_permit_detail', id=pirmet.id)

    latest_inspection_report_notes = (
        PirmetChangeLog.objects.filter(
            pirmet=pirmet,
            change_type='details_update',
            notes__startswith='inspection_report_notes:',
        )
        .order_by('-created_at')
        .first()
    )
    inspection_report_notes = None
    if latest_inspection_report_notes and ':' in latest_inspection_report_notes.notes:
        inspection_report_notes = latest_inspection_report_notes.notes.split(':', 1)[1].strip()

    return render(
        request,
        'hcsd/vehicle_permit_detail.html',
        {
            'pirmet': pirmet,
            'transport': transport,
            'review_errors': review_errors,
            'request_documents': _request_documents(pirmet),
            'inspection_report_decision': inspection_report_decision,
            'inspection_report_date': inspection_report_date,
            'inspection_report_notes': inspection_report_notes,
            'inspection_report_photos': _vehicle_inspection_report_photo_docs(pirmet),
            'inspection_receiver_name': inspection_receiver_name,
            'assigned_inspector_name': assigned_inspector_name,
            'assigned_inspector_id': assigned_inspector_user.id if assigned_inspector_user else None,
            'can_review_pirmet': _can_inspector(request.user),
            'can_receive_inspection_request': can_receive_inspection_request,
            'can_reassign_inspector': can_reassign_inspector,
            'can_submit_inspection_report': can_submit_inspection_report,
            'can_record_payment': _can_admin(request.user),
            'inspector_users': _inspector_users_qs(),
        },
    )


@login_required
def waste_permit(request):
    if not _can_data_entry(request.user):
        return redirect('clearance_list')

    companies = Company.objects.select_related('enginer').all().order_by('name')
    selected_company_id = _parse_int(request.GET.get('company_id') or request.POST.get('company_id'))
    selected_company = (
        Company.objects.select_related('enginer').filter(id=selected_company_id).first()
        if selected_company_id
        else None
    )
    form_data = {
        'request_email': '',
    }
    form_errors = []
    invalid_docs = []

    if request.method == 'POST':
        company_id = _parse_int(request.POST.get('company_id'))
        company = (
            Company.objects.select_related('enginer').filter(id=company_id).first()
            if company_id
            else None
        )
        if not company:
            form_errors.append('company_select_invalid')
        elif _company_has_active_extension(company):
            form_errors.append('company_has_active_extension')

        form_data.update(
            {
                'request_email': (request.POST.get('request_email') or '').strip(),
            }
        )
        if not form_data['request_email']:
            form_errors.append('request_email_required')

        documents = request.FILES.getlist('documents')
        if not documents:
            form_errors.append('documents_required')
        else:
            for doc in documents:
                ext = os.path.splitext(doc.name)[1].lower()
                if ext not in ALLOWED_DOC_EXTENSIONS:
                    invalid_docs.append(doc.name)
            if invalid_docs:
                form_errors.append('documents_invalid')

        if not form_errors:
            permit = PirmetClearance.objects.create(
                company=company,
                permit_type='waste_disposal',
                status='payment_pending',
                request_email=form_data['request_email'] or None,
            )
            for doc in documents:
                PirmetDocument.objects.create(pirmet=permit, file=doc)
            _log_pirmet_change(
                permit,
                'created',
                request.user,
                new_status=permit.status,
                notes='Waste disposal base permit created.',
            )
            _log_pirmet_change(
                permit,
                'document_upload',
                request.user,
                notes=f'Documents uploaded: {len(documents)}',
            )
            _log_company_change(
                company,
                'waste_permit_created',
                request.user,
                notes=f'تم إنشاء تصريح التخلص من النفايات رقم {permit.permit_no}.',
            )
            return redirect('waste_permit_detail', id=permit.id)

    context = {
        'companies': companies,
        'selected_company_id': selected_company_id,
        'selected_company': selected_company,
        'form_data': form_data,
        'form_errors': form_errors,
    }
    if invalid_docs:
        context['invalid_docs'] = invalid_docs
    return render(request, 'hcsd/waste_permit.html', context)


@login_required
def waste_permit_detail(request, id):
    pirmet = get_object_or_404(
        PirmetClearance.objects.select_related('company', 'waste_details').prefetch_related('documents', 'waste_disposal_requests'),
        id=id,
        permit_type='waste_disposal',
    )
    review_errors = []
    today = datetime.date.today()
    waste_details = getattr(pirmet, 'waste_details', None)
    is_active = bool(
        pirmet.status == 'issued'
        and pirmet.issue_date
        and pirmet.dateOfExpiry
        and pirmet.dateOfExpiry >= today
    )

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'send_payment_link':
            if not _can_admin(request.user):
                review_errors.append('ليس لديك صلاحية لإدخال رقم الدفع.')
            if pirmet.status != 'payment_pending':
                review_errors.append('هذا الطلب ليس بانتظار إدخال رقم دفع التصريح.')
            payment_number = (request.POST.get('payment_number') or '').strip()
            if not payment_number:
                review_errors.append('يرجى إدخال رقم أمر دفع التصريح.')
            if not review_errors:
                pirmet.PaymentNumber = payment_number
                pirmet.save(update_fields=['PaymentNumber'])
                _log_pirmet_change(
                    pirmet,
                    'details_update',
                    request.user,
                    notes='Waste permit payment reference recorded.',
                )
                _log_company_change(
                    pirmet.company,
                    'waste_permit_payment_reference',
                    request.user,
                    notes=f'تم تسجيل رقم دفع تصريح التخلص #{pirmet.permit_no}.',
                )
                return redirect('waste_permit_detail', id=pirmet.id)

        if action == 'payment':
            if not _can_admin(request.user):
                review_errors.append('ليس لديك صلاحية لتأكيد الدفع.')
            if pirmet.status != 'payment_pending':
                review_errors.append('هذا الطلب ليس بانتظار الدفع.')
            if not (pirmet.PaymentNumber or '').strip():
                review_errors.append('يرجى إدخال رقم أمر الدفع أولاً.')
            receipt = (
                request.FILES.get('payment_receipt_camera')
                or request.FILES.get('payment_receipt')
            )
            if not receipt:
                review_errors.append('يرجى إرفاق إيصال الدفع.')
            else:
                ext = os.path.splitext(receipt.name)[1].lower()
                if ext not in ALLOWED_DOC_EXTENSIONS:
                    review_errors.append('يُسمح فقط بملفات PDF أو صور للإيصال.')
            if not review_errors:
                old_status = pirmet.status
                pirmet.payment_receipt = receipt
                pirmet.payment_date = datetime.date.today()
                issue_date = datetime.date.today()
                expiry_date = _add_months(issue_date, 6)
                pirmet.issue_date = issue_date
                pirmet.dateOfExpiry = expiry_date
                # New flow: after permit payment proof, issue the permit directly.
                pirmet.status = 'issued'
                pirmet.save()
                _log_pirmet_change(
                    pirmet,
                    'status_change',
                    request.user,
                    old_status=old_status,
                    new_status=pirmet.status,
                    notes='Waste permit payment received and permit issued.',
                )
                _log_company_change(
                    pirmet.company,
                    'waste_permit_paid',
                    request.user,
                    notes=f'تم تأكيد دفع تصريح التخلص #{pirmet.permit_no}.',
                )
                _log_company_change(
                    pirmet.company,
                    'waste_permit_issued',
                    request.user,
                    notes=f'تم إصدار تصريح التخلص #{pirmet.permit_no} لمدة 6 أشهر.',
                )
                return redirect('waste_permit_detail', id=pirmet.id)

        if action == 'issue':
            if not _can_admin(request.user):
                review_errors.append('ليس لديك صلاحية لإصدار التصريح.')
            if pirmet.status != 'payment_completed':
                review_errors.append('لا يمكن إصدار التصريح قبل تأكيد الدفع.')
            if not review_errors:
                old_status = pirmet.status
                issue_date = datetime.date.today()
                expiry_date = _add_months(issue_date, 6)
                pirmet.issue_date = issue_date
                pirmet.dateOfExpiry = expiry_date
                pirmet.status = 'issued'
                pirmet.save(update_fields=['issue_date', 'dateOfExpiry', 'status'])
                _log_pirmet_change(
                    pirmet,
                    'status_change',
                    request.user,
                    old_status=old_status,
                    new_status=pirmet.status,
                    notes='Waste permit issued for 6 months.',
                )
                _log_company_change(
                    pirmet.company,
                    'waste_permit_issued',
                    request.user,
                    notes=f'تم إصدار تصريح التخلص #{pirmet.permit_no} لمدة 6 أشهر.',
                )
                return redirect('waste_permit_detail', id=pirmet.id)

    disposal_requests = list(
        pirmet.waste_disposal_requests.select_related('inspected_by').order_by('-created_at')
    )
    for disposal_request in disposal_requests:
        disposal_request.inspected_by_name = _display_user_name(disposal_request.inspected_by) or '-'
    return render(
        request,
        'hcsd/waste_permit_detail.html',
        {
            'pirmet': pirmet,
            'waste_details': waste_details,
            'review_errors': review_errors,
            'request_documents': _request_documents(pirmet),
            'can_record_payment': _can_admin(request.user),
            'can_issue_pirmet': _can_admin(request.user),
            'is_active': is_active,
            'disposal_requests': disposal_requests,
        },
    )


@login_required
def waste_disposal_request_detail(request, permit_id, request_id=None):
    permit = get_object_or_404(
        PirmetClearance.objects.select_related('company'),
        id=permit_id,
        permit_type='waste_disposal',
    )
    today = datetime.date.today()
    if not permit.dateOfExpiry or permit.dateOfExpiry < today:
        return redirect('waste_permit_detail', id=permit.id)

    if request_id is None:
        if not _can_data_entry(request.user):
            return redirect('waste_permit_detail', id=permit.id)
        active_request = (
            permit.waste_disposal_requests.filter(status__in={'payment_pending', 'inspection_pending'})
            .order_by('-id')
            .first()
        )
        if active_request:
            return redirect(
                'waste_disposal_request_detail',
                permit_id=permit.id,
                request_id=active_request.id,
            )
        if permit.status not in {'issued', 'disposal_approved', 'disposal_rejected'}:
            return redirect('waste_permit_detail', id=permit.id)
        review_errors = []
        if request.method == 'POST':
            action = request.POST.get('action')
            if action == 'create_request':
                documents = request.FILES.getlist('request_documents')
                waste_classification = request.POST.get('waste_classification', 'hazardous')
                waste_type = request.POST.get('waste_type', 'empty_pesticide_containers')
                material_state = request.POST.get('material_state', 'solid')
                valid_classifications = {c[0] for c in WasteDisposalRequest.WASTE_CLASSIFICATION_CHOICES}
                valid_types = {c[0] for c in WasteDisposalRequest.WASTE_TYPE_CHOICES}
                valid_states = {c[0] for c in WasteDisposalRequest.MATERIAL_STATE_CHOICES}
                if waste_classification not in valid_classifications:
                    waste_classification = 'hazardous'
                if waste_type not in valid_types:
                    waste_type = 'empty_pesticide_containers'
                if material_state not in valid_states:
                    material_state = 'solid'
                invalid_docs = []
                for doc in documents:
                    ext = os.path.splitext(doc.name)[1].lower()
                    if ext not in ALLOWED_DOC_EXTENSIONS:
                        invalid_docs.append(doc.name)
                if not documents:
                    review_errors.append('يرجى إرفاق مستند واحد على الأقل قبل إنشاء طلب التخلص.')
                if invalid_docs:
                    review_errors.append('يُسمح فقط بملفات PDF أو صور: ' + ', '.join(invalid_docs))

                if not review_errors:
                    disposal_request = WasteDisposalRequest.objects.create(
                        permit=permit,
                        status='payment_pending',
                        waste_classification=waste_classification,
                        waste_type=waste_type,
                        material_state=material_state,
                    )
                    for doc in documents:
                        WasteDisposalRequestDocument.objects.create(
                            disposal_request=disposal_request,
                            file=doc,
                        )
                    _log_company_change(
                        permit.company,
                        'waste_request_created',
                        request.user,
                        notes=(
                            f'تم إنشاء طلب التخلص رقم {disposal_request.id} للتصريح '
                            f'#{permit.permit_no} مع {len(documents)} مستند.'
                        ),
                    )
                    _log_pirmet_change(
                        permit,
                        'document_upload',
                        request.user,
                        notes=f'waste_disposal_request_documents:{disposal_request.id}:{len(documents)}',
                    )
                    return redirect(
                        'waste_disposal_request_detail',
                        permit_id=permit.id,
                        request_id=disposal_request.id,
                    )

        return render(
            request,
            'hcsd/waste_disposal_request_detail.html',
            {
                'permit': permit,
                'disposal_request': None,
                'review_errors': review_errors,
                'create_mode': True,
                'can_create_disposal_request': _can_data_entry(request.user),
            },
        )

    disposal_request = get_object_or_404(
        WasteDisposalRequest.objects.select_related('permit', 'permit__company', 'inspected_by'),
        id=request_id,
        permit=permit,
    )
    request_documents = list(disposal_request.documents.order_by('-uploaded_at'))
    review_errors = []
    assigned_inspector = disposal_request.inspected_by
    can_upload_request_documents = (
        (_can_data_entry(request.user) or _can_admin(request.user))
        and disposal_request.status == 'payment_pending'
    )
    can_receive_disposal_request = (
        _can_inspector(request.user)
        and disposal_request.status == 'inspection_pending'
        and not assigned_inspector
    )
    can_reassign_disposal_inspector = (
        _can_admin(request.user)
        and disposal_request.status == 'inspection_pending'
        and assigned_inspector
    )
    can_submit_disposal_report = (
        _can_inspector(request.user)
        and disposal_request.status == 'inspection_pending'
        and assigned_inspector
        and assigned_inspector.id == request.user.id
    )

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'send_payment_link':
            if not _can_admin(request.user):
                review_errors.append('ليس لديك صلاحية لإدخال رقم الدفع.')
            if disposal_request.status != 'payment_pending':
                review_errors.append('الطلب ليس بانتظار الدفع.')
            if not request_documents:
                review_errors.append('لا يمكن إدخال أمر الدفع قبل إرفاق مستندات طلب التخلص.')
            reference = (request.POST.get('disposal_reference') or '').strip()
            if not reference:
                review_errors.append('يرجى إدخال رقم أمر دفع طلب التخلص.')
            if not review_errors:
                disposal_request.disposal_reference = reference
                disposal_request.save(update_fields=['disposal_reference'])
                _log_pirmet_change(
                    permit,
                    'details_update',
                    request.user,
                    notes=f'waste_disposal_payment_reference:{disposal_request.id}',
                )
                _log_company_change(
                    permit.company,
                    'waste_request_payment_reference',
                    request.user,
                    notes=f'تم تسجيل رقم دفع طلب التخلص رقم {disposal_request.id}.',
                )
                return redirect('waste_disposal_request_detail', permit_id=permit.id, request_id=disposal_request.id)

        if action == 'upload_request_documents':
            if not (_can_data_entry(request.user) or _can_admin(request.user)):
                review_errors.append('ليس لديك صلاحية لإرفاق مستندات طلب التخلص.')
            if disposal_request.status != 'payment_pending':
                review_errors.append('لا يمكن إرفاق مستندات الطلب بعد بدء مرحلة التفتيش.')
            documents = request.FILES.getlist('request_documents')
            invalid_docs = []
            for doc in documents:
                ext = os.path.splitext(doc.name)[1].lower()
                if ext not in ALLOWED_DOC_EXTENSIONS:
                    invalid_docs.append(doc.name)
            if not documents:
                review_errors.append('يرجى إرفاق مستند واحد على الأقل.')
            if invalid_docs:
                review_errors.append('يُسمح فقط بملفات PDF أو صور: ' + ', '.join(invalid_docs))

            if not review_errors:
                for doc in documents:
                    WasteDisposalRequestDocument.objects.create(
                        disposal_request=disposal_request,
                        file=doc,
                    )
                _log_pirmet_change(
                    permit,
                    'document_upload',
                    request.user,
                    notes=f'waste_disposal_request_documents:{disposal_request.id}:{len(documents)}',
                )
                return redirect(
                    'waste_disposal_request_detail',
                    permit_id=permit.id,
                    request_id=disposal_request.id,
                )

        if action == 'payment':
            if not _can_admin(request.user):
                review_errors.append('ليس لديك صلاحية لتأكيد الدفع.')
            if disposal_request.status != 'payment_pending':
                review_errors.append('الطلب ليس بانتظار الدفع.')
            if not (disposal_request.disposal_reference or '').strip():
                review_errors.append('يرجى إدخال رقم أمر الدفع أولاً.')
            receipt = request.FILES.get('disposal_payment_receipt')
            if not receipt:
                review_errors.append('يرجى إرفاق إيصال الدفع.')
            else:
                ext = os.path.splitext(receipt.name)[1].lower()
                if ext not in ALLOWED_DOC_EXTENSIONS:
                    review_errors.append('يُسمح فقط بملفات PDF أو صور للإيصال.')
            if not review_errors:
                old_permit_status = permit.status
                disposal_request.disposal_payment_receipt = receipt
                disposal_request.status = 'inspection_pending'
                disposal_request.inspected_by = None
                disposal_request.save(
                    update_fields=['disposal_payment_receipt', 'status', 'inspected_by', 'updated_at']
                )
                permit_update_fields = []
                if permit.status != 'inspection_pending':
                    permit.status = 'inspection_pending'
                    permit_update_fields.append('status')
                if permit.unapprovedReason:
                    permit.unapprovedReason = None
                    permit_update_fields.append('unapprovedReason')
                if permit_update_fields:
                    permit.save(update_fields=permit_update_fields)
                InspectorReview.objects.update_or_create(
                    pirmet=permit,
                    defaults={
                        'inspector': None,
                        'inspector_user': None,
                        'isApproved': False,
                        'comments': 'بانتظار استلام مفتش لطلب التخلص.',
                    },
                )
                _log_pirmet_change(
                    permit,
                    'status_change',
                    request.user,
                    old_status=old_permit_status,
                    new_status=permit.status,
                    notes=f'waste_disposal_payment_received:{disposal_request.id}',
                )
                _log_company_change(
                    permit.company,
                    'waste_request_paid',
                    request.user,
                    notes=f'تم تأكيد دفع طلب التخلص رقم {disposal_request.id}.',
                )
                return redirect('waste_disposal_request_detail', permit_id=permit.id, request_id=disposal_request.id)

        if action == 'receive_for_inspection':
            if not _can_inspector(request.user):
                review_errors.append('ليس لديك صلاحية لاستلام الطلب للتفتيش.')
            if disposal_request.status != 'inspection_pending':
                review_errors.append('الطلب ليس جاهزًا للاستلام للتفتيش.')
            if disposal_request.inspected_by_id and disposal_request.inspected_by_id != request.user.id:
                review_errors.append('تم استلام الطلب بواسطة مفتش آخر.')

            if not review_errors:
                if not disposal_request.inspected_by_id:
                    disposal_request.inspected_by = request.user
                    disposal_request.save(update_fields=['inspected_by', 'updated_at'])
                    InspectorReview.objects.update_or_create(
                        pirmet=permit,
                        defaults={
                            'inspector': None,
                            'inspector_user': request.user,
                            'isApproved': False,
                            'comments': 'تم استلام طلب التخلص للتفتيش.',
                        },
                    )
                    _log_pirmet_change(
                        permit,
                        'details_update',
                        request.user,
                        notes=f'inspection_received_by:{_display_user_name(request.user)}',
                    )
                return redirect(
                    'waste_disposal_request_detail',
                    permit_id=permit.id,
                    request_id=disposal_request.id,
                )

        if action == 'reassign_inspector':
            if not _can_admin(request.user):
                review_errors.append('ليس لديك صلاحية لتغيير المفتش المستلم.')
            if disposal_request.status != 'inspection_pending':
                review_errors.append('الطلب ليس في مرحلة التفتيش.')
            if not disposal_request.inspected_by_id:
                review_errors.append('لا يمكن تغيير المفتش قبل استلام الطلب.')
            inspector_id = _parse_int(request.POST.get('inspector_id'))
            inspector_user = (
                _inspector_users_qs().filter(id=inspector_id).first()
                if inspector_id
                else None
            )
            if not inspector_user:
                review_errors.append('يرجى اختيار مفتش صحيح.')

            if not review_errors:
                disposal_request.inspected_by = inspector_user
                disposal_request.save(update_fields=['inspected_by', 'updated_at'])
                InspectorReview.objects.update_or_create(
                    pirmet=permit,
                    defaults={
                        'inspector': None,
                        'inspector_user': inspector_user,
                        'isApproved': False,
                        'comments': 'تم تغيير المفتش المستلم لطلب التخلص.',
                    },
                )
                _log_pirmet_change(
                    permit,
                    'details_update',
                    request.user,
                    notes=f'inspection_received_by:{_display_user_name(inspector_user)}',
                )
                return redirect(
                    'waste_disposal_request_detail',
                    permit_id=permit.id,
                    request_id=disposal_request.id,
                )

        if action == 'submit_inspection_report':
            if not _can_inspector(request.user):
                review_errors.append('ليس لديك صلاحية لإضافة تقرير التفتيش.')
            if disposal_request.status != 'inspection_pending':
                review_errors.append('الطلب ليس في مرحلة التفتيش.')
            if not disposal_request.inspected_by:
                review_errors.append('يجب استلام الطلب من قبل مفتش قبل إدخال التقرير.')
            elif disposal_request.inspected_by_id != request.user.id:
                review_errors.append('فقط المفتش الذي استلم الطلب يمكنه إدخال تقرير التفتيش.')
            decision = (request.POST.get('inspection_decision') or '').strip().lower()
            notes = (request.POST.get('inspection_notes') or '').strip()
            if decision not in {'approved', 'rejected'}:
                review_errors.append('يرجى اختيار نتيجة التقرير.')
            if decision == 'rejected' and not notes:
                review_errors.append('يرجى كتابة سبب الرفض.')
            if not review_errors:
                old_permit_status = permit.status
                if decision == 'approved':
                    disposal_request.status = 'completed'
                    permit.status = 'disposal_approved'
                    if permit.unapprovedReason:
                        permit.unapprovedReason = None
                else:
                    disposal_request.status = 'rejected'
                    permit.status = 'disposal_rejected'
                    permit.unapprovedReason = notes or 'Waste disposal inspection rejected.'
                disposal_request.inspection_notes = notes or None
                disposal_request.inspected_by = request.user
                disposal_request.save(update_fields=['status', 'inspection_notes', 'inspected_by', 'updated_at'])
                permit_update_fields = ['status']
                if decision == 'approved' and permit.unapprovedReason is None:
                    pass
                else:
                    permit_update_fields.append('unapprovedReason')
                permit.save(update_fields=permit_update_fields)
                InspectorReview.objects.update_or_create(
                    pirmet=permit,
                    defaults={
                        'inspector': None,
                        'inspector_user': request.user,
                        'isApproved': decision == 'approved',
                        'comments': notes or ('تمت الموافقة على طلب التخلص.' if decision == 'approved' else 'تم رفض طلب التخلص.'),
                    },
                )
                _log_pirmet_change(
                    permit,
                    'status_change',
                    request.user,
                    old_status=old_permit_status,
                    new_status=permit.status,
                    notes=f'Waste disposal request {disposal_request.id} decision: {decision}.',
                )
                _log_pirmet_change(
                    permit,
                    'details_update',
                    request.user,
                    notes=f'waste_disposal_inspection:{disposal_request.id}:{decision}',
                )
                _log_pirmet_change(
                    permit,
                    'details_update',
                    request.user,
                    notes=f'inspection_report:{decision}',
                )
                if notes:
                    _log_pirmet_change(
                        permit,
                        'details_update',
                        request.user,
                        notes=f'inspection_report_notes:{notes}',
                    )
                _log_company_change(
                    permit.company,
                    'waste_request_inspected',
                    request.user,
                    notes=f'نتيجة تفتيش طلب التخلص رقم {disposal_request.id}: {"معتمد" if decision == "approved" else "مرفوض"}.',
                )
                return redirect('waste_disposal_request_detail', permit_id=permit.id, request_id=disposal_request.id)

    return render(
        request,
        'hcsd/waste_disposal_request_detail.html',
        {
            'permit': permit,
            'disposal_request': disposal_request,
            'request_documents': request_documents,
            'review_errors': review_errors,
            'can_record_payment': _can_admin(request.user),
            'can_review_request': _can_inspector(request.user),
            'can_receive_disposal_request': can_receive_disposal_request,
            'can_reassign_disposal_inspector': can_reassign_disposal_inspector,
            'can_submit_disposal_report': can_submit_disposal_report,
            'can_upload_request_documents': can_upload_request_documents,
            'assigned_inspector_name': _display_user_name(assigned_inspector) if assigned_inspector else None,
            'assigned_inspector_id': assigned_inspector.id if assigned_inspector else None,
            'inspector_users': _inspector_users_qs(),
            'create_mode': False,
        },
    )


@login_required
def pest_control_permit(request):
    if not _can_data_entry(request.user):
        return redirect('clearance_list')
    companies = Company.objects.select_related('enginer').all().order_by('name')
    selected_company_id = _parse_int(request.GET.get('company_id') or request.POST.get('company_id'))
    selected_company = (
        Company.objects.select_related('enginer').filter(id=selected_company_id).first()
        if selected_company_id
        else None
    )
    selected_enginer = selected_company.enginer if selected_company else None
    initial_expiry_date = _calculate_permit_expiry(
        selected_company.trade_license_exp if selected_company else None
    )
    selected_allowed_activities = _activities_for_enginer(selected_enginer)
    selected_restricted_activities = _restricted_activities_for_enginer(selected_enginer)

    form_data = {
        'company_name': selected_company.name if selected_company else '',
        'trade_license_no': selected_company.number if selected_company else '',
        'trade_license_exp': (
            selected_company.trade_license_exp.isoformat()
            if selected_company and selected_company.trade_license_exp
            else ''
        ),
        'company_address': selected_company.address if selected_company else '',
        'landline': selected_company.landline if selected_company else '',
        'owner_phone': selected_company.owner_phone if selected_company else '',
        'company_email': selected_company.email if selected_company else '',
        'business_activity': selected_company.business_activity if selected_company else '',
        'request_email': '',
        'engineer_name': selected_enginer.name if selected_enginer else '',
        'engineer_email': selected_enginer.email if selected_enginer else '',
        'engineer_phone': selected_enginer.phone if selected_enginer else '',
        'expiry_date': initial_expiry_date.isoformat() if initial_expiry_date else '',
        'allowed_other': '',
        'restricted_other': '',
    }

    form_errors = []
    invalid_docs = []
    trade_license_notice = _expired_trade_license_notice(
        selected_company.trade_license_exp if selected_company else None
    )
    engineer_notice = _engineer_no_certificate_notice(selected_enginer)

    if request.method == 'POST':
        company_id = _parse_int(request.POST.get('company_id'))
        company = (
            Company.objects.select_related('enginer').filter(id=company_id).first()
            if company_id
            else None
        )
        original_company_trade_license_exp = company.trade_license_exp if company else None
        if company_id and not company:
            form_errors.append('company_select_invalid')
        elif company and _company_has_active_extension(company):
            form_errors.append('company_has_active_extension')

        form_data.update(
            {
                'company_name': (request.POST.get('company_name') or '').strip(),
                'trade_license_no': (request.POST.get('trade_license_no') or '').strip(),
                'trade_license_exp': (request.POST.get('trade_license_exp') or '').strip(),
                'company_address': (request.POST.get('company_address') or '').strip(),
                'landline': (request.POST.get('landline') or '').strip(),
                'owner_phone': (request.POST.get('owner_phone') or '').strip(),
                'company_email': (request.POST.get('company_email') or '').strip(),
                'business_activity': (request.POST.get('business_activity') or '').strip(),
                'request_email': (request.POST.get('request_email') or '').strip(),
                'engineer_name': (request.POST.get('engineer_name') or '').strip(),
                'engineer_email': (request.POST.get('engineer_email') or '').strip(),
                'engineer_phone': (request.POST.get('engineer_phone') or '').strip(),
                'allowed_other': (request.POST.get('allowed_other') or '').strip(),
                'restricted_other': (request.POST.get('restricted_other') or '').strip(),
            }
        )

        business_activity_text = form_data['business_activity']

        if not company:
            if not form_data['company_name']:
                form_errors.append('company_name_required')
            if not form_data['trade_license_no']:
                form_errors.append('trade_license_no_required')
            if not form_data['company_address']:
                form_errors.append('company_address_required')

        trade_license_exp = _parse_date(form_data['trade_license_exp'])
        if form_data['trade_license_exp'] and not trade_license_exp:
            form_errors.append('trade_license_exp_invalid')
        elif not form_data['trade_license_exp']:
            form_errors.append('trade_license_exp_required')

        trade_license_notice = _expired_trade_license_notice(trade_license_exp)

        expiry_date = _calculate_permit_expiry(trade_license_exp)
        form_data['expiry_date'] = expiry_date.isoformat() if expiry_date else ''

        if not form_data['request_email']:
            form_errors.append('request_email_required')

        can_submit_without_engineer = True
        if company:
            can_submit_without_engineer = not PirmetClearance.objects.filter(
                company=company,
                permit_type='pest_control',
            ).exists()

        enginer = None
        pending_enginer_fields = []
        if company:
            enginer = company.enginer
            if not enginer:
                if can_submit_without_engineer:
                    engineer_notice = 'تنبيه: هذه الشركة بدون مهندس حالياً. يمكن تقديم الطلب واستكمال بيانات المهندس بعد التفتيش/الاستكمال.'
                else:
                    form_errors.append('company_engineer_missing')
            else:
                if _can_admin(request.user):
                    pending_enginer_fields = []
                    if form_data['engineer_name'] and enginer.name != form_data['engineer_name']:
                        enginer.name = form_data['engineer_name']
                        pending_enginer_fields.append('name')
                    if form_data['engineer_email'] and enginer.email != form_data['engineer_email']:
                        enginer.email = form_data['engineer_email']
                        pending_enginer_fields.append('email')
                    if form_data['engineer_phone'] and enginer.phone != form_data['engineer_phone']:
                        enginer.phone = form_data['engineer_phone']
                        pending_enginer_fields.append('phone')
                engineer_notice = _engineer_no_certificate_notice(enginer)
        else:
            if form_data['engineer_name'] or form_data['engineer_email'] or form_data['engineer_phone']:
                if not (form_data['engineer_name'] and form_data['engineer_email'] and form_data['engineer_phone']):
                    form_errors.append('engineer_required')
                else:
                    enginer = Enginer.objects.filter(email=form_data['engineer_email']).first()
                    if not enginer:
                        form_errors.append('engineer_not_registered')
                    else:
                        pending_enginer_fields = []
                        if form_data['engineer_name'] and enginer.name != form_data['engineer_name']:
                            enginer.name = form_data['engineer_name']
                            pending_enginer_fields.append('name')
                        if form_data['engineer_phone'] and enginer.phone != form_data['engineer_phone']:
                            enginer.phone = form_data['engineer_phone']
                            pending_enginer_fields.append('phone')
                        engineer_notice = _engineer_no_certificate_notice(enginer)
            else:
                engineer_notice = 'تنبيه: يمكن تقديم الطلب بدون مهندس للشركة الجديدة، وسيتم استكمال المهندس لاحقاً.'

        allowed_activities = _activities_for_enginer(enginer)
        restricted_activities = _restricted_activities_for_enginer(enginer)
        selected_allowed_activities = allowed_activities
        selected_restricted_activities = restricted_activities

        documents = request.FILES.getlist('documents')
        if not documents:
            form_errors.append('documents_required')
        else:
            for doc in documents:
                ext = os.path.splitext(doc.name)[1].lower()
                if ext not in ALLOWED_DOC_EXTENSIONS:
                    invalid_docs.append(doc.name)
            if invalid_docs:
                form_errors.append('documents_invalid')


        if not form_errors:
          with transaction.atomic():
            if enginer and pending_enginer_fields:
                enginer.save(update_fields=pending_enginer_fields)
            if not company:
                company = Company.objects.create(
                    name=form_data['company_name'],
                    number=form_data['trade_license_no'],
                    trade_license_exp=trade_license_exp,
                    address=form_data['company_address'],
                    landline=form_data['landline'] or None,
                    owner_phone=form_data['owner_phone'] or None,
                    email=form_data['company_email'] or None,
                    business_activity=business_activity_text or None,
                    enginer=enginer,
                    pest_control_type='public_health_pest_control',
                )
                _log_company_change(company, 'created', request.user, notes='Company created from permit request.')
            elif enginer and not company.enginer:
                company.enginer = enginer
                company.save(update_fields=['enginer'])
            elif company:
                company_changed_fields = []
                company_updates = {
                    'name': form_data['company_name'],
                    'number': form_data['trade_license_no'],
                    'trade_license_exp': trade_license_exp,
                    'address': form_data['company_address'],
                    'landline': form_data['landline'] or None,
                    'owner_phone': form_data['owner_phone'] or None,
                    'email': form_data['company_email'] or None,
                    'business_activity': business_activity_text or None,
                }
                for field, value in company_updates.items():
                    if getattr(company, field) != value:
                        setattr(company, field, value)
                        company_changed_fields.append(field)
                if company_changed_fields:
                    company.save(update_fields=company_changed_fields)
                    _log_company_change(
                        company,
                        'updated',
                        request.user,
                        notes='Company data updated from permit request form.',
                    )

            violation_reference_expiry = _initial_violation_reference_expiry(
                original_company_trade_license_exp,
                trade_license_exp,
            )
            permit = PirmetClearance.objects.create(
                company=company,
                dateOfExpiry=expiry_date,
                violation_reference_expiry=violation_reference_expiry,
                permit_type='pest_control',
                status='order_received',
                allowed_activities=','.join(allowed_activities) if allowed_activities else None,
                restricted_activities=','.join(restricted_activities) if restricted_activities else None,
                allowed_other=None,
                restricted_other=None,
                request_email=form_data['request_email'] or None,
            )
            for doc in documents:
                PirmetDocument.objects.create(pirmet=permit, file=doc)
            _log_pirmet_change(permit, 'created', request.user, new_status=permit.status, notes='Permit request created.')
            if documents:
                _log_pirmet_change(
                    permit,
                    'document_upload',
                    request.user,
                    notes=f'Documents uploaded: {len(documents)}',
                )
            return redirect('pest_control_permit_detail', id=permit.id)

    context = {
        'companies': companies,
        'selected_company_id': selected_company_id,
        'form_data': form_data,
        'selected_allowed_activities': selected_allowed_activities,
        'selected_restricted_activities': selected_restricted_activities,
        'form_errors': form_errors,
        'trade_license_notice': trade_license_notice,
        'engineer_notice': engineer_notice,
    }
    if invalid_docs:
        context['invalid_docs'] = invalid_docs
    return render(request, 'hcsd/pest_control_activity_permit.html', context)


@login_required
def pest_control_permit_detail(request, id):
    pirmet = get_object_or_404(
        PirmetClearance.objects.select_related('company', 'company__enginer').prefetch_related('documents'),
        id=id,
        permit_type='pest_control',
    )
    _inspection_detail_logs = list(
        PirmetChangeLog.objects.filter(
            pirmet=pirmet,
            change_type='details_update',
        ).filter(
            Q(notes__startswith='inspection_received_by:')
            | Q(notes__startswith='inspection_report:')
            | Q(notes__startswith='inspection_report_notes:')
            | Q(notes__startswith='head_remarks:')
        )
        .select_related('changed_by')
        .order_by('-created_at')
    )
    latest_inspection_receive = next(
        (l for l in _inspection_detail_logs if l.notes.startswith('inspection_received_by:')), None
    )
    latest_inspection_report = next(
        (l for l in _inspection_detail_logs if l.notes.startswith('inspection_report:')), None
    )
    latest_inspection_report_notes_log = next(
        (l for l in _inspection_detail_logs if l.notes.startswith('inspection_report_notes:')), None
    )
    latest_head_remarks_log = next(
        (l for l in _inspection_detail_logs if l.notes.startswith('head_remarks:')), None
    )

    inspection_receiver_name = None
    if latest_inspection_receive and ':' in latest_inspection_receive.notes:
        inspection_receiver_name = latest_inspection_receive.notes.split(':', 1)[1].strip()
    inspection_report_decision = (
        _inspection_report_decision_from_note(latest_inspection_report.notes)
        if latest_inspection_report
        else None
    )
    inspection_report_by = (
        _display_user_name(latest_inspection_report.changed_by)
        if latest_inspection_report and latest_inspection_report.changed_by
        else None
    )
    inspection_report_date = (
        latest_inspection_report.created_at if latest_inspection_report else None
    )
    inspection_report_notes = None
    if latest_inspection_report_notes_log and ':' in latest_inspection_report_notes_log.notes:
        inspection_report_notes = latest_inspection_report_notes_log.notes.split(':', 1)[1].strip()
    head_remarks = None
    if latest_head_remarks_log and ':' in latest_head_remarks_log.notes:
        head_remarks = latest_head_remarks_log.notes.split(':', 1)[1].strip()
    head_approval_log = (
        PirmetChangeLog.objects.filter(
            pirmet=pirmet,
            change_type='status_change',
            new_status='head_approved',
        )
        .select_related('changed_by')
        .order_by('-created_at')
        .first()
    )
    head_approved_by = (
        _display_user_name(head_approval_log.changed_by)
        if head_approval_log and head_approval_log.changed_by
        else None
    )
    head_approved_date = (
        head_approval_log.created_at if head_approval_log else None
    )

    assigned_review = InspectorReview.objects.filter(pirmet=pirmet).select_related(
        'inspector', 'inspector_user'
    ).first()
    assigned_inspector_user = assigned_review.inspector_user if assigned_review else None
    assigned_inspector_name = (
        _display_user_name(assigned_inspector_user)
        if assigned_inspector_user
        else None
    )
    if assigned_inspector_name:
        inspection_receiver_name = assigned_inspector_name
    can_receive_inspection_request = (
        _can_inspector(request.user)
        and pirmet.status == 'inspection_pending'
        and not assigned_inspector_user
    )
    can_reassign_inspector = False
    can_submit_inspection_report = (
        _can_inspector(request.user)
        and pirmet.status == 'inspection_pending'
        and assigned_inspector_user
        and assigned_inspector_user.id == request.user.id
    )
    can_manage_inspection_photos = (
        _can_admin(request.user)
        or _can_data_entry(request.user)
        or (
            _can_inspector(request.user)
            and assigned_inspector_user
            and assigned_inspector_user.id == request.user.id
        )
    )
    can_add_inspection_photos = (
        _can_inspector(request.user)
        and assigned_inspector_user
        and assigned_inspector_user.id == request.user.id
        and bool(pirmet.inspection_payment_receipt)
        and not can_submit_inspection_report
    )
    renewal_reference_date = _violation_reference_expiry_date(
        pirmet,
        timezone.localdate(),
    )
    delay_months_after_grace = _delay_months_after_first_month(
        renewal_reference_date,
        timezone.localdate(),
    )
    delay_days_total = 0
    if renewal_reference_date and timezone.localdate() > renewal_reference_date:
        delay_days_total = (timezone.localdate() - renewal_reference_date).days
    violation_amount_due = delay_months_after_grace * 100
    violation_required = delay_months_after_grace > 0
    violation_order_recorded = bool((pirmet.violation_payment_order_number or '').strip())
    violation_receipt_recorded = bool(pirmet.violation_payment_receipt)
    violation_payment_completed = (
        violation_order_recorded
        and violation_receipt_recorded
        and (pirmet.violation_amount or 0) == violation_amount_due
    )
    can_record_violation_order = (
        _can_admin(request.user)
        and pirmet.status == 'inspection_completed'
        and violation_required
        and not violation_order_recorded
    )
    can_record_violation_receipt = (
        _can_admin(request.user)
        and pirmet.status == 'inspection_completed'
        and violation_required
        and violation_order_recorded
        and not violation_receipt_recorded
    )
    requirements_required = bool(pirmet.inspection_requires_insurance)
    can_record_inspection_payment_reference = (
        _can_admin(request.user)
        and pirmet.status in {'order_received', 'inspection_payment_pending'}
    )
    can_record_inspection_payment_receipt = (
        _can_admin(request.user)
        and pirmet.status == 'inspection_payment_pending'
    )
    can_head_approve = (
        _can_admin(request.user)
        and pirmet.status == 'inspection_completed'
        and inspection_report_decision == 'approved'
    )
    can_record_permit_payment_reference = (
        _can_admin(request.user)
        and pirmet.status == 'head_approved'
        and (not violation_required or violation_payment_completed)
    )
    show_admin_close_form = (
        _can_admin(request.user)
        and pirmet.status not in {'issued', 'cancelled_admin', 'closed_requirements_pending'}
        and not (pirmet.status == 'inspection_completed' and inspection_report_decision == 'rejected')
    )
    review_errors = []

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'update_request_email':
            if not _can_admin(request.user):
                review_errors.append('ليس لديك صلاحية لتعديل بريد الطلب.')
            new_email = (request.POST.get('request_email') or '').strip()
            if not new_email:
                review_errors.append('يرجى إدخال بريد الطلب.')
            if not review_errors:
                pirmet.request_email = new_email
                pirmet.save(update_fields=['request_email'])
                _log_pirmet_change(
                    pirmet,
                    'details_update',
                    request.user,
                    notes='Request email updated.',
                )
                return redirect('pest_control_permit_detail', id=pirmet.id)

        if action == 'admin_update_request_data':
            if not _can_admin(request.user):
                review_errors.append('ليس لديك صلاحية لتعديل بيانات التصريح.')

            company_email = (request.POST.get('company_email') or '').strip()
            request_email = (request.POST.get('request_email') or '').strip()
            inspection_payment_reference = (request.POST.get('inspection_payment_reference') or '').strip()
            payment_number = (request.POST.get('payment_number') or '').strip()
            issue_date_raw = (request.POST.get('issue_date') or '').strip()
            expiry_date_raw = (request.POST.get('expiry_date') or '').strip()
            payment_date_raw = (request.POST.get('payment_date') or '').strip()
            issue_date = _parse_date(issue_date_raw)
            expiry_date = _parse_date(expiry_date_raw)
            payment_date = _parse_date(payment_date_raw)

            if not request_email:
                review_errors.append('يرجى إدخال بريد الطلب.')
            if issue_date_raw and not issue_date:
                review_errors.append('تاريخ إخراج التصريح غير صالح.')
            if expiry_date_raw and not expiry_date:
                review_errors.append('تاريخ انتهاء التصريح غير صالح.')
            if payment_date_raw and not payment_date:
                review_errors.append('تاريخ الدفع غير صالح.')

            enginer = pirmet.company.enginer
            engineer_email = (request.POST.get('engineer_email') or '').strip()
            engineer_phone = (request.POST.get('engineer_phone') or '').strip()

            if not review_errors:
                changed_labels = []
                if pirmet.request_email != request_email:
                    pirmet.request_email = request_email
                    changed_labels.append('بريد مُرسل الطلب')
                if pirmet.inspection_payment_reference != (inspection_payment_reference or None):
                    pirmet.inspection_payment_reference = inspection_payment_reference or None
                    changed_labels.append('رقم أمر دفع التفتيش')
                if pirmet.PaymentNumber != (payment_number or None):
                    pirmet.PaymentNumber = payment_number or None
                    changed_labels.append('رقم أمر دفع تصريح المزاولة')
                if pirmet.issue_date != issue_date:
                    pirmet.issue_date = issue_date
                    changed_labels.append('تاريخ إخراج التصريح')
                if pirmet.dateOfExpiry != expiry_date:
                    pirmet.dateOfExpiry = expiry_date
                    changed_labels.append('تاريخ انتهاء التصريح')
                if pirmet.payment_date != payment_date:
                    pirmet.payment_date = payment_date
                    changed_labels.append('تاريخ الدفع')
                if pirmet.company.email != (company_email or None):
                    pirmet.company.email = company_email or None
                    pirmet.company.save(update_fields=['email'])
                    _log_company_change(
                        pirmet.company,
                        'updated',
                        request.user,
                        notes='Company email updated from permit request detail page.',
                    )
                    changed_labels.append('بريد الشركة')
                if changed_labels:
                    pirmet.save(update_fields=[
                        'request_email',
                        'inspection_payment_reference',
                        'PaymentNumber',
                        'issue_date',
                        'dateOfExpiry',
                        'payment_date',
                    ])

                if enginer:
                    engineer_changed = []
                    if engineer_email and enginer.email != engineer_email:
                        enginer.email = engineer_email
                        engineer_changed.append('email')
                        changed_labels.append('بريد المهندس')
                    if engineer_phone and enginer.phone != engineer_phone:
                        enginer.phone = engineer_phone
                        engineer_changed.append('phone')
                        changed_labels.append('رقم تواصل المهندس')
                    if engineer_changed:
                        enginer.save(update_fields=engineer_changed)

                if changed_labels:
                    _log_pirmet_change(
                        pirmet,
                        'details_update',
                        request.user,
                        notes='Admin updated request data: ' + '، '.join(changed_labels),
                    )
                else:
                    review_errors.append('لا توجد تغييرات لحفظها.')

                if not review_errors:
                    return redirect('pest_control_permit_detail', id=pirmet.id)

        if action == 'cancel_admin':
            if not _can_admin(request.user):
                review_errors.append('ليس لديك صلاحية لإلغاء/إغلاق الطلب إدارياً.')
            elif pirmet.status in {'issued', 'cancelled_admin'}:
                review_errors.append('لا يمكن إلغاء هذا الطلب في حالته الحالية.')

            cancel_reason = (request.POST.get('cancel_reason') or '').strip()
            if not cancel_reason:
                review_errors.append('يرجى كتابة سبب الإلغاء/الإغلاق الإداري.')

            if not review_errors:
                old_status = pirmet.status
                pirmet.status = 'cancelled_admin'
                pirmet.save(update_fields=['status'])
                _log_pirmet_change(
                    pirmet,
                    'status_change',
                    request.user,
                    old_status=old_status,
                    new_status=pirmet.status,
                    notes=f'Administrative cancellation: {cancel_reason}',
                )
                return redirect('pest_control_permit_detail', id=pirmet.id)

        if action == 'save_violation_payment_order':
            if not _can_admin(request.user):
                review_errors.append('ليس لديك صلاحية لإدخال بيانات مخالفة التأخير.')
            if pirmet.status != 'inspection_completed':
                review_errors.append('يمكن إدخال أمر دفع المخالفة فقط بعد انتهاء التفتيش.')
            if not violation_required:
                review_errors.append('لا توجد مخالفة تأخير مطلوبة لهذا الطلب.')
            if violation_receipt_recorded:
                review_errors.append('تم حفظ إيصال المخالفة بالفعل، لا يمكن تعديل أمر الدفع.')

            violation_order = (request.POST.get('violation_payment_order_number') or '').strip()
            if not violation_order:
                review_errors.append('يرجى إدخال رقم أمر دفع المخالفة.')

            if not review_errors:
                pirmet.violation_payment_order_number = violation_order
                pirmet.violation_amount = violation_amount_due
                pirmet.save(update_fields=['violation_payment_order_number', 'violation_amount'])
                _log_pirmet_change(
                    pirmet,
                    'details_update',
                    request.user,
                    notes=f'Violation order recorded. Amount: {violation_amount_due}',
                )
                return redirect('pest_control_permit_detail', id=pirmet.id)

        if action == 'save_violation_payment_receipt':
            if not _can_admin(request.user):
                review_errors.append('ليس لديك صلاحية لإدخال إيصال مخالفة التأخير.')
            if pirmet.status != 'inspection_completed':
                review_errors.append('يمكن إدخال إيصال المخالفة فقط بعد انتهاء التفتيش.')
            if not violation_required:
                review_errors.append('لا توجد مخالفة تأخير مطلوبة لهذا الطلب.')
            if not (pirmet.violation_payment_order_number or '').strip():
                review_errors.append('يرجى إدخال رقم أمر دفع المخالفة أولاً.')
            if violation_receipt_recorded:
                review_errors.append('تم إدخال إيصال المخالفة مسبقاً.')

            violation_receipt = request.FILES.get('violation_payment_receipt')
            if not violation_receipt:
                review_errors.append('يرجى إرفاق إيصال دفع المخالفة.')
            else:
                ext = os.path.splitext(violation_receipt.name)[1].lower()
                if ext not in ALLOWED_DOC_EXTENSIONS:
                    review_errors.append('يُسمح فقط بملفات PDF أو صور لإيصال المخالفة.')

            if not review_errors:
                pirmet.violation_amount = violation_amount_due
                pirmet.violation_payment_receipt = violation_receipt
                pirmet.save(update_fields=['violation_amount', 'violation_payment_receipt'])
                _log_pirmet_change(
                    pirmet,
                    'document_upload',
                    request.user,
                    notes='Violation payment receipt uploaded.',
                )
                return redirect('pest_control_permit_detail', id=pirmet.id)

        if action == 'send_inspection_payment_link':
            if not _can_admin(request.user):
                review_errors.append('ليس لديك صلاحية لإدخال الرقم المرجعي لدفع التفتيش.')
            if pirmet.status not in {'order_received', 'inspection_payment_pending'}:
                review_errors.append('لا يمكن تعديل الرقم المرجعي في هذه المرحلة.')

            inspection_reference = (request.POST.get('inspection_payment_reference') or '').strip()
            if not inspection_reference:
                review_errors.append('يرجى إدخال الرقم المرجعي لدفع التفتيش.')

            if not review_errors:
                old_status = pirmet.status
                pirmet.inspection_payment_reference = inspection_reference
                if old_status == 'order_received':
                    pirmet.status = 'inspection_payment_pending'
                    pirmet.save(update_fields=['inspection_payment_reference', 'status'])
                    _log_pirmet_change(
                        pirmet,
                        'status_change',
                        request.user,
                        old_status=old_status,
                        new_status=pirmet.status,
                        notes='Inspection payment reference recorded.',
                    )
                else:
                    pirmet.save(update_fields=['inspection_payment_reference'])
                    _log_pirmet_change(
                        pirmet,
                        'details_update',
                        request.user,
                        notes='Inspection payment reference updated.',
                    )
                return redirect('pest_control_permit_detail', id=pirmet.id)

        if action == 'inspection_payment':
            if not _can_admin(request.user):
                review_errors.append('ليس لديك صلاحية لتأكيد دفع التفتيش.')
            if pirmet.status != 'inspection_payment_pending':
                review_errors.append('هذا الطلب ليس بانتظار دفع التفتيش.')

            inspection_reference = (request.POST.get('inspection_payment_reference') or '').strip()
            receipt = request.FILES.get('inspection_payment_receipt')
            if not receipt:
                review_errors.append('يرجى إرفاق إيصال دفع التفتيش.')
            if not inspection_reference and not pirmet.inspection_payment_reference:
                review_errors.append('يرجى إدخال الرقم المرجعي لدفع التفتيش أولاً.')
            if receipt:
                ext = os.path.splitext(receipt.name)[1].lower()
                if ext not in ALLOWED_DOC_EXTENSIONS:
                    review_errors.append('يُسمح فقط بملفات PDF أو صور للإيصال.')

            if not review_errors:
                old_status = pirmet.status
                if inspection_reference:
                    pirmet.inspection_payment_reference = inspection_reference
                pirmet.inspection_payment_receipt = receipt
                # After inspection fee is paid, the request moves directly to inspection.
                pirmet.status = 'inspection_pending'
                pirmet.save()
                _log_pirmet_change(
                    pirmet,
                    'status_change',
                    request.user,
                    old_status=old_status,
                    new_status=pirmet.status,
                    notes='Inspection payment received.',
                )
                return redirect('pest_control_permit_detail', id=pirmet.id)

        if action in {'approve', 'reject'}:
            if not _can_inspector(request.user):
                review_errors.append('ليس لديك صلاحية لمراجعة التصاريح.')
            if pirmet.status != 'review_pending':
                review_errors.append('هذا الطلب ليس بانتظار المراجعة.')

            inspector_id = _parse_int(request.POST.get('inspector_id'))
            remarks = (request.POST.get('remarks') or '').strip()
            inspector_user = (
                _inspector_users_qs().filter(id=inspector_id).first()
                if inspector_id
                else None
            )
            if not inspector_user:
                review_errors.append('يرجى اختيار مفتش صحيح.')
            if action == 'reject' and not remarks:
                review_errors.append('يرجى كتابة سبب عدم الاعتماد.')

            if not review_errors:
                InspectorReview.objects.update_or_create(
                    pirmet=pirmet,
                    defaults={
                        'inspector': None,
                        'inspector_user': inspector_user,
                        'isApproved': action == 'approve',
                        'comments': remarks,
                    },
                )
                old_status = pirmet.status
                if action == 'approve':
                    pirmet.status = 'approved'
                    pirmet.approvedRemarks = remarks
                    pirmet.approvedBy = request.user
                else:
                    pirmet.status = 'inspection_completed'
                    pirmet.unapprovedReason = remarks
                    pirmet.unapprovedBy = request.user
                pirmet.save()
                _log_pirmet_change(
                    pirmet,
                    'status_change',
                    request.user,
                    old_status=old_status,
                    new_status=pirmet.status,
                    notes=remarks or 'Inspector review updated.',
                )
                return redirect('pest_control_permit_detail', id=pirmet.id)

        if action == 'head_approve':
            if not _can_admin(request.user):
                review_errors.append('ليس لديك صلاحية للاعتماد النهائي.')
            if pirmet.status != 'inspection_completed':
                review_errors.append('هذا الطلب ليس في مرحلة الاعتماد النهائي.')
            if inspection_report_decision != 'approved':
                review_errors.append('لا يمكن الاعتماد النهائي قبل اعتماد تقرير التفتيش.')
            head_decision = (request.POST.get('head_decision') or '').strip()
            if head_decision not in {'approved', 'rejected'}:
                review_errors.append('يرجى اختيار قرار الاعتماد النهائي.')
            head_remarks = (request.POST.get('head_remarks') or '').strip()
            if head_decision == 'rejected' and not head_remarks:
                review_errors.append('يرجى كتابة سبب الرفض.')

            if not review_errors:
                old_status = pirmet.status
                if head_decision == 'approved':
                    pirmet.status = 'head_approved'
                    pirmet.save(update_fields=['status'])
                    _log_pirmet_change(
                        pirmet,
                        'status_change',
                        request.user,
                        old_status=old_status,
                        new_status=pirmet.status,
                        notes='Head of section final approval.',
                    )
                    if head_remarks:
                        _log_pirmet_change(
                            pirmet,
                            'details_update',
                            request.user,
                            notes=f'head_remarks:{head_remarks}',
                        )
                else:
                    pirmet.status = 'cancelled_admin'
                    pirmet.save(update_fields=['status'])
                    _log_pirmet_change(
                        pirmet,
                        'status_change',
                        request.user,
                        old_status=old_status,
                        new_status=pirmet.status,
                        notes='Head of section rejected - request closed.',
                    )
                    if head_remarks:
                        _log_pirmet_change(
                            pirmet,
                            'details_update',
                            request.user,
                            notes=f'head_remarks:{head_remarks}',
                        )
                return redirect('pest_control_permit_detail', id=pirmet.id)

        if action == 'send_payment_link':
            if not _can_admin(request.user):
                review_errors.append('ليس لديك صلاحية لإدخال الرقم المرجعي للدفع.')
            if pirmet.status != 'head_approved':
                review_errors.append('هذا الطلب ليس في مرحلة إدخال رقم دفع التصريح.')
            if violation_required and not violation_payment_completed:
                review_errors.append('يرجى استكمال أمر دفع المخالفة وإيصالها قبل إدخال رقم دفع التصريح.')
            payment_number = (request.POST.get('payment_number') or '').strip()
            if not payment_number:
                review_errors.append('يرجى إدخال الرقم المرجعي لدفع التصريح.')

            if not review_errors:
                old_status = pirmet.status
                pirmet.PaymentNumber = payment_number
                pirmet.status = 'payment_pending'
                pirmet.save(update_fields=['PaymentNumber', 'status'])
                _log_pirmet_change(
                    pirmet,
                    'status_change',
                    request.user,
                    old_status=old_status,
                    new_status=pirmet.status,
                    notes='Permit payment reference recorded.',
                )
                return redirect('pest_control_permit_detail', id=pirmet.id)

        if action == 'payment':
            if not _can_admin(request.user):
                review_errors.append('ليس لديك صلاحية لتأكيد الدفع.')
            if pirmet.status != 'payment_pending':
                review_errors.append('هذا الطلب ليس بانتظار الدفع.')
            if violation_required and not violation_payment_completed:
                review_errors.append('يرجى استكمال سداد المخالفة أولاً.')
            if not (pirmet.PaymentNumber or '').strip():
                review_errors.append('يرجى إدخال الرقم المرجعي لدفع التصريح أولاً.')

            receipt = (
                request.FILES.get('payment_receipt_camera')
                or request.FILES.get('payment_receipt')
            )
            if not receipt:
                review_errors.append('يرجى إرفاق إيصال الدفع.')
            else:
                ext = os.path.splitext(receipt.name)[1].lower()
                if ext not in ALLOWED_DOC_EXTENSIONS:
                    review_errors.append('يُسمح فقط بملفات PDF أو صور للإيصال.')

            if not review_errors:
                old_status = pirmet.status
                pirmet.payment_receipt = receipt
                pirmet.payment_date = datetime.date.today()
                # New flow: once payment proof is uploaded, issue the permit immediately.
                pirmet.status = 'issued'
                pirmet.save()
                _log_pirmet_change(
                    pirmet,
                    'status_change',
                    request.user,
                    old_status=old_status,
                    new_status=pirmet.status,
                    notes='Payment received and permit issued.',
                )
                return redirect('pest_control_permit_detail', id=pirmet.id)

        if action == 'receive_for_inspection':
            if not _can_inspector(request.user):
                review_errors.append('ليس لديك صلاحية لاستلام الطلب للتفتيش. هذه الصلاحية للمفتشين فقط.')
            if pirmet.status != 'inspection_pending':
                review_errors.append('هذا الطلب ليس في مرحلة التفتيش.')

            if not review_errors:
                with transaction.atomic():
                    locked_pirmet = (
                        PirmetClearance.objects.select_for_update()
                        .filter(id=pirmet.id, permit_type='pest_control')
                        .first()
                    )
                    if not locked_pirmet:
                        review_errors.append('تعذر العثور على الطلب.')
                    elif locked_pirmet.status != 'inspection_pending':
                        review_errors.append('هذا الطلب لم يعد بانتظار الاستلام للتفتيش.')
                    else:
                        locked_review = (
                            InspectorReview.objects.select_for_update()
                            .filter(pirmet=locked_pirmet)
                            .only('id', 'inspector_user_id')
                            .first()
                        )
                        locked_inspector_user_id = locked_review.inspector_user_id if locked_review else None
                        if locked_inspector_user_id and locked_inspector_user_id != request.user.id:
                            review_errors.append('تم استلام الطلب بواسطة مفتش آخر.')
                        else:
                            InspectorReview.objects.update_or_create(
                                pirmet=locked_pirmet,
                                defaults={
                                    'inspector': None,
                                    'inspector_user': request.user,
                                    'isApproved': False,
                                    'comments': 'تم استلام الطلب للتفتيش.',
                                },
                            )
                            _log_pirmet_change(
                                locked_pirmet,
                                'details_update',
                                request.user,
                                notes=f'inspection_received_by:{_display_user_name(request.user)}',
                            )
                if not review_errors:
                    return redirect('pest_control_permit_detail', id=pirmet.id)

        if action == 'submit_inspection_report':
            if not _can_inspector(request.user):
                review_errors.append('ليس لديك صلاحية لإضافة تقرير التفتيش.')
            if pirmet.status != 'inspection_pending':
                review_errors.append('هذا الطلب ليس في مرحلة إدخال تقرير التفتيش.')

            assigned_review = InspectorReview.objects.filter(pirmet=pirmet).select_related(
                'inspector', 'inspector_user'
            ).first()
            assigned_inspector_user = assigned_review.inspector_user if assigned_review else None
            if (
                not assigned_inspector_user
                or assigned_inspector_user.id != request.user.id
            ):
                review_errors.append('فقط المفتش الذي استلم الطلب يمكنه إدخال التقرير.')

            decision_raw = (request.POST.get('inspection_decision') or '').strip().lower()
            report_notes = (request.POST.get('inspection_report_notes') or '').strip()
            requirements_required = decision_raw == 'requirements_required'
            decision = 'approved' if decision_raw == 'approved' else decision_raw
            photos = request.FILES.getlist('inspection_report_photos')

            if decision_raw not in {'approved', 'requirements_required', 'rejected'}:
                review_errors.append('يرجى اختيار نتيجة التقرير.')
            if decision == 'rejected' and not report_notes:
                review_errors.append('يرجى كتابة ملاحظات سبب عدم الاعتماد.')
            invalid_photos = []
            for photo in photos:
                ext = os.path.splitext(photo.name)[1].lower()
                if ext not in {'.png', '.jpg', '.jpeg'}:
                    invalid_photos.append(photo.name)
            if invalid_photos:
                review_errors.append('يُسمح فقط برفع صور JPG/PNG لتقرير التفتيش.')

            if not review_errors:
                old_status = pirmet.status
                update_fields = ['status']
                if decision == 'approved':
                    pirmet.status = 'inspection_completed'
                    if pirmet.inspection_requires_insurance:
                        pirmet.inspection_requires_insurance = False
                        update_fields.append('inspection_requires_insurance')
                    if pirmet.unapprovedReason:
                        pirmet.unapprovedReason = None
                        update_fields.append('unapprovedReason')
                elif requirements_required:
                    pirmet.status = 'closed_requirements_pending'
                    if not pirmet.inspection_requires_insurance:
                        pirmet.inspection_requires_insurance = True
                        update_fields.append('inspection_requires_insurance')
                    if pirmet.unapprovedReason:
                        pirmet.unapprovedReason = None
                        update_fields.append('unapprovedReason')
                    if (pirmet.insurance_payment_order_number or '').strip():
                        pirmet.insurance_payment_order_number = None
                        update_fields.append('insurance_payment_order_number')
                    if pirmet.insurance_payment_receipt:
                        pirmet.insurance_payment_receipt = None
                        update_fields.append('insurance_payment_receipt')
                else:
                    pirmet.status = 'inspection_completed'
                    pirmet.unapprovedReason = report_notes or 'Inspection rejected.'
                    update_fields.append('unapprovedReason')
                    if pirmet.inspection_requires_insurance:
                        pirmet.inspection_requires_insurance = False
                        update_fields.append('inspection_requires_insurance')
                    if (pirmet.insurance_payment_order_number or '').strip():
                        pirmet.insurance_payment_order_number = None
                        update_fields.append('insurance_payment_order_number')
                    if pirmet.insurance_payment_receipt:
                        pirmet.insurance_payment_receipt = None
                        update_fields.append('insurance_payment_receipt')
                pirmet.save(update_fields=update_fields)
                _log_pirmet_change(
                    pirmet,
                    'status_change',
                    request.user,
                    old_status=old_status,
                    new_status=pirmet.status,
                    notes='Inspection report submitted.',
                )
                _log_pirmet_change(
                    pirmet,
                    'details_update',
                    request.user,
                    notes=f'inspection_report:{decision}',
                )
                if decision in {'approved', 'requirements_required'}:
                    requirements_note = 'yes' if requirements_required else 'no'
                    _log_pirmet_change(
                        pirmet,
                        'details_update',
                        request.user,
                        notes=f'inspection_requires_insurance:{requirements_note}',
                    )
                    if requirements_required:
                        _log_company_change(
                            pirmet.company,
                            'requirements_followup_needed',
                            request.user,
                            notes=(
                                'تم تفتيش الشركة وتسجيل اشتراطات واجبة الاستيفاء، '
                                'وتم إغلاق الطلب لحين إنشاء طلب تأمين استيفاء الشروط.'
                            ),
                        )
                if report_notes:
                    _log_pirmet_change(
                        pirmet,
                        'details_update',
                        request.user,
                        notes=f'inspection_report_notes:{report_notes}',
                    )
                if photos:
                    timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S%f')
                    for index, photo in enumerate(photos, start=1):
                        ext = os.path.splitext(photo.name)[1].lower() or '.jpg'
                        photo.name = (
                            f'{INSPECTION_REPORT_PHOTO_PREFIX}'
                            f'{pirmet.id}_{timestamp}_{index}{ext}'
                        )
                        PirmetDocument.objects.create(pirmet=pirmet, file=photo)
                    _log_pirmet_change(
                        pirmet,
                        'document_upload',
                        request.user,
                        notes=f'Inspection report photos uploaded: {len(photos)}',
                    )
                return redirect('pest_control_permit_detail', id=pirmet.id)

        if action == 'add_inspection_photos':
            if not can_add_inspection_photos:
                review_errors.append('ليس لديك صلاحية لإضافة صور التفتيش.')
            photos = request.FILES.getlist('inspection_report_photos_extra')
            if not photos:
                review_errors.append('يرجى اختيار صورة واحدة على الأقل.')
            invalid_photos = []
            for photo in photos:
                ext = os.path.splitext(photo.name)[1].lower()
                if ext not in {'.png', '.jpg', '.jpeg'}:
                    invalid_photos.append(photo.name)
            if invalid_photos:
                review_errors.append('يُسمح فقط برفع صور JPG/PNG: ' + ', '.join(invalid_photos))

            if not review_errors:
                timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S%f')
                for index, photo in enumerate(photos, start=1):
                    ext = os.path.splitext(photo.name)[1].lower() or '.jpg'
                    photo.name = (
                        f'{INSPECTION_REPORT_PHOTO_PREFIX}'
                        f'{pirmet.id}_{timestamp}_extra_{index}{ext}'
                    )
                    PirmetDocument.objects.create(pirmet=pirmet, file=photo)
                _log_pirmet_change(
                    pirmet,
                    'document_upload',
                    request.user,
                    notes=f'Inspection report photos uploaded: {len(photos)}',
                )
                return redirect('pest_control_permit_detail', id=pirmet.id)

        if action == 'delete_inspection_photo':
            if not can_manage_inspection_photos:
                review_errors.append('ليس لديك صلاحية لحذف صور التفتيش.')
            photo_id = _parse_int(request.POST.get('photo_id'))
            photo_doc = (
                PirmetDocument.objects.filter(id=photo_id, pirmet=pirmet).first()
                if photo_id
                else None
            )
            inspection_photo_ids = {doc.id for doc in _inspection_report_photo_docs(pirmet)}
            if not photo_doc:
                review_errors.append('الصورة غير موجودة.')
            elif photo_doc.id not in inspection_photo_ids:
                review_errors.append('لا يمكن حذف هذا الملف من هنا لأنه ليس صورة تفتيش.')

            if not review_errors and photo_doc:
                deleted_name = os.path.basename(photo_doc.file.name or '')
                if photo_doc.file:
                    photo_doc.file.delete(save=False)
                photo_doc.delete()
                _log_pirmet_change(
                    pirmet,
                    'details_update',
                    request.user,
                    notes=f'Inspection report photo deleted: {deleted_name}',
                )
                return redirect('pest_control_permit_detail', id=pirmet.id)

        if action == 'issue':
            if not _can_admin(request.user):
                review_errors.append('ليس لديك صلاحية لإصدار التصريح.')
            if pirmet.status != 'inspection_completed':
                review_errors.append('هذا الطلب ليس جاهزاً للإصدار. يجب إنهاء تقرير التفتيش أولاً.')
            if inspection_report_decision != 'approved':
                review_errors.append('لا يمكن إصدار التصريح قبل اعتماد تقرير التفتيش.')
            if violation_required and not violation_payment_completed:
                review_errors.append('يرجى استكمال سداد مخالفة التأخير قبل إصدار التصريح.')

            if not review_errors:
                old_status = pirmet.status
                pirmet.status = 'issued'
                pirmet.save(update_fields=['status'])
                _log_pirmet_change(
                    pirmet,
                    'status_change',
                    request.user,
                    old_status=old_status,
                    new_status=pirmet.status,
                    notes='Permit issued.',
                )
                return redirect('pest_control_permit_detail', id=pirmet.id)

        if action == 'update_permit_details':
            if not _can_admin(request.user):
                review_errors.append('ليس لديك صلاحية لتعديل بيانات التصريح.')
            if pirmet.status != 'issued':
                review_errors.append('لا يمكن تعديل البيانات إلا بعد إصدار التصريح.')

            issue_date = _parse_date(request.POST.get('issue_date'))
            expiry_date = _parse_date(request.POST.get('expiry_date'))
            if not review_errors:
                if issue_date:
                    pirmet.issue_date = issue_date
                if expiry_date:
                    pirmet.dateOfExpiry = expiry_date
                pirmet.save()
                _log_pirmet_change(
                    pirmet,
                    'details_update',
                    request.user,
                    notes='Permit dates updated.',
                )
                return redirect('pest_control_permit_detail', id=pirmet.id)

    changes = (
        PirmetChangeLog.objects.filter(pirmet=pirmet)
        .select_related('changed_by')
        .order_by('created_at')
    )
    status_changes = [
        change
        for change in changes
        if change.change_type in {'created', 'status_change', 'payment_update'}
    ]
    detail_changes = [
        change
        for change in changes
        if change.change_type in {'details_update', 'document_upload'}
    ]

    insurance_requests = list(
        RequirementInsuranceRequest.objects.filter(related_permit=pirmet).order_by('-id')
    )

    return render(
        request,
        'hcsd/pest_control_activity_permit_detail.html',
        {
            'pirmet': pirmet,
            'inspector_review': assigned_review,
            'insurance_requests': insurance_requests,
            'allowed_activities': _split_activities(pirmet.allowed_activities),
            'restricted_activities': _split_activities(pirmet.restricted_activities),
            'review_errors': review_errors,
            'status_changes': status_changes,
            'detail_changes': detail_changes,
            'inspection_receiver_name': inspection_receiver_name,
            'inspection_report_decision': inspection_report_decision,
            'inspection_report_by': inspection_report_by,
            'inspection_report_date': inspection_report_date,
            'inspection_report_notes': inspection_report_notes,
            'inspection_report_photos': _inspection_report_photo_docs(pirmet),
            'request_documents': _request_documents(pirmet),
            'assigned_inspector_name': assigned_inspector_name,
            'assigned_inspector_id': assigned_inspector_user.id if assigned_inspector_user else None,
            'can_receive_inspection_request': can_receive_inspection_request,
            'can_reassign_inspector': can_reassign_inspector,
            'can_submit_inspection_report': can_submit_inspection_report,
            'can_manage_inspection_photos': can_manage_inspection_photos,
            'can_add_inspection_photos': can_add_inspection_photos,
            'delay_months_after_grace': delay_months_after_grace,
            'delay_days_total': delay_days_total,
            'renewal_reference_date': renewal_reference_date,
            'violation_amount_due': violation_amount_due,
            'violation_required': violation_required,
            'violation_order_recorded': violation_order_recorded,
            'violation_receipt_recorded': violation_receipt_recorded,
            'violation_payment_completed': violation_payment_completed,
            'requirements_required': requirements_required,
            'can_record_violation_order': can_record_violation_order,
            'can_record_violation_receipt': can_record_violation_receipt,
            'can_record_inspection_payment_reference': can_record_inspection_payment_reference,
            'can_record_inspection_payment_receipt': can_record_inspection_payment_receipt,
            'can_head_approve': can_head_approve,
            'head_remarks': head_remarks,
            'head_approved_by': head_approved_by,
            'head_approved_date': head_approved_date,
            'can_record_permit_payment_reference': can_record_permit_payment_reference,
            'show_admin_close_form': show_admin_close_form,
            'can_review_pirmet': _can_inspector(request.user),
            'can_record_payment': _can_admin(request.user),
            'can_issue_pirmet': _can_admin(request.user),
            'can_update_pirmet': _can_admin(request.user),
            'inspector_users': _inspector_users_qs(),
        },
    )


@login_required
def pest_control_permit_print(request, id):
    pirmet = get_object_or_404(
        PirmetClearance.objects.select_related('company', 'company__enginer'),
        id=id,
        permit_type='pest_control',
    )
    return render(request, 'hcsd/pest_control_activity_permit_print.html', {
        'pirmet': pirmet,
        'allowed_activities': _split_activities(pirmet.allowed_activities),
        'restricted_activities': _split_activities(pirmet.restricted_activities),
    })


@login_required
def pest_control_permit_view(request, id):
    pirmet = get_object_or_404(
        PirmetClearance.objects.select_related('company', 'company__enginer').prefetch_related('documents'),
        id=id,
        permit_type='pest_control',
    )
    if pirmet.status not in {'payment_completed', 'issued'}:
        return redirect('pest_control_permit_detail', id=pirmet.id)

    return render(
        request,
        'hcsd/pest_control_activity_permit_view.html',
        {
            'pirmet': pirmet,
            'allowed_activities': _split_activities(pirmet.allowed_activities),
            'restricted_activities': _split_activities(pirmet.restricted_activities),
        },
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
        .filter(company=company, permit_type='waste_disposal', status__in=['issued', 'disposal_approved', 'payment_completed'])
        .order_by('-issue_date', '-id')
        .first()
    )
    # Fall back to the requested permit if no issued one exists
    if permit is None:
        permit = get_object_or_404(
            PirmetClearance.objects.select_related('company', 'waste_details'),
            id=permit_id,
            permit_type='waste_disposal',
            status__in=['payment_completed', 'issued'],
        )

    waste = getattr(permit, 'waste_details', None)
    return render(request, 'hcsd/waste_disposal_permit_print.html', {
        'permit': permit,
        'waste': waste,
    })


@login_required
def printer(request, permit_id=None):
    requested_id = permit_id or _parse_int(request.GET.get('permit_id'))
    permits_qs = PirmetClearance.objects.select_related('company', 'company__enginer').filter(
        permit_type='pest_control',
        status__in=['payment_completed', 'issued'],
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
