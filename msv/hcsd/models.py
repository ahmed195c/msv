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
        ('order_received', 'تم استلام الطلب'),
        ('inspection_payment_pending', 'بانتظار دفع التفتيش'),
        ('review_pending', 'بانتظار مراجعة المفتش'),
        ('needs_completion', 'يحتاج استكمال'),
        ('approved', 'معتمد من المفتش'),
        ('payment_pending', 'بانتظار الدفع'),
        ('issued', 'صادر'),
        ('inspection_pending', 'بانتظار التفتيش'),
        ('inspection_completed', 'اكتمل التفتيش'),
        ('violation_payment_link_pending', 'بانتظار رابط دفع المخالفة'),
        ('violation_payment_pending', 'بانتظار دفع المخالفة'),
        ('head_approved', 'الاعتماد النهائي'),
        ('closed_requirements_pending', 'مغلق - متطلبات معلقة'),
        ('cancelled_admin', 'ملغى إدارياً'),
        ('disposal_approved', 'موافقة على التخلص'),
        ('disposal_rejected', 'رفض التخلص'),
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
        ('payment_pending', 'بانتظار الدفع'),
        ('inspection_pending', 'بانتظار التفتيش'),
        ('approved', 'معتمد'),
        ('rejected', 'مرفوض'),
        ('completed', 'مكتمل'),
        ('cancelled_admin', 'ملغى إدارياً'),
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

    # ── Timeline tracking (who did what, and when) ──
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='waste_disposal_requests_created',
    )
    reference_recorded_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='waste_disposal_references_recorded',
    )
    reference_recorded_at = models.DateTimeField(null=True, blank=True)
    payment_confirmed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='waste_disposal_payments_confirmed',
    )
    payment_confirmed_at = models.DateTimeField(null=True, blank=True)
    received_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='waste_disposal_requests_received',
    )
    received_at = models.DateTimeField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='waste_disposal_requests_cancelled',
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(null=True, blank=True)

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
        ('removed_from_company', 'Removed From Company'),
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


# ---------------------------------------------------------------------------
# Field Work Orders
# ---------------------------------------------------------------------------

class FieldWorkOrder(models.Model):
    STATUS_CHOICES = [
        ('new',                  'جديد'),
        ('supervisor_assigned',  'تم تعيين مراقب'),
        ('order_received',       'تم استلام الطلب'),
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
        ('manual',    'يدوي'),
        ('excel',     'مستورد من Excel'),
        ('recurring', 'طلب دوري متكرر'),
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
        max_length=30, choices=STATUS_CHOICES, default='new', db_index=True, verbose_name='الحالة',
    )
    source = models.CharField(
        max_length=10, choices=SOURCE_CHOICES, default='manual', db_index=True, verbose_name='المصدر',
    )
    COMPLAINT_SOURCE_CHOICES = [
        ('electronic',      'طلبات إلكترونية'),
        ('correspondence',  'تراسل'),
        ('office',          'طلبات مكتب'),
        ('hotline',         'خط ساخن'),
    ]
    complaint_source = models.CharField(
        max_length=20, choices=COMPLAINT_SOURCE_CHOICES, blank=True, default='',
        verbose_name='مصدر الشكوى',
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='field_work_orders_created', verbose_name='أنشئ بواسطة',
    )
    recurring_template = models.ForeignKey(
        'FieldWorkRecurringOrder', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='generated_orders', verbose_name='الطلب الدوري المصدر',
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name='تاريخ الإنشاء')
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
    report_findings      = models.JSONField(default=list, blank=True, verbose_name='الملاحظات الميدانية')
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

    STATUS_LABELS_EN = {
        'new':                        'New',
        'supervisor_assigned':         'Supervisor Assigned',
        'order_received':              'Order Received',
        'private_company':            'Private Company',
        'cust_declined':              'Customer Declined',
        'wrong_phone':                'Wrong Phone',
        'phone_off':                  'Phone Off',
        'no_answer':                  'No Answer',
        'completed':                  'Completed',
        'postponed_client':           'Postponed by Client',
        'gov_dept':                   'Government Dept.',
        'other_municipal':            'Other Municipality',
        'closed_private_building':    'Closed — Private Building',
        'closed_no_answer':           'Closed — No Answer',
        'closed_other_municipal':     'Closed — Other Municipality',
        'closed_observation':         'Closed — Observation',
        'closed_low_infestation':     'Closed — Low Infestation',
        'closed_moderate_infestation':'Closed — Moderate Infestation',
        'closed_high_infestation':    'Closed — High Infestation',
        'closed_out_of_service':      'Closed — Out of Service',
        'closed_customer_refused':    'Closed — Customer Refused',
        'closed_mobile_off':          'Closed — Mobile Off',
        'closed_not_attending':       'Closed — Not Attending',
        'closed_not_available':       'Closed — Not Available',
        'closed_scheduled_client':    'Closed — Scheduled by Client',
    }

    class Meta:
        indexes = [
            models.Index(fields=['status', 'created_at'], name='fw_status_created_idx'),
            models.Index(fields=['request_date'], name='fw_request_date_idx'),
            models.Index(fields=['assigned_supervisor', 'status'], name='fw_sup_status_idx'),
        ]

    @property
    def status_en(self):
        return self.STATUS_LABELS_EN.get(self.status, self.status)

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


