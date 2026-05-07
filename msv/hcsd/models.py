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
    email = models.EmailField(blank=True, default='')
    phone = models.CharField(max_length=20)
    card_number = models.CharField(max_length=4, unique=True, null=True, blank=True, editable=False)
    public_health_cert = models.FileField(
        upload_to='engineer_certificates/', null=True, blank=True
    )
    public_health_cert_issue_date = models.DateField(null=True, blank=True)
    public_health_cert_expiry_date = models.DateField(null=True, blank=True)
    termite_cert = models.FileField(
        upload_to='engineer_certificates/', null=True, blank=True
    )
    termite_cert_issue_date = models.DateField(null=True, blank=True)
    termite_cert_expiry_date = models.DateField(null=True, blank=True)

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
    unapprovedBy = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='unapproved_pirmets')
    approvedBy = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_pirmets')
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
            ('engineer_addition', 'Engineer Addition Request'),
        ],
    )
    engineer_to_add = models.ForeignKey(
        'Enginer',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='addition_requests',
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
    DOC_TYPE_ENGINEER = 'engineer_doc'
    DOC_TYPE_INSPECTION = 'inspection_photo'
    DOC_TYPE_CHOICES = [
        (DOC_TYPE_ENGINEER, 'مستند مهندس'),
        (DOC_TYPE_INSPECTION, 'صورة/مستند تفتيش'),
    ]

    pirmet = models.ForeignKey(PirmetClearance, on_delete=models.CASCADE, related_name='documents')
    file = models.FileField(upload_to='pirmet_documents/')
    doc_type = models.CharField(max_length=30, choices=DOC_TYPE_CHOICES, default=DOC_TYPE_ENGINEER)
    notes = models.TextField(blank=True, default='')
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
        ('cancelled_admin', 'Cancelled Administratively'),
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


class WasteDisposalInspectionPhoto(models.Model):
    disposal_request = models.ForeignKey(
        WasteDisposalRequest,
        on_delete=models.CASCADE,
        related_name='inspection_photos',
    )
    file = models.FileField(upload_to='pirmet_documents/waste_disposal_inspection_photos/')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='waste_inspection_photos_uploaded',
    )

    def __str__(self):
        return f"{self.disposal_request.permit.company.name} - Inspection Photo #{self.id}"


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
        ('leave_recorded', 'Leave Recorded'),
        ('leave_closed', 'Leave Closed'),
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


class PublicHealthExamRequestDocument(models.Model):
    exam_request = models.ForeignKey(
        PublicHealthExamRequest,
        on_delete=models.CASCADE,
        related_name='documents',
    )
    file = models.FileField(upload_to='public_health_exam_requests/documents/')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['uploaded_at']


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
        ('location_saved', 'Location Saved'),
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


# ══════════════════════════════════════════
#  Complaints System
# ══════════════════════════════════════════

