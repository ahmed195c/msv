import datetime
import io
import os
import zipfile
import uuid
from decimal import Decimal, InvalidOperation

from django.contrib.auth import login
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import Group
from django.core.files.base import ContentFile
from django.db.models import OuterRef, Subquery, Prefetch, Q
from django.http import HttpResponseForbidden
from django.shortcuts import render, redirect, get_object_or_404
from django.utils.text import slugify
from .models import (
    Company,
    BUSINESS_ACTIVITY_CHOICES,
    CompanyChangeLog,
    Enginer,
    EnginerStatusLog,
    InspectorReview,
    DisposalProcess,
    InspectionReport,
    PirmetClearance,
    PirmetChangeLog,
    PirmetDocument,
    PesticideTransportPermit,
    WasteDisposalPermit,
)
# Create your views here.

ALLOWED_DOC_EXTENSIONS = {'.pdf', '.png', '.jpg', '.jpeg'}
ROLE_DATA_ENTRY = 'Data Entry'
ROLE_INSPECTOR = 'Inspector'
ROLE_ADMIN = 'Administration'
FINAL_STATUSES = {'issued', 'disposal_approved', 'disposal_rejected'}
BUSINESS_ACTIVITY_LABELS = dict(BUSINESS_ACTIVITY_CHOICES)


def _parse_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _format_business_activity(value):
    if not value:
        return ''
    items = [item.strip() for item in value.split(',') if item.strip()]
    labels = [BUSINESS_ACTIVITY_LABELS.get(item, item) for item in items]
    return '، '.join(labels)


def _safe_bundle_segment(value, fallback):
    safe_value = slugify(value or '', allow_unicode=True)
    return safe_value or fallback


def _build_documents_bundle(documents, bundle_path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for index, doc in enumerate(documents, start=1):
            ext = os.path.splitext(doc.name)[1].lower()
            filename = f"document_{index:02d}{ext}"
            archive.writestr(filename, doc.read())
    buffer.seek(0)
    return ContentFile(buffer.read(), name=bundle_path)


def _append_documents_bundle(pirmet, documents):
    if not documents:
        return None

    if pirmet.request_documents_bundle and pirmet.request_documents_bundle.name:
        bundle_path = pirmet.request_documents_bundle.name
    else:
        bundle_folder = (
            f"{_safe_bundle_segment(pirmet.company.name, 'company')}_"
            f"{_safe_bundle_segment(pirmet.permit_type, 'permit')}"
        )
        bundle_name = f"{bundle_folder}_{pirmet.id}.zip"
        bundle_path = f"{bundle_folder}/{bundle_name}"

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        if pirmet.request_documents_bundle:
            with pirmet.request_documents_bundle.open('rb') as existing_file:
                with zipfile.ZipFile(existing_file, 'r') as existing_zip:
                    for info in existing_zip.infolist():
                        archive.writestr(info.filename, existing_zip.read(info.filename))
        for doc in documents:
            ext = os.path.splitext(doc.name)[1].lower()
            filename = f"document_{uuid.uuid4().hex}{ext}"
            archive.writestr(filename, doc.read())
    buffer.seek(0)
    bundle_file = ContentFile(buffer.read(), name=bundle_path)
    pirmet.request_documents_bundle.save(bundle_path, bundle_file, save=True)
    return bundle_path


def _user_in_groups(user, group_names):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=group_names).exists()


def _can_data_entry(user):
    return _user_in_groups(user, [ROLE_DATA_ENTRY, ROLE_ADMIN])


def _can_inspector(user):
    return _user_in_groups(user, [ROLE_INSPECTOR, ROLE_ADMIN])


def _can_admin(user):
    return _user_in_groups(user, [ROLE_ADMIN])


def _parse_date(value, errors=None, required_code=None, invalid_code=None, required=True):
    if not value:
        if required and errors is not None and required_code:
            errors.append(required_code)
        return None
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        if errors is not None and invalid_code:
            errors.append(invalid_code)
        return None


def _upsert_company(
    name,
    number,
    address=None,
    trade_license_exp=None,
    business_activity=None,
    landline=None,
    owner_phone=None,
    email=None,
    enginer=None,
):
    company = Company.objects.filter(name=name, number=number).first()
    if company:
        needs_save = False
        if address and company.address != address:
            company.address = address
            needs_save = True
        if trade_license_exp is not None and company.trade_license_exp != trade_license_exp:
            company.trade_license_exp = trade_license_exp
            needs_save = True
        if business_activity:
            company.business_activity = business_activity
            needs_save = True
        if landline:
            company.landline = landline
            needs_save = True
        if owner_phone:
            company.owner_phone = owner_phone
            needs_save = True
        if email:
            company.email = email
            needs_save = True
        if enginer is not None and company.enginer_id != enginer.id:
            company.enginer = enginer
            needs_save = True
        if needs_save:
            company.save()
        return company

    return Company.objects.create(
        name=name,
        number=number,
        address=address or '',
        trade_license_exp=trade_license_exp,
        business_activity=business_activity or None,
        landline=landline or None,
        owner_phone=owner_phone or None,
        email=email or None,
        enginer=enginer,
    )


def _log_pirmet_change(
    pirmet,
    change_type,
    user=None,
    old_status=None,
    new_status=None,
    notes=None,
):
    PirmetChangeLog.objects.create(
        pirmet=pirmet,
        change_type=change_type,
        old_status=old_status,
        new_status=new_status,
        notes=notes or '',
        changed_by=user if user and user.is_authenticated else None,
    )


def _log_enginer_status(enginer, action, notes=''):
    EnginerStatusLog.objects.create(
        enginer=enginer,
        action=action,
        notes=notes or '',
    )


def _log_company_change(company, action, user=None, notes=None, attachment=None):
    CompanyChangeLog.objects.create(
        company=company,
        action=action,
        notes=notes or '',
        attachment=attachment,
        changed_by=user if user and user.is_authenticated else None,
    )


def _clearance_list_context(user):
    inspector_name_subquery = (
        InspectorReview.objects.filter(pirmet_id=OuterRef('pk'))
        .values('inspector__name')[:1]
    )
    return {
        'clearances': (
            PirmetClearance.objects.select_related('company')
            .prefetch_related('documents')
            .annotate(inspector_name=Subquery(inspector_name_subquery))
            .order_by('-dateOfCreation')
        ),
        'companies': Company.objects.all().order_by('name'),
        'engineers': Enginer.objects.all().order_by('name'),
        'can_create_pirmet': _can_data_entry(user),
        'can_review_pirmet': _can_inspector(user),
        'can_record_payment': _can_admin(user),
        'can_issue_pirmet': _can_admin(user),
        'can_delete_pirmet': _can_admin(user),
    }


def _render_clearance_list(request, errors=None):
    context = _clearance_list_context(request.user)
    if errors:
        context['form_errors'] = errors
    return render(request, 'hcsd/clearance_list.html', context)


def register(request):
    if request.user.is_authenticated:
        return redirect('home')

    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            group, _ = Group.objects.get_or_create(name=ROLE_DATA_ENTRY)
            user.groups.add(group)
            login(request, user)
            return redirect('home')
    else:
        form = UserCreationForm()

    return render(request, 'hcsd/register.html', {'form': form})


def home(request):
    latest_pirmet = (
        PirmetClearance.objects.exclude(status__in=FINAL_STATUSES)
        .select_related('company')
        .order_by('-dateOfCreation')
    )
    return render(
        request,
        'hcsd/base.html',
        {'latest_pirmet': latest_pirmet, 'show_latest': True},
    )


def permit_types(request):
    return render(request, 'hcsd/permit_types.html')


