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
        ph_expiry_date, ph_is_expired = _certificate_expiry(engineer.public_health_cert_issue_date, engineer.public_health_cert_expiry_date)
        termite_expiry_date, termite_is_expired = _certificate_expiry(engineer.termite_cert_issue_date, engineer.termite_cert_expiry_date)
        engineer._ph_expiry_date = ph_expiry_date
        engineer.public_health_cert_is_expired = ph_is_expired
        engineer._termite_expiry_date = termite_expiry_date
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
                    log_notes = f'من: {start_date:%d/%m/%Y}'
                    if expected_return_date:
                        log_notes += f' — عودة متوقعة: {expected_return_date:%d/%m/%Y}'
                    if substitute:
                        log_notes += f' — البديل: {substitute.name}'
                    if notes:
                        log_notes += f' — {notes}'
                    EnginerStatusLog.objects.create(
                        enginer=enginer,
                        action='leave_recorded',
                        notes=log_notes,
                        changed_by=request.user,
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
                EnginerStatusLog.objects.create(
                    enginer=enginer,
                    action='leave_closed',
                    notes=f'تاريخ العودة الفعلية: {actual_return:%d/%m/%Y}',
                    changed_by=request.user,
                )
                return redirect('enginer_detail', id=enginer.id)

        elif not _can_data_entry(request.user):
            error = 'التحديث متاح لموظفي الإدخال أو الإدارة فقط.'
        else:
            updated = False
            public_health_cert = request.FILES.get('public_health_cert')
            termite_cert = request.FILES.get('termite_cert')
            ph_expiry = _parse_date((request.POST.get('public_health_cert_expiry_date') or '').strip())
            tc_expiry = _parse_date((request.POST.get('termite_cert_expiry_date') or '').strip())
            if public_health_cert:
                previous_public_health_cert = enginer.public_health_cert.name if enginer.public_health_cert else None
                enginer.public_health_cert = public_health_cert
                if ph_expiry:
                    enginer.public_health_cert_expiry_date = ph_expiry
                EnginerStatusLog.objects.create(
                    enginer=enginer,
                    action='public_health_cert_uploaded',
                    notes='Public health certificate updated.',
                    changed_by=request.user,
                    archived_file=previous_public_health_cert or None,
                )
                updated = True
            elif ph_expiry and enginer.public_health_cert:
                enginer.public_health_cert_expiry_date = ph_expiry
                updated = True
            if termite_cert:
                previous_termite_cert = enginer.termite_cert.name if enginer.termite_cert else None
                enginer.termite_cert = termite_cert
                if tc_expiry:
                    enginer.termite_cert_expiry_date = tc_expiry
                EnginerStatusLog.objects.create(
                    enginer=enginer,
                    action='termite_cert_uploaded',
                    notes='Termite certificate updated.',
                    changed_by=request.user,
                    archived_file=previous_termite_cert or None,
                )
                updated = True
            elif tc_expiry and enginer.termite_cert:
                enginer.termite_cert_expiry_date = tc_expiry
                updated = True
            if updated:
                enginer.save()
                return redirect('enginer_detail', id=enginer.id)
            error = 'يرجى إرفاق ملف واحد على الأقل أو تحديث تاريخ الانتهاء.'

    # Re-fetch active leave after possible POST changes
    active_leave = enginer.leaves.filter(actual_return_date__isnull=True).order_by('-created_at').first()
    leave_history = enginer.leaves.select_related('substitute', 'created_by', 'closed_by').order_by('-created_at')
    logs = enginer.status_logs.select_related('changed_by').all().order_by('-created_at')
    archived_logs = [log for log in logs if getattr(log, 'archived_file', None)]
    public_health_expiry_date, public_health_is_expired = _certificate_expiry(enginer.public_health_cert_issue_date, enginer.public_health_cert_expiry_date)
    termite_expiry_date, termite_is_expired = _certificate_expiry(enginer.termite_cert_issue_date, enginer.termite_cert_expiry_date)
    associated_companies = list(
        Company.objects.filter(
            Q(enginer=enginer) | Q(engineers=enginer)
        ).distinct().order_by('name')
    )
    for co in associated_companies:
        co.is_primary = (co.enginer_id == enginer.id)
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
            'associated_companies': associated_companies,
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
            request_document = request.FILES.getlist('request_document')
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
                exam_req = PublicHealthExamRequest.objects.create(
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
                    created_by=request.user,
                    status='submitted',
                )
                for doc_file in request_document:
                    PublicHealthExamRequestDocument.objects.create(
                        exam_request=exam_req,
                        file=doc_file,
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
            'exam_request_documents': list(exam_request.documents.all()),
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