class Complaint(models.Model):
    STATUS_CHOICES = [
        ('new',                 'جديدة'),
        ('assigned_inspector',  'بانتظار التفتيش'),
        ('inspection_done',     'اكتمل التفتيش'),
        ('assigned_supervisor', 'بانتظار المعالجة'),
        ('in_progress',         'قيد المعالجة'),
        ('resolved',            'تم الحل'),
        ('closed',              'مغلقة'),
    ]

    PEST_CHOICES = [
        ('ant',         'نمل'),
        ('mosquito',    'بعوض'),
        ('fly',         'ذباب'),
        ('rat',         'فئران'),
        ('cockroach',   'صراصير'),
        ('honey_bee',   'نحل'),
        ('scorpion',    'عقارب'),
        ('snake',       'ثعبان'),
        ('wasp',        'دبابير'),
        ('lizard',      'سحلية'),
        ('other',       'أخرى'),
    ]

    complaint_number = models.CharField(
        max_length=100,
        verbose_name='رقم الشكوى',
    )
    pdf_file = models.FileField(
        upload_to='complaints/pdfs/',
        verbose_name='ملف الشكوى (PDF)',
        null=True,
        blank=True,
    )
    # Complainant info
    complainant_name = models.CharField(max_length=200, blank=True, verbose_name='اسم المتعامل')
    complainant_mobile = models.CharField(max_length=30, blank=True, verbose_name='موبايل المتعامل')
    area = models.CharField(max_length=200, blank=True, verbose_name='المنطقة')
    street_number = models.CharField(max_length=50, blank=True, verbose_name='رقم الشارع')
    house_number = models.CharField(max_length=50, blank=True, verbose_name='رقم المنزل')
    # Pest types: comma-separated keys from PEST_CHOICES
    pest_types = models.CharField(max_length=200, blank=True, verbose_name='أنواع الآفات')
    notes = models.TextField(
        blank=True,
        verbose_name='ملاحظات',
    )
    latitude = models.DecimalField(
        max_digits=10, decimal_places=7,
        null=True, blank=True,
        verbose_name='خط العرض',
    )
    longitude = models.DecimalField(
        max_digits=10, decimal_places=7,
        null=True, blank=True,
        verbose_name='خط الطول',
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='new',
        verbose_name='الحالة',
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='complaints_created',
        verbose_name='أضيف بواسطة',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'شكوى'
        verbose_name_plural = 'الشكاوي'

    def __str__(self):
        return f"شكوى #{self.complaint_number}"


class ComplaintInspection(models.Model):
    """Inspector visit record: GPS location + photos."""
    complaint = models.OneToOneField(
        Complaint, on_delete=models.CASCADE, related_name='inspection',
        verbose_name='الشكوى',
    )
    inspector = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='complaint_inspections', verbose_name='المفتش',
    )
    assigned_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='complaint_inspections_assigned', verbose_name='أسند بواسطة',
    )
    assigned_at = models.DateTimeField(auto_now_add=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True, verbose_name='خط العرض')
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True, verbose_name='خط الطول')
    location_notes = models.TextField(blank=True, verbose_name='وصف الموقع')
    inspection_notes = models.TextField(blank=True, verbose_name='ملاحظات التفتيش')
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name='تاريخ الإنجاز')

    class Meta:
        verbose_name = 'تفتيش شكوى'
        verbose_name_plural = 'تفتيش الشكاوي'

    def __str__(self):
        return f"تفتيش — {self.complaint}"


class ComplaintResolution(models.Model):
    """Supervisor resolution record: workers, vehicles, days, photos."""
    complaint = models.OneToOneField(
        Complaint, on_delete=models.CASCADE, related_name='resolution',
        verbose_name='الشكوى',
    )
    supervisor = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='complaint_resolutions', verbose_name='المراقب',
    )
    assigned_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='complaint_resolutions_assigned', verbose_name='أسند بواسطة',
    )
    assigned_at = models.DateTimeField(auto_now_add=True)
    CLOSING_STATUS_CHOICES = [
        ('ok',              'تم التنفيذ (OK)'),
        ('no_answer',       'لا يوجد رد'),
        ('private_company', 'أُحيل لشركة خاصة'),
        ('need_ulv',        'يحتاج رش ULV'),
        ('need_approval',   'يحتاج موافقة'),
        ('no_need',         'لا يحتاج تدخل'),
    ]

    num_workers = models.PositiveIntegerField(null=True, blank=True, verbose_name='عدد العمال')
    num_days = models.PositiveIntegerField(null=True, blank=True, verbose_name='عدد الأيام')
    work_notes = models.TextField(blank=True, verbose_name='ملاحظات المعالجة')
    closing_status = models.CharField(
        max_length=20, choices=CLOSING_STATUS_CHOICES,
        blank=True, verbose_name='حالة الإغلاق',
    )
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name='تاريخ الإنجاز')

    class Meta:
        verbose_name = 'معالجة شكوى'
        verbose_name_plural = 'معالجة الشكاوي'

    def __str__(self):
        return f"معالجة — {self.complaint}"


