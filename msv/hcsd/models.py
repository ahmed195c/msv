import datetime

from django.contrib.auth.models import User
from django.db import models

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
    business_activity = models.CharField(max_length=150, null=True, blank=True)
    landline = models.CharField(max_length=30, null=True, blank=True)
    owner_phone = models.CharField(max_length=30, null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
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
    email = models.EmailField()
    phone = models.CharField(max_length=20)
    public_health_cert = models.FileField(
        upload_to='engineer_certificates/', null=True, blank=True
    )
    termite_cert = models.FileField(
        upload_to='engineer_certificates/', null=True, blank=True
    )

    @property
    def has_public_health_cert(self):
        return bool(self.public_health_cert)

    @property
    def has_termite_cert(self):
        return bool(self.termite_cert)

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
        ('payment_completed', 'Payment Completed'),
        ('issued', 'Issued'),
        ('inspection_pending', 'Inspection Pending'),
        ('inspection_completed', 'Inspection Completed'),
        ('disposal_approved', 'Disposal Approved'),
        ('disposal_rejected', 'Disposal Rejected'),
    ]
    unapprovedReason = models.TextField(null=True, blank=True)
    unapprovedBy = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='unapproved_pirmets')
    approvedBy = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='approved_pirmets')
    approvedRemarks = models.TextField(null=True, blank=True)
    company = models.ForeignKey(Company, on_delete=models.CASCADE)
    dateOfCreation = models.DateField(auto_now_add=True)
    dateOfExpiry = models.DateField(null=True, blank=True)
    permit_no = models.CharField(max_length=50, null=True, blank=True, unique=True)
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
    request_email = models.EmailField(null=True, blank=True)
    request_documents_bundle = models.FileField(
        upload_to='pirmet_documents/bundles/', null=True, blank=True
    )
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='order_received')
    
    def _generate_permit_no(self):
        year = self.dateOfCreation.year if self.dateOfCreation else datetime.date.today().year
        return f"PRM-{year}-{self.pk:06d}"

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if is_new and not self.permit_no:
            self.permit_no = self._generate_permit_no()
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


class InspectorReview(models.Model):
    pirmet = models.OneToOneField(PirmetClearance, on_delete=models.CASCADE)
    inspector = models.ForeignKey(Enginer, on_delete=models.SET_NULL, null=True)
    reviewDate = models.DateTimeField(auto_now_add=True)
    isApproved = models.BooleanField(default=False)
    comments = models.TextField(blank=True)
    
    def __str__(self):
        return f"{self.pirmet.company.name} - {'Approved' if self.isApproved else 'Pending'}"


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
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.enginer.name} - {self.action}"


class CompanyChangeLog(models.Model):
    ACTION_CHOICES = [
        ('created', 'Created'),
        ('updated', 'Updated'),
        ('engineer_changed', 'Engineer Changed'),
        ('extension_requested', 'Extension Requested'),
    ]

    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name='change_logs'
    )
    action = models.CharField(max_length=40, choices=ACTION_CHOICES)
    notes = models.TextField(blank=True)
    changed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True
    )
    attachment = models.FileField(
        upload_to='company_extension_requests/', null=True, blank=True
    )
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
    old_status = models.CharField(max_length=25, null=True, blank=True)
    new_status = models.CharField(max_length=25, null=True, blank=True)
    notes = models.TextField(blank=True)
    changed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.pirmet.company.name} - {self.change_type}"