class FieldWorkOrderLog(models.Model):
    ACTION_CHOICES = [
        ('created',          'إنشاء الأمر'),
        ('assigned',         'تعيين مراقب'),
        ('reassigned',       'إعادة تعيين مراقب'),
        ('unassigned',       'إلغاء تعيين مراقب'),
        ('received',         'استلام الأمر'),
        ('status_changed',   'تغيير الحالة'),
        ('postponed',        'تأجيل الموعد'),
        ('closed',           'إغلاق الأمر'),
        ('completed',        'إتمام الخدمة'),
    ]
    _ACTION_EN = {
        'created':        'Order Created',
        'assigned':       'Supervisor Assigned',
        'reassigned':     'Supervisor Reassigned',
        'unassigned':     'Supervisor Unassigned',
        'received':       'Order Received',
        'status_changed': 'Status Changed',
        'postponed':      'Appointment Postponed',
        'closed':         'Order Closed',
        'completed':      'Service Completed',
    }

    @property
    def action_en(self):
        return self._ACTION_EN.get(self.action, self.action)

    order      = models.ForeignKey(FieldWorkOrder, on_delete=models.CASCADE, related_name='logs', verbose_name='الأمر')
    action     = models.CharField(max_length=20, choices=ACTION_CHOICES, verbose_name='الإجراء')
    actor      = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='fw_logs', verbose_name='بواسطة')
    timestamp  = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name='التوقيت')
    from_value = models.CharField(max_length=200, blank=True, verbose_name='من')
    to_value   = models.CharField(max_length=200, blank=True, verbose_name='إلى')
    note       = models.CharField(max_length=300, blank=True, verbose_name='ملاحظة')

    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'سجل تغيير'
        verbose_name_plural = 'سجل تغييرات الأوامر'

    def __str__(self):
        return f"{self.get_action_display()} — {self.order_id}"


class FieldWorkRecurringOrder(models.Model):
    WEEKDAY_CHOICES = [
        (0, 'يوم اثنين'),
        (1, 'يوم ثلاثاء'),
        (2, 'يوم أربعاء'),
        (3, ' يوم خميس'),
        (4, ' يوم جمعة'),
        (5, ' يوم سبت '),
        (6, 'يوم أحد'),
    ]

    site_name        = models.CharField(max_length=200, blank=True, verbose_name='اسم الموقع')
    customer_name    = models.CharField(max_length=200, blank=True, verbose_name='اسم المتعامل')
    mobile           = models.CharField(max_length=30, blank=True, verbose_name='الموبايل')
    location         = models.CharField(max_length=300, blank=True, verbose_name='العنوان')
    area             = models.CharField(max_length=200, blank=True, verbose_name='المنطقة')
    street_number    = models.CharField(max_length=50, blank=True, verbose_name='رقم الشارع')
    house_number     = models.CharField(max_length=50, blank=True, verbose_name='رقم المنزل')
    pest_types       = models.CharField(max_length=300, blank=True, verbose_name='نوع الحشرات')
    complaint_source = models.CharField(
        max_length=20, choices=FieldWorkOrder.COMPLAINT_SOURCE_CHOICES, blank=True, default='',
        verbose_name='مصدر الشكوى',
    )
    notes = models.TextField(blank=True, verbose_name='ملاحظات')

    weekday   = models.PositiveSmallIntegerField(choices=WEEKDAY_CHOICES, verbose_name='يوم التكرار')
    is_active = models.BooleanField(default=True, verbose_name='مفعّل')

    last_generated_on = models.DateField(null=True, blank=True, verbose_name='آخر إنشاء تلقائي')

    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='field_work_recurring_orders_created', verbose_name='أنشئ بواسطة',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='تاريخ الإنشاء')

    class Meta:
        ordering = ['weekday', '-created_at']
        verbose_name = 'طلب دوري متكرر'
        verbose_name_plural = 'الطلبات الدورية المتكررة'

    def __str__(self):
        return f"{self.customer_name or self.site_name or '—'} — {self.get_weekday_display()}"

    def generate_order(self, on_date=None):
        """Create this template's field-work order for `on_date` (default: today) and mark it generated."""
        from django.utils import timezone
        on_date = on_date or timezone.localdate()
        order = FieldWorkOrder.objects.create(
            site_name=self.site_name,
            customer_name=self.customer_name,
            mobile=self.mobile,
            area=self.area,
            street_number=self.street_number,
            house_number=self.house_number,
            location=self.location,
            pest_types=self.pest_types,
            complaint_source=self.complaint_source,
            notes=self.notes,
            request_date=on_date,
            status='new',
            source='recurring',
            created_by=self.created_by,
            recurring_template=self,
        )
        self.last_generated_on = on_date
        self.save(update_fields=['last_generated_on'])
        return order


