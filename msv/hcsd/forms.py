import base64
import binascii
import io
import uuid

from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, UnidentifiedImageError

from .models import MedicalFacility, MedicalWasteInspection, UserProfile


class StaffRegistrationForm(forms.Form):
    full_name = forms.CharField(
        max_length=150,
        label='الاسم',
        widget=forms.TextInput(
            attrs={
                'placeholder': 'الاسم الكامل',
                'autocomplete': 'name',
            }
        ),
    )
    admin_number = forms.CharField(
        max_length=150,
        label='الرقم الإداري',
        widget=forms.TextInput(
            attrs={
                'placeholder': 'أدخل الرقم الإداري',
                'autocomplete': 'username',
                'inputmode': 'numeric',
            }
        ),
    )
    email = forms.EmailField(
        label='البريد الإلكتروني',
        widget=forms.EmailInput(
            attrs={
                'placeholder': 'name@example.com',
                'autocomplete': 'email',
            }
        ),
    )
    password = forms.CharField(
        label='كلمة السر',
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                'placeholder': 'كلمة السر',
                'autocomplete': 'new-password',
            }
        ),
        help_text='استخدم 8 أحرف على الأقل مع مزيج من الحروف/الأرقام.',
    )
    password_confirm = forms.CharField(
        label='تأكيد كلمة السر',
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                'placeholder': 'أعد إدخال كلمة السر',
                'autocomplete': 'new-password',
            }
        ),
    )

    def clean_admin_number(self):
        admin_number = (self.cleaned_data.get('admin_number') or '').strip()
        if not admin_number:
            raise forms.ValidationError('الرقم الإداري مطلوب.')
        if User.objects.filter(username__iexact=admin_number).exists():
            raise forms.ValidationError('هذا الرقم الإداري مستخدم بالفعل.')
        return admin_number

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('هذا البريد الإلكتروني مستخدم بالفعل.')
        return email

    def clean_password(self):
        password = self.cleaned_data.get('password') or ''
        try:
            validate_password(password)
        except ValidationError as exc:
            raise forms.ValidationError(exc.messages)
        return password

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        password_confirm = cleaned_data.get('password_confirm')
        if password and password_confirm and password != password_confirm:
            self.add_error('password_confirm', 'تأكيد كلمة السر غير مطابق.')
        return cleaned_data

    def save(self):
        full_name = (self.cleaned_data['full_name'] or '').strip()
        admin_number = self.cleaned_data['admin_number']
        email = self.cleaned_data['email']
        password = self.cleaned_data['password']

        user = User(
            username=admin_number,
            email=email,
        )
        user.first_name = full_name
        user.set_password(password)
        user.save()
        UserProfile.objects.create(user=user, admin_number=admin_number)
        return user


class MedicalFacilityForm(forms.ModelForm):
    class Meta:
        model = MedicalFacility
        fields = ['name', 'license_number', 'address', 'phone', 'notes']
        error_messages = {'name': {'required': 'يرجى إدخال اسم المنشأة.'}}

    def clean_name(self):
        return self.cleaned_data['name'].strip()

    def clean_license_number(self):
        return self.cleaned_data['license_number'].strip()


MEDICAL_WASTE_MAX_UPLOAD_BYTES = 10 * 1024 * 1024
SIGNATURE_DATA_PREFIX = 'data:image/png;base64,'
SIGNATURE_MAX_DATA_CHARS = 700_000
SIGNATURE_MAX_WIDTH = 1000
SIGNATURE_MAX_HEIGHT = 400
_YES, _NO = 'yes', 'no'


def _signature_png(data_url):
    """The PNG bytes of a signature drawn on the form's pad. The image is
    re-encoded so only pixels are stored, whatever the browser actually sent."""
    invalid = ValidationError('تعذّرت قراءة التوقيع، يرجى التوقيع مرة أخرى.')
    if not data_url.startswith(SIGNATURE_DATA_PREFIX) or len(data_url) > SIGNATURE_MAX_DATA_CHARS:
        raise invalid
    try:
        raw = base64.b64decode(data_url[len(SIGNATURE_DATA_PREFIX):], validate=True)
        image = Image.open(io.BytesIO(raw))
        if (
            image.format != 'PNG'
            or image.width > SIGNATURE_MAX_WIDTH
            or image.height > SIGNATURE_MAX_HEIGHT
        ):
            raise invalid
        output = io.BytesIO()
        image.convert('RGBA').save(output, format='PNG')
    except (binascii.Error, UnidentifiedImageError, OSError, ValueError) as exc:
        raise invalid from exc
    return output.getvalue()