class ComplaintVehicle(models.Model):
    """Vehicle used during complaint resolution."""
    resolution = models.ForeignKey(
        ComplaintResolution, on_delete=models.CASCADE, related_name='vehicles',
        verbose_name='المعالجة',
    )
    plate_number = models.CharField(max_length=50, verbose_name='رقم اللوحة')
    vehicle_type = models.CharField(max_length=100, blank=True, verbose_name='نوع المركبة')

    class Meta:
        verbose_name = 'مركبة'
        verbose_name_plural = 'المركبات'

    def __str__(self):
        return self.plate_number


class ComplaintMaterial(models.Model):
    """Chemical material used during complaint resolution."""
    resolution = models.ForeignKey(
        ComplaintResolution, on_delete=models.CASCADE, related_name='materials',
        verbose_name='المعالجة',
    )
    material_name = models.CharField(max_length=150, verbose_name='اسم المادة')
    quantity = models.CharField(max_length=50, blank=True, verbose_name='الكمية')

    class Meta:
        verbose_name = 'مادة كيميائية'
        verbose_name_plural = 'المواد الكيميائية'

    def __str__(self):
        return f"{self.material_name} — {self.resolution}"


class ComplaintPhoto(models.Model):
    """Photo attached to a complaint at a specific phase."""
    PHASE_CHOICES = [
        ('inspection',  'صور التفتيش'),
        ('during_work', 'صور أثناء العمل'),
        ('after_work',  'صور بعد الانتهاء'),
    ]
    complaint = models.ForeignKey(
        Complaint, on_delete=models.CASCADE, related_name='photos',
        verbose_name='الشكوى',
    )
    phase = models.CharField(max_length=20, choices=PHASE_CHOICES, verbose_name='المرحلة')
    file = models.ImageField(upload_to='complaints/photos/', verbose_name='الصورة')
    uploaded_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='complaint_photos', verbose_name='رُفعت بواسطة',
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['uploaded_at']
        verbose_name = 'صورة شكوى'
        verbose_name_plural = 'صور الشكاوي'

    def __str__(self):
        return f"{self.get_phase_display()} — {self.complaint}"


# ---------------------------------------------------------------------------
# Field Work Orders
# ---------------------------------------------------------------------------