class FieldWorkSupervisorProfile(models.Model):
    user         = models.OneToOneField(
        User, on_delete=models.CASCADE,
        related_name='fw_supervisor_profile', verbose_name='المستخدم',
    )
    name_ar      = models.CharField(max_length=100, blank=True, verbose_name='الاسم بالعربية')
    name_en      = models.CharField(max_length=100, blank=True, verbose_name='الاسم بالإنجليزية')
    admin_number = models.CharField(max_length=50,  blank=True, verbose_name='الرقم الإداري')

    class Meta:
        verbose_name = 'ملف مراقب عمل ميداني'
        verbose_name_plural = 'ملفات مراقبي العمل الميداني'

    def __str__(self):
        return self.name_ar or self.user.get_full_name() or self.user.username


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
#  User Profile
# ══════════════════════════════════════════

class UserProfile(models.Model):
    user = models.OneToOneField(
        User, on_delete=models.CASCADE,
        related_name='profile', verbose_name='المستخدم',
    )
    admin_number = models.CharField(
        max_length=150, blank=True, verbose_name='الرقم الإداري',
    )

    class Meta:
        verbose_name = 'ملف المستخدم'
        verbose_name_plural = 'ملفات المستخدمين'

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} ({self.admin_number})"


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
        ('work_paused',         'العمل متوقف مؤقتاً'),
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


class WeedRemovalWorkSession(models.Model):
    END_TYPE_CHOICES = [
        ('postponed', 'مؤجل'),
        ('completed', 'مكتمل'),
    ]
    task          = models.ForeignKey(
        WeedRemovalSupervisorTask, on_delete=models.CASCADE,
        related_name='work_sessions', verbose_name='المهمة',
    )
    started_at    = models.DateTimeField(verbose_name='وقت البدء')
    ended_at      = models.DateTimeField(null=True, blank=True, verbose_name='وقت الانتهاء')
    end_type      = models.CharField(
        max_length=10, choices=END_TYPE_CHOICES,
        null=True, blank=True, verbose_name='نوع الإنهاء',
    )
    workers_count = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name='عدد العمال')
    notes         = models.TextField(blank=True, verbose_name='ملاحظات التقرير')

    class Meta:
        ordering            = ['started_at']
        verbose_name        = 'جلسة عمل إزالة حشائش'
        verbose_name_plural = 'جلسات عمل إزالة الحشائش'

    def __str__(self):
        return f"جلسة {self.started_at:%Y-%m-%d} — {self.task}"


