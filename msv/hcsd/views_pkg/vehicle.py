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
    inspection_report_by = None
    if latest_inspection_report:
        if latest_inspection_report.changed_by:
            inspection_report_by = _display_user_name(latest_inspection_report.changed_by)
        else:
            # user deleted — fall back to the inspector who received the request
            inspection_report_by = inspection_receiver_name

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
            if pirmet.status not in {'inspection_completed', 'payment_pending'}:
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
            if pirmet.status != 'payment_pending':
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

        if action == 'update_payment_number':
            if not _can_admin(request.user):
                review_errors.append('ليس لديك صلاحية لتعديل رقم أمر الدفع.')
            elif pirmet.status != 'payment_pending':
                review_errors.append('لا يمكن تعديل رقم أمر الدفع إلا في حالة بانتظار الدفع.')
            else:
                new_number = (request.POST.get('payment_number') or '').strip()
                if not new_number:
                    review_errors.append('يرجى إدخال رقم أمر الدفع الجديد.')
                else:
                    pirmet.PaymentNumber = new_number
                    pirmet.save(update_fields=['PaymentNumber'])
                    _log_pirmet_change(
                        pirmet,
                        'details_update',
                        request.user,
                        notes=f'Payment number updated to: {new_number}',
                    )
                    return redirect('vehicle_permit_detail', id=pirmet.id)

        if action == 'admin_update_request_data' and _can_admin(request.user):
            import datetime as _dt
            def _parse_date(val):
                try:
                    return _dt.date.fromisoformat(val.strip()) if val and val.strip() else None
                except ValueError:
                    return None
            update_fields = []
            issue_date = _parse_date(request.POST.get('issue_date', ''))
            if issue_date is not None:
                pirmet.issue_date = issue_date
                update_fields.append('issue_date')
            expiry_date = _parse_date(request.POST.get('expiry_date', ''))
            if expiry_date is not None:
                pirmet.dateOfExpiry = expiry_date
                update_fields.append('dateOfExpiry')
            payment_number = (request.POST.get('payment_number') or '').strip()
            if payment_number:
                pirmet.PaymentNumber = payment_number
                update_fields.append('PaymentNumber')
            request_email = (request.POST.get('request_email') or '').strip()
            if request_email:
                pirmet.request_email = request_email
                update_fields.append('request_email')
            if update_fields:
                pirmet.save(update_fields=update_fields)
                _log_pirmet_change(pirmet, 'details_update', request.user, notes='admin_update_request_data')
            new_file = request.FILES.get('new_receipt_file')
            if new_file:
                ext = os.path.splitext(new_file.name)[1].lower()
                if ext in ALLOWED_DOC_EXTENSIONS:
                    pirmet.payment_receipt = new_file
                    pirmet.save(update_fields=['payment_receipt'])
                    _log_pirmet_change(pirmet, 'details_update', request.user, notes='payment_receipt:replaced')
            return redirect('vehicle_permit_detail', id=pirmet.id)

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
                    return redirect('vehicle_permit_detail', id=pirmet.id)

        if action == 'delete_receipt' and _can_admin(request.user):
            field = (request.POST.get('receipt_field') or '').strip()
            allowed = {'inspection_payment_receipt', 'payment_receipt'}
            if field in allowed and getattr(pirmet, field):
                setattr(pirmet, field, None)
                pirmet.save(update_fields=[field])
                _log_pirmet_change(pirmet, 'details_update', request.user, notes=f'{field}:deleted')
                return redirect('vehicle_permit_detail', id=pirmet.id)

        if action == 'replace_receipt' and _can_admin(request.user):
            field = (request.POST.get('receipt_field') or '').strip()
            allowed = {'inspection_payment_receipt', 'payment_receipt'}
            new_file = request.FILES.get('new_receipt_file')
            if field in allowed and new_file:
                ext = os.path.splitext(new_file.name)[1].lower()
                if ext in ALLOWED_DOC_EXTENSIONS:
                    setattr(pirmet, field, new_file)
                    pirmet.save(update_fields=[field])
                    _log_pirmet_change(pirmet, 'details_update', request.user, notes=f'{field}:replaced')
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
            'inspection_report_by': inspection_report_by,
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
            'user_is_admin': _can_admin(request.user),
            'show_admin_close_form': (
                _can_admin(request.user)
                and pirmet.status not in {'issued', 'cancelled_admin'}
            ),
            'inspector_users': _inspector_users_qs(),
        },
    )