class FieldWorkOrder(models.Model):
    STATUS_CHOICES = [
        ('new',               'جديد'),
        ('private_company',   'شركة خاصة'),
        ('cust_declined',     'العميل رفض الخدمة'),
        ('wrong_phone',       'رقم الهاتف خاطئ'),
        ('phone_off',         'الهاتف مغلق'),
        ('no_answer',         'لا يوجد رد'),
        ('completed',         'تم إنجاز الخدمة'),
        ('postponed_client',  'تأجيل من العميل'),
        ('gov_dept',          'جهة حكومية — يلزم إرسال موافقة'),
        ('other_municipal',          'تابعة لبلدية أخرى'),
        ('closed_private_building',  'مغلق — شركة نظافة خاصة (داخل بناية)'),
        ('closed_no_answer',         'مغلق — لم يرد العميل على الهاتف'),
        ('closed_other_municipal',   'مغلق — تابع لبلدية أخرى'),
        ('closed_observation',       'مغلق — ملاحظة'),
        ('closed_low_infestation',   'مغلق — تفشٍ خفيف'),
        ('closed_moderate_infestation', 'مغلق — تفشٍ متوسط'),
        ('closed_high_infestation',  'مغلق — تفشٍ شديد'),
        ('closed_out_of_service',    'مغلق — خارج نطاق الخدمة'),
        ('closed_customer_refused',  'مغلق — العميل رفض الخدمة'),
        ('closed_mobile_off',        'مغلق — هاتف العميل مغلق'),
        ('closed_not_attending',     'مغلق — العميل لا يرد على المكالمات'),
        ('closed_not_available',     'مغلق — العميل غير متاح'),
        ('closed_scheduled_client',  'مغلق — تم الجدولة من قِبل العميل'),
    ]

    SOURCE_CHOICES = [
        ('manual', 'يدوي'),
        ('excel',  'مستورد من Excel'),
    ]

    # ── Original generic fields ───────────────────────────────────────────
    site_name      = models.CharField(max_length=200, blank=True, verbose_name='اسم الموقع')
    work_type      = models.CharField(max_length=200, blank=True, verbose_name='نوع العمل')
    location       = models.CharField(max_length=300, blank=True, verbose_name='العنوان')
    description    = models.TextField(blank=True, verbose_name='وصف العمل')
    work_date      = models.DateField(null=True, blank=True, verbose_name='تاريخ التنفيذ')
    workers_count  = models.PositiveIntegerField(null=True, blank=True, verbose_name='عدد العمال')
    equipment_used = models.TextField(blank=True, verbose_name='المعدات المستخدمة')
    work_completed   = models.BooleanField(null=True, blank=True, verbose_name='اكتملت العملية')
    notes            = models.TextField(blank=True, verbose_name='ملاحظات')
    # ── Assignment ────────────────────────────────────────────────────────
    assigned_supervisor = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='field_work_assigned', verbose_name='المراقب المعيّن',
    )
    assigned_at = models.DateTimeField(null=True, blank=True, verbose_name='تاريخ التعيين')
    received_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='field_work_received', verbose_name='المراقب المستلِم',
    )
    received_at = models.DateTimeField(null=True, blank=True, verbose_name='تاريخ الاستلام')
    # ── GPS location ──────────────────────────────────────────────────────
    gps_lat          = models.FloatField(null=True, blank=True, verbose_name='خط العرض')
    gps_lng          = models.FloatField(null=True, blank=True, verbose_name='خط الطول')
    location_saved_at = models.DateTimeField(null=True, blank=True, verbose_name='وقت حفظ الموقع')
    location_saved_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='field_work_locations_saved', verbose_name='حفظ الموقع',
    )
    # ── Supervisor report fields ──────────────────────────────────────────
    building_type    = models.CharField(max_length=100, blank=True, verbose_name='نوع المبنى')
    vehicles_count   = models.PositiveIntegerField(null=True, blank=True, verbose_name='عدد السيارات')
    postponed_until  = models.DateField(null=True, blank=True, verbose_name='تاريخ التأجيل')
    pesticides_used  = models.TextField(blank=True, verbose_name='المبيدات المستخدمة')
    supervisor_notes = models.TextField(blank=True, verbose_name='ملاحظات المراقب')
    no_answer_screenshot = models.ImageField(
        upload_to='field_work/no_answer/', null=True, blank=True,
        verbose_name='صورة عدم الرد',
    )
    report_submitted_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='field_work_reports', verbose_name='أدخل التقرير',
    )
    report_submitted_at = models.DateTimeField(null=True, blank=True, verbose_name='تاريخ التقرير')
    time_in             = models.DateTimeField(null=True, blank=True, verbose_name='وقت الوصول')
    status         = models.CharField(
        max_length=30, choices=STATUS_CHOICES, default='new', verbose_name='الحالة',
    )
    source = models.CharField(
        max_length=10, choices=SOURCE_CHOICES, default='manual', verbose_name='المصدر',
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='field_work_orders_created', verbose_name='أنشئ بواسطة',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='تاريخ الإنشاء')
    updated_at = models.DateTimeField(auto_now=True)

    # ── Excel import fields ───────────────────────────────────────────────
    order_number        = models.CharField(max_length=30, blank=True, db_index=True, verbose_name='رقم الطلب')
    request_date        = models.DateField(null=True, blank=True, verbose_name='تاريخ الطلب')
    close_date          = models.DateField(null=True, blank=True, verbose_name='تاريخ الإغلاق')
    customer_name       = models.CharField(max_length=200, blank=True, verbose_name='اسم المتعامل')
    mobile              = models.CharField(max_length=30, blank=True, verbose_name='الموبايل')
    street_number       = models.CharField(max_length=50, blank=True, verbose_name='رقم الشارع')
    house_number        = models.CharField(max_length=50, blank=True, verbose_name='رقم المنزل')
    area                = models.CharField(max_length=200, blank=True, verbose_name='المنطقة')
    pest_types          = models.CharField(max_length=300, blank=True, verbose_name='نوع الحشرات')
    supervisor_name     = models.CharField(max_length=200, blank=True, verbose_name='المشرف المعالج')
    worker_name         = models.CharField(max_length=200, blank=True, verbose_name='العامل')
    excel_status        = models.CharField(max_length=100, blank=True, verbose_name='حالة الطلب (Excel)')
    excel_status_note   = models.CharField(max_length=100, blank=True, verbose_name='ملاحظة الحالة (Excel)')
    month_sheet         = models.CharField(max_length=20, blank=True, verbose_name='الشهر')

    spray_location       = models.CharField(max_length=300, blank=True, verbose_name='مكان الرش')
    spray_entries        = models.JSONField(default=list, blank=True, verbose_name='سجلات الرش')
    pests_found          = models.JSONField(default=list, blank=True, verbose_name='الحشرات الموجودة')
    client_signature     = models.TextField(blank=True, verbose_name='توقيع العميل')
    supervisor_signature = models.TextField(blank=True, verbose_name='توقيع المراقب')

    # Pest treatment checkboxes
    treated_ant       = models.BooleanField(default=False, verbose_name='نمل')
    treated_cockroach = models.BooleanField(default=False, verbose_name='صراصير')
    treated_mosquito  = models.BooleanField(default=False, verbose_name='بعوض')
    treated_fly       = models.BooleanField(default=False, verbose_name='ذباب')
    treated_rat       = models.BooleanField(default=False, verbose_name='فئران')
    treated_snake     = models.BooleanField(default=False, verbose_name='ثعبان')
    treated_scorpion  = models.BooleanField(default=False, verbose_name='عقارب')
    treated_wasps     = models.BooleanField(default=False, verbose_name='دبابير')
    treated_bees      = models.BooleanField(default=False, verbose_name='نحل')
    treated_other     = models.BooleanField(default=False, verbose_name='أخرى')

    # Chemical materials used
    used_boom          = models.BooleanField(default=False, verbose_name='BOOM')
    used_kothreni      = models.BooleanField(default=False, verbose_name='K OTHRENI')
    used_diesel        = models.BooleanField(default=False, verbose_name='DIESEL')
    used_petrol        = models.BooleanField(default=False, verbose_name='PETROL')
    used_cyphorce      = models.BooleanField(default=False, verbose_name='CYPHORCE')
    used_rat_poison    = models.BooleanField(default=False, verbose_name='RAT POISON')
    used_eco_larvacide = models.BooleanField(default=False, verbose_name='ECO LARVACIDE')
    used_snake_deter   = models.BooleanField(default=False, verbose_name='SNAKE DETER')
    used_hymenopthor   = models.BooleanField(default=False, verbose_name='HYMENOPTHOR GR')
    used_permothor     = models.BooleanField(default=False, verbose_name='PERMOTHOR DUST')
    used_rat_glue      = models.BooleanField(default=False, verbose_name='RAT GLUE')
    used_rapetr_gel    = models.BooleanField(default=False, verbose_name='RAPETR GEL')
    used_graibait      = models.BooleanField(default=False, verbose_name='GRAIBAIT')
    used_difron        = models.BooleanField(default=False, verbose_name='DIFRON 25 SC')
    used_fly_attractant = models.BooleanField(default=False, verbose_name='FLY ATTRACTANT')

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'أمر عمل ميداني'
        verbose_name_plural = 'أوامر العمل الميداني'

    def __str__(self):
        if self.order_number:
            return f"#{self.order_number} — {self.customer_name or self.area or ''}"
        return f"#{self.id} — {self.work_type} — {self.site_name or 'بدون موقع'}"

    def photos_by_phase(self, phase):
        return self.photos.filter(phase=phase)


