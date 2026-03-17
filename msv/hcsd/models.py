import random

from django.contrib.auth.models import User
from django.db import IntegrityError, models
from django.utils import timezone

# Create your models here.
BUSINESS_ACTIVITY_CHOICES = [
    ('pest_control', 'نشاط مكافحة'),
    ('buy_sell', 'نشاط بيع وشراء'),
    ('cleaning', 'نشاط نظافة'),
]


class Company(models.Model):
    name = models.CharField(max_length=100)
    number = models.CharField(max_length=50)
    address = models.CharField(max_length=255)
    trade_license_exp = models.DateField(null=True, blank=True)
    business_activity = models.TextField(null=True, blank=True)
    landline = models.CharField(max_length=30, null=True, blank=True)
    owner_phone = models.CharField(max_length=30, null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    location_area = models.CharField(max_length=150, null=True, blank=True)
    location_street = models.CharField(max_length=180, null=True, blank=True)
    pest_control_type = models.CharField(
        max_length=30,
        null=True,
        blank=True,
        choices=[
            ('public_health_pest_control', 'Public Health Pest Control'),
            ('termite_control', 'Termite Control'),
            ('grain_pests', 'Grain Pests Control'),
        ],
    )
    enginer = models.ForeignKey(
        'Enginer', on_delete=models.SET_NULL, null=True, blank=True
    )
    engineers = models.ManyToManyField(
        'Enginer',
        blank=True,
        related_name='companies',
    )
    companyDocuments = models.FileField(upload_to='company_documents/', null=True, blank=True)

    def business_activity_list(self):
        if not self.business_activity:
            return []
        return [
            item.strip()
            for item in self.business_activity.split(',')
            if item.strip()
        ]

    @property
    def business_activity_display(self):
        labels = []
        lookup = dict(BUSINESS_ACTIVITY_CHOICES)
        for item in self.business_activity_list():
            labels.append(lookup.get(item, item))
        return '، '.join(labels)

    def __str__(self):
        return self.name
    
class Enginer(models.Model):
    name = models.CharField(max_length=100)
    national_or_unified_number = models.CharField(max_length=50, null=True, blank=True)
    email = models.EmailField()
    phone = models.CharField(max_length=20)
    card_number = models.CharField(max_length=4, unique=True, null=True, blank=True, editable=False)
    public_health_cert = models.FileField(
        upload_to='engineer_certificates/', null=True, blank=True
    )
    public_health_cert_issue_date = models.DateField(null=True, blank=True)
    termite_cert = models.FileField(
        upload_to='engineer_certificates/', null=True, blank=True
    )
    termite_cert_issue_date = models.DateField(null=True, blank=True)

    @property
    def has_public_health_cert(self):
        return bool(self.public_health_cert)

    @property
    def has_termite_cert(self):
        return bool(self.termite_cert)

    @staticmethod
    def _random_card_number():
        return f"{random.randint(0, 9999):04d}"

    def _generate_unique_card_number(self):
        for _ in range(12000):
            candidate = self._random_card_number()
            exists = Enginer.objects.filter(card_number=candidate)
            if self.pk:
                exists = exists.exclude(pk=self.pk)
            if not exists.exists():
                return candidate
        raise RuntimeError('Unable to generate a unique 4-digit card number.')

    def save(self, *args, **kwargs):
        if not self.card_number:
            self.card_number = self._generate_unique_card_number()
        try:
            return super().save(*args, **kwargs)
        except IntegrityError:
            # Retry once in case of a concurrent write collision.
            self.card_number = self._generate_unique_card_number()
            return super().save(*args, **kwargs)

    def __str__(self):
        return self.name
    
class PirmetClearance(models.Model):
    STATUS_CHOICES = [
        ('order_received', 'Order Received'),
        ('inspection_payment_pending', 'Inspection Payment Pending'),
        ('review_pending', 'Pending Inspector Review'),
        ('needs_completion', 'Needs Completion'),
        ('approved', 'Inspector Approved'),
        ('payment_pending', 'Waiting for Payment'),
        ('issued', 'Issued'),
        ('inspection_pending', 'Inspection Pending'),
        ('inspection_completed', 'Inspection Completed'),
        ('violation_payment_link_pending', 'Violation Payment Link Pending'),
        ('violation_payment_pending', 'Violation Payment Pending'),
        ('head_approved', 'الاعتماد النهائي'),
        ('closed_requirements_pending', 'Closed - Requirements Pending'),
        ('cancelled_admin', 'Cancelled Administratively'),
        ('disposal_approved', 'Disposal Approved'),
        ('disposal_rejected', 'Disposal Rejected'),
    ]
    unapprovedReason = models.TextField(null=True, blank=True)
    unapprovedBy = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='unapproved_pirmets')
    approvedBy = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='approved_pirmets')
    approvedRemarks = models.TextField(null=True, blank=True)
    head_approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='head_approved_pirmets')
    head_approved_date = models.DateField(null=True, blank=True)
    head_approved_notes = models.TextField(null=True, blank=True)
    company = models.ForeignKey(Company, on_delete=models.CASCADE)
    dateOfCreation = models.DateField(auto_now_add=True)
    dateOfExpiry = models.DateField(null=True, blank=True)
    permit_no = models.CharField(max_length=50, null=True, blank=True, unique=True, editable=False)
    issue_date = models.DateField(null=True, blank=True)
    allowed_activities = models.TextField(null=True, blank=True)
    restricted_activities = models.TextField(null=True, blank=True)
    allowed_other = models.CharField(max_length=255, null=True, blank=True)
    restricted_other = models.CharField(max_length=255, null=True, blank=True)
    company_rep = models.CharField(max_length=150, null=True, blank=True)
    department_stamp = models.CharField(max_length=150, null=True, blank=True)
    permit_type = models.CharField(
        max_length=30,
        default='pest_control',
        choices=[
            ('pest_control', 'Pest Control Permit'),
            ('pesticide_transport', 'Pesticide Transport Permit'),
            ('waste_disposal', 'Waste Disposal Permit'),
        ],
    )
    payment_date = models.DateField(null=True, blank=True)
    payment_link = models.CharField(max_length=500, null=True, blank=True)
    PaymentNumber = models.CharField(max_length=100, null=True, blank=True)
    payment_email = models.EmailField(null=True, blank=True)
    payment_receipt = models.FileField(
        upload_to='pirmet_documents/payment_receipts/', null=True, blank=True
    )
    inspection_payment_link = models.CharField(max_length=500, null=True, blank=True)
    inspection_payment_reference = models.CharField(max_length=100, null=True, blank=True)
    inspection_payment_email = models.EmailField(null=True, blank=True)
    inspection_payment_receipt = models.FileField(
        upload_to='pirmet_documents/inspection_receipts/', null=True, blank=True
    )
    violation_reference_expiry = models.DateField(null=True, blank=True)
    violation_payment_order_number = models.CharField(max_length=100, null=True, blank=True)
    violation_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    violation_payment_receipt = models.FileField(
        upload_to='pirmet_documents/violation_receipts/', null=True, blank=True
    )
    inspection_requires_insurance = models.BooleanField(default=False)
    insurance_payment_order_number = models.CharField(max_length=100, null=True, blank=True)
    insurance_payment_receipt = models.FileField(
        upload_to='pirmet_documents/insurance_receipts/', null=True, blank=True
    )
    request_email = models.EmailField(null=True, blank=True)
    request_documents_bundle = models.FileField(
        upload_to='pirmet_documents/bundles/', null=True, blank=True
    )
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='order_received')
    
    def _generate_permit_no(self):
        return str(self.pk)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        desired_no = self._generate_permit_no()
        if self.permit_no != desired_no:
            self.permit_no = desired_no
            super().save(update_fields=['permit_no'])

    def __str__(self):
        return f"{self.company.name} - {self.status}"


