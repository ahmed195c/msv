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
        status__in=['issued'],
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
            status__in=['issued'],
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

        trade_license_exp = _parse_date(trade_license_exp_value)
        if trade_license_exp_value and not trade_license_exp:
            error = 'تاريخ انتهاء الرخصة التجارية غير صالح.'

        enginer = None
        if enginer_id:
            enginer = Enginer.objects.filter(id=enginer_id).first()
            if not enginer:
                error = 'يرجى اختيار مهندس صحيح.'

        # تحديد نوع المكافحة تلقائياً من شهادات المهندس
        if enginer and enginer.has_termite_cert:
            pest_control_type = 'termite_control'
        elif enginer and enginer.has_public_health_cert:
            pest_control_type = 'public_health_pest_control'
        else:
            pest_control_type = 'public_health_pest_control'

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
            'error': error,
        },
    )


@login_required
def company_detail(request, id):
    company = get_object_or_404(Company.objects.select_related('enginer'), id=id)
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
        if action == 'save_location':
            lat_raw = (request.POST.get('latitude') or '').strip()
            lng_raw = (request.POST.get('longitude') or '').strip()
            location_area   = (request.POST.get('location_area') or '').strip()
            location_street = (request.POST.get('location_street') or '').strip()
            try:
                lat = round(float(lat_raw), 6) if lat_raw else None
                lng = round(float(lng_raw), 6) if lng_raw else None
            except ValueError:
                lat = lng = None
            if lat is None or lng is None:
                pass  # ignore bad submit without coordinates
            else:
                update_f = ['latitude', 'longitude']
                company.latitude  = lat
                company.longitude = lng
                if location_area:
                    company.location_area = location_area
                    update_f.append('location_area')
                if location_street:
                    company.location_street = location_street
                    update_f.append('location_street')
                company.save(update_fields=update_f)
                notes_parts = [f'إحداثيات: {lat}, {lng}']
                if location_area:
                    notes_parts.append(f'المنطقة: {location_area}')
                if location_street:
                    notes_parts.append(f'الموقع: {location_street}')
                _log_company_change(
                    company,
                    'location_saved',
                    request.user,
                    notes=' — '.join(notes_parts),
                )
            return redirect('company_detail', id=company.id)
        elif action == 'close_extension':
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
        'issued': 'تم إصدار التصريح',
        'inspection_pending': 'جاهز للاستلام',
        'inspection_completed': 'تم إنهاء التفتيش',
        'violation_payment_link_pending': 'بانتظار إرسال رابط دفع المخالفة',
        'violation_payment_pending': 'بانتظار دفع المخالفة',
        'head_approved': 'تم الاعتماد النهائي',
        'closed_requirements_pending': 'مغلق - اشتراطات واجبة الاستيفاء',
        'cancelled_admin': 'مغلق',
        'disposal_approved': 'إتلاف معتمد',
        'disposal_rejected': 'إتلاف مرفوض',
    }

    for permit in permits:
        permit.permit_label_ar = _permit_label_ar(permit.permit_type)
        permit.status_label_ar = permit_status_labels.get(permit.status, permit.get_status_display())
        permit.detail_url_name = _permit_detail_url_name(permit.permit_type)
        permit.is_issued_record = bool(permit.issue_date) or permit.status == 'issued'
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
        company.change_logs.filter(action='extension_requested')
        .select_related('changed_by')
        .order_by('-created_at')
    )
    for ext in extension_logs:
        ext.is_active = bool(ext.extension_end_date and ext.extension_end_date >= today)

    logs = company.change_logs.select_related('changed_by').order_by('-created_at')
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