class FieldWorkPhoto(models.Model):
    PHASE_CHOICES = [
        ('work',   'صور العمل'),
        ('before', 'قبل العمل'),
        ('during', 'أثناء العمل'),
        ('after',  'بعد العمل'),
    ]

    work_order = models.ForeignKey(
        FieldWorkOrder, on_delete=models.CASCADE, related_name='photos',
        verbose_name='أمر العمل',
    )
    phase = models.CharField(max_length=10, choices=PHASE_CHOICES, verbose_name='المرحلة')
    file = models.ImageField(upload_to='field_work/photos/', verbose_name='الصورة')
    caption = models.CharField(max_length=200, blank=True, verbose_name='وصف الصورة')
    uploaded_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='field_work_photos', verbose_name='رُفعت بواسطة',
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['phase', 'uploaded_at']
        verbose_name = 'صورة عمل ميداني'
        verbose_name_plural = 'صور العمل الميداني'

    def __str__(self):
        return f"{self.get_phase_display()} — {self.work_order}"


class FieldWorkSupervisorArea(models.Model):
    supervisor = models.ForeignKey(
        User, on_delete=models.CASCADE,
        related_name='fw_supervisor_areas', verbose_name='المراقب',
        limit_choices_to={'groups__name__in': ['fw_supervisor', 'Field Work Supervisor']},
    )
    area = models.CharField(max_length=200, verbose_name='المنطقة')
    assigned_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='fw_area_assignments_made', verbose_name='عُيِّن بواسطة',
    )
    assigned_at = models.DateTimeField(auto_now_add=True, verbose_name='تاريخ التعيين')

    class Meta:
        unique_together = [('supervisor', 'area')]
        ordering = ['supervisor__first_name', 'area']
        verbose_name = 'منطقة مراقب عمل ميداني'
        verbose_name_plural = 'مناطق مراقبي العمل الميداني'

    def __str__(self):
        return f"{self.supervisor.get_full_name() or self.supervisor.username} — {self.area}"


