import datetime
import os

from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group, User
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from .models import (
    Company,
    CompanyChangeLog,
    Enginer,
    EnginerStatusLog,
    InspectorReview,
    PesticideTransportPermit,
    PirmetChangeLog,
    PirmetClearance,
    PirmetDocument,
    WasteDisposalRequest,
)
from .forms import StaffRegistrationForm

ALLOWED_DOC_EXTENSIONS = {'.pdf', '.png', '.jpg', '.jpeg'}
PEST_ACTIVITY_ORDER = [
    'public_health_pest_control',
    'termite_control',
    'grain_pests',
]
PEST_ACTIVITY_KEYS = set(PEST_ACTIVITY_ORDER)
GROUP_NAME_ALIASES = {
    'admin': ['admin', 'Administration'],
    'inspector': ['inspector', 'Inspector'],
    'data_entry': ['data_entry', 'Data Entry'],
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
    day = min(
        value.day,
        [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1],
    )
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
    if not enginer:
        return []
    activities = []
    if enginer.public_health_cert:
        activities.append('public_health_pest_control')
    if enginer.termite_cert and 'termite_control' not in activities:
        activities.append('termite_control')
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


def _can_admin(user):
    return user.is_authenticated and (
        user.is_superuser
        or user.is_staff
        or _has_any_group(user, GROUP_NAME_ALIASES['admin'])
    )


def _can_inspector(user):
    return user.is_authenticated and (
        _can_admin(user)
        or _has_any_group(user, GROUP_NAME_ALIASES['inspector'])
    )


def _can_data_entry(user):
    return user.is_authenticated and (
        _can_admin(user)
        or _has_any_group(user, GROUP_NAME_ALIASES['data_entry'])
    )


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
    if decision in {'approved', 'rejected'}:
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


def _log_pirmet_change(pirmet, change_type, user, old_status=None, new_status=None, notes=''):
    PirmetChangeLog.objects.create(
        pirmet=pirmet,
        change_type=change_type,
        old_status=old_status,
        new_status=new_status,
        notes=notes,
        changed_by=user if user and user.is_authenticated else None,
    )


def _log_company_change(company, action, user, notes='', attachment=None):
    CompanyChangeLog.objects.create(
        company=company,
        action=action,
        notes=notes,
        changed_by=user if user and user.is_authenticated else None,
        attachment=attachment,
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


def home(request):
    latest_pirmet = (
        PirmetClearance.objects.filter(permit_type__in=['pest_control', 'pesticide_transport', 'waste_disposal'])
        .select_related('company')
        .order_by('-dateOfCreation')[:8]
    )
    for permit in latest_pirmet:
        permit.permit_label_ar = _permit_label_ar(permit.permit_type)
        permit.detail_url_name = _permit_detail_url_name(permit.permit_type)
    return render(request, 'hcsd/base.html', {'latest_pirmet': latest_pirmet, 'show_latest': True})


@login_required
def company_list(request):
    query = (request.GET.get('q') or '').strip()
    status_filter = (request.GET.get('status') or 'all').strip()
    today = datetime.date.today()

    companies = Company.objects.all()
    if query:
        companies = companies.filter(Q(name__icontains=query) | Q(number__icontains=query))
    companies = list(companies)

    rows = []
    for company in companies:
        latest_issued_permit = (
            PirmetClearance.objects.filter(
                company=company,
                permit_type='pest_control',
                status__in=['issued', 'payment_completed'],
            )
            .order_by('-dateOfCreation')
            .first()
        )
        latest_permit_any = (
            PirmetClearance.objects.filter(company=company, permit_type='pest_control')
            .order_by('-dateOfCreation')
            .first()
        )
        has_expired_permit = PirmetClearance.objects.filter(
            company=company,
            permit_type__in=['pest_control', 'pesticide_transport'],
            status__in=['issued', 'payment_completed'],
            dateOfExpiry__isnull=False,
            dateOfExpiry__lt=today,
        ).exists()
        activity_keys = _activity_keys_for_company(company, latest_issued_permit)

        latest_extension = (
            CompanyChangeLog.objects.filter(company=company, action='extension_requested')
            .order_by('-created_at')
            .first()
        )
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

    # Default ordering: closest expiry first (activity expiry, then trade license expiry).
    rows.sort(
        key=lambda row: (
            row['effective_expiry'] is None,
            row['effective_expiry'] or datetime.date.max,
            row['trade_expiry'] is None,
            row['trade_expiry'] or datetime.date.max,
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
        if action == 'request_extension':
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

    permits = (
        PirmetClearance.objects.filter(
            company=company,
            permit_type__in=['pest_control', 'pesticide_transport', 'waste_disposal'],
        )
        .order_by('-dateOfCreation')
    )
    latest_permits = {}
    for permit in permits:
        permit.permit_label_ar = _permit_label_ar(permit.permit_type)
        permit.detail_url_name = _permit_detail_url_name(permit.permit_type)
        if permit.permit_type not in latest_permits:
            latest_permits[permit.permit_type] = permit

    logs = company.change_logs.all().order_by('-created_at')
    latest_extension = company.change_logs.filter(action='extension_requested').order_by('-created_at').first()
    if latest_extension and latest_extension.extension_end_date:
        days_left = (latest_extension.extension_end_date - datetime.date.today()).days
        if 0 <= days_left <= 7:
            extension_notice = f'تنبيه: تنتهي المهلة الحالية بتاريخ {latest_extension.extension_end_date:%Y-%m-%d} (بعد {days_left} يوم).'
        elif days_left < 0:
            extension_notice = f'تنبيه: انتهت المهلة الحالية بتاريخ {latest_extension.extension_end_date:%Y-%m-%d}.'

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
            'logs': logs,
            'latest_pest_permit': latest_permits.get('pest_control'),
            'latest_vehicle_permit': latest_permits.get('pesticide_transport'),
            'latest_waste_permit': latest_permits.get('waste_disposal'),
            'company_permits': permits,
        },
    )


@login_required
def enginer_list(request):
    engineers = Enginer.objects.all().order_by('name')
    return render(
        request,
        'hcsd/enginer_list.html',
        {
            'engineers': engineers,
            'can_add_enginer': _can_data_entry(request.user),
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
            elif not public_health_cert:
                error = 'يرجى إرفاق شهادة الصحة العامة.'

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
    if request.method == 'POST':
        if not _can_data_entry(request.user):
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

    logs = enginer.status_logs.select_related('changed_by').all().order_by('-created_at')
    archived_logs = [log for log in logs if getattr(log, 'archived_file', None)]
    return render(
        request,
        'hcsd/enginer_detail.html',
        {
            'enginer': enginer,
            'can_update_enginer': _can_data_entry(request.user),
            'error': error,
            'logs': logs,
            'archived_logs': archived_logs,
        },
    )


@login_required
def clearance_list(request):
    clearances = (
        PirmetClearance.objects.filter(permit_type__in=['pest_control', 'pesticide_transport', 'waste_disposal'])
        .select_related('company')
        .order_by('-dateOfCreation')
    )
    reviews = InspectorReview.objects.filter(pirmet__in=clearances).select_related('inspector', 'inspector_user')
    review_map = {review.pirmet_id: review for review in reviews}
    inspection_receive_changes = (
        PirmetChangeLog.objects.filter(
            pirmet__in=clearances,
            change_type='details_update',
            notes__startswith='inspection_received_by:',
        )
        .order_by('pirmet_id', '-created_at')
    )
    inspection_report_changes = (
        PirmetChangeLog.objects.filter(
            pirmet__in=clearances,
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
    for clearance in clearances:
        clearance.permit_label_ar = _permit_label_ar(clearance.permit_type)
        clearance.detail_url_name = _permit_detail_url_name(clearance.permit_type)
        review = review_map.get(clearance.id)
        clearance.inspector_name = _inspector_review_name(review)
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
        report_change = inspection_report_map.get(clearance.id)
        clearance.inspection_report_decision = (
            _inspection_report_decision_from_note(report_change.notes)
            if report_change
            else None
        )

    return render(
        request,
        'hcsd/clearance_list.html',
        {
            'clearances': clearances,
            'can_create_pirmet': _can_data_entry(request.user),
            'form_errors': [],
        },
    )


def permit_types(request):
    return render(request, 'hcsd/permit_types.html')


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
    can_submit_inspection_report = (
        _can_inspector(request.user)
        and pirmet.status == 'inspection_pending'
        and (
            not assigned_inspector_user
            or assigned_inspector_user.id == request.user.id
        )
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

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'receive_for_inspection':
            if not _can_inspector(request.user):
                review_errors.append('ليس لديك صلاحية لاستلام الطلب للتفتيش.')
            if pirmet.status != 'inspection_pending':
                review_errors.append('هذا الطلب ليس في مرحلة التفتيش.')

            inspector_id = _parse_int(request.POST.get('inspector_id'))
            inspector_user = (
                _inspector_users_qs().filter(id=inspector_id).first()
                if inspector_id
                else None
            )
            if not inspector_user:
                review_errors.append('يرجى اختيار مفتش صحيح.')

            if not review_errors:
                InspectorReview.objects.update_or_create(
                    pirmet=pirmet,
                    defaults={
                        'inspector': None,
                        'inspector_user': inspector_user,
                        'isApproved': False,
                        'comments': 'تم استلام الطلب للتفتيش.',
                    },
                )
                _log_pirmet_change(
                    pirmet,
                    'details_update',
                    request.user,
                    notes=f'inspection_received_by:{_display_user_name(inspector_user)}',
                )
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
                    pirmet.status = 'payment_pending'
                    if pirmet.unapprovedReason:
                        pirmet.unapprovedReason = None
                    pirmet.save(update_fields=['status', 'unapprovedReason'])
                else:
                    pirmet.status = 'needs_completion'
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
            if pirmet.status != 'payment_pending':
                review_errors.append('هذا الطلب ليس بانتظار إدخال رقم دفع التصريح.')
            payment_number = (request.POST.get('payment_number') or '').strip()
            if not payment_number:
                review_errors.append('يرجى إدخال رقم أمر دفع تصريح المركبة.')

            if not review_errors:
                pirmet.PaymentNumber = payment_number
                pirmet.save(update_fields=['PaymentNumber'])
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
                pirmet.status = 'payment_completed'
                pirmet.save()
                _log_pirmet_change(
                    pirmet,
                    'status_change',
                    request.user,
                    old_status=old_status,
                    new_status=pirmet.status,
                    notes='Vehicle permit payment received.',
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
            'inspection_report_notes': inspection_report_notes,
            'inspection_report_photos': _vehicle_inspection_report_photo_docs(pirmet),
            'inspection_receiver_name': inspection_receiver_name,
            'can_review_pirmet': _can_inspector(request.user),
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
        PirmetClearance.objects.select_related('company').prefetch_related('documents', 'waste_disposal_requests'),
        id=id,
        permit_type='waste_disposal',
    )
    review_errors = []
    today = datetime.date.today()
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
                pirmet.status = 'payment_completed'
                pirmet.save()
                _log_pirmet_change(
                    pirmet,
                    'status_change',
                    request.user,
                    old_status=old_status,
                    new_status=pirmet.status,
                    notes='Waste permit payment received.',
                )
                _log_company_change(
                    pirmet.company,
                    'waste_permit_paid',
                    request.user,
                    notes=f'تم تأكيد دفع تصريح التخلص #{pirmet.permit_no}.',
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

    disposal_requests = pirmet.waste_disposal_requests.select_related('inspected_by').order_by('-created_at')
    return render(
        request,
        'hcsd/waste_permit_detail.html',
        {
            'pirmet': pirmet,
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
    if permit.status != 'issued' or not permit.dateOfExpiry or permit.dateOfExpiry < today:
        return redirect('waste_permit_detail', id=permit.id)

    if request_id is None:
        if not _can_data_entry(request.user):
            return redirect('waste_permit_detail', id=permit.id)
        disposal_request = WasteDisposalRequest.objects.create(permit=permit, status='payment_pending')
        _log_company_change(
            permit.company,
            'waste_request_created',
            request.user,
            notes=f'تم إنشاء طلب التخلص رقم {disposal_request.id} للتصريح #{permit.permit_no}.',
        )
        return redirect('waste_disposal_request_detail', permit_id=permit.id, request_id=disposal_request.id)

    disposal_request = get_object_or_404(
        WasteDisposalRequest.objects.select_related('permit', 'permit__company', 'inspected_by'),
        id=request_id,
        permit=permit,
    )
    review_errors = []

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'send_payment_link':
            if not _can_admin(request.user):
                review_errors.append('ليس لديك صلاحية لإدخال رقم الدفع.')
            if disposal_request.status != 'payment_pending':
                review_errors.append('الطلب ليس بانتظار الدفع.')
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
                disposal_request.disposal_payment_receipt = receipt
                disposal_request.status = 'inspection_pending'
                disposal_request.save(update_fields=['disposal_payment_receipt', 'status'])
                _log_pirmet_change(
                    permit,
                    'status_change',
                    request.user,
                    notes=f'waste_disposal_payment_received:{disposal_request.id}',
                )
                _log_company_change(
                    permit.company,
                    'waste_request_paid',
                    request.user,
                    notes=f'تم تأكيد دفع طلب التخلص رقم {disposal_request.id}.',
                )
                return redirect('waste_disposal_request_detail', permit_id=permit.id, request_id=disposal_request.id)

        if action == 'submit_inspection_report':
            if not _can_inspector(request.user):
                review_errors.append('ليس لديك صلاحية لإضافة تقرير التفتيش.')
            if disposal_request.status != 'inspection_pending':
                review_errors.append('الطلب ليس في مرحلة التفتيش.')
            decision = (request.POST.get('inspection_decision') or '').strip().lower()
            notes = (request.POST.get('inspection_notes') or '').strip()
            if decision not in {'approved', 'rejected'}:
                review_errors.append('يرجى اختيار نتيجة التقرير.')
            if decision == 'rejected' and not notes:
                review_errors.append('يرجى كتابة سبب الرفض.')
            if not review_errors:
                if decision == 'approved':
                    disposal_request.status = 'completed'
                else:
                    disposal_request.status = 'rejected'
                disposal_request.inspection_notes = notes or None
                disposal_request.inspected_by = request.user
                disposal_request.save(update_fields=['status', 'inspection_notes', 'inspected_by', 'updated_at'])
                _log_pirmet_change(
                    permit,
                    'details_update',
                    request.user,
                    notes=f'waste_disposal_inspection:{disposal_request.id}:{decision}',
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
            'review_errors': review_errors,
            'can_record_payment': _can_admin(request.user),
            'can_review_request': _can_inspector(request.user),
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
    engineer_notice = ''

    if request.method == 'POST':
        company_id = _parse_int(request.POST.get('company_id'))
        company = (
            Company.objects.select_related('enginer').filter(id=company_id).first()
            if company_id
            else None
        )
        if company_id and not company:
            form_errors.append('company_select_invalid')

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
        if company:
            enginer = company.enginer
            if not enginer:
                if can_submit_without_engineer:
                    engineer_notice = 'تنبيه: هذه الشركة بدون مهندس حالياً. يمكن تقديم الطلب واستكمال بيانات المهندس بعد التفتيش/الاستكمال.'
                else:
                    form_errors.append('company_engineer_missing')
            else:
                changed_fields = []
                if form_data['engineer_name'] and enginer.name != form_data['engineer_name']:
                    enginer.name = form_data['engineer_name']
                    changed_fields.append('name')
                if form_data['engineer_email'] and enginer.email != form_data['engineer_email']:
                    enginer.email = form_data['engineer_email']
                    changed_fields.append('email')
                if form_data['engineer_phone'] and enginer.phone != form_data['engineer_phone']:
                    enginer.phone = form_data['engineer_phone']
                    changed_fields.append('phone')
                if changed_fields:
                    enginer.save(update_fields=changed_fields)
                if not enginer.public_health_cert:
                    form_errors.append('engineer_cert_required')
        else:
            if form_data['engineer_name'] or form_data['engineer_email'] or form_data['engineer_phone']:
                if not (form_data['engineer_name'] and form_data['engineer_email'] and form_data['engineer_phone']):
                    form_errors.append('engineer_required')
                else:
                    enginer = Enginer.objects.filter(email=form_data['engineer_email']).first()
                    if not enginer:
                        form_errors.append('engineer_not_registered')
                    else:
                        if enginer.name != form_data['engineer_name']:
                            enginer.name = form_data['engineer_name']
                        if enginer.phone != form_data['engineer_phone']:
                            enginer.phone = form_data['engineer_phone']
                        if enginer.name != form_data['engineer_name'] or enginer.phone != form_data['engineer_phone']:
                            enginer.save(update_fields=['name', 'phone'])
                        if not enginer.public_health_cert:
                            form_errors.append('engineer_cert_required')
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

            permit = PirmetClearance.objects.create(
                company=company,
                dateOfExpiry=expiry_date,
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
    inspection_report_by = (
        _display_user_name(latest_inspection_report.changed_by)
        if latest_inspection_report and latest_inspection_report.changed_by
        else None
    )
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

    assigned_review = InspectorReview.objects.filter(pirmet=pirmet).select_related(
        'inspector', 'inspector_user'
    ).first()
    assigned_inspector_user = assigned_review.inspector_user if assigned_review else None
    can_submit_inspection_report = (
        _can_inspector(request.user)
        and pirmet.status == 'inspection_pending'
        and (
            not assigned_inspector_user
            or assigned_inspector_user.id == request.user.id
        )
    )
    can_manage_inspection_photos = (
        pirmet.status in {'inspection_pending', 'inspection_completed'}
        and (
            _can_admin(request.user)
            or (
                _can_inspector(request.user)
                and (
                    not assigned_inspector_user
                    or assigned_inspector_user.id == request.user.id
                )
            )
        )
    )
    review_errors = []

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'complete_missing':
            if not (_can_inspector(request.user) or _can_data_entry(request.user)):
                review_errors.append('ليس لديك صلاحية لتحويل الطلب لإعادة التفتيش.')
            if pirmet.status != 'needs_completion':
                review_errors.append('هذا الطلب ليس بحاجة لاستكمال نواقص.')

            notes = (request.POST.get('completion_notes') or '').strip()
            documents = request.FILES.getlist('documents')
            invalid_docs = [
                doc.name
                for doc in documents
                if os.path.splitext(doc.name)[1].lower() not in ALLOWED_DOC_EXTENSIONS
            ]
            if invalid_docs:
                review_errors.append('يُسمح فقط بملفات PDF أو صور: ' + ', '.join(invalid_docs))
            if not documents and not notes:
                review_errors.append('يرجى إضافة مستندات أو كتابة توضيح للنواقص المستكملة.')

            if not review_errors:
                if documents:
                    for doc in documents:
                        PirmetDocument.objects.create(pirmet=pirmet, file=doc)
                    _log_pirmet_change(
                        pirmet,
                        'document_upload',
                        request.user,
                        notes=f'Documents uploaded: {len(documents)}',
                    )
                if notes:
                    _log_pirmet_change(pirmet, 'details_update', request.user, notes=notes)

                old_status = pirmet.status
                pirmet.status = 'inspection_pending'
                pirmet.save(update_fields=['status'])
                _log_pirmet_change(
                    pirmet,
                    'status_change',
                    request.user,
                    old_status=old_status,
                    new_status=pirmet.status,
                    notes='Request moved to re-inspection after completion.',
                )
                return redirect('pest_control_permit_detail', id=pirmet.id)

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

        if action in {'approve', 'needs_completion'}:
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
            if action == 'needs_completion' and not remarks:
                review_errors.append('يرجى كتابة النواقص المطلوبة.')

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
                    pirmet.status = 'needs_completion'
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

        if action == 'send_payment_link':
            if not _can_admin(request.user):
                review_errors.append('ليس لديك صلاحية لإدخال الرقم المرجعي للدفع.')
            if pirmet.status != 'inspection_completed':
                review_errors.append('هذا الطلب ليس في مرحلة إدخال رقم دفع التصريح.')

            latest_inspection_report = (
                PirmetChangeLog.objects.filter(
                    pirmet=pirmet,
                    change_type='details_update',
                    notes__startswith='inspection_report:',
                )
                .order_by('-created_at')
                .first()
            )
            inspection_decision = (
                _inspection_report_decision_from_note(latest_inspection_report.notes)
                if latest_inspection_report
                else None
            )
            if inspection_decision != 'approved':
                review_errors.append('لا يمكن إدخال رقم الدفع قبل اعتماد تقرير التفتيش.')

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
                pirmet.status = 'payment_completed'
                pirmet.save()
                _log_pirmet_change(
                    pirmet,
                    'status_change',
                    request.user,
                    old_status=old_status,
                    new_status=pirmet.status,
                    notes='Payment received.',
                )
                return redirect('pest_control_permit_detail', id=pirmet.id)

        if action == 'receive_for_inspection':
            if not _can_inspector(request.user):
                review_errors.append('ليس لديك صلاحية لاستلام الطلب للتفتيش.')
            if pirmet.status != 'inspection_pending':
                review_errors.append('هذا الطلب ليس في مرحلة التفتيش.')

            inspector_id = _parse_int(request.POST.get('inspector_id'))
            inspector_user = (
                _inspector_users_qs().filter(id=inspector_id).first()
                if inspector_id
                else None
            )
            if not inspector_user:
                review_errors.append('يرجى اختيار مفتش صحيح.')

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
                if review_errors:
                    pass
                else:
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
                assigned_inspector_user
                and assigned_inspector_user.id != request.user.id
            ):
                review_errors.append('فقط المفتش الذي استلم الطلب يمكنه إدخال التقرير.')

            decision = (request.POST.get('inspection_decision') or '').strip().lower()
            report_notes = (request.POST.get('inspection_report_notes') or '').strip()
            photos = request.FILES.getlist('inspection_report_photos')

            if decision not in {'approved', 'rejected'}:
                review_errors.append('يرجى اختيار نتيجة التقرير (معتمد أو غير معتمد).')
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
                    if pirmet.unapprovedReason:
                        pirmet.unapprovedReason = None
                        update_fields.append('unapprovedReason')
                else:
                    pirmet.status = 'needs_completion'
                    pirmet.unapprovedReason = report_notes or 'Inspection rejected.'
                    update_fields.append('unapprovedReason')
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
            if not can_manage_inspection_photos:
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
            if not photo_doc:
                review_errors.append('الصورة غير موجودة.')
            elif INSPECTION_REPORT_PHOTO_PREFIX not in (photo_doc.file.name or ''):
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
            latest_inspection_report = (
                PirmetChangeLog.objects.filter(
                    pirmet=pirmet,
                    change_type='details_update',
                    notes__startswith='inspection_report:',
                )
                .order_by('-created_at')
                .first()
            )
            inspection_decision = (
                _inspection_report_decision_from_note(latest_inspection_report.notes)
                if latest_inspection_report
                else None
            )
            if inspection_decision != 'approved':
                review_errors.append('لا يمكن إصدار التصريح قبل اعتماد تقرير التفتيش.')

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
            if pirmet.status not in {'payment_completed', 'issued'}:
                review_errors.append('لا يمكن تعديل البيانات قبل اكتمال الدفع.')

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

    return render(
        request,
        'hcsd/pest_control_activity_permit_detail.html',
        {
            'pirmet': pirmet,
            'inspector_review': InspectorReview.objects.filter(pirmet=pirmet).select_related('inspector', 'inspector_user').first(),
            'allowed_activities': _split_activities(pirmet.allowed_activities),
            'restricted_activities': _split_activities(pirmet.restricted_activities),
            'review_errors': review_errors,
            'status_changes': status_changes,
            'detail_changes': detail_changes,
            'inspection_receiver_name': inspection_receiver_name,
            'inspection_report_decision': inspection_report_decision,
            'inspection_report_by': inspection_report_by,
            'inspection_report_notes': inspection_report_notes,
            'inspection_report_photos': _inspection_report_photo_docs(pirmet),
            'request_documents': _request_documents(pirmet),
            'can_submit_inspection_report': can_submit_inspection_report,
            'can_manage_inspection_photos': can_manage_inspection_photos,
            'can_review_pirmet': _can_inspector(request.user),
            'can_complete_missing': (_can_inspector(request.user) or _can_data_entry(request.user)),
            'can_record_payment': _can_admin(request.user),
            'can_issue_pirmet': _can_admin(request.user),
            'can_update_pirmet': _can_admin(request.user),
            'inspector_users': _inspector_users_qs(),
        },
    )


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


def register(request):
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
            login(request, user)
            return redirect('home')
    else:
        form = StaffRegistrationForm()

    return render(request, 'hcsd/register.html', {'form': form})


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