def basetemplate(request):
    companies = Company.objects.all().order_by('name')
    selected_company_id = _parse_int(request.GET.get('company_id'))
    if request.method == 'POST':
        errors = []
        company_id = _parse_int(request.POST.get('company_id'))
        company_name = (request.POST.get('company_name') or '').strip()
        trade_license_no = (request.POST.get('trade_license_no') or '').strip()
        trade_license_exp_value = request.POST.get('trade_license_exp')
        business_activity_values = [
            item.strip()
            for item in request.POST.getlist('business_activity')
            if item.strip()
        ]
        business_activity = ','.join(business_activity_values)
        company_address = (request.POST.get('company_address') or '').strip()
        landline = (request.POST.get('landline') or '').strip()
        owner_phone = (request.POST.get('owner_phone') or '').strip()
        company_email = (request.POST.get('company_email') or '').strip()
        request_email = (request.POST.get('request_email') or '').strip()
        issue_value = request.POST.get('issue_date')
        expiry_value = request.POST.get('expiry_date')
        engineer_name = (request.POST.get('engineer_name') or '').strip()
        engineer_email = (request.POST.get('engineer_email') or '').strip()
        engineer_phone = (request.POST.get('engineer_phone') or '').strip()
        allowed_activities = request.POST.getlist('allowed_activities')
        restricted_activities = request.POST.getlist('restricted_activities')
        allowed_other = (request.POST.get('allowed_other') or '').strip()
        restricted_other = (request.POST.get('restricted_other') or '').strip()
        company_rep = (request.POST.get('company_rep') or '').strip()
        department_stamp = (request.POST.get('department_stamp') or '').strip()
        documents = request.FILES.getlist('documents')

        company = None
        if company_id:
            company = Company.objects.filter(id=company_id).first()
            if not company:
                errors.append('company_select_invalid')

        if company:
            if not company_name:
                company_name = company.name
            if not trade_license_no:
                trade_license_no = company.number
            if not company_address:
                company_address = company.address
            if not landline and company.landline:
                landline = company.landline
            if not owner_phone and company.owner_phone:
                owner_phone = company.owner_phone
            if not company_email and company.email:
                company_email = company.email
            if not business_activity and company.business_activity:
                business_activity = company.business_activity

        if business_activity and not business_activity_values:
            business_activity_values = [
                item.strip()
                for item in business_activity.split(',')
                if item.strip()
            ]

        if not company_name:
            errors.append('company_name_required')
        if not trade_license_no:
            errors.append('trade_license_no_required')
        if not company_address:
            errors.append('company_address_required')

        trade_license_exp = None
        if trade_license_exp_value:
            trade_license_exp = _parse_date(
                trade_license_exp_value,
                errors,
                None,
                'trade_license_exp_invalid',
                required=False,
            )
        elif company and company.trade_license_exp:
            trade_license_exp = company.trade_license_exp

        if (
            not trade_license_exp
            and not trade_license_exp_value
            and not (company and company.trade_license_exp)
        ):
            errors.append('trade_license_exp_required')
        issue_date = _parse_date(
            issue_value, errors, required=False
        )
        date_of_expiry = _parse_date(
            expiry_value, errors, required=False
        )

        if not request_email:
            errors.append('request_email_required')

        enginer = None
        if engineer_name or engineer_email or engineer_phone:
            if not engineer_name or not engineer_email or not engineer_phone:
                errors.append('engineer_required')
            else:
                enginer = Enginer.objects.filter(email=engineer_email).first()
                if not enginer:
                    errors.append('engineer_not_registered')
                else:
                    if enginer.name != engineer_name or enginer.phone != engineer_phone:
                        enginer.name = engineer_name
                        enginer.phone = engineer_phone
                        enginer.save()
                    if not enginer.public_health_cert:
                        errors.append('engineer_cert_required')
        else:
            if company and company.enginer:
                enginer = company.enginer
                if not enginer.public_health_cert:
                    errors.append('engineer_cert_required')
            else:
                errors.append('engineer_required')

        invalid_docs = []
        if not documents:
            errors.append('documents_required')
        else:
            for doc in documents:
                ext = os.path.splitext(doc.name)[1].lower()
                if ext not in ALLOWED_DOC_EXTENSIONS:
                    invalid_docs.append(doc.name)
            if invalid_docs:
                errors.append('documents_invalid')

        if errors:
            context = {
                'form_errors': errors,
                'companies': companies,
                'selected_company_id': company_id,
                'selected_business_activities': business_activity_values,
            }
            if invalid_docs:
                context['invalid_docs'] = invalid_docs
            return render(request, 'hcsd/basetemplate.html', context)

        if not enginer:
            return render(
                request,
                'hcsd/basetemplate.html',
                {
                    'form_errors': errors or ['engineer_required'],
                    'companies': companies,
                    'selected_company_id': company_id,
                    'selected_business_activities': business_activity_values,
                },
            )

        company = _upsert_company(
            company_name,
            trade_license_no,
            address=company_address,
            trade_license_exp=trade_license_exp,
            business_activity=business_activity,
            landline=landline,
            owner_phone=owner_phone,
            email=company_email,
            enginer=enginer,
        )

        pirmet = PirmetClearance.objects.create(
            company=company,
            dateOfExpiry=date_of_expiry,
            status='order_received',
            issue_date=issue_date,
            permit_type='pest_control',
            allowed_activities=(
                ','.join(allowed_activities) if allowed_activities else None
            ),
            restricted_activities=(
                ','.join(restricted_activities) if restricted_activities else None
            ),
            allowed_other=allowed_other or None,
            restricted_other=restricted_other or None,
            company_rep=company_rep or None,
            department_stamp=department_stamp or None,
            request_email=request_email or None,
        )
        bundle_folder = (
            f"{_safe_bundle_segment(company.name, 'company')}_"
            f"{_safe_bundle_segment(pirmet.permit_type, 'permit')}"
        )
        bundle_name = f"{bundle_folder}_{pirmet.id}.zip"
        bundle_path = f"{bundle_folder}/{bundle_name}"
        bundle_file = _build_documents_bundle(documents, bundle_path)
        pirmet.request_documents_bundle.save(bundle_path, bundle_file, save=True)

        _log_pirmet_change(
            pirmet,
            'created',
            request.user,
            new_status=pirmet.status,
            notes='Created from permit form (email request).',
        )
        _log_pirmet_change(
            pirmet,
            'document_upload',
            request.user,
            notes='Request documents bundled.',
        )

        return render(
            request,
            'hcsd/basetemplate.html',
            {
                'success_message': 'submitted',
                'companies': companies,
                'selected_company_id': selected_company_id,
            },
        )

    return render(
        request,
        'hcsd/basetemplate.html',
        {'companies': companies, 'selected_company_id': selected_company_id},
    )


def pest_control_permit(request):
    return basetemplate(request)


def pesticide_transport_permit(request):
    companies = Company.objects.all().order_by('name')
    selected_company_id = _parse_int(request.GET.get('company_id'))
    if request.method == 'POST':
        errors = []
        company_id = _parse_int(request.POST.get('company_id'))
        company_name = (request.POST.get('company_name') or '').strip()
        trade_license_no = (request.POST.get('trade_license_no') or '').strip()
        trade_license_exp_value = request.POST.get('trade_license_exp')
        company_address = (request.POST.get('company_address') or '').strip()
        landline = (request.POST.get('landline') or '').strip()
        owner_phone = (request.POST.get('owner_phone') or '').strip()
        company_email = (request.POST.get('company_email') or '').strip()
        business_activity_values = [
            item.strip()
            for item in request.POST.getlist('business_activity')
            if item.strip()
        ]
        business_activity = ','.join(business_activity_values)
        contact_number = (request.POST.get('contact_number') or '').strip()
        activity_type = (request.POST.get('activity_type') or '').strip()
        issue_value = request.POST.get('issue_date')
        expiry_value = request.POST.get('expiry_date')
        receipt_no = (request.POST.get('receipt_no') or '').strip()
        receipt_date_value = request.POST.get('receipt_date')
        vehicle_type = (request.POST.get('vehicle_type') or '').strip()
        vehicle_color = (request.POST.get('vehicle_color') or '').strip()
        vehicle_number = (request.POST.get('vehicle_number') or '').strip()
        vehicle_license_expiry_value = request.POST.get(
            'vehicle_license_expiry'
        )
        issue_authority = (request.POST.get('issue_authority') or '').strip()
        documents = request.FILES.getlist('documents')

        company = None
        if company_id:
            company = Company.objects.filter(id=company_id).first()
            if not company:
                errors.append('company_select_invalid')

        if company:
            if not company_name:
                company_name = company.name
            if not trade_license_no:
                trade_license_no = company.number
            if not company_address:
                company_address = company.address
            if not landline and company.landline:
                landline = company.landline
            if not owner_phone and company.owner_phone:
                owner_phone = company.owner_phone
            if not company_email and company.email:
                company_email = company.email
            if not business_activity and company.business_activity:
                business_activity = company.business_activity

        if business_activity and not business_activity_values:
            business_activity_values = [
                item.strip()
                for item in business_activity.split(',')
                if item.strip()
            ]

        if not activity_type and business_activity:
            activity_type = _format_business_activity(business_activity)

        if not company_name:
            errors.append('company_name_required')
        if not trade_license_no:
            errors.append('trade_license_no_required')
        if not company_address:
            errors.append('company_address_required')
        if not contact_number:
            errors.append('contact_number_required')
        if not activity_type:
            errors.append('activity_type_required')
        if not vehicle_type:
            errors.append('vehicle_type_required')
        if not vehicle_color:
            errors.append('vehicle_color_required')
        if not vehicle_number:
            errors.append('vehicle_number_required')
        if not issue_authority:
            errors.append('issue_authority_required')

        trade_license_exp = None
        if trade_license_exp_value:
            trade_license_exp = _parse_date(
                trade_license_exp_value,
                errors,
                None,
                'trade_license_exp_invalid',
                required=False,
            )
        elif company and company.trade_license_exp:
            trade_license_exp = company.trade_license_exp

        if (
            not trade_license_exp
            and not trade_license_exp_value
            and not (company and company.trade_license_exp)
        ):
            errors.append('trade_license_exp_required')
        issue_date = _parse_date(
            issue_value, errors, 'issue_date_required', 'issue_date_invalid'
        )
        date_of_expiry = _parse_date(
            expiry_value, errors, 'expiry_date_required', 'expiry_date_invalid'
        )
        vehicle_license_expiry = _parse_date(
            vehicle_license_expiry_value,
            errors,
            'vehicle_license_expiry_required',
            'vehicle_license_expiry_invalid',
        )
        receipt_date = _parse_date(
            receipt_date_value,
            errors,
            None,
            'receipt_date_invalid',
            required=False,
        )

        invalid_docs = []
        if not documents:
            errors.append('documents_required')
        else:
            for doc in documents:
                ext = os.path.splitext(doc.name)[1].lower()
                if ext not in ALLOWED_DOC_EXTENSIONS:
                    invalid_docs.append(doc.name)
            if invalid_docs:
                errors.append('documents_invalid')

        if errors:
            context = {
                'form_errors': errors,
                'companies': companies,
                'selected_company_id': company_id,
                'selected_business_activities': business_activity_values,
            }
            if invalid_docs:
                context['invalid_docs'] = invalid_docs
            return render(
                request, 'hcsd/pesticide_transport_permit.html', context
            )

        company = _upsert_company(
            company_name,
            trade_license_no,
            address=company_address,
            trade_license_exp=trade_license_exp,
            business_activity=business_activity,
            landline=landline,
            owner_phone=owner_phone,
            email=company_email,
        )

        pirmet = PirmetClearance.objects.create(
            company=company,
            dateOfExpiry=date_of_expiry,
            status='review_pending',
            issue_date=issue_date,
            permit_type='pesticide_transport',
            payment_date=receipt_date,
        )
        if receipt_no:
            pirmet.PaymentNumber = receipt_no
            pirmet.save()

        PesticideTransportPermit.objects.create(
            pirmet=pirmet,
            contact_number=contact_number,
            activity_type=activity_type,
            vehicle_type=vehicle_type,
            vehicle_color=vehicle_color,
            vehicle_number=vehicle_number,
            vehicle_license_expiry=vehicle_license_expiry,
            issue_authority=issue_authority,
        )

        for doc in documents:
            PirmetDocument.objects.create(pirmet=pirmet, file=doc)

        _log_pirmet_change(
            pirmet,
            'created',
            request.user,
            new_status=pirmet.status,
            notes='Created from pesticide transport permit form.',
        )
        _log_pirmet_change(
            pirmet,
            'document_upload',
            request.user,
            notes=f'Documents uploaded: {len(documents)}',
        )
        if receipt_no:
            _log_pirmet_change(
                pirmet,
                'payment_update',
                request.user,
                notes=f'Payment receipt number provided: {receipt_no}',
            )

        return render(
            request,
            'hcsd/pesticide_transport_permit.html',
            {
                'success_message': 'submitted',
                'companies': companies,
                'selected_company_id': selected_company_id,
            },
        )

    return render(
        request,
        'hcsd/pesticide_transport_permit.html',
        {'companies': companies, 'selected_company_id': selected_company_id},
    )


