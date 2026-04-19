import os

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from ..models import (
    Company, Enginer, InspectorReview, PirmetChangeLog, PirmetClearance, PirmetDocument,
)
from .common import (
    ALLOWED_DOC_EXTENSIONS,
    _can_admin, _can_inspector, _can_data_entry,
    _display_user_name, _inspector_users_qs,
    _inspection_report_decision_from_note,
    _log_pirmet_change,
)

ENGINEER_ADDITION_PHOTO_PREFIX = 'eng_addition_inspection_'


@login_required
def engineer_addition_create(request):
    if not (_can_admin(request.user) or _can_data_entry(request.user)):
        return redirect('clearance_list')

    errors = []
    companies = Company.objects.order_by('name')

    if request.method == 'POST':
        company_id = request.POST.get('company_id', '').strip()
        engineer_name = request.POST.get('engineer_name', '').strip()
        engineer_id_number = request.POST.get('engineer_id_number', '').strip()
        engineer_phone = request.POST.get('engineer_phone', '').strip()
        request_email = request.POST.get('request_email', '').strip()
        has_general_cert = bool(request.POST.get('has_general_cert'))
        has_termite_cert = bool(request.POST.get('has_termite_cert'))
        general_cert_file = request.FILES.get('general_cert_file')
        termite_cert_file = request.FILES.get('termite_cert_file')
        extra_docs = request.FILES.getlist('engineer_documents')

        if not company_id:
            errors.append('يرجى اختيار الشركة.')
        if not engineer_name:
            errors.append('يرجى إدخال اسم المهندس.')
        if not engineer_phone:
            errors.append('يرجى إدخال رقم هاتف المهندس.')
        if general_cert_file:
            ext = os.path.splitext(general_cert_file.name)[1].lower()
            if ext not in ALLOWED_DOC_EXTENSIONS:
                errors.append('صيغة شهادة الصحة العامة غير مقبولة.')
        if termite_cert_file:
            ext = os.path.splitext(termite_cert_file.name)[1].lower()
            if ext not in ALLOWED_DOC_EXTENSIONS:
                errors.append('صيغة شهادة النمل الأبيض غير مقبولة.')
        for doc in extra_docs:
            ext = os.path.splitext(doc.name)[1].lower()
            if ext not in ALLOWED_DOC_EXTENSIONS:
                errors.append(f'الملف "{doc.name}" غير مقبول — يُسمح بـ PDF أو صور فقط.')
                break

        company = None
        if company_id and not errors:
            try:
                company = Company.objects.get(id=int(company_id))
            except (Company.DoesNotExist, ValueError):
                errors.append('الشركة المختارة غير موجودة.')

        if not errors:
            with transaction.atomic():
                engineer = Enginer(
                    name=engineer_name,
                    national_or_unified_number=engineer_id_number or None,
                    phone=engineer_phone,
                )
                if has_general_cert and general_cert_file:
                    engineer.public_health_cert = general_cert_file
                if has_termite_cert and termite_cert_file:
                    engineer.termite_cert = termite_cert_file
                engineer.save()

                pirmet = PirmetClearance.objects.create(
                    company=company,
                    permit_type='engineer_addition',
                    status='order_received',
                    engineer_to_add=engineer,
                    request_email=request_email or None,
                )
                for doc in extra_docs:
                    PirmetDocument.objects.create(pirmet=pirmet, file=doc)
                _log_pirmet_change(
                    pirmet, 'status_change', request.user,
                    old_status=None, new_status='order_received',
                    notes='Engineer addition request created.',
                )
            return redirect('engineer_addition_detail', id=pirmet.id)

    return render(request, 'hcsd/engineer_addition_create.html', {
        'companies': companies,
        'errors': errors,
    })