# ══════════════════════════════════════════
#  Container Transfer Requests
# ══════════════════════════════════════════

class ContainerTransferRequest(models.Model):
    STATUS_CHOICES = [
        ('new',               'جديد'),
        ('assigned',          'بانتظار المفتش'),
        ('location_saved',    'تم حفظ الموقع'),
        ('biaa_contacted',    'تم التواصل مع بيئة'),
        ('biaa_transferred',  'تم نقل الحاوية'),
        ('report_submitted',  'تم تقديم التقرير'),
        ('closed',            'مغلق'),
        ('rejected',          'مرفوض'),
    ]

    complaint_number = models.CharField(max_length=100, verbose_name='رقم الشكوى')
    pdf_file = models.FileField(
        upload_to='container_requests/pdfs/',
        null=True, blank=True,
        verbose_name='ملف PDF',
    )
    complainant_name   = models.CharField(max_length=200, blank=True, verbose_name='اسم المتعامل')
    complainant_mobile = models.CharField(max_length=30,  blank=True, verbose_name='رقم الموبايل')
    area               = models.CharField(max_length=200, blank=True, verbose_name='المنطقة')
    house_number       = models.CharField(max_length=50,  blank=True, verbose_name='رقم المنزل')
    notes              = models.TextField(blank=True, verbose_name='تفاصيل الطلب')
    status = models.CharField(
        max_length=30, choices=STATUS_CHOICES, default='new',
        verbose_name='الحالة',
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='container_requests_created',
        verbose_name='أضيف بواسطة',
    )
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name        = 'طلب نقل حاوية'
        verbose_name_plural = 'طلبات نقل الحاويات'

    def __str__(self):
        return f"حاوية #{self.complaint_number}"


