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

        enginer = None
        pending_enginer_fields = []
        if company:
            enginer = company.enginer
            if not enginer:
                engineer_notice = 'تنبيه: هذه الشركة بدون مهندس مسجل حالياً. يمكن تقديم الطلب واستكمال بيانات المهندس لاحقاً.'
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
        _display_user_name(pirmet.head_approved_by)
        if pirmet.head_approved_by
        else (
            _display_user_name(head_approval_log.changed_by)
            if head_approval_log and head_approval_log.changed_by
            else None
        )
    )
    head_approved_date = pirmet.head_approved_date or (
        head_approval_log.created_at if head_approval_log else None
    )
    head_approved_notes = pirmet.head_approved_notes

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
    violation_amount_due = int(pirmet.violation_amount) if pirmet.violation_amount else delay_months_after_grace * 100
    violation_required = delay_months_after_grace > 0
    violation_order_recorded = bool((pirmet.violation_payment_order_number or '').strip())
    violation_receipt_recorded = bool(pirmet.violation_payment_receipt)
    violation_payment_completed = (
        violation_order_recorded
        and violation_receipt_recorded
    )
    can_record_violation_order = (
        _can_admin(request.user)
        and pirmet.status == 'violation_payment_link_pending'
        and violation_required
        and not violation_order_recorded
    )
    can_record_violation_receipt = (
        _can_admin(request.user)
        and pirmet.status in {'violation_payment_pending', 'head_approved'}
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

                # Handle receipt file uploads
                receipt_update_fields = []
                for field_name, label in (
                    ('inspection_payment_receipt', 'إيصال دفع التفتيش'),
                    ('payment_receipt', 'إيصال دفع تصريح المزاولة'),
                ):
                    receipt_file = request.FILES.get(field_name)
                    if receipt_file:
                        ext = os.path.splitext(receipt_file.name)[1].lower()
                        if ext in ALLOWED_DOC_EXTENSIONS:
                            setattr(pirmet, field_name, receipt_file)
                            receipt_update_fields.append(field_name)
                            changed_labels.append(label)
                        else:
                            review_errors.append(f'يُسمح فقط بملفات PDF أو صور لـ {label}.')

                if changed_labels:
                    pirmet.save(update_fields=[
                        'request_email',
                        'inspection_payment_reference',
                        'PaymentNumber',
                        'issue_date',
                        'dateOfExpiry',
                        'payment_date',
                    ] + receipt_update_fields)

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
            if pirmet.status != 'violation_payment_link_pending':
                review_errors.append('يمكن إدخال أمر دفع المخالفة فقط في مرحلة انتظار رابط دفع المخالفة.')
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
                pirmet.status = 'violation_payment_pending'
                pirmet.save(update_fields=['violation_payment_order_number', 'violation_amount', 'status'])
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
            if pirmet.status not in {'violation_payment_pending', 'head_approved'}:
                review_errors.append('يمكن إدخال إيصال المخالفة فقط في مرحلة انتظار دفع المخالفة.')
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
                old_status = pirmet.status
                pirmet.violation_amount = violation_amount_due
                pirmet.violation_payment_receipt = violation_receipt
                if pirmet.status == 'violation_payment_pending':
                    pirmet.status = 'head_approved'
                    pirmet.save(update_fields=['violation_amount', 'violation_payment_receipt', 'status'])
                else:
                    pirmet.save(update_fields=['violation_amount', 'violation_payment_receipt'])
                _log_pirmet_change(
                    pirmet,
                    'document_upload',
                    request.user,
                    old_status=old_status,
                    new_status=pirmet.status,
                    notes='Violation payment receipt uploaded.',
                )
                return redirect('pest_control_permit_detail', id=pirmet.id)

        if action == 'update_violation_data':
            if not (_can_admin(request.user) or _can_data_entry(request.user)):
                review_errors.append('ليس لديك صلاحية لتعديل بيانات المخالفة.')

            order_number = (request.POST.get('violation_payment_order_number') or '').strip()
            update_fields = []
            if order_number:
                pirmet.violation_payment_order_number = order_number
                update_fields.append('violation_payment_order_number')

            receipt_file = request.FILES.get('violation_payment_receipt')
            if receipt_file:
                ext = os.path.splitext(receipt_file.name)[1].lower()
                if ext in ALLOWED_DOC_EXTENSIONS:
                    pirmet.violation_payment_receipt = receipt_file
                    update_fields.append('violation_payment_receipt')
                else:
                    review_errors.append('يُسمح فقط بملفات PDF أو صور لإيصال المخالفة.')

            if not review_errors and update_fields:
                pirmet.save(update_fields=update_fields)
                _log_pirmet_change(
                    pirmet,
                    'details_update',
                    request.user,
                    notes='Violation data updated by admin/data-entry.',
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
                    pirmet.head_approved_by = request.user
                    pirmet.head_approved_date = datetime.date.today()
                    pirmet.head_approved_notes = head_remarks or None
                    if violation_required and not violation_payment_completed:
                        pirmet.status = 'violation_payment_link_pending'
                    else:
                        pirmet.status = 'head_approved'
                    pirmet.save(update_fields=['status', 'head_approved_by', 'head_approved_date', 'head_approved_notes'])
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
                if not pirmet.issue_date:
                    pirmet.issue_date = datetime.date.today()
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

        if action == 'delete_receipt' and _can_admin(request.user):
            field = (request.POST.get('receipt_field') or '').strip()
            allowed = {'inspection_payment_receipt', 'violation_payment_receipt', 'payment_receipt'}
            if field in allowed and getattr(pirmet, field):
                setattr(pirmet, field, None)
                pirmet.save(update_fields=[field])
                _log_pirmet_change(pirmet, 'details_update', request.user, notes=f'{field}:deleted')
                return redirect('pest_control_permit_detail', id=pirmet.id)

        if action == 'replace_receipt' and _can_admin(request.user):
            field = (request.POST.get('receipt_field') or '').strip()
            allowed = {'inspection_payment_receipt', 'violation_payment_receipt', 'payment_receipt'}
            new_file = request.FILES.get('new_receipt_file')
            if field in allowed and new_file:
                ext = os.path.splitext(new_file.name)[1].lower()
                if ext in ALLOWED_DOC_EXTENSIONS:
                    setattr(pirmet, field, new_file)
                    pirmet.save(update_fields=[field])
                    _log_pirmet_change(pirmet, 'details_update', request.user, notes=f'{field}:replaced')
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
            'head_approved_notes': head_approved_notes,
            'can_record_permit_payment_reference': can_record_permit_payment_reference,
            'show_admin_close_form': show_admin_close_form,
            'can_review_pirmet': _can_inspector(request.user),
            'can_record_payment': _can_admin(request.user),
            'can_issue_pirmet': _can_admin(request.user),
            'can_update_pirmet': _can_admin(request.user),
            'user_is_admin': _can_admin(request.user),
            'user_is_data_entry': _can_data_entry(request.user),
            'inspector_users': _inspector_users_qs(),
        },
    )