def waste_disposal_permit(request):
    companies = Company.objects.all().order_by('name')
    selected_company_id = _parse_int(request.GET.get('company_id'))
    if request.method == 'POST':
        errors = []
        company_id = _parse_int(request.POST.get('company_id'))
        company_name = (request.POST.get('company_name') or '').strip()
        trade_license_no = (request.POST.get('trade_license_no') or '').strip()
        trade_license_exp_value = request.POST.get('trade_license_exp')
        company_address = (request.POST.get('company_address') or '').strip()
        landline = (request.POST.get('landline') or '').strip()
        owner_phone = (request.POST.get('owner_phone') or '').strip()
        company_email = (request.POST.get('company_email') or '').strip()
        business_activity_values = [
            item.strip()
            for item in request.POST.getlist('business_activity')
            if item.strip()
        ]
        business_activity = ','.join(business_activity_values)
        issue_value = request.POST.get('issue_date')
        expiry_value = request.POST.get('expiry_date')
        receipt_no = (request.POST.get('receipt_no') or '').strip()
        receipt_date_value = request.POST.get('receipt_date')
        waste_classification = (request.POST.get('waste_classification') or '').strip()
        waste_quantity_value = (
            request.POST.get('waste_quantity_monthly') or ''
        ).strip()
        waste_types = (request.POST.get('waste_types') or '').strip()
        material_state = (request.POST.get('material_state') or '').strip()
        project_number = (request.POST.get('project_number') or '').strip()
        project_type = (request.POST.get('project_type') or '').strip()
        contractors = (request.POST.get('contractors') or '').strip()
        employee_number = (request.POST.get('employee_number') or '').strip()
        documents = request.FILES.getlist('documents')

        company = None
        if company_id:
            company = Company.objects.filter(id=company_id).first()
            if not company:
                errors.append('company_select_invalid')

        if company:
            if not company_name:
                company_name = company.name
            if not trade_license_no:
                trade_license_no = company.number
            if not company_address:
                company_address = company.address
            if not landline and company.landline:
                landline = company.landline
            if not owner_phone and company.owner_phone:
                owner_phone = company.owner_phone
            if not company_email and company.email:
                company_email = company.email
            if not business_activity and company.business_activity:
                business_activity = company.business_activity

        if business_activity and not business_activity_values:
            business_activity_values = [
                item.strip()
                for item in business_activity.split(',')
                if item.strip()
            ]

        if not company_name:
            errors.append('company_name_required')
        if not trade_license_no:
            errors.append('trade_license_no_required')
        if not company_address:
            errors.append('company_address_required')
        if not business_activity:
            errors.append('business_activity_required')

        trade_license_exp = None
        if trade_license_exp_value:
            trade_license_exp = _parse_date(
                trade_license_exp_value,
                errors,
                None,
                'trade_license_exp_invalid',
                required=False,
            )
        elif company and company.trade_license_exp:
            trade_license_exp = company.trade_license_exp

        if (
            not trade_license_exp
            and not trade_license_exp_value
            and not (company and company.trade_license_exp)
        ):
            errors.append('trade_license_exp_required')
        if not waste_classification:
            errors.append('waste_classification_required')
        if not waste_types:
            errors.append('waste_types_required')
        if not material_state:
            errors.append('material_state_required')

        issue_date = _parse_date(
            issue_value, errors, 'issue_date_required', 'issue_date_invalid'
        )
        date_of_expiry = _parse_date(
            expiry_value, errors, 'expiry_date_required', 'expiry_date_invalid'
        )
        receipt_date = _parse_date(
            receipt_date_value,
            errors,
            None,
            'receipt_date_invalid',
            required=False,
        )

        waste_quantity_monthly = None
        if not waste_quantity_value:
            errors.append('waste_quantity_required')
        else:
            try:
                waste_quantity_monthly = Decimal(waste_quantity_value)
            except (InvalidOperation, ValueError):
                errors.append('waste_quantity_invalid')

        invalid_docs = []
        if not documents:
            errors.append('documents_required')
        else:
            for doc in documents:
                ext = os.path.splitext(doc.name)[1].lower()
                if ext not in ALLOWED_DOC_EXTENSIONS:
                    invalid_docs.append(doc.name)
            if invalid_docs:
                errors.append('documents_invalid')

        if errors:
            context = {
                'form_errors': errors,
                'companies': companies,
                'selected_company_id': company_id,
                'selected_business_activities': business_activity_values,
            }
            if invalid_docs:
                context['invalid_docs'] = invalid_docs
            return render(
                request, 'hcsd/waste_disposal_permit.html', context
            )

        company = _upsert_company(
            company_name,
            trade_license_no,
            address=company_address,
            trade_license_exp=trade_license_exp,
            business_activity=business_activity,
            landline=landline,
            owner_phone=owner_phone,
            email=company_email,
        )

        pirmet = PirmetClearance.objects.create(
            company=company,
            dateOfExpiry=date_of_expiry,
            status='review_pending',
            issue_date=issue_date,
            permit_type='waste_disposal',
            payment_date=receipt_date,
        )
        if receipt_no:
            pirmet.PaymentNumber = receipt_no
            pirmet.save()

        WasteDisposalPermit.objects.create(
            pirmet=pirmet,
            waste_classification=waste_classification,
            waste_quantity_monthly=waste_quantity_monthly,
            waste_types=waste_types,
            material_state=material_state,
            project_number=project_number or None,
            project_type=project_type or None,
            contractors=contractors or None,
            employee_number=employee_number or None,
        )

        for doc in documents:
            PirmetDocument.objects.create(pirmet=pirmet, file=doc)

        _log_pirmet_change(
            pirmet,
            'created',
            request.user,
            new_status=pirmet.status,
            notes='Created from waste disposal permit form.',
        )
        _log_pirmet_change(
            pirmet,
            'document_upload',
            request.user,
            notes=f'Documents uploaded: {len(documents)}',
        )
        if receipt_no:
            _log_pirmet_change(
                pirmet,
                'payment_update',
                request.user,
                notes=f'Payment receipt number provided: {receipt_no}',
            )

        return render(
            request,
            'hcsd/waste_disposal_permit.html',
            {
                'success_message': 'submitted',
                'companies': companies,
                'selected_company_id': selected_company_id,
            },
        )

    return render(
        request,
        'hcsd/waste_disposal_permit.html',
        {'companies': companies, 'selected_company_id': selected_company_id},
    )

