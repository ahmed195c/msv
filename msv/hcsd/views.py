import datetime
import os

from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import Group, User
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from .models import (
    Company,
    CompanyChangeLog,
    Enginer,
    EnginerStatusLog,
    InspectorReview,
    PirmetChangeLog,
    PirmetClearance,
    PirmetDocument,
)

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


def _parse_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
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


def _activities_for_enginer(enginer):
    if not enginer:
        return []
    activities = []
    if enginer.public_health_cert:
        activities.extend(
            [
                'public_health_pest_control',
                'grain_pests',
            ]
        )
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


def _inspection_report_photo_count_from_note(note):
    prefix = 'Inspection report photos uploaded:'
    if not note or not note.startswith(prefix):
        return 0
    try:
        return int(note.split(':', 1)[1].strip())
    except (TypeError, ValueError):
        return 0


def _inspection_report_photo_docs(pirmet):
    # Prefer explicitly tagged photo filenames used by the current workflow.
    named_photos = list(
        PirmetDocument.objects.filter(
            pirmet=pirmet,
            file__icontains=INSPECTION_REPORT_PHOTO_PREFIX,
        ).order_by('uploadedAt')
    )
    if named_photos:
        return named_photos

    # Backward-compatible fallback for old records uploaded before tagging.
    latest_photo_log = (
        PirmetChangeLog.objects.filter(
            pirmet=pirmet,
            change_type='document_upload',
            notes__startswith='Inspection report photos uploaded:',
        )
        .order_by('-created_at')
        .first()
    )
    if not latest_photo_log:
        return []

    expected_count = _inspection_report_photo_count_from_note(latest_photo_log.notes)
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


def home(request):
    latest_pirmet = (
        PirmetClearance.objects.filter(permit_type='pest_control')
        .select_related('company')
        .order_by('-dateOfCreation')[:8]
    )
    return render(request, 'hcsd/base.html', {'latest_pirmet': latest_pirmet, 'show_latest': True})


@login_required
def company_list(request):
    query = (request.GET.get('q') or '').strip()
    activity_filter = (request.GET.get('activity') or 'all').strip()
    sort = (request.GET.get('sort') or 'name_asc').strip()

    companies = Company.objects.all()
    if query:
        companies = companies.filter(Q(name__icontains=query) | Q(number__icontains=query))
    companies = list(companies)

    rows = []
    for company in companies:
        permit = (
            PirmetClearance.objects.filter(
                company=company,
                permit_type='pest_control',
                status='issued',
            )
            .order_by('-issue_date', '-dateOfCreation')
            .first()
        )
        activity_keys = _activity_keys_for_company(company, permit)
        last_issued = None
        if permit:
            last_issued = permit.issue_date or permit.dateOfCreation
        rows.append(
            {
                'company': company,
                'activity_keys': activity_keys,
                'last_issued': last_issued,
            }
        )

    if activity_filter != 'all':
        rows = [row for row in rows if activity_filter in row['activity_keys']]

    if sort == 'name_desc':
        rows.sort(key=lambda row: (row['company'].name or ''), reverse=True)
    elif sort == 'number_asc':
        rows.sort(key=lambda row: (row['company'].number or ''))
    elif sort == 'number_desc':
        rows.sort(key=lambda row: (row['company'].number or ''), reverse=True)
    elif sort == 'last_issued_asc':
        rows.sort(key=lambda row: row['last_issued'] or datetime.date.min)
    elif sort == 'last_issued_desc':
        rows.sort(key=lambda row: row['last_issued'] or datetime.date.min, reverse=True)
    else:
        rows.sort(key=lambda row: (row['company'].name or ''))

    return render(
        request,
        'hcsd/companyes_info.html',
        {
            'company_rows': rows,
            'query': query,
            'activity_filter': activity_filter,
            'sort': sort,
            'can_add_company': _can_data_entry(request.user),
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
        }

        if not _can_data_entry(request.user):
            error = 'ليس لديك صلاحية لإضافة الشركات.'
        elif not name or not number or not address:
            error = 'يرجى إدخال اسم الشركة ورقم الرخصة والعنوان.'
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

        if not error and enginer:
            if pest_control_type == 'termite_control' and not enginer.termite_cert:
                error = 'المهندس المختار لا يملك شهادة النمل الأبيض.'
            elif pest_control_type != 'termite_control' and not enginer.public_health_cert:
                error = 'المهندس المختار لا يملك شهادة صحة عامة.'

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
            _log_company_change(company, 'created', request.user, notes='Company created.')
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
                if not extension_type:
                    extension_error = 'يرجى إدخال نوع المهلة.'
                elif not extension_document:
                    extension_error = 'يرجى إرفاق مستند المهلة.'
                else:
                    _log_company_change(
                        company,
                        'extension_requested',
                        request.user,
                        notes=extension_type,
                        attachment=extension_document,
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

                if not error and enginer:
                    if pest_control_type == 'termite_control' and not enginer.termite_cert:
                        error = 'المهندس المختار لا يملك شهادة النمل الأبيض.'
                    elif pest_control_type != 'termite_control' and not enginer.public_health_cert:
                        error = 'المهندس المختار لا يملك شهادة صحة عامة.'

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

                    _log_company_change(company, 'updated', request.user, notes='Company updated.')
                    if 'engineer_changed' in changes:
                        _log_company_change(company, 'engineer_changed', request.user, notes='Engineer changed.')
                    return redirect('company_detail', id=company.id)

    permits = (
        PirmetClearance.objects.filter(company=company, permit_type='pest_control')
        .order_by('-dateOfCreation')
    )
    latest_permit = permits.first()

    logs = company.change_logs.all().order_by('-created_at')

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
            'can_edit_company': can_edit_company,
            'can_request_extension': can_request_extension,
            'logs': logs,
            'latest_permit': latest_permit,
            'company_permits': permits,
        },
    )