class WeedRemovalSessionVehicle(models.Model):
    VEHICLE_TYPE_CHOICES = [
        ('pickup',  'بيك آب'),
        ('bobcat',  'بوبكات'),
        ('tractor', 'تراكتور'),
        ('truck',   'شاحنة'),
        ('loader',  'لودر'),
        ('other',   'أخرى'),
    ]
    session      = models.ForeignKey(
        WeedRemovalWorkSession, on_delete=models.CASCADE,
        related_name='vehicles', verbose_name='الجلسة',
    )
    vehicle_type = models.CharField(
        max_length=20, choices=VEHICLE_TYPE_CHOICES, verbose_name='نوع المركبة',
    )
    count        = models.PositiveSmallIntegerField(default=1, verbose_name='العدد')
    notes        = models.CharField(max_length=200, blank=True, verbose_name='ملاحظات')

    class Meta:
        verbose_name        = 'مركبة جلسة إزالة حشائش'
        verbose_name_plural = 'مركبات جلسات إزالة الحشائش'

    def __str__(self):
        return f"{self.get_vehicle_type_display()} × {self.count}"


class WeedRemovalVehicle(models.Model):
    VEHICLE_TYPE_CHOICES = [
        ('pickup',  'بيك آب'),
        ('bobcat',  'بوبكات'),
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
    session = models.ForeignKey(
        'WeedRemovalWorkSession', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='photos', verbose_name='الجلسة',
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


class EngineerCompanyRemoval(models.Model):
    enginer    = models.ForeignKey('Enginer', on_delete=models.CASCADE, related_name='company_removals')
    company    = models.ForeignKey('Company', on_delete=models.CASCADE, related_name='engineer_removals')
    removed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='engineer_removals_recorded')
    removed_at = models.DateTimeField(auto_now_add=True)
    notes      = models.TextField(blank=True)

    class Meta:
        ordering = ['-removed_at']
        verbose_name        = 'سجل إزالة مهندس'
        verbose_name_plural = 'سجلات إزالة المهندسين'

    def __str__(self):
        return f"{self.enginer.name} ← {self.company.name}"


class EngineerRemovalDocument(models.Model):
    removal     = models.ForeignKey(EngineerCompanyRemoval, on_delete=models.CASCADE, related_name='documents')
    file        = models.FileField(upload_to='engineer_removals/')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['uploaded_at']
        verbose_name        = 'مستند إزالة مهندس'
        verbose_name_plural = 'مستندات إزالة المهندسين'

    def __str__(self):
        return f"مستند — {self.removal}"


# ══════════════════════════════════════════
#  Rodent Control — building trap monitoring
# ══════════════════════════════════════════

class RodentControlBuilding(models.Model):
    """A building/site tracked for rodent-control trap (RBS) monitoring.
    One trap per building — monthly visit records track its status over time."""
    name          = models.CharField(max_length=200, verbose_name='اسم البناية')
    number        = models.CharField(max_length=50, blank=True, verbose_name='رقم البناية')
    area          = models.CharField(max_length=150, blank=True, verbose_name='المنطقة')
    location      = models.CharField(max_length=300, blank=True, verbose_name='الموقع')
    latitude      = models.FloatField(null=True, blank=True, verbose_name='خط العرض')
    longitude     = models.FloatField(null=True, blank=True, verbose_name='خط الطول')
    notes         = models.TextField(blank=True, verbose_name='ملاحظات')
    is_active     = models.BooleanField(default=True, verbose_name='قيد المتابعة')
    created_by    = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='rodent_buildings_created',
    )
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        verbose_name        = 'بناية متابعة مصايد'
        verbose_name_plural = 'بنايات متابعة المصايد'

    def __str__(self):
        return self.name


