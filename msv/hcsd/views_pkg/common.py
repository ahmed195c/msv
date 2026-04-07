import calendar
import datetime
import os

from django.contrib.auth.models import Group, User
from django.utils import timezone
from django.db.models import Q
from django.urls import reverse

from ..models import (
    Company, CompanyChangeLog, EngineerCertificateRequest, EngineerLeave,
    Enginer, EnginerStatusLog, InspectorReview, PesticideTransportPermit,
    PirmetChangeLog, PirmetClearance, PirmetDocument, PublicHealthExamRequest,
    PublicHealthExamRequestDocument, RequirementInsuranceRequest,
    WasteDisposalRequest, WasteDisposalRequestDocument,
)

ALLOWED_DOC_EXTENSIONS = {'.pdf', '.png', '.jpg', '.jpeg'}
PEST_ACTIVITY_ORDER = ['public_health_pest_control', 'termite_control', 'grain_pests']
PEST_ACTIVITY_KEYS = set(PEST_ACTIVITY_ORDER)
PUBLIC_HEALTH_ACTIVITY_KEYS = ['public_health_pest_control', 'grain_pests']
GROUP_NAME_ALIASES = {
    'admin': ['admin', 'Administration'],
    'inspector': ['inspector', 'Inspector'],
    'data_entry': ['data_entry', 'Data Entry'],
    'head': ['head', 'Head'],
}
ROLE_CAPABILITIES = {
    'admin': {'admin', 'inspect', 'data_entry', 'head_approve'},
    'inspector': {'inspect'},
    'data_entry': {'data_entry'},
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
            status='issued',
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


def _certificate_expiry(issue_date, stored_expiry_date=None):
    if stored_expiry_date:
        return stored_expiry_date, stored_expiry_date < timezone.localdate()
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
        permit.status == 'issued'
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