@login_required
def engineer_addition_detail(request, id):
    pirmet = get_object_or_404(
        PirmetClearance.objects.select_related('company', 'engineer_to_add'),
        id=id,
        permit_type='engineer_addition',
    )
    engineer = pirmet.engineer_to_add

    # --- Inspection receive/report logs ---
    _detail_logs = list(
        PirmetChangeLog.objects.filter(
            pirmet=pirmet,
            change_type='details_update',
        ).filter(
            notes__startswith='inspection_received_by:'
        ) | PirmetChangeLog.objects.filter(
            pirmet=pirmet,
            change_type='details_update',
            notes__startswith='inspection_report:',
        ).order_by('-created_at').select_related('changed_by')
    )
    latest_receive = next((l for l in _detail_logs if l.notes.startswith('inspection_received_by:')), None)
    latest_report = next((l for l in _detail_logs if l.notes.startswith('inspection_report:')), None)

    inspection_receiver_name = None
    if latest_receive and ':' in latest_receive.notes:
        inspection_receiver_name = latest_receive.notes.split(':', 1)[1].strip()

    inspection_report_decision = (
        _inspection_report_decision_from_note(latest_report.notes)
        if latest_report else None
    )

    # Assigned inspector
    assigned_review = InspectorReview.objects.filter(pirmet=pirmet).select_related('inspector_user').first()
    assigned_inspector_user = assigned_review.inspector_user if assigned_review else None

    # Permissions
    is_admin = _can_admin(request.user)
    is_data_entry = _can_data_entry(request.user)
    is_inspector = _can_inspector(request.user)

    can_record_inspection_order = (
        is_admin and pirmet.status == 'order_received'
    )
    can_record_inspection_receipt = (
        is_admin and pirmet.status == 'order_received'
        and bool(pirmet.inspection_payment_reference)
    )
    can_receive_inspection = (
        is_inspector
        and pirmet.status == 'inspection_pending'
        and inspection_receiver_name is None
    )
    can_submit_inspection_report = (
        is_inspector
        and pirmet.status == 'inspection_pending'
        and assigned_inspector_user
        and assigned_inspector_user.id == request.user.id
        and inspection_receiver_name is not None
    )
    can_record_payment_order = (
        is_admin and pirmet.status == 'inspection_completed'
        and inspection_report_decision == 'approved'
    )
    can_record_payment_receipt = (
        is_admin and pirmet.status == 'payment_pending'
    )
    can_complete = (
        is_admin and pirmet.status == 'payment_pending'
        and bool(pirmet.payment_receipt)
    )

    review_errors = []

    if request.method == 'POST':
        action = request.POST.get('action', '').strip()

        if action == 'record_inspection_order':
            if not is_admin:
                review_errors.append('ليس لديك صلاحية.')
            order_no = request.POST.get('inspection_payment_reference', '').strip()
            if not order_no:
                review_errors.append('يرجى إدخال رقم أمر دفع التفتيش.')
            if not review_errors:
                pirmet.inspection_payment_reference = order_no
                pirmet.save(update_fields=['inspection_payment_reference'])
                _log_pirmet_change(pirmet, 'details_update', request.user,
                    notes=f'Inspection payment order recorded: {order_no}')
                return redirect('engineer_addition_detail', id=pirmet.id)

        elif action == 'record_inspection_receipt':
            if not is_admin:
                review_errors.append('ليس لديك صلاحية.')
            receipt = request.FILES.get('inspection_payment_receipt')
            if not receipt:
                review_errors.append('يرجى رفع إيصال التفتيش.')
            else:
                ext = os.path.splitext(receipt.name)[1].lower()
                if ext not in ALLOWED_DOC_EXTENSIONS:
                    review_errors.append('صيغة الملف غير مقبولة.')
            if not review_errors:
                old_status = pirmet.status
                pirmet.inspection_payment_receipt = receipt
                pirmet.status = 'inspection_pending'
                pirmet.save(update_fields=['inspection_payment_receipt', 'status'])
                _log_pirmet_change(pirmet, 'status_change', request.user,
                    old_status=old_status, new_status=pirmet.status,
                    notes='Inspection receipt uploaded.')
                return redirect('engineer_addition_detail', id=pirmet.id)

        elif action == 'receive_for_inspection':
            if not is_inspector:
                review_errors.append('ليس لديك صلاحية.')
            if pirmet.status != 'inspection_pending':
                review_errors.append('الطلب ليس جاهزاً للاستلام.')
            if not review_errors:
                InspectorReview.objects.update_or_create(
                    pirmet=pirmet,
                    defaults={
                        'inspector': None,
                        'inspector_user': request.user,
                        'isApproved': False,
                        'comments': 'تم استلام الطلب للتفتيش.',
                    },
                )
                _log_pirmet_change(pirmet, 'details_update', request.user,
                    notes=f'inspection_received_by:{_display_user_name(request.user)}')
                return redirect('engineer_addition_detail', id=pirmet.id)

        elif action == 'submit_inspection_report':
            if not is_inspector:
                review_errors.append('ليس لديك صلاحية.')
            decision = request.POST.get('inspection_decision', '').strip().lower()
            report_notes = request.POST.get('inspection_report_notes', '').strip()
            inspection_files = request.FILES.getlist('inspection_files')
            if decision not in {'approved', 'rejected'}:
                review_errors.append('يرجى اختيار نتيجة التقرير.')
            if decision == 'rejected' and not report_notes:
                review_errors.append('يرجى كتابة ملاحظات سبب عدم الاعتماد.')
            for f in inspection_files:
                ext = os.path.splitext(f.name)[1].lower()
                if ext not in ALLOWED_DOC_EXTENSIONS:
                    review_errors.append(f'الملف "{f.name}" غير مقبول — يُسمح بـ PDF أو صور فقط.')
                    break
            if not review_errors:
                with transaction.atomic():
                    old_status = pirmet.status
                    pirmet.status = 'inspection_completed'
                    if decision == 'rejected':
                        pirmet.unapprovedReason = report_notes or 'Inspection rejected.'
                        pirmet.save(update_fields=['status', 'unapprovedReason'])
                    else:
                        pirmet.save(update_fields=['status'])
                    InspectorReview.objects.update_or_create(
                        pirmet=pirmet,
                        defaults={'isApproved': decision == 'approved', 'comments': report_notes},
                    )
                    for f in inspection_files:
                        PirmetDocument.objects.create(
                            pirmet=pirmet,
                            file=f,
                            doc_type=PirmetDocument.DOC_TYPE_INSPECTION,
                            notes=report_notes,
                        )
                    _log_pirmet_change(pirmet, 'status_change', request.user,
                        old_status=old_status, new_status=pirmet.status,
                        notes='Engineer addition inspection report submitted.')
                    _log_pirmet_change(pirmet, 'details_update', request.user,
                        notes=f'inspection_report:{decision}')
                    if report_notes:
                        _log_pirmet_change(pirmet, 'details_update', request.user,
                            notes=f'inspection_report_notes:{report_notes}')
                return redirect('engineer_addition_detail', id=pirmet.id)

        elif action == 'record_payment_order':
            if not is_admin:
                review_errors.append('ليس لديك صلاحية.')
            order_no = request.POST.get('payment_order_number', '').strip()
            if not order_no:
                review_errors.append('يرجى إدخال رقم أمر الدفع.')
            if not review_errors:
                old_status = pirmet.status
                pirmet.PaymentNumber = order_no
                pirmet.status = 'payment_pending'
                pirmet.save(update_fields=['PaymentNumber', 'status'])
                _log_pirmet_change(pirmet, 'status_change', request.user,
                    old_status=old_status, new_status=pirmet.status,
                    notes=f'Payment order recorded: {order_no}')
                return redirect('engineer_addition_detail', id=pirmet.id)

        elif action == 'record_payment_receipt':
            if not is_admin:
                review_errors.append('ليس لديك صلاحية.')
            receipt = request.FILES.get('payment_receipt')
            if not receipt:
                review_errors.append('يرجى رفع إيصال الدفع.')
            else:
                ext = os.path.splitext(receipt.name)[1].lower()
                if ext not in ALLOWED_DOC_EXTENSIONS:
                    review_errors.append('صيغة الملف غير مقبولة.')
            if not review_errors:
                pirmet.payment_receipt = receipt
                pirmet.save(update_fields=['payment_receipt'])
                _log_pirmet_change(pirmet, 'details_update', request.user,
                    notes='Payment receipt uploaded.')
                return redirect('engineer_addition_detail', id=pirmet.id)

        elif action == 'complete':
            if not is_admin:
                review_errors.append('ليس لديك صلاحية.')
            if pirmet.status != 'payment_pending':
                review_errors.append('الطلب ليس جاهزاً للإتمام.')
            if not pirmet.payment_receipt:
                review_errors.append('يرجى رفع إيصال الدفع أولاً.')
            if not engineer:
                review_errors.append('لا يوجد مهندس مرتبط بهذا الطلب.')
            if not review_errors:
                with transaction.atomic():
                    company = pirmet.company
                    # Add engineer to company
                    if company.enginer_id and company.enginer_id != engineer.id:
                        # Company already has a main engineer → add as secondary
                        company.engineers.add(engineer)
                    else:
                        # No main engineer yet → set as main
                        company.enginer = engineer
                        company.save(update_fields=['enginer'])

                    old_status = pirmet.status
                    pirmet.status = 'issued'
                    pirmet.save(update_fields=['status'])
                    _log_pirmet_change(pirmet, 'status_change', request.user,
                        old_status=old_status, new_status='issued',
                        notes=f'Engineer addition completed. Engineer ID: {engineer.id}')
                return redirect('engineer_addition_detail', id=pirmet.id)

        elif action == 'admin_close':
            if not is_admin:
                review_errors.append('ليس لديك صلاحية.')
            close_reason = request.POST.get('close_reason', '').strip()
            if not close_reason:
                review_errors.append('يرجى كتابة سبب الإغلاق.')
            if not review_errors:
                old_status = pirmet.status
                pirmet.status = 'cancelled_admin'
                pirmet.unapprovedReason = close_reason
                pirmet.save(update_fields=['status', 'unapprovedReason'])
                _log_pirmet_change(pirmet, 'status_change', request.user,
                    old_status=old_status, new_status='cancelled_admin',
                    notes=f'Admin closed: {close_reason}')
                return redirect('engineer_addition_detail', id=pirmet.id)

    inspection_photos = pirmet.documents.filter(
        doc_type=PirmetDocument.DOC_TYPE_INSPECTION
    ).order_by('uploadedAt')
    engineer_docs = pirmet.documents.filter(
        doc_type=PirmetDocument.DOC_TYPE_ENGINEER
    ).order_by('uploadedAt')

    return render(request, 'hcsd/engineer_addition_detail.html', {
        'pirmet': pirmet,
        'engineer': engineer,
        'inspection_receiver_name': inspection_receiver_name,
        'inspection_report_decision': inspection_report_decision,
        'assigned_inspector_user': assigned_inspector_user,
        'inspector_users': _inspector_users_qs(),
        'inspection_photos': inspection_photos,
        'engineer_docs': engineer_docs,
        'review_errors': review_errors,
        'can_record_inspection_order': can_record_inspection_order,
        'can_record_inspection_receipt': can_record_inspection_receipt,
        'can_receive_inspection': can_receive_inspection,
        'can_submit_inspection_report': can_submit_inspection_report,
        'can_record_payment_order': can_record_payment_order,
        'can_record_payment_receipt': can_record_payment_receipt,
        'can_complete': can_complete,
        'user_is_admin': is_admin,
        'user_is_data_entry': is_data_entry,
    })
