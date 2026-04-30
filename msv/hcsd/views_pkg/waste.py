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
    WasteDisposalRequest, WasteDisposalRequestDocument, WasteDisposalInspectionPhoto,
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
            if pirmet.status != 'payment_pending':
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

        if action == 'cancel_admin':
            if not _can_admin(request.user):
                review_errors.append('ليس لديك صلاحية لإغلاق الطلب.')
            elif pirmet.status in {'issued', 'cancelled_admin'}:
                review_errors.append('لا يمكن إغلاق هذا الطلب في حالته الحالية.')
            else:
                cancel_reason = (request.POST.get('cancel_reason') or '').strip()
                if not cancel_reason:
                    review_errors.append('يرجى كتابة سبب الإغلاق.')
                else:
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
            'show_admin_close_form': (
                _can_admin(request.user)
                and pirmet.status not in {'issued', 'cancelled_admin'}
            ),
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
    inspection_photos = list(disposal_request.inspection_photos.select_related('uploaded_by').order_by('uploaded_at'))
    review_errors = []
    assigned_inspector = disposal_request.inspected_by
    can_upload_inspection_photos = (
        _can_inspector(request.user)
        and disposal_request.status == 'inspection_pending'
        and assigned_inspector
        and assigned_inspector.id == request.user.id
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

        if action == 'upload_inspection_photos':
            if not _can_inspector(request.user):
                review_errors.append('ليس لديك صلاحية لرفع صور التفتيش.')
            elif disposal_request.status != 'inspection_pending':
                review_errors.append('لا يمكن رفع صور التفتيش في هذه المرحلة.')
            elif not assigned_inspector or assigned_inspector.id != request.user.id:
                review_errors.append('فقط المفتش المستلم يمكنه رفع صور التفتيش.')
            else:
                photos = request.FILES.getlist('inspection_photos')
                invalid_photos = [
                    f.name for f in photos
                    if os.path.splitext(f.name)[1].lower() not in ALLOWED_DOC_EXTENSIONS
                ]
                if not photos:
                    review_errors.append('يرجى اختيار صورة أو مستند واحد على الأقل.')
                elif invalid_photos:
                    review_errors.append('يُسمح فقط بملفات PDF أو صور: ' + ', '.join(invalid_photos))
                else:
                    for photo in photos:
                        WasteDisposalInspectionPhoto.objects.create(
                            disposal_request=disposal_request,
                            file=photo,
                            uploaded_by=request.user,
                        )
                    return redirect('waste_disposal_request_detail', permit_id=permit.id, request_id=disposal_request.id)

        if action == 'delete_inspection_photo':
            photo_id = _parse_int(request.POST.get('photo_id'))
            photo = WasteDisposalInspectionPhoto.objects.filter(id=photo_id, disposal_request=disposal_request).first()
            if photo and _can_inspector(request.user):
                photo.file.delete(save=False)
                photo.delete()
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
            photos = request.FILES.getlist('inspection_photos')
            invalid_photos = [
                f.name for f in photos
                if os.path.splitext(f.name)[1].lower() not in ALLOWED_DOC_EXTENSIONS
            ]
            if invalid_photos:
                review_errors.append('يُسمح فقط بملفات PDF أو صور: ' + ', '.join(invalid_photos))
            if not review_errors:
                for photo in photos:
                    WasteDisposalInspectionPhoto.objects.create(
                        disposal_request=disposal_request,
                        file=photo,
                        uploaded_by=request.user,
                    )
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

        if action == 'cancel_admin':
            if not _can_admin(request.user):
                review_errors.append('ليس لديك صلاحية لإغلاق الطلب.')
            elif disposal_request.status in {'approved', 'completed', 'cancelled_admin'}:
                review_errors.append('لا يمكن إغلاق هذا الطلب في حالته الحالية.')
            else:
                cancel_reason = (request.POST.get('cancel_reason') or '').strip()
                if not cancel_reason:
                    review_errors.append('يرجى كتابة سبب الإغلاق.')
                else:
                    disposal_request.status = 'cancelled_admin'
                    disposal_request.save(update_fields=['status', 'updated_at'])
                    _log_pirmet_change(
                        permit,
                        'status_change',
                        request.user,
                        notes=f'waste_disposal_request_cancelled:{disposal_request.id}:{cancel_reason}',
                    )
                    return redirect('waste_disposal_request_detail', permit_id=permit.id, request_id=disposal_request.id)

    _final_statuses = {'approved', 'completed', 'cancelled_admin', 'rejected'}
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
            'can_upload_inspection_photos': can_upload_inspection_photos,
            'inspection_photos': inspection_photos,
            'assigned_inspector_name': _display_user_name(assigned_inspector) if assigned_inspector else None,
            'assigned_inspector_id': assigned_inspector.id if assigned_inspector else None,
            'inspector_users': _inspector_users_qs(),
            'create_mode': False,
            'show_admin_close_form': (
                _can_admin(request.user)
                and disposal_request.status not in _final_statuses
            ),
        },
    )