class MedicalWasteInspectionForm(forms.ModelForm):
    """Validates the inspection form; only the chosen inspection type's fields
    are required and kept, so a changed type leaves no stale answers behind."""

    point_1 = forms.TypedChoiceField(
        label='نقطة التفتيش 1', required=False, empty_value=None,
        choices=[(_YES, 'نعم'), (_NO, 'لا')], coerce=lambda value: value == _YES,
    )
    point_2 = forms.TypedChoiceField(
        label='نقطة التفتيش 2', required=False, empty_value=None,
        choices=[(_YES, 'نعم'), (_NO, 'لا')], coerce=lambda value: value == _YES,
    )
    point_3 = forms.TypedChoiceField(
        label='نقطة التفتيش 3', required=False, empty_value=None,
        choices=[(_YES, 'نعم'), (_NO, 'لا')], coerce=lambda value: value == _YES,
    )
    point_4 = forms.TypedChoiceField(
        label='نقطة التفتيش 4', required=False, empty_value=None,
        choices=[(_YES, 'نعم'), (_NO, 'لا')], coerce=lambda value: value == _YES,
    )

    inspector_signature_data = forms.CharField(label='توقيع المفتش', required=False)
    inspector_signature_clear = forms.BooleanField(required=False)
    representative_signature_data = forms.CharField(label='توقيع ممثل المنشأة', required=False)
    representative_signature_clear = forms.BooleanField(required=False)

    POINT_FIELDS = ('point_1', 'point_2', 'point_3', 'point_4')
    SIGNATURE_FIELDS = ('inspector_signature', 'representative_signature')
    # What each inspection type keeps; everything else is reset on save.
    TYPE_ONLY_RESETS = {
        'visit_type': '', 'point_1': None, 'point_2': None, 'point_3': None, 'point_4': None,
        'contract_action': '', 'notice_days': None,
        'waste_medicines': False, 'waste_cosmetics': False, 'waste_lab_chemicals': False,
        'waste_damaged_supplies': False, 'estimated_weight': '', 'letter_action': False,
        'site_report_action': False,
    }
    CONTRACT_FIELDS = {'visit_type', *POINT_FIELDS, 'contract_action', 'notice_days'}
    EXPIRED_FIELDS = {
        'waste_medicines', 'waste_cosmetics', 'waste_lab_chemicals', 'waste_damaged_supplies',
        'estimated_weight', 'letter_action',
    }
    NO_WASTE_FIELDS = {'site_report_action'}

    class Meta:
        model = MedicalWasteInspection
        fields = [
            'inspector_name', 'inspection_date', 'facility', 'inspection_type',
            'visit_type', 'point_1', 'point_2', 'point_3', 'point_4',
            'contract_action', 'notice_days', 'waste_medicines', 'waste_cosmetics',
            'waste_lab_chemicals', 'waste_damaged_supplies', 'estimated_weight', 'letter_action',
            'site_report_action', 'notice_attachment',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        facility = self.fields['facility']
        facility.required = True
        facility.error_messages['required'] = 'يرجى اختيار المنشأة.'
        facility.error_messages['invalid_choice'] = 'المنشأة المختارة غير موجودة.'
        # Templates compare these as strings, bound or not.
        for name in self.POINT_FIELDS:
            answer = self.initial.get(name)
            self.initial[name] = '' if answer is None else (_YES if answer else _NO)
        issued_on = self.initial.get('inspection_date')
        if hasattr(issued_on, 'isoformat'):
            self.initial['inspection_date'] = issued_on.isoformat()

    def _clean_upload(self, name):
        upload = self.cleaned_data.get(name)
        if upload and getattr(upload, 'size', 0) > MEDICAL_WASTE_MAX_UPLOAD_BYTES:
            raise ValidationError('حجم الملف يتجاوز الحد المسموح (10 ميجابايت).')
        return upload

    def clean_inspector_signature_data(self):
        data_url = self.cleaned_data.get('inspector_signature_data')
        return _signature_png(data_url) if data_url else b''

    def clean_representative_signature_data(self):
        data_url = self.cleaned_data.get('representative_signature_data')
        return _signature_png(data_url) if data_url else b''

    def clean_notice_attachment(self):
        return self._clean_upload('notice_attachment')

    def _validate_contract(self, data):
        if not data.get('visit_type'):
            self.add_error('visit_type', 'يرجى تحديد نوع الزيارة.')
        for name in self.POINT_FIELDS:
            if data.get(name) is None and name not in self.errors:
                self.add_error(name, 'يرجى اختيار نعم أو لا.')
        action = data.get('contract_action')
        if not action:
            self.add_error('contract_action', 'يرجى تحديد الإجراء المتخذ.')
        elif action == MedicalWasteInspection.ACTION_NOTICE:
            if not data.get('notice_days') and 'notice_days' not in self.errors:
                self.add_error('notice_days', 'يرجى إدخال مدة الإخطار بالأيام.')
        else:
            data['notice_days'] = None

    def _validate_expired(self, data):
        fields = [field for field, _ in MedicalWasteInspection.WASTE_TYPE_FIELDS]
        if not any(data.get(field) for field in fields):
            self.add_error('waste_medicines', 'يرجى اختيار نوع واحد من النفايات على الأقل.')

    def clean(self):
        data = super().clean()
        inspection_type = data.get('inspection_type')
        kept = {
            MedicalWasteInspection.TYPE_CONTRACT: self.CONTRACT_FIELDS,
            MedicalWasteInspection.TYPE_EXPIRED: self.EXPIRED_FIELDS,
            MedicalWasteInspection.TYPE_NO_WASTE: self.NO_WASTE_FIELDS,
        }.get(inspection_type)
        if kept is None:
            return data
        for name, empty in self.TYPE_ONLY_RESETS.items():
            if name not in kept:
                data[name] = empty
                self.errors.pop(name, None)
        if inspection_type == MedicalWasteInspection.TYPE_CONTRACT:
            self._validate_contract(data)
        elif inspection_type == MedicalWasteInspection.TYPE_EXPIRED:
            self._validate_expired(data)
        return data

    def save(self, commit=True):
        report = super().save(commit=False)
        report.copy_facility_data()
        for name in self.SIGNATURE_FIELDS:
            png = self.cleaned_data.get(f'{name}_data')
            if png:
                getattr(report, name).save(f'{uuid.uuid4().hex}.png', ContentFile(png), save=False)
            elif self.cleaned_data.get(f'{name}_clear'):
                setattr(report, name, '')
        if commit:
            report.save()
        return report