class PirmetDocument(models.Model):
    pirmet = models.ForeignKey(PirmetClearance, on_delete=models.CASCADE, related_name='documents')
    file = models.FileField(upload_to='pirmet_documents/')
    uploadedAt = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.pirmet.company.name} - {self.file.name}"


class PesticideTransportPermit(models.Model):
    pirmet = models.OneToOneField(
        PirmetClearance, on_delete=models.CASCADE, related_name='transport_details'
    )
    contact_number = models.CharField(max_length=30, null=True, blank=True)
    activity_type = models.CharField(max_length=150, null=True, blank=True)
    vehicle_type = models.CharField(max_length=120, null=True, blank=True)
    vehicle_color = models.CharField(max_length=50, null=True, blank=True)
    vehicle_number = models.CharField(max_length=50, null=True, blank=True)
    vehicle_license_expiry = models.DateField(null=True, blank=True)
    issue_authority = models.CharField(max_length=120, null=True, blank=True)

    def __str__(self):
        return f"{self.pirmet.company.name} - Transport Details"


class WasteDisposalPermit(models.Model):
    pirmet = models.OneToOneField(
        PirmetClearance, on_delete=models.CASCADE, related_name='waste_details'
    )
    waste_classification = models.CharField(max_length=120, null=True, blank=True)
    waste_quantity_monthly = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    waste_types = models.TextField(null=True, blank=True)
    material_state = models.CharField(max_length=80, null=True, blank=True)
    project_number = models.CharField(max_length=80, null=True, blank=True)
    project_type = models.CharField(max_length=120, null=True, blank=True)
    contractors = models.CharField(max_length=150, null=True, blank=True)
    employee_number = models.CharField(max_length=50, null=True, blank=True)
    
    def __str__(self):
        return f"{self.pirmet.company.name} - Waste Details"