class ContainerTransferInspection(models.Model):
    request = models.OneToOneField(
        ContainerTransferRequest, on_delete=models.CASCADE,
        related_name='inspection', verbose_name='الطلب',
    )
    inspector = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='container_inspections', verbose_name='المفتش',
    )
    assigned_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='container_inspections_assigned', verbose_name='أسند بواسطة',
    )
    assigned_at = models.DateTimeField(auto_now_add=True)

    # Location (saved by inspector before work)
    latitude        = models.FloatField(null=True, blank=True, verbose_name='خط العرض')
    longitude       = models.FloatField(null=True, blank=True, verbose_name='خط الطول')
    location_notes  = models.TextField(blank=True, verbose_name='ملاحظات الموقع')
    location_saved_at = models.DateTimeField(null=True, blank=True, verbose_name='وقت حفظ الموقع')

    # Bee'ah contact
    biaa_contacted_at    = models.DateTimeField(null=True, blank=True, verbose_name='وقت التواصل مع بيئة')
    biaa_contact_notes   = models.TextField(blank=True, verbose_name='ملاحظات التواصل مع بيئة')
    biaa_transferred_at  = models.DateTimeField(null=True, blank=True, verbose_name='وقت نقل الحاوية')

    # Final report
    report_notes   = models.TextField(blank=True, verbose_name='ملاحظات التقرير')
    completed_at   = models.DateTimeField(null=True, blank=True, verbose_name='تاريخ الإغلاق')

    # Rejection
    rejection_reason = models.TextField(blank=True, verbose_name='سبب الرفض')
    rejected_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='container_inspections_rejected', verbose_name='رُفض بواسطة',
    )
    rejected_at = models.DateTimeField(null=True, blank=True, verbose_name='تاريخ الرفض')

    class Meta:
        verbose_name        = 'تفتيش طلب حاوية'
        verbose_name_plural = 'تفتيش طلبات الحاويات'

    def __str__(self):
        return f"تفتيش — {self.request}"


class ContainerTransferPhoto(models.Model):
    PHASE_CHOICES = [
        ('before', 'صور قبل النقل'),
        ('after',  'صور بعد النقل'),
    ]
    request = models.ForeignKey(
        ContainerTransferRequest, on_delete=models.CASCADE,
        related_name='photos', verbose_name='الطلب',
    )
    phase       = models.CharField(max_length=10, choices=PHASE_CHOICES, verbose_name='المرحلة')
    file        = models.ImageField(upload_to='container_requests/photos/', verbose_name='الصورة')
    uploaded_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='container_photos', verbose_name='رُفعت بواسطة',
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['uploaded_at']
        verbose_name        = 'صورة حاوية'
        verbose_name_plural = 'صور الحاويات'

    def __str__(self):
        return f"{self.get_phase_display()} — {self.request}"


# ═══════════════════════════════════════════════════════════════════════════════
# Weed Removal
# ═══════════════════════════════════════════════════════════════════════════════

class WeedRemovalRequest(models.Model):
    STATUS_CHOICES = [
        ('new',                 'جديد'),
        ('inspector_assigned',  'بانتظار المفتش'),
        ('inspection_done',     'اكتمل التفتيش'),
        ('supervisor_assigned', 'بانتظار المراقب'),
        ('work_in_progress',    'العمل جارٍ'),
        ('work_done',           'تم إنهاء العمل'),
        ('closed',              'مغلق'),
        ('rejected',            'مرفوض'),
    ]

    complaint_number   = models.CharField(max_length=100, verbose_name='رقم الشكوى')
    pdf_file           = models.FileField(
        upload_to='weed_removal/pdfs/', null=True, blank=True, verbose_name='ملف PDF',
    )
    complainant_name   = models.CharField(max_length=200, blank=True, verbose_name='اسم المتعامل')
    complainant_mobile = models.CharField(max_length=30,  blank=True, verbose_name='رقم الموبايل')
    area               = models.CharField(max_length=200, blank=True, verbose_name='المنطقة')
    house_number       = models.CharField(max_length=50,  blank=True, verbose_name='رقم المنزل')
    notes              = models.TextField(blank=True, verbose_name='ملاحظات')
    status             = models.CharField(
        max_length=30, choices=STATUS_CHOICES, default='new', verbose_name='الحالة',
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='weed_requests_created', verbose_name='أضيف بواسطة',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name        = 'طلب إزالة حشائش'
        verbose_name_plural = 'طلبات إزالة الحشائش'

    def __str__(self):
        return f"حشائش #{self.complaint_number}"


class WeedRemovalInspection(models.Model):
    request = models.OneToOneField(
        WeedRemovalRequest, on_delete=models.CASCADE, related_name='inspection',
    )
    inspector = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='weed_inspections', verbose_name='المفتش',
    )
    assigned_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='weed_inspections_assigned', verbose_name='عُيِّن بواسطة',
    )
    assigned_at      = models.DateTimeField(auto_now_add=True)
    inspection_notes = models.TextField(blank=True, verbose_name='ملاحظات التفتيش')
    completed_at     = models.DateTimeField(null=True, blank=True, verbose_name='وقت الإتمام')

    # Location
    latitude         = models.FloatField(null=True, blank=True, verbose_name='خط العرض')
    longitude        = models.FloatField(null=True, blank=True, verbose_name='خط الطول')
    location_notes   = models.TextField(blank=True, verbose_name='ملاحظات الموقع')
    location_saved_at = models.DateTimeField(null=True, blank=True, verbose_name='وقت حفظ الموقع')

    # Rejection
    rejection_reason = models.TextField(blank=True, verbose_name='سبب الرفض')
    rejected_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='weed_inspections_rejected', verbose_name='رُفض بواسطة',
    )
    rejected_at = models.DateTimeField(null=True, blank=True, verbose_name='وقت الرفض')

    class Meta:
        verbose_name        = 'تفتيش إزالة حشائش'
        verbose_name_plural = 'تفتيش طلبات إزالة الحشائش'

    def __str__(self):
        return f"تفتيش — {self.request}"