def clearance_list(request):
    if request.method == 'POST':
        if not request.user.is_authenticated:
            return redirect('login')

        action = request.POST.get('action')
        if action == 'update_request_email':
            if not _can_admin(request.user):
                review_errors.append('ليس لديك صلاحية لتعديل بريد الطلب.')
            new_email = (request.POST.get('request_email') or '').strip()
            if not new_email:
                review_errors.append('يرجى إدخال بريد الطلب.')
            if not review_errors:
                old_email = pirmet.request_email or ''
                pirmet.request_email = new_email
                if not pirmet.inspection_payment_email or pirmet.inspection_payment_email == old_email:
                    pirmet.inspection_payment_email = new_email
                if not pirmet.payment_email or pirmet.payment_email == old_email:
                    pirmet.payment_email = new_email
                pirmet.save()
                _log_pirmet_change(
                    pirmet,
                    'details_update',
                    request.user,
                    notes=f'تحديث بريد الطلب إلى: {new_email}',
                )
                return redirect('pirmet_detail', id=pirmet.id)

        if action == 'send_inspection_payment_link':
            if not _can_admin(request.user):
                review_errors.append('ليس لديك صلاحية لإرسال رابط دفع التفتيش.')
            if pirmet.status != 'order_received':
                review_errors.append('هذا الطلب ليس بانتظار رابط دفع التفتيش.')

            inspection_link = (request.POST.get('inspection_payment_link') or '').strip()
            inspection_email = (request.POST.get('inspection_payment_email') or '').strip()
            inspection_reference = (
                request.POST.get('inspection_payment_reference') or ''
            ).strip()

            if not inspection_link:
                review_errors.append('يرجى إدخال رابط دفع التفتيش.')
            if not inspection_email and pirmet.request_email:
                inspection_email = pirmet.request_email
            if not inspection_email:
                review_errors.append('يرجى إدخال البريد المرسل له رابط التفتيش.')
            if not inspection_reference:
                review_errors.append('يرجى إدخال رقم مرجع دفع التفتيش.')

            if not review_errors:
                old_status = pirmet.status
                pirmet.inspection_payment_link = inspection_link
                pirmet.inspection_payment_email = inspection_email
                pirmet.inspection_payment_reference = inspection_reference
                pirmet.status = 'inspection_payment_pending'
                pirmet.save()
                _log_pirmet_change(
                    pirmet,
                    'status_change',
                    request.user,
                    old_status=old_status,
                    new_status=pirmet.status,
                    notes=f'Inspection payment link sent to {inspection_email}: {inspection_link}',
                )
                return redirect('pirmet_detail', id=pirmet.id)

        if action == 'inspection_payment':
            if not _can_admin(request.user):
                review_errors.append('ليس لديك صلاحية لتأكيد دفع التفتيش.')
            if pirmet.status != 'inspection_payment_pending':
                review_errors.append('هذا الطلب ليس بانتظار دفع التفتيش.')

            inspection_reference = (
                request.POST.get('inspection_payment_reference') or ''
            ).strip()
            inspection_receipt = request.FILES.get('inspection_payment_receipt')

            if not inspection_reference:
                review_errors.append('يرجى إدخال رقم مرجع دفع التفتيش.')
            if not inspection_receipt:
                review_errors.append('يرجى إرفاق إيصال دفع التفتيش.')
            else:
                ext = os.path.splitext(inspection_receipt.name)[1].lower()
                if ext not in ALLOWED_DOC_EXTENSIONS:
                    review_errors.append('إيصال التفتيش يجب أن يكون PDF أو صورة.')

            if not review_errors:
                old_status = pirmet.status
                pirmet.inspection_payment_reference = inspection_reference
                pirmet.inspection_payment_receipt = inspection_receipt
                pirmet.status = 'review_pending'
                pirmet.save()
                _log_pirmet_change(
                    pirmet,
                    'payment_update',
                    request.user,
                    old_status=old_status,
                    new_status=pirmet.status,
                    notes=f'Inspection payment recorded: {inspection_reference}',
                )
                return redirect('pirmet_detail', id=pirmet.id)

        if action == 'send_payment_link':
            if not _can_admin(request.user):
                review_errors.append('ليس لديك صلاحية لإرسال رابط دفع التصريح.')
            if pirmet.status != 'approved':
                review_errors.append('هذا الطلب ليس بانتظار رابط دفع التصريح.')

            payment_link = (request.POST.get('payment_link') or '').strip()
            payment_email = (request.POST.get('payment_email') or '').strip()
            payment_number = (request.POST.get('payment_number') or '').strip()

            if not payment_link:
                review_errors.append('يرجى إدخال رابط دفع التصريح.')
            if not payment_email and pirmet.request_email:
                payment_email = pirmet.request_email
            if not payment_email:
                review_errors.append('يرجى إدخال البريد المرسل له رابط التصريح.')
            if not payment_number:
                review_errors.append('يرجى إدخال رقم مرجع دفع التصريح.')

            if not review_errors:
                old_status = pirmet.status
                pirmet.payment_link = payment_link
                pirmet.payment_email = payment_email
                pirmet.PaymentNumber = payment_number
                pirmet.status = 'payment_pending'
                pirmet.save()
                _log_pirmet_change(
                    pirmet,
                    'status_change',
                    request.user,
                    old_status=old_status,
                    new_status=pirmet.status,
                    notes=f'Payment link sent to {payment_email}: {payment_link}',
                )
                return redirect('pirmet_detail', id=pirmet.id)

        if action == 'payment':
            if not _can_admin(request.user):
                review_errors.append('ليس لديك صلاحية لتأكيد دفع التصريح.')
            if pirmet.status != 'payment_pending':
                review_errors.append('هذا الطلب ليس بانتظار دفع التصريح.')

            payment_receipt = request.FILES.get('payment_receipt')

            if not payment_receipt:
                review_errors.append('يرجى إرفاق إيصال دفع التصريح.')
            else:
                ext = os.path.splitext(payment_receipt.name)[1].lower()
                if ext not in ALLOWED_DOC_EXTENSIONS:
                    review_errors.append('إيصال التصريح يجب أن يكون PDF أو صورة.')

            if not review_errors:
                old_status = pirmet.status
                pirmet.payment_receipt = payment_receipt
                if not pirmet.payment_date:
                    pirmet.payment_date = datetime.date.today()
                pirmet.status = 'payment_completed'
                pirmet.save()
                _log_pirmet_change(
                    pirmet,
                    'payment_update',
                    request.user,
                    old_status=old_status,
                    new_status=pirmet.status,
                    notes='Permit payment recorded.',
                )
                return redirect('pirmet_detail', id=pirmet.id)

        if action == 'issue':
            if not _can_admin(request.user):
                review_errors.append('ليس لديك صلاحية لإصدار التصريح.')
            if pirmet.status != 'payment_completed':
                review_errors.append('هذا الطلب غير جاهز للإصدار.')

            if not review_errors:
                old_status = pirmet.status
                pirmet.status = 'issued'
                pirmet.save()
                _log_pirmet_change(
                    pirmet,
                    'status_change',
                    request.user,
                    old_status=old_status,
                    new_status=pirmet.status,
                    notes='Permit issued.',
                )
                return redirect('pirmet_detail', id=pirmet.id)

        if action == 'update_permit_details':
            if not _can_admin(request.user):
                review_errors.append('ليس لديك صلاحية لتحديث بيانات التصريح.')
            if pirmet.status not in {'payment_completed', 'issued'}:
                review_errors.append('تحديث بيانات التصريح متاح بعد السداد.')

            issue_value = request.POST.get('issue_date')
            expiry_value = request.POST.get('expiry_date')

            issue_date = _parse_date(issue_value, required=False)
            expiry_date = _parse_date(expiry_value, required=False)

            if not issue_date and not expiry_date:
                review_errors.append('يرجى إدخال تاريخ إصدار أو انتهاء التصريح.')

            if not review_errors:
                changes = []
                if issue_date:
                    pirmet.issue_date = issue_date
                    changes.append('تاريخ الإصدار')
                if expiry_date:
                    pirmet.dateOfExpiry = expiry_date
                    changes.append('تاريخ الانتهاء')
                if changes:
                    pirmet.save()
                    _log_pirmet_change(
                        pirmet,
                        'details_update',
                        request.user,
                        notes='تم تحديث: ' + '، '.join(changes),
                    )
                return redirect('pirmet_detail', id=pirmet.id)

        if action == 'create':
            if not _can_data_entry(request.user):
                return _render_clearance_list(
                    request,
                    ['You do not have permission to create permits.'],
                )

            errors = []
            company_id = _parse_int(request.POST.get('company_id'))
            expiry_value = request.POST.get('dateOfExpiry')
            documents = request.FILES.getlist('documents')

            company = None
            if not company_id:
                errors.append('Please select a valid company.')
            else:
                company = Company.objects.filter(id=company_id).first()
                if not company:
                    errors.append('Please select a valid company.')

            date_of_expiry = None
            if not expiry_value:
                errors.append('Expiry date is required.')
            else:
                try:
                    date_of_expiry = datetime.date.fromisoformat(expiry_value)
                except ValueError:
                    errors.append('Expiry date is invalid.')

            if not documents:
                errors.append('At least one PDF or image document is required.')
            else:
                invalid_docs = []
                for doc in documents:
                    ext = os.path.splitext(doc.name)[1].lower()
                    if ext not in ALLOWED_DOC_EXTENSIONS:
                        invalid_docs.append(doc.name)
                if invalid_docs:
                    errors.append(
                        'Only PDF, JPG, or PNG files are allowed: '
                        + ', '.join(invalid_docs)
                    )

            if errors:
                return _render_clearance_list(request, errors)

            pirmet = PirmetClearance.objects.create(
                company=company,
                dateOfExpiry=date_of_expiry,
                status='review_pending',
                permit_type='pest_control',
            )
            for doc in documents:
                PirmetDocument.objects.create(pirmet=pirmet, file=doc)

            _log_pirmet_change(
                pirmet,
                'created',
                request.user,
                new_status=pirmet.status,
                notes='Created from clearance list.',
            )
            _log_pirmet_change(
                pirmet,
                'document_upload',
                request.user,
                notes=f'Documents uploaded: {len(documents)}',
            )

            return redirect('clearance_list')

        if action == 'approve':
            if not _can_inspector(request.user):
                return _render_clearance_list(
                    request,
                    ['You do not have permission to review permits.'],
                )

            errors = []
            pirmet_id = _parse_int(request.POST.get('pirmet_id'))
            inspector_id = _parse_int(request.POST.get('inspector_id'))
            remarks = (request.POST.get('remarks') or '').strip()

            pirmet = None
            if not pirmet_id:
                errors.append('Selected permit was not found.')
            else:
                pirmet = PirmetClearance.objects.filter(id=pirmet_id).first()
                if not pirmet:
                    errors.append('Selected permit was not found.')
                elif pirmet.status != 'review_pending':
                    errors.append('This permit is not waiting for review.')

            inspector = None
            if not inspector_id:
                errors.append('Please select a valid inspector.')
            else:
                inspector = Enginer.objects.filter(id=inspector_id).first()
                if not inspector:
                    errors.append('Please select a valid inspector.')

            if errors:
                return _render_clearance_list(request, errors)

            InspectorReview.objects.update_or_create(
                pirmet=pirmet,
                defaults={
                    'inspector': inspector,
                    'isApproved': True,
                    'comments': remarks,
                },
            )
            old_status = pirmet.status
            pirmet.status = 'approved'
            pirmet.approvedRemarks = remarks
            if request.user.is_authenticated:
                pirmet.approvedBy = request.user
            pirmet.save()
            _log_pirmet_change(
                pirmet,
                'status_change',
                request.user,
                old_status=old_status,
                new_status=pirmet.status,
                notes=remarks or 'Approved by inspector.',
            )

            return redirect('clearance_list')

        if action in {'needs_completion', 'reject'}:
            if not _can_inspector(request.user):
                return _render_clearance_list(
                    request,
                    ['You do not have permission to review permits.'],
                )

            errors = []
            pirmet_id = _parse_int(request.POST.get('pirmet_id'))
            inspector_id = _parse_int(request.POST.get('inspector_id'))
            remarks = (request.POST.get('remarks') or '').strip()

            pirmet = None
            if not pirmet_id:
                errors.append('Selected permit was not found.')
            else:
                pirmet = PirmetClearance.objects.filter(id=pirmet_id).first()
                if not pirmet:
                    errors.append('Selected permit was not found.')
                elif pirmet.status != 'review_pending':
                    errors.append('This permit is not waiting for review.')

            inspector = None
            if not inspector_id:
                errors.append('Please select a valid inspector.')
            else:
                inspector = Enginer.objects.filter(id=inspector_id).first()
                if not inspector:
                    errors.append('Please select a valid inspector.')

            if not remarks:
                errors.append('Completion notes are required.')

            if errors:
                return _render_clearance_list(request, errors)

            InspectorReview.objects.update_or_create(
                pirmet=pirmet,
                defaults={
                    'inspector': inspector,
                    'isApproved': False,
                    'comments': remarks,
                },
            )
            old_status = pirmet.status
            pirmet.status = 'needs_completion'
            pirmet.unapprovedReason = remarks
            if request.user.is_authenticated:
                pirmet.unapprovedBy = request.user
            pirmet.save()
            _log_pirmet_change(
                pirmet,
                'status_change',
                request.user,
                old_status=old_status,
                new_status=pirmet.status,
                notes=remarks or 'Returned for completion by inspector.',
            )

            return redirect('clearance_list')

        if action == 'send_payment_link':
            if not _can_admin(request.user):
                return _render_clearance_list(
                    request,
                    ['You do not have permission to send payment links.'],
                )

            errors = []
            pirmet_id = _parse_int(request.POST.get('pirmet_id'))
            payment_link = (request.POST.get('payment_link') or '').strip()
            payment_email = (request.POST.get('payment_email') or '').strip()
            payment_number = (request.POST.get('payment_number') or '').strip()

            pirmet = None
            if not pirmet_id:
                errors.append('Selected permit was not found.')
            else:
                pirmet = PirmetClearance.objects.filter(id=pirmet_id).first()
                if not pirmet:
                    errors.append('Selected permit was not found.')
                elif pirmet.status != 'approved':
                    errors.append(
                        'This permit is not waiting for payment link.',
                    )

            if not payment_link:
                errors.append('Payment link is required.')
            if not payment_email:
                errors.append('Payment email is required.')
            if not payment_number:
                errors.append('Payment reference is required.')

            if errors:
                return _render_clearance_list(request, errors)

            old_status = pirmet.status
            pirmet.payment_link = payment_link
            pirmet.payment_email = payment_email
            pirmet.PaymentNumber = payment_number
            pirmet.status = 'payment_pending'
            pirmet.save()
            _log_pirmet_change(
                pirmet,
                'status_change',
                request.user,
                old_status=old_status,
                new_status=pirmet.status,
                notes=f'Payment link sent to {payment_email}: {payment_link}',
            )

            return redirect('clearance_list')

        if action == 'send_inspection_payment_link':
            if not _can_admin(request.user):
                return _render_clearance_list(
                    request,
                    ['You do not have permission to send inspection payment links.'],
                )

            errors = []
            pirmet_id = _parse_int(request.POST.get('pirmet_id'))
            payment_link = (request.POST.get('inspection_payment_link') or '').strip()
            payment_reference = (request.POST.get('inspection_payment_reference') or '').strip()
            payment_email = (request.POST.get('inspection_payment_email') or '').strip()

            pirmet = None
            if not pirmet_id:
                errors.append('Selected permit was not found.')
            else:
                pirmet = PirmetClearance.objects.filter(id=pirmet_id).first()
                if not pirmet:
                    errors.append('Selected permit was not found.')
                elif pirmet.status != 'order_received':
                    errors.append(
                        'This permit is not waiting for inspection payment link.',
                    )

            if not payment_link:
                errors.append('Inspection payment link is required.')
            if not payment_email:
                errors.append('Inspection payment email is required.')
            if not payment_reference:
                errors.append('Inspection payment reference is required.')

            if errors:
                return _render_clearance_list(request, errors)

            old_status = pirmet.status
            pirmet.inspection_payment_link = payment_link
            pirmet.inspection_payment_reference = payment_reference
            pirmet.inspection_payment_email = payment_email
            pirmet.status = 'inspection_payment_pending'
            pirmet.save()
            _log_pirmet_change(
                pirmet,
                'status_change',
                request.user,
                old_status=old_status,
                new_status=pirmet.status,
                notes=f'Inspection payment link sent to {payment_email}: {payment_link}',
            )

            return redirect('clearance_list')

        if action == 'inspection_payment':
            if not _can_admin(request.user):
                return _render_clearance_list(
                    request,
                    ['You do not have permission to record inspection payments.'],
                )

            errors = []
            pirmet_id = _parse_int(request.POST.get('pirmet_id'))
            payment_reference = (request.POST.get('inspection_payment_reference') or '').strip()
            payment_receipt = request.FILES.get('inspection_payment_receipt')

            pirmet = None
            if not pirmet_id:
                errors.append('Selected permit was not found.')
            else:
                pirmet = PirmetClearance.objects.filter(id=pirmet_id).first()
                if not pirmet:
                    errors.append('Selected permit was not found.')
                elif pirmet.status != 'inspection_payment_pending':
                    errors.append('This permit is not waiting for inspection payment.')

            if not payment_reference:
                errors.append('Inspection payment reference is required.')
            if not payment_receipt:
                errors.append('Inspection payment receipt is required.')
            elif payment_receipt:
                ext = os.path.splitext(payment_receipt.name)[1].lower()
                if ext not in ALLOWED_DOC_EXTENSIONS:
                    errors.append('Inspection payment receipt must be PDF or image.')

            if errors:
                return _render_clearance_list(request, errors)

            old_status = pirmet.status
            pirmet.inspection_payment_reference = payment_reference
            if payment_receipt:
                pirmet.inspection_payment_receipt = payment_receipt
            pirmet.status = 'review_pending'
            pirmet.save()
            _log_pirmet_change(
                pirmet,
                'payment_update',
                request.user,
                old_status=old_status,
                new_status=pirmet.status,
                notes=f'Inspection payment recorded: {payment_reference}',
            )

            return redirect('clearance_list')

        if action == 'payment':
            if not _can_admin(request.user):
                return _render_clearance_list(
                    request,
                    ['You do not have permission to record payments.'],
                )

            errors = []
            pirmet_id = _parse_int(request.POST.get('pirmet_id'))
            payment_number = (request.POST.get('payment_number') or '').strip()
            payment_receipt = request.FILES.get('payment_receipt')

            pirmet = None
            if not pirmet_id:
                errors.append('Selected permit was not found.')
            else:
                pirmet = PirmetClearance.objects.filter(id=pirmet_id).first()
                if not pirmet:
                    errors.append('Selected permit was not found.')
                elif pirmet.status != 'payment_pending':
                    errors.append('This permit is not waiting for payment.')

            if not payment_receipt:
                errors.append('Payment receipt is required.')
            elif payment_receipt:
                ext = os.path.splitext(payment_receipt.name)[1].lower()
                if ext not in ALLOWED_DOC_EXTENSIONS:
                    errors.append('Payment receipt must be PDF or image.')

            if errors:
                return _render_clearance_list(request, errors)

            old_status = pirmet.status
            if payment_number:
                pirmet.PaymentNumber = payment_number
            if payment_receipt:
                pirmet.payment_receipt = payment_receipt
            if not pirmet.payment_date:
                pirmet.payment_date = datetime.date.today()
            pirmet.status = 'payment_completed'
            pirmet.save()
            _log_pirmet_change(
                pirmet,
                'payment_update',
                request.user,
                old_status=old_status,
                new_status=pirmet.status,
                notes=f'Payment recorded: {payment_number}',
            )

            return redirect('clearance_list')

        if action == 'issue':
            if not _can_admin(request.user):
                return _render_clearance_list(
                    request,
                    ['You do not have permission to issue permits.'],
                )

            errors = []
            pirmet_id = _parse_int(request.POST.get('pirmet_id'))
            pirmet = None
            if not pirmet_id:
                errors.append('Selected permit was not found.')
            else:
                pirmet = PirmetClearance.objects.filter(id=pirmet_id).first()
                if not pirmet:
                    errors.append('Selected permit was not found.')
                elif pirmet.status != 'payment_completed':
                    errors.append('This permit is not ready to be issued.')

            if errors:
                return _render_clearance_list(request, errors)

            old_status = pirmet.status
            pirmet.status = 'issued'
            pirmet.save()
            _log_pirmet_change(
                pirmet,
                'status_change',
                request.user,
                old_status=old_status,
                new_status=pirmet.status,
                notes='Permit issued.',
            )

            return redirect('clearance_list')

        if action == 'delete':
            if not _can_admin(request.user):
                return _render_clearance_list(
                    request,
                    ['You do not have permission to delete permits.'],
                )

            errors = []
            pirmet_id = _parse_int(request.POST.get('pirmet_id'))
            if not pirmet_id:
                errors.append('Selected permit was not found.')
            else:
                pirmet = PirmetClearance.objects.filter(id=pirmet_id).first()
                if not pirmet:
                    errors.append('Selected permit was not found.')
                else:
                    pirmet.delete()

            if errors:
                return _render_clearance_list(request, errors)

            return redirect('clearance_list')

        return redirect('clearance_list')

    return _render_clearance_list(request)