@login_required
def enginer_list(request):
    engineers = Enginer.objects.all().order_by('name')
    error = ''
    form_data = {}
    if request.method == 'POST':
        if not _can_data_entry(request.user):
            error = 'ليس لديك صلاحية لإضافة مهندسين.'
        else:
            name = (request.POST.get('name') or '').strip()
            email = (request.POST.get('email') or '').strip()
            phone = (request.POST.get('phone') or '').strip()
            public_health_cert = request.FILES.get('public_health_cert')
            termite_cert = request.FILES.get('termite_cert')

            form_data = {'name': name, 'email': email, 'phone': phone}
            if not name or not email or not phone:
                error = 'يرجى إدخال بيانات المهندس كاملة.'
            elif not public_health_cert:
                error = 'يرجى إرفاق شهادة الصحة العامة.'

            if not error:
                enginer = Enginer.objects.create(
                    name=name,
                    email=email,
                    phone=phone,
                    public_health_cert=public_health_cert,
                    termite_cert=termite_cert,
                )
                EnginerStatusLog.objects.create(
                    enginer=enginer,
                    action='created',
                    notes='Engineer created.',
                )
                EnginerStatusLog.objects.create(
                    enginer=enginer,
                    action='public_health_cert_uploaded',
                    notes='Public health certificate uploaded.',
                )
                if termite_cert:
                    EnginerStatusLog.objects.create(
                        enginer=enginer,
                        action='termite_cert_uploaded',
                        notes='Termite certificate uploaded.',
                    )
                return redirect('enginer_list')

    return render(
        request,
        'hcsd/enginer_list.html',
        {
            'engineers': engineers,
            'can_add_enginer': _can_data_entry(request.user),
            'error': error,
            'form_data': form_data,
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
                enginer.public_health_cert = public_health_cert
                EnginerStatusLog.objects.create(
                    enginer=enginer,
                    action='public_health_cert_uploaded',
                    notes='Public health certificate updated.',
                )
                updated = True
            if termite_cert:
                enginer.termite_cert = termite_cert
                EnginerStatusLog.objects.create(
                    enginer=enginer,
                    action='termite_cert_uploaded',
                    notes='Termite certificate updated.',
                )
                updated = True
            if updated:
                enginer.save()
                return redirect('enginer_detail', id=enginer.id)
            error = 'يرجى إرفاق ملف واحد على الأقل.'

    logs = enginer.status_logs.all().order_by('-created_at')
    return render(
        request,
        'hcsd/enginer_detail.html',
        {
            'enginer': enginer,
            'can_update_enginer': _can_data_entry(request.user),
            'error': error,
            'logs': logs,
        },
    )


@login_required
def clearance_list(request):
    clearances = (
        PirmetClearance.objects.filter(permit_type='pest_control')
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
        review = review_map.get(clearance.id)
        clearance.inspector_name = _inspector_review_name(review)
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
                'request_email': (request.POST.get('request_email') or '').strip(),
                'allowed_other': (request.POST.get('allowed_other') or '').strip(),
                'restricted_other': (request.POST.get('restricted_other') or '').strip(),
            }
        )

        business_activity_text = ''
        if company:
            business_activity_text = company.business_activity or ''
            form_data.update(
                {
                    'company_name': company.name,
                    'trade_license_no': company.number,
                    'trade_license_exp': (
                        company.trade_license_exp.isoformat()
                        if company.trade_license_exp
                        else ''
                    ),
                    'company_address': company.address,
                    'landline': company.landline or '',
                    'owner_phone': company.owner_phone or '',
                    'company_email': company.email or '',
                    'business_activity': business_activity_text,
                }
            )
            if company.enginer:
                form_data.update(
                    {
                        'engineer_name': company.enginer.name,
                        'engineer_email': company.enginer.email,
                        'engineer_phone': company.enginer.phone,
                    }
                )
            else:
                form_data.update(
                    {
                        'engineer_name': '',
                        'engineer_email': '',
                        'engineer_phone': '',
                    }
                )
        else:
            business_activity_text = (request.POST.get('business_activity') or '').strip()
            form_data.update(
                {
                    'company_name': (request.POST.get('company_name') or '').strip(),
                    'trade_license_no': (request.POST.get('trade_license_no') or '').strip(),
                    'trade_license_exp': (request.POST.get('trade_license_exp') or '').strip(),
                    'company_address': (request.POST.get('company_address') or '').strip(),
                    'landline': (request.POST.get('landline') or '').strip(),
                    'owner_phone': (request.POST.get('owner_phone') or '').strip(),
                    'company_email': (request.POST.get('company_email') or '').strip(),
                    'business_activity': business_activity_text,
                    'engineer_name': (request.POST.get('engineer_name') or '').strip(),
                    'engineer_email': (request.POST.get('engineer_email') or '').strip(),
                    'engineer_phone': (request.POST.get('engineer_phone') or '').strip(),
                }
            )

        if not company:
            if not form_data['company_name']:
                form_errors.append('company_name_required')
            if not form_data['trade_license_no']:
                form_errors.append('trade_license_no_required')
            if not form_data['company_address']:
                form_errors.append('company_address_required')

        trade_license_exp = None
        if company:
            trade_license_exp = company.trade_license_exp
            if not trade_license_exp:
                form_errors.append('trade_license_exp_required')
        else:
            trade_license_exp = _parse_date(form_data['trade_license_exp'])
            if form_data['trade_license_exp'] and not trade_license_exp:
                form_errors.append('trade_license_exp_invalid')
            elif not form_data['trade_license_exp']:
                form_errors.append('trade_license_exp_required')

        if trade_license_exp and trade_license_exp < datetime.date.today():
            form_errors.append('trade_license_expired')

        expiry_date = _calculate_permit_expiry(trade_license_exp)
        form_data['expiry_date'] = expiry_date.isoformat() if expiry_date else ''

        if not form_data['request_email']:
            form_errors.append('request_email_required')

        enginer = None
        if company:
            enginer = company.enginer
            if not enginer:
                form_errors.append('company_engineer_missing')
            elif not enginer.public_health_cert:
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
                form_errors.append('engineer_required')

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
        and not inspection_report_decision
        and (
            not assigned_inspector_user
            or assigned_inspector_user.id == request.user.id
            or _can_admin(request.user)
        )
    )
    review_errors = []

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'complete_missing':
            if not _can_data_entry(request.user):
                review_errors.append('ليس لديك صلاحية لاستكمال النواقص.')
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
                pirmet.status = 'review_pending'
                pirmet.save(update_fields=['status'])
                _log_pirmet_change(
                    pirmet,
                    'status_change',
                    request.user,
                    old_status=old_status,
                    new_status=pirmet.status,
                    notes='Completed missing requirements.',
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
            existing_receive = PirmetChangeLog.objects.filter(
                pirmet=pirmet,
                change_type='details_update',
                notes__startswith='inspection_received_by:',
            ).exists()

            if not inspector_user:
                review_errors.append('يرجى اختيار مفتش صحيح.')
            if existing_receive:
                review_errors.append('تم استلام الطلب للتفتيش مسبقاً.')

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
                and not _can_admin(request.user)
            ):
                review_errors.append('فقط المفتش الذي استلم الطلب يمكنه إدخال التقرير.')

            existing_report = PirmetChangeLog.objects.filter(
                pirmet=pirmet,
                change_type='details_update',
                notes__startswith='inspection_report:',
            ).exists()
            if existing_report:
                review_errors.append('تم إدخال تقرير التفتيش مسبقاً.')

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
                pirmet.status = 'inspection_completed'
                if decision == 'rejected':
                    pirmet.unapprovedReason = report_notes or 'Inspection rejected.'
                    update_fields.append('unapprovedReason')
                elif pirmet.unapprovedReason:
                    pirmet.unapprovedReason = None
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
            'can_submit_inspection_report': can_submit_inspection_report,
            'can_review_pirmet': _can_inspector(request.user),
            'can_complete_missing': _can_data_entry(request.user),
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
        form = UserCreationForm(request.POST)
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
        form = UserCreationForm()

    return render(request, 'hcsd/register.html', {'form': form})


def printer(request):
    return render(request, 'hcsd/printer.html')