class WasteDisposalRequest(models.Model):
    STATUS_CHOICES = [
        ('payment_pending', 'Waiting for Disposal Payment'),
        ('inspection_pending', 'Inspection Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('completed', 'Completed'),
    ]

    WASTE_CLASSIFICATION_CHOICES = [
        ('hazardous', 'المخلفات الخطرة'),
        ('non_hazardous', 'المخلفات الغير خطرة'),
    ]

    WASTE_TYPE_CHOICES = [
        ('empty_pesticide_containers', 'عبوات مبيدات فارغة'),
        ('general_waste', 'نفايات عامة'),
        ('sorted_dry_waste', 'نفايات جافة مفرزة'),
        ('green_waste', 'المخلفات الخضراء'),
        ('tires', 'إطارات'),
        ('commercial_industrial_waste', 'المخلفات التجارية والصناعية'),
        ('wood', 'خشب'),
        ('liquid_waste', 'النفايات السائلة'),
        ('construction_demolition_waste', 'مخلفات الهدم والبناء'),
    ]

    MATERIAL_STATE_CHOICES = [
        ('solid', 'صلبة'),
        ('gas', 'غازية'),
    ]

    permit = models.ForeignKey(
        PirmetClearance,
        on_delete=models.CASCADE,
        related_name='waste_disposal_requests',
    )
    waste_classification = models.CharField(
        max_length=20,
        choices=WASTE_CLASSIFICATION_CHOICES,
        default='hazardous',
    )
    waste_type = models.CharField(
        max_length=40,
        choices=WASTE_TYPE_CHOICES,
        default='empty_pesticide_containers',
    )
    material_state = models.CharField(
        max_length=10,
        choices=MATERIAL_STATE_CHOICES,
        default='solid',
    )
    request_date = models.DateField(auto_now_add=True)
    disposal_reference = models.CharField(max_length=100, null=True, blank=True)
    disposal_payment_receipt = models.FileField(
        upload_to='pirmet_documents/waste_disposal_receipts/', null=True, blank=True
    )
    inspection_notes = models.TextField(null=True, blank=True)
    inspected_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='waste_disposal_inspections',
    )
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='payment_pending')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.permit.company.name} - Disposal Request #{self.id}"


class WasteDisposalRequestDocument(models.Model):
    disposal_request = models.ForeignKey(
        WasteDisposalRequest,
        on_delete=models.CASCADE,
        related_name='documents',
    )
    file = models.FileField(upload_to='pirmet_documents/waste_disposal_request_documents/')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.disposal_request.permit.company.name} - Waste Request Doc #{self.id}"