def pirmet_detail(request, id):
    pirmet = get_object_or_404(
        PirmetClearance.objects.select_related('company', 'company__enginer')
        .prefetch_related('documents'),
        id=id,
    )
    review_errors = []
    if request.method == 'POST':
        if not request.user.is_authenticated:
            return redirect('login')

        action = request.POST.get('action')
        if action == 'complete_missing':
            if not _can_data_entry(request.user):
                review_errors.append('ليس لديك صلاحية لاستكمال النواقص.')

            if pirmet.status != 'needs_completion':
                review_errors.append('هذا الطلب ليس بحاجة لاستكمال نواقص.')

            notes = (request.POST.get('completion_notes') or '').strip()
            documents = request.FILES.getlist('documents')

            invalid_docs = []
            for doc in documents:
                ext = os.path.splitext(doc.name)[1].lower()
                if ext not in ALLOWED_DOC_EXTENSIONS:
                    invalid_docs.append(doc.name)
            if invalid_docs:
                review_errors.append(
                    'يُسمح فقط بملفات PDF أو صور (JPG/PNG): '
                    + ', '.join(invalid_docs)
                )

            if not documents and not notes:
                review_errors.append('يرجى إضافة مستندات أو كتابة توضيح للنواقص المستكملة.')

            if not review_errors:
                if documents:
                    if pirmet.permit_type == 'pest_control':
                        _append_documents_bundle(pirmet, documents)
                        _log_pirmet_change(
                            pirmet,
                            'document_upload',
                            request.user,
                            notes='Additional documents appended to bundle.',
                        )
                    else:
                        for doc in documents:
                            PirmetDocument.objects.create(pirmet=pirmet, file=doc)
                        _log_pirmet_change(
                            pirmet,
                            'document_upload',
                            request.user,
                            notes=f'Documents uploaded: {len(documents)}',
                        )

                if notes:
                    _log_pirmet_change(
                        pirmet,
                        'details_update',
                        request.user,
                        notes=notes,
                    )

                old_status = pirmet.status
                pirmet.status = 'review_pending'
                pirmet.save()
                _log_pirmet_change(
                    pirmet,
                    'status_change',
                    request.user,
                    old_status=old_status,
                    new_status=pirmet.status,
                    notes='Completed missing requirements.',
                )

                return redirect('pirmet_detail', id=pirmet.id)

        if action in {'approve', 'needs_completion', 'reject'}:
            if not _can_inspector(request.user):
                review_errors.append('ليس لديك صلاحية لمراجعة التصاريح.')

            inspector_id = _parse_int(request.POST.get('inspector_id'))
            remarks = (request.POST.get('remarks') or '').strip()

            if pirmet.status != 'review_pending':
                review_errors.append('هذا الطلب ليس بانتظار المراجعة.')

            inspector = None
            if not inspector_id:
                review_errors.append('يرجى اختيار المفتش.')
            else:
                inspector = Enginer.objects.filter(id=inspector_id).first()
                if not inspector:
                    review_errors.append('يرجى اختيار مفتش صحيح.')

            if action in {'needs_completion', 'reject'} and not remarks:
                review_errors.append('يرجى كتابة النواقص المطلوبة.')

            if not review_errors:
                InspectorReview.objects.update_or_create(
                    pirmet=pirmet,
                    defaults={
                        'inspector': inspector,
                        'isApproved': action == 'approve',
                        'comments': remarks,
                    },
                )
                old_status = pirmet.status
                if action == 'approve':
                    pirmet.status = 'approved'
                    pirmet.approvedRemarks = remarks
                    if request.user.is_authenticated:
                        pirmet.approvedBy = request.user
                    pirmet.save()
                    _log_pirmet_change(
                        pirmet,
                        'status_change',
                        request.user,
                        old_status=old_status,
                        new_status=pirmet.status,
                        notes=remarks or 'Approved by inspector.',
                    )
                else:
                    pirmet.status = 'needs_completion'
                    pirmet.unapprovedReason = remarks
                    if request.user.is_authenticated:
                        pirmet.unapprovedBy = request.user
                    pirmet.save()
                    _log_pirmet_change(
                        pirmet,
                        'status_change',
                        request.user,
                        old_status=old_status,
                        new_status=pirmet.status,
                        notes=remarks or 'Returned for completion by inspector.',
                    )

                return redirect('pirmet_detail', id=pirmet.id)

    transport_details = PesticideTransportPermit.objects.filter(pirmet=pirmet).first()
    waste_details = WasteDisposalPermit.objects.filter(pirmet=pirmet).first()
    changes = (
        PirmetChangeLog.objects.filter(pirmet=pirmet)
        .select_related('changed_by')
        .order_by('-created_at')
    )
    inspector_review = InspectorReview.objects.filter(pirmet=pirmet).first()
    disposal_process = DisposalProcess.objects.filter(pirmet=pirmet).first()
    inspection_report = (
        InspectionReport.objects.filter(disposal=disposal_process).first()
        if disposal_process
        else None
    )

    def _split_activities(value):
        if not value:
            return []
        items = [item.strip() for item in value.split(',') if item.strip()]
        return items

    status_changes = [
        change
        for change in changes
        if change.change_type in {'created', 'status_change', 'payment_update'}
    ]
    status_changes.reverse()
    detail_changes = [
        change
        for change in changes
        if change.change_type in {'details_update', 'document_upload'}
    ]
    detail_changes.reverse()

    return render(
        request,
        'hcsd/pirmet_detail.html',
        {
            'pirmet': pirmet,
            'inspector_review': inspector_review,
            'disposal_process': disposal_process,
            'inspection_report': inspection_report,
            'allowed_activities': _split_activities(pirmet.allowed_activities),
            'restricted_activities': _split_activities(pirmet.restricted_activities),
            'transport_details': transport_details,
            'waste_details': waste_details,
            'changes': changes,
            'status_changes': status_changes,
            'detail_changes': detail_changes,
            'review_errors': review_errors,
            'can_review_pirmet': _can_inspector(request.user),
            'can_complete_missing': _can_data_entry(request.user),
            'can_record_payment': _can_admin(request.user),
            'can_issue_pirmet': _can_admin(request.user),
            'can_update_pirmet': _can_admin(request.user),
            'engineers': Enginer.objects.all().order_by('name'),
        },
    )