class RodentControlVisit(models.Model):
    """One monthly trap-status record for a building. Auto-generated on the
    1st of each month by generate_rodent_control_visits; filled in when the
    team actually visits."""
    building        = models.ForeignKey(
        RodentControlBuilding, on_delete=models.CASCADE, related_name='visits',
    )
    period_start    = models.DateField(verbose_name='شهر المتابعة')  # always day=1

    visit_date      = models.DateField(null=True, blank=True, verbose_name='تاريخ الزيارة')
    visited_by      = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='rodent_visits_recorded',
    )

    # Summary flags — kept for the list-page badge and for the historical
    # data imported from the old spreadsheets (which only ever had this much
    # detail). Auto-derived from the counts below whenever a visit is
    # recorded through the real field-report form.
    inspected       = models.BooleanField(default=False, verbose_name='تم التفتيش')
    infested        = models.BooleanField(default=False, verbose_name='بها إصابة')
    damaged         = models.BooleanField(default=False, verbose_name='تالفة')
    newly_installed = models.BooleanField(default=False, verbose_name='تم تركيب مصيدة جديدة')
    replenished     = models.BooleanField(default=False, verbose_name='تم تعبئتها')

    # ── Field-report detail (matches the team leader's real visit report) ──
    team_leader_name = models.CharField(max_length=150, blank=True, verbose_name='اسم قائد الفريق')
    team_leader_id   = models.CharField(max_length=50, blank=True, verbose_name='الرقم الوظيفي')
    time_in          = models.TimeField(null=True, blank=True, verbose_name='وقت الدخول')
    time_out         = models.TimeField(null=True, blank=True, verbose_name='وقت الخروج')

    rbs_inspected_count     = models.PositiveIntegerField(null=True, blank=True, verbose_name='إجمالي المصايد المفتشة')
    rbs_lock_ok              = models.BooleanField(default=True, verbose_name='قفل المصيدة سليم')
    rbs_infested_count      = models.PositiveIntegerField(null=True, blank=True, verbose_name='المصايد المصابة')
    rbs_damaged_count       = models.PositiveIntegerField(null=True, blank=True, verbose_name='المصايد التالفة')
    rbs_new_installed_count = models.PositiveIntegerField(null=True, blank=True, verbose_name='المصايد المركبة حديثاً')
    stick_change_ok          = models.BooleanField(default=True, verbose_name='تم تغيير اللاصقة')
    rbs_replenished_count   = models.PositiveIntegerField(null=True, blank=True, verbose_name='المصايد المعاد تعبئتها')

    manholes_inspected_count = models.PositiveIntegerField(null=True, blank=True, verbose_name='إجمالي المناهيل المفتشة')
    manholes_treated_count   = models.PositiveIntegerField(null=True, blank=True, verbose_name='المناهيل المعالجة')
    manholes_treated_qty     = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True, verbose_name='كمية معالجة المناهيل')
    manholes_infested_count  = models.PositiveIntegerField(null=True, blank=True, verbose_name='المناهيل المصابة')

    burrows_outside_count  = models.PositiveIntegerField(null=True, blank=True, verbose_name='الجحور الخارجية')
    burrows_infested_count = models.PositiveIntegerField(null=True, blank=True, verbose_name='الجحور المصابة')

    trees_inspected_count = models.PositiveIntegerField(null=True, blank=True, verbose_name='إجمالي النخيل المفتش')
    trees_treated_count   = models.PositiveIntegerField(null=True, blank=True, verbose_name='النخيل المعالج')
    trees_infested_count  = models.PositiveIntegerField(null=True, blank=True, verbose_name='النخيل المصاب')

    rodenticide_type     = models.CharField(max_length=150, blank=True, verbose_name='نوع المادة')
    rodenticide_quantity = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True, verbose_name='الكمية',
    )
    notes           = models.TextField(blank=True, verbose_name='ملاحظات الزيارة')

    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-period_start']
        unique_together = [('building', 'period_start')]
        verbose_name        = 'زيارة متابعة مصيدة'
        verbose_name_plural = 'زيارات متابعة المصايد'

    def __str__(self):
        return f"{self.building.name} — {self.period_start:%Y-%m}"


# ══════════════════════════════════════════
#  Campaign Follow-up — independent, standalone tracking
# ══════════════════════════════════════════

class CampaignRequest(models.Model):
    """A single site flagged for a campaign visit. An inspector marks it
    handled simply by writing a note — no separate status field, no fixed
    workflow. Presence of a note is the whole status model."""
    company_name    = models.CharField(max_length=200, verbose_name='اسم الشركة')
    location        = models.CharField(max_length=300, blank=True, verbose_name='الموقع')
    photo           = models.ImageField(upload_to='campaign/photos/', null=True, blank=True, verbose_name='صورة')
    building_number = models.CharField(max_length=50, blank=True, verbose_name='رقم البناية')
    area            = models.CharField(max_length=150, blank=True, verbose_name='المنطقة')
    google_maps_url = models.URLField(max_length=500, blank=True, verbose_name='رابط الموقع على خرائط قوقل')

    note      = models.TextField(blank=True, verbose_name='ملاحظة المفتش')
    noted_by  = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='campaign_notes_written',
    )
    noted_at  = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='campaign_requests_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name        = 'طلب متابعة حملة'
        verbose_name_plural = 'طلبات متابعة الحملة'

    def __str__(self):
        return self.company_name

    @property
    def is_done(self):
        return bool(self.note.strip())