class InspectorReview(models.Model):
    pirmet = models.OneToOneField(PirmetClearance, on_delete=models.CASCADE)
    inspector = models.ForeignKey(Enginer, on_delete=models.SET_NULL, null=True)
    inspector_user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inspector_reviews',
    )
    reviewDate = models.DateTimeField(auto_now_add=True)
    isApproved = models.BooleanField(default=False)
    comments = models.TextField(blank=True)
    
    def __str__(self):
        return (
            f"{self.pirmet.company.name} - "
            f"{'Approved' if self.isApproved else 'Pending'}"
        )


class DisposalProcess(models.Model):
    pirmet = models.OneToOneField(PirmetClearance, on_delete=models.CASCADE)
    inspectionFee = models.DecimalField(max_digits=10, decimal_places=2, default=200)
    feePaid = models.BooleanField(default=False)
    feePaidDate = models.DateTimeField(null=True, blank=True)
    
    def __str__(self):
        return f"{self.pirmet.company.name} - Disposal"


class InspectionReport(models.Model):
    APPROVAL_CHOICES = [
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('pending', 'Pending'),
    ]
    
    disposal = models.OneToOneField(DisposalProcess, on_delete=models.CASCADE)
    inspector = models.ForeignKey(Enginer, on_delete=models.SET_NULL, null=True)
    inspectionDate = models.DateTimeField(auto_now_add=True)
    approval = models.CharField(max_length=10, choices=APPROVAL_CHOICES, default='pending')
    reportNotes = models.TextField()
    rejectionReason = models.TextField(blank=True, null=True)
    
    def __str__(self):
        return f"{self.disposal.pirmet.company.name} - {self.approval}"


class EnginerStatusLog(models.Model):
    ACTION_CHOICES = [
        ('created', 'Created'),
        ('public_health_cert_uploaded', 'Public Health Certificate Uploaded'),
        ('termite_cert_uploaded', 'Termite Certificate Uploaded'),
    ]

    enginer = models.ForeignKey(
        Enginer, on_delete=models.CASCADE, related_name='status_logs'
    )
    action = models.CharField(max_length=40, choices=ACTION_CHOICES)
    notes = models.TextField(blank=True)
    changed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    archived_file = models.FileField(
        upload_to='engineer_certificates/archive/', null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.enginer.name} - {self.action}"


class EngineerLeave(models.Model):
    """Records an engineer's leave period with optional substitute assignment."""

    engineer = models.ForeignKey(
        Enginer, on_delete=models.CASCADE, related_name='leaves'
    )
    substitute = models.ForeignKey(
        Enginer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='substitute_for',
    )
    start_date = models.DateField()
    expected_return_date = models.DateField(null=True, blank=True)
    actual_return_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='engineer_leaves_created'
    )
    closed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='engineer_leaves_closed'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def is_active(self):
        return self.actual_return_date is None

    def __str__(self):
        return f"{self.engineer.name} - إجازة من {self.start_date}"