def pirmet_print(request, id):
    pirmet = get_object_or_404(
        PirmetClearance.objects.select_related('company', 'company__enginer'),
        id=id,
    )
    if pirmet.status not in {'payment_completed', 'issued'}:
        return redirect('pirmet_detail', id=pirmet.id)

    transport_details = PesticideTransportPermit.objects.filter(pirmet=pirmet).first()
    waste_details = WasteDisposalPermit.objects.filter(pirmet=pirmet).first()
    inspector_review = InspectorReview.objects.filter(pirmet=pirmet).first()

    def _split_activities(value):
        if not value:
            return []
        items = [item.strip() for item in value.split(',') if item.strip()]
        return items

    return render(
        request,
        'hcsd/pirmet_print.html',
        {
            'pirmet': pirmet,
            'transport_details': transport_details,
            'waste_details': waste_details,
            'inspector_review': inspector_review,
            'allowed_activities': _split_activities(pirmet.allowed_activities),
            'restricted_activities': _split_activities(pirmet.restricted_activities),
        },
    )



def company_list(request):
    query = (request.GET.get('q') or '').strip()
    activity_filter = (request.GET.get('activity') or 'all').strip()
    sort = (request.GET.get('sort') or 'name_asc').strip()

    companies = Company.objects.all()
    if query:
        companies = companies.filter(
            Q(name__icontains=query) | Q(number__icontains=query)
        )

    issued_pest_permits = (
        PirmetClearance.objects.filter(
            status='issued', permit_type='pest_control'
        )
        .order_by('-issue_date', '-dateOfCreation')
    )
    companies = companies.order_by('name').prefetch_related(
        Prefetch(
            'pirmetclearance_set',
            queryset=issued_pest_permits,
            to_attr='issued_pest_permits',
        )
    )

    activity_map = {
        'public_health_pest_control': 'مكافحة آفات الصحة العامة',
        'termite_control': 'مكافحة النمل الأبيض',
        'grain_pests': 'مكافحة آفات الحبوب',
        'flying_insects': 'مكافحة الحشرات الطائرة',
        'rodents': 'مكافحة القوارض',
    }

    company_rows = []
    for company in companies:
        permit = (
            company.issued_pest_permits[0]
            if getattr(company, 'issued_pest_permits', [])
            else None
        )
        activity_keys = []
        if permit and permit.allowed_activities:
            activity_keys = [
                item.strip()
                for item in permit.allowed_activities.split(',')
                if item.strip()
            ]
        elif company.pest_control_type:
            activity_keys = [company.pest_control_type]
        if 'termite_control' in activity_keys and 'public_health_pest_control' not in activity_keys:
            activity_keys = ['public_health_pest_control'] + activity_keys
        activity_labels = [
            activity_map.get(key, key) for key in activity_keys if key
        ]
        if permit and permit.allowed_other:
            activity_labels.append(f'أخرى: {permit.allowed_other}')
        if not activity_labels:
            activity_labels = ['غير مصرح']

        last_issued = None
        if permit:
            last_issued = permit.issue_date or permit.dateOfCreation

        if activity_filter != 'all':
            if activity_filter not in activity_keys:
                continue

        company_rows.append(
            {
                'company': company,
                'activity_labels': activity_labels,
                'last_issued': last_issued,
            }
        )

    def _sort_key(row, missing_date):
        if sort.startswith('number'):
            return (row['company'].number or '').lower()
        if sort.startswith('last_issued'):
            return row['last_issued'] or missing_date
        return (row['company'].name or '').lower()

    reverse = sort.endswith('_desc')
    if sort.startswith('last_issued'):
        missing = (
            datetime.date.min
            if reverse
            else datetime.date.max
        )
        company_rows = sorted(
            company_rows,
            key=lambda row: _sort_key(row, missing),
            reverse=reverse,
        )
    else:
        company_rows = sorted(
            company_rows,
            key=lambda row: _sort_key(row, datetime.date.min),
            reverse=reverse,
        )

    return render(
        request,
        'hcsd/companyes_info.html',
        {
            'company_rows': company_rows,
            'query': query,
            'activity_filter': activity_filter,
            'sort': sort,
            'can_add_company': _can_data_entry(request.user),
        },
    )