class WeedRemovalSupervisorTask(models.Model):
    request = models.OneToOneField(
        WeedRemovalRequest, on_delete=models.CASCADE, related_name='supervisor_task',
    )
    supervisor = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='weed_supervisor_tasks', verbose_name='المراقب',
    )
    assigned_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='weed_supervisor_tasks_assigned', verbose_name='عُيِّن بواسطة',
    )
    assigned_at   = models.DateTimeField(auto_now_add=True)
    workers_count = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name='عدد العمال')
    report_notes  = models.TextField(blank=True, verbose_name='ملاحظات التقرير')
    completed_at  = models.DateTimeField(null=True, blank=True, verbose_name='وقت الإتمام')

    class Meta:
        verbose_name        = 'مهمة مراقب إزالة حشائش'
        verbose_name_plural = 'مهام مراقبي إزالة الحشائش'

    def __str__(self):
        return f"مراقب — {self.request}"


class WeedRemovalVehicle(models.Model):
    VEHICLE_TYPE_CHOICES = [
        ('pickup',  'بيك آب'),
        ('tractor', 'تراكتور'),
        ('truck',   'شاحنة'),
        ('loader',  'لودر'),
        ('other',   'أخرى'),
    ]
    task         = models.ForeignKey(
        WeedRemovalSupervisorTask, on_delete=models.CASCADE, related_name='vehicles',
    )
    vehicle_type = models.CharField(max_length=20, choices=VEHICLE_TYPE_CHOICES, verbose_name='نوع المركبة')
    count        = models.PositiveSmallIntegerField(default=1, verbose_name='العدد')
    notes        = models.CharField(max_length=200, blank=True, verbose_name='ملاحظات')

    class Meta:
        verbose_name        = 'مركبة إزالة حشائش'
        verbose_name_plural = 'مركبات إزالة الحشائش'

    def __str__(self):
        return f"{self.get_vehicle_type_display()} × {self.count}"


class WeedRemovalPhoto(models.Model):
    PHASE_CHOICES = [
        ('before', 'صور قبل العمل'),
        ('during', 'صور أثناء العمل'),
        ('after',  'صور بعد العمل'),
    ]
    request = models.ForeignKey(
        WeedRemovalRequest, on_delete=models.CASCADE, related_name='photos',
    )
    phase       = models.CharField(max_length=10, choices=PHASE_CHOICES, verbose_name='المرحلة')
    file        = models.ImageField(upload_to='weed_removal/photos/', verbose_name='الصورة')
    uploaded_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='weed_photos_uploaded',
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['uploaded_at']
        verbose_name        = 'صورة إزالة حشائش'
        verbose_name_plural = 'صور إزالة الحشائش'

    def __str__(self):
        return f"{self.get_phase_display()} — {self.request}"