def pest_control_permit_print(request, id):
    pirmet = get_object_or_404(
        PirmetClearance.objects.select_related('company', 'company__enginer'),
        id=id,
        permit_type='pest_control',
    )
    enginer = pirmet.company.enginer if pirmet.company else None
    allowed = _activities_for_enginer(enginer)
    restricted = _restricted_activities_for_enginer(enginer)
    return render(request, 'hcsd/pest_control_activity_permit_print.html', {
        'pirmet': pirmet,
        'allowed_activities': allowed,
        'restricted_activities': restricted,
        'permit_detail_path': reverse('pest_control_permit_print', args=[pirmet.id]),
    })


@login_required
def pest_control_permit_view(request, id):
    pirmet = get_object_or_404(
        PirmetClearance.objects.select_related('company', 'company__enginer').prefetch_related('documents'),
        id=id,
        permit_type='pest_control',
    )
    if pirmet.status != 'issued':
        return redirect('pest_control_permit_detail', id=pirmet.id)

    return render(
        request,
        'hcsd/pest_control_activity_permit_view.html',
        {
            'pirmet': pirmet,
            'allowed_activities': _split_activities(pirmet.allowed_activities),
            'restricted_activities': _split_activities(pirmet.restricted_activities),
            'permit_detail_path': reverse('pest_control_permit_detail', args=[pirmet.id]),
        },
    )