def company_detail(request, id):
    company = get_object_or_404(Company, id=id)
    error = None
    extension_error = None
    selected_business_activities = company.business_activity_list()
    selected_pest_control_type = company.pest_control_type or ''
    form_data = {
        'name': company.name,
        'number': company.number,
        'address': company.address,
        'trade_license_exp': company.trade_license_exp.isoformat()
        if company.trade_license_exp
        else '',
        'landline': company.landline or '',
        'owner_phone': company.owner_phone or '',
        'email': company.email or '',
        'enginer_id': str(company.enginer_id) if company.enginer_id else '',
    }

    if request.method == 'POST':
        if not request.user.is_authenticated:
            return redirect('login')
        action = request.POST.get('action')
        if action == 'request_extension':
            if not _can_data_entry(request.user):
                return HttpResponseForbidden('You do not have permission to request extensions.')

            extension_type = (request.POST.get('extension_type') or '').strip()
            extension_doc = request.FILES.get('extension_document')
            if not extension_type:
                extension_error = 'يرجى إدخال نوع المهلة.'
            if not extension_doc:
                extension_error = extension_error or 'يرجى إرفاق مستند المهلة.'
            else:
                ext = os.path.splitext(extension_doc.name)[1].lower()
                if ext not in ALLOWED_DOC_EXTENSIONS:
                    extension_error = 'المستندات المسموحة هي PDF أو صور فقط.'

            if not extension_error:
                _log_company_change(
                    company,
                    'extension_requested',
                    request.user,
                    notes=f'طلب مهلة: {extension_type}',
                    attachment=extension_doc,
                )
                return redirect('company_detail', id=company.id)
        else:
            if not _can_admin(request.user):
                return HttpResponseForbidden('You do not have permission to edit companies.')

            name = (request.POST.get('name') or '').strip()
            number = (request.POST.get('number') or '').strip()
            address = (request.POST.get('address') or '').strip()
            trade_license_exp_value = request.POST.get('trade_license_exp')
            landline = (request.POST.get('landline') or '').strip()
            owner_phone = (request.POST.get('owner_phone') or '').strip()
            email = (request.POST.get('email') or '').strip()
            business_activity_values = [
                item.strip()
                for item in request.POST.getlist('business_activity')
                if item.strip()
            ]
            business_activity = ','.join(business_activity_values)
            enginer_id = request.POST.get('enginer')
            pest_control_type = request.POST.get('pest_control_type')

            form_data = {
                'name': name,
                'number': number,
                'address': address,
                'trade_license_exp': trade_license_exp_value or '',
                'landline': landline,
                'owner_phone': owner_phone,
                'email': email,
                'enginer_id': enginer_id or '',
            }
            selected_business_activities = business_activity_values
            selected_pest_control_type = pest_control_type or ''

            if not name or not number or not address or not enginer_id:
                error = 'يرجى تعبئة جميع الحقول المطلوبة.'
            elif not pest_control_type:
                error = 'يرجى اختيار نوع المكافحة.'

            trade_license_exp = None
            if not error and trade_license_exp_value:
                trade_license_exp = _parse_date(
                    trade_license_exp_value,
                    errors=None,
                    required=False,
                )
                if trade_license_exp is None:
                    error = 'تاريخ انتهاء الرخصة غير صالح.'

            enginer = None
            if not error:
                try:
                    enginer = Enginer.objects.get(id=enginer_id)
                except Enginer.DoesNotExist:
                    error = 'لم يتم العثور على المهندس.'

            if not error:
                if not enginer.public_health_cert:
                    error = 'لا يمكن اختيار المهندس قبل إرفاق شهادة نجاح الصحة العامة.'
                elif pest_control_type == 'termite_control' and not enginer.termite_cert:
                    error = 'لا يمكن اختيار مهندس لمكافحة النمل الأبيض بدون شهادة النمل الأبيض.'

            if not error:
                old_enginer = company.enginer
                changed_labels = []

                def _track(label, old, new):
                    if old != new:
                        changed_labels.append(label)

                _track('الاسم التجاري', company.name, name)
                _track('رقم الرخصة التجارية', company.number, number)
                _track('عنوان الشركة', company.address, address)
                _track('تاريخ انتهاء الرخصة التجارية', company.trade_license_exp, trade_license_exp)
                _track('أنشطة الرخصة', company.business_activity or '', business_activity or '')
                _track('رقم الهاتف الأرضي', company.landline or '', landline or '')
                _track('رقم هاتف المالك', company.owner_phone or '', owner_phone or '')
                _track('البريد الإلكتروني', company.email or '', email or '')
                _track('نوع المكافحة', company.pest_control_type or '', pest_control_type or '')

                engineer_changed = company.enginer_id != enginer.id

                company.name = name
                company.number = number
                company.address = address
                company.trade_license_exp = trade_license_exp
                company.business_activity = business_activity or None
                company.landline = landline or None
                company.owner_phone = owner_phone or None
                company.email = email or None
                company.pest_control_type = pest_control_type
                company.enginer = enginer
                company.save()

                if engineer_changed:
                    old_name = old_enginer.name if old_enginer else 'بدون مهندس'
                    new_name = enginer.name if enginer else 'بدون مهندس'
                    _log_company_change(
                        company,
                        'engineer_changed',
                        request.user,
                        notes=f'تغيير المهندس من {old_name} إلى {new_name}',
                    )

                if changed_labels:
                    _log_company_change(
                        company,
                        'updated',
                        request.user,
                        notes='تم تحديث: ' + '، '.join(changed_labels),
                    )

                return redirect('company_detail', id=company.id)

    logs = company.change_logs.order_by('-created_at')
    today = datetime.date.today()
    valid_filter = Q(dateOfExpiry__isnull=True) | Q(dateOfExpiry__gte=today)

    def _latest_valid(permit_type):
        return (
            PirmetClearance.objects.filter(
                company=company, status='issued', permit_type=permit_type
            )
            .filter(valid_filter)
            .order_by('-issue_date', '-dateOfCreation')
            .first()
        )

    permit_definitions = [
        ('pest_control', 'النشاط', 'pest_control_permit'),
        ('pesticide_transport', 'المركبة', 'pesticide_transport_permit'),
        ('waste_disposal', 'التخلص', 'waste_disposal_permit'),
    ]
    permit_statuses = []
    for permit_type, label, form_view in permit_definitions:
        valid_permit = _latest_valid(permit_type)
        permit_statuses.append(
            {
                'permit_type': permit_type,
                'label': label,
                'form_view': form_view,
                'permit_id': valid_permit.id if valid_permit else None,
                'is_valid': bool(valid_permit),
            }
        )

    return render(
        request,
        'hcsd/company_details.html',
        {
            'company': company,
            'engineers': Enginer.objects.all().order_by('name'),
            'business_activity_choices': BUSINESS_ACTIVITY_CHOICES,
            'selected_business_activities': selected_business_activities,
            'selected_pest_control_type': selected_pest_control_type,
            'form_data': form_data,
            'can_edit_company': _can_admin(request.user),
            'error': error,
            'extension_error': extension_error,
            'can_request_extension': _can_data_entry(request.user),
            'logs': logs,
            'permit_statuses': permit_statuses,
        },
    )