class PublicHealthExamRequest(models.Model):
    STATUS_CHOICES = [
        ('submitted', 'بانتظار الاعتماد'),
        ('inspector_approved', 'تم الاعتماد'),
        ('payment_pending', 'بانتظار الدفع'),
        ('scheduled', 'تم حجز الموعد'),
        ('rejected', 'مرفوض'),
        # Legacy statuses kept for old records.
        ('payment_received', 'بانتظار الدفع'),
        ('completed', 'مكتمل'),
    ]

    enginer = models.ForeignKey(
        Enginer,
        on_delete=models.CASCADE,
        related_name='public_health_exam_requests',
    )
    company = models.ForeignKey(
        Company,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='public_health_exam_requests',
    )
    serial_number = models.CharField(max_length=100, null=True, blank=True)
    attempt_number = models.PositiveIntegerField()
    exam_fee = models.DecimalField(max_digits=10, decimal_places=2, default=200)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='submitted')

    request_submission_date = models.DateField(null=True, blank=True)
    exam_number = models.CharField(max_length=100, null=True, blank=True)
    unified_number = models.CharField(max_length=100, null=True, blank=True)
    identity_number = models.CharField(max_length=100, null=True, blank=True)
    exam_language = models.CharField(max_length=50, null=True, blank=True)
    exam_type = models.CharField(max_length=120, null=True, blank=True)
    qualified_technician_name = models.CharField(max_length=200, null=True, blank=True)
    phone_number = models.CharField(max_length=30, null=True, blank=True)
    company_trade_name = models.CharField(max_length=200, null=True, blank=True)
    trade_license_number = models.CharField(max_length=100, null=True, blank=True)

    request_notes = models.TextField(blank=True)
    request_document = models.FileField(
        upload_to='public_health_exam_requests/documents/',
        null=True,
        blank=True,
    )

    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='public_health_exam_reviews',
    )
    review_notes = models.TextField(blank=True)
    recommendation = models.TextField(blank=True)
    exam_result = models.CharField(max_length=120, null=True, blank=True)

    payment_link = models.CharField(max_length=500, null=True, blank=True)
    payment_reference = models.CharField(max_length=120, null=True, blank=True)
    payment_receipt_number = models.CharField(max_length=120, null=True, blank=True)
    payment_receipt_date = models.DateField(null=True, blank=True)
    payment_receipt = models.FileField(
        upload_to='public_health_exam_requests/receipts/',
        null=True,
        blank=True,
    )
    payment_received_at = models.DateTimeField(null=True, blank=True)

    exam_datetime = models.DateTimeField(null=True, blank=True)
    exam_location = models.CharField(max_length=200, null=True, blank=True)

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='public_health_exam_requests_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    @staticmethod
    def fee_for_attempt(attempt_number):
        if attempt_number <= 1:
            return 200
        if attempt_number == 2:
            return 500
        return 1000

    @classmethod
    def next_attempt_number(cls, enginer, exam_type=None):
        if not enginer:
            return 1
        qs = cls.objects.filter(enginer=enginer)
        if exam_type:
            qs = qs.filter(exam_type=exam_type)
        return qs.count() + 1

    def save(self, *args, **kwargs):
        if not self.attempt_number:
            self.attempt_number = self.next_attempt_number(self.enginer, exam_type=self.exam_type)
        if not self.exam_fee:
            self.exam_fee = self.fee_for_attempt(self.attempt_number)
        if not self.request_submission_date:
            self.request_submission_date = timezone.localdate()
        if self.company:
            if not self.company_trade_name:
                self.company_trade_name = self.company.name
            if not self.trade_license_number:
                self.trade_license_number = self.company.number
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.enginer.name} - Exam Request #{self.id} (Attempt {self.attempt_number})"


