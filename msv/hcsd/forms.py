from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError


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
        return user