def add_company(request):
    if not request.user.is_authenticated:
        return redirect('login')
    if not _can_data_entry(request.user):
        return HttpResponseForbidden('You do not have permission to add companies.')

    if request.method == 'POST':
        name = (request.POST.get('name') or '').strip()
        number = (request.POST.get('number') or '').strip()
        address = (request.POST.get('address') or '').strip()
        trade_license_exp_value = request.POST.get('trade_license_exp')
        landline = (request.POST.get('landline') or '').strip()
        owner_phone = (request.POST.get('owner_phone') or '').strip()
        email = (request.POST.get('email') or '').strip()
        business_activity_values = [
            item.strip()
            for item in request.POST.getlist('business_activity')
            if item.strip()
        ]
        business_activity = ','.join(business_activity_values)
        enginer_id = request.POST.get('enginer')
        pest_control_type = request.POST.get('pest_control_type')

        error = None
        if not name or not number or not address or not enginer_id:
            error = 'يرجى تعبئة جميع الحقول المطلوبة.'
        elif not pest_control_type:
            error = 'يرجى اختيار نوع المكافحة.'
        else:
            trade_license_exp = None
            if trade_license_exp_value:
                trade_license_exp = _parse_date(
                    trade_license_exp_value,
                    errors=None,
                    required=False,
                )
                if trade_license_exp is None:
                    error = 'تاريخ انتهاء الرخصة غير صالح.'

        if error:
            return render(
                request,
                'hcsd/add_company.html',
                {
                    'error': error,
                    'engineers': Enginer.objects.all().order_by('name'),
                    'form_data': {
                        'name': name,
                        'number': number,
                        'address': address,
                        'trade_license_exp': trade_license_exp_value,
                        'landline': landline,
                        'owner_phone': owner_phone,
                        'email': email,
                        'enginer_id': enginer_id,
                    },
                    'selected_pest_control_type': pest_control_type,
                    'selected_business_activities': business_activity_values,
                },
            )

        try:
            enginer = Enginer.objects.get(id=enginer_id)
            if not enginer.public_health_cert:
                return render(
                    request,
                    'hcsd/add_company.html',
                    {
                        'error': 'لا يمكن اختيار المهندس قبل إرفاق شهادة نجاح الصحة العامة.',
                        'engineers': Enginer.objects.all().order_by('name'),
                        'form_data': {
                            'name': name,
                            'number': number,
                            'address': address,
                            'trade_license_exp': trade_license_exp_value,
                            'landline': landline,
                            'owner_phone': owner_phone,
                            'email': email,
                            'enginer_id': enginer_id,
                        },
                        'selected_pest_control_type': pest_control_type,
                        'selected_business_activities': business_activity_values,
                    },
                )
            if pest_control_type == 'termite_control' and not enginer.termite_cert:
                return render(
                    request,
                    'hcsd/add_company.html',
                    {
                        'error': 'لا يمكن اختيار مهندس لمكافحة النمل الأبيض بدون شهادة النمل الأبيض.',
                        'engineers': Enginer.objects.all().order_by('name'),
                        'form_data': {
                            'name': name,
                            'number': number,
                            'address': address,
                            'trade_license_exp': trade_license_exp_value,
                            'landline': landline,
                            'owner_phone': owner_phone,
                            'email': email,
                            'enginer_id': enginer_id,
                        },
                        'selected_pest_control_type': pest_control_type,
                        'selected_business_activities': business_activity_values,
                    },
                )
            company = Company.objects.create(
                name=name,
                number=number,
                address=address,
                trade_license_exp=trade_license_exp,
                business_activity=business_activity or None,
                landline=landline or None,
                owner_phone=owner_phone or None,
                email=email or None,
                enginer=enginer,
                pest_control_type=pest_control_type,
            )
            _log_company_change(company, 'created', request.user)
            return redirect('company_list')
        except Enginer.DoesNotExist:
            return render(
                request,
                'hcsd/add_company.html',
                {
                    'error': 'لم يتم العثور على المهندس.',
                    'engineers': Enginer.objects.all().order_by('name'),
                    'form_data': {
                        'name': name,
                        'number': number,
                        'address': address,
                        'enginer_id': enginer_id,
                    },
                    'selected_pest_control_type': pest_control_type,
                },
            )
    
    engineers = Enginer.objects.all().order_by('name')
    return render(request, 'hcsd/add_company.html', {'engineers': engineers})


def enginer_list(request):
    if not request.user.is_authenticated:
        return redirect('login')
    if not _can_data_entry(request.user):
        return HttpResponseForbidden('You do not have permission to manage engineers.')

    if request.method == 'POST':
        name = (request.POST.get('name') or '').strip()
        email = (request.POST.get('email') or '').strip()
        phone = (request.POST.get('phone') or '').strip()
        public_health_cert = request.FILES.get('public_health_cert')
        termite_cert = request.FILES.get('termite_cert')

        error = None
        if not name or not email or not phone:
            error = 'يرجى تعبئة جميع الحقول المطلوبة.'
        elif Enginer.objects.filter(email=email).exists():
            error = 'هذا البريد الإلكتروني مسجل مسبقاً.'
        elif not public_health_cert:
            error = 'يرجى إرفاق شهادة نجاح الصحة العامة.'
        else:
            invalid_docs = []
            for doc in [public_health_cert, termite_cert]:
                if not doc:
                    continue
                ext = os.path.splitext(doc.name)[1].lower()
                if ext not in ALLOWED_DOC_EXTENSIONS:
                    invalid_docs.append(doc.name)
            if invalid_docs:
                error = 'الملفات المسموحة هي PDF أو صور فقط.'
            elif termite_cert and not public_health_cert:
                error = 'لا يمكن إرفاق شهادة النمل الأبيض قبل شهادة الصحة العامة.'

        if error:
            return render(
                request,
                'hcsd/enginer_list.html',
                {
                    'engineers': Enginer.objects.all().order_by('name'),
                    'error': error,
                    'can_add_enginer': _can_data_entry(request.user),
                    'form_data': {
                        'name': name,
                        'email': email,
                        'phone': phone,
                    },
                },
            )

        enginer = Enginer.objects.create(
            name=name,
            email=email,
            phone=phone,
            public_health_cert=public_health_cert,
            termite_cert=termite_cert,
        )
        _log_enginer_status(enginer, 'created')
        _log_enginer_status(enginer, 'public_health_cert_uploaded')
        if termite_cert:
            _log_enginer_status(enginer, 'termite_cert_uploaded')

        return redirect('enginer_list')

    return render(
        request,
        'hcsd/enginer_list.html',
        {
            'engineers': Enginer.objects.all().order_by('name'),
            'can_add_enginer': _can_data_entry(request.user),
        },
    )


def enginer_detail(request, id):
    if not request.user.is_authenticated:
        return redirect('login')

    enginer = get_object_or_404(Enginer, id=id)
    error = None

    if request.method == 'POST':
        if not _can_data_entry(request.user):
            return HttpResponseForbidden('You do not have permission to update engineers.')

        public_health_cert = request.FILES.get('public_health_cert')
        termite_cert = request.FILES.get('termite_cert')

        if not public_health_cert and not termite_cert:
            error = 'يرجى إرفاق شهادة واحدة على الأقل.'
        else:
            invalid_docs = []
            for doc in [public_health_cert, termite_cert]:
                if not doc:
                    continue
                ext = os.path.splitext(doc.name)[1].lower()
                if ext not in ALLOWED_DOC_EXTENSIONS:
                    invalid_docs.append(doc.name)
            if invalid_docs:
                error = 'الملفات المسموحة هي PDF أو صور فقط.'
            elif termite_cert and not (public_health_cert or enginer.public_health_cert):
                error = 'يجب إرفاق شهادة الصحة العامة قبل شهادة النمل الأبيض.'

        if not error:
            if public_health_cert:
                enginer.public_health_cert = public_health_cert
                _log_enginer_status(enginer, 'public_health_cert_uploaded')
            if termite_cert:
                enginer.termite_cert = termite_cert
                _log_enginer_status(enginer, 'termite_cert_uploaded')
            enginer.save()
            return redirect('enginer_detail', id=enginer.id)

    logs = enginer.status_logs.order_by('-created_at')

    return render(
        request,
        'hcsd/enginer_detail.html',
        {
            'enginer': enginer,
            'logs': logs,
            'error': error,
            'can_update_enginer': _can_data_entry(request.user),
        },
    )