class EngineerCertificateRequest(models.Model):
    CERTIFICATE_TYPE_CHOICES = [
        ('public_health', 'شهادة اختبار عام'),
        ('termite', 'شهادة النمل الأبيض'),
    ]
    STATUS_CHOICES = [
        ('submitted', 'تم تقديم طلب الشهادة'),
        ('payment_pending', 'بانتظار سداد رسوم الشهادة'),
        ('payment_received', 'تم استلام الإيصال والهوية الإماراتية'),
        ('issued', 'تم إصدار الشهادة'),
        ('rejected', 'مرفوض'),
    ]

    exam_request = models.OneToOneField(
        PublicHealthExamRequest,
        on_delete=models.CASCADE,
        related_name='certificate_request',
        null=True,
        blank=True,
    )
    enginer = models.ForeignKey(
        Enginer,
        on_delete=models.CASCADE,
        related_name='certificate_requests',
    )
    certificate_type = models.CharField(max_length=30, choices=CERTIFICATE_TYPE_CHOICES)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='submitted')

    payment_link = models.CharField(max_length=500, null=True, blank=True)
    payment_order_number = models.CharField(max_length=120, null=True, blank=True)
    payment_receipt = models.FileField(
        upload_to='engineer_certificate_requests/receipts/',
        null=True,
        blank=True,
    )
    emirates_id_document = models.FileField(
        upload_to='engineer_certificate_requests/emirates_id/',
        null=True,
        blank=True,
    )
    payment_received_at = models.DateTimeField(null=True, blank=True)

    issued_certificate = models.FileField(
        upload_to='engineer_certificate_requests/issued_certificates/',
        null=True,
        blank=True,
    )
    certificate_issue_date = models.DateField(null=True, blank=True)
    issued_at = models.DateTimeField(null=True, blank=True)
    issued_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='issued_engineer_certificates',
    )
    rejection_reason = models.TextField(blank=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='engineer_certificate_requests_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.enginer.name} - Certificate Request #{self.id}"


class CompanyChangeLog(models.Model):
    ACTION_CHOICES = [
        ('created', 'Created'),
        ('updated', 'Updated'),
        ('engineer_changed', 'Engineer Changed'),
        ('extension_requested', 'Extension Requested'),
        ('extension_closed', 'Extension Closed'),
        ('requirements_followup_needed', 'Requirements Follow-up Needed'),
        ('requirements_insurance_created', 'Requirements Insurance Created'),
        ('requirements_insurance_paid', 'Requirements Insurance Paid'),
        ('requirements_insurance_refunded', 'Requirements Insurance Refunded'),
        ('waste_permit_created', 'Waste Permit Created'),
        ('waste_permit_payment_reference', 'Waste Permit Payment Reference'),
        ('waste_permit_paid', 'Waste Permit Paid'),
        ('waste_permit_issued', 'Waste Permit Issued'),
        ('waste_request_created', 'Waste Request Created'),
        ('waste_request_payment_reference', 'Waste Request Payment Reference'),
        ('waste_request_paid', 'Waste Request Paid'),
        ('waste_request_inspected', 'Waste Request Inspected'),
    ]

    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name='change_logs'
    )
    action = models.CharField(max_length=60, choices=ACTION_CHOICES)
    notes = models.TextField(blank=True)
    changed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True
    )
    attachment = models.FileField(
        upload_to='company_extension_requests/', null=True, blank=True
    )
    extension_start_date = models.DateField(null=True, blank=True)
    extension_end_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.company.name} - {self.action}"


class PirmetChangeLog(models.Model):
    CHANGE_CHOICES = [
        ('created', 'Created'),
        ('status_change', 'Status Changed'),
        ('payment_update', 'Payment Updated'),
        ('document_upload', 'Documents Uploaded'),
        ('details_update', 'Details Updated'),
    ]

    pirmet = models.ForeignKey(
        PirmetClearance, on_delete=models.CASCADE, related_name='changes'
    )
    change_type = models.CharField(max_length=30, choices=CHANGE_CHOICES)
    old_status = models.CharField(max_length=40, null=True, blank=True)
    new_status = models.CharField(max_length=40, null=True, blank=True)
    notes = models.TextField(blank=True)
    changed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.pirmet.company.name} - {self.change_type}"


class RequirementInsuranceRequest(models.Model):
    STATUS_CHOICES = [
        ('created', 'تم إنشاء الطلب'),
        ('payment_order_recorded', 'تم إدخال أمر دفع التأمين'),
        ('active', 'تم دفع التأمين'),
        ('refunded', 'تم استرداد التأمين'),
        ('cancelled', 'مغلق'),
    ]
    DURATION_CHOICES = [
        (1, 'شهر واحد'),
        (3, '3 أشهر'),
        (6, '6 أشهر'),
    ]

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name='requirement_insurance_requests',
    )
    related_permit = models.ForeignKey(
        PirmetClearance,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='requirement_insurance_requests',
    )
    duration_months = models.PositiveSmallIntegerField(choices=DURATION_CHOICES)
    requirements_notes = models.TextField(blank=True)
    payment_order_number = models.CharField(max_length=100, null=True, blank=True)
    payment_receipt = models.FileField(
        upload_to='requirement_insurance/payment_receipts/',
        null=True,
        blank=True,
    )
    payment_received_at = models.DateTimeField(null=True, blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    refund_reference_number = models.CharField(max_length=100, null=True, blank=True)
    refund_receipt = models.FileField(
        upload_to='requirement_insurance/refund_receipts/',
        null=True,
        blank=True,
    )
    refunded_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='created')
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='requirement_insurance_requests_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f"{self.company.name} - Requirement Insurance #{self.id}"
