from django.contrib import admin

from .models import (
    Company,
    Complaint, ComplaintInspection, ComplaintResolution, ComplaintVehicle, ComplaintPhoto, ComplaintMaterial,
    Enginer,
    FieldWorkOrder, FieldWorkPhoto,
    InspectorReview,
    PirmetClearance,
    PirmetDocument,
    PirmetChangeLog,
    PesticideTransportPermit,
    RequirementInsuranceRequest,
    WasteDisposalPermit,
)


@admin.register(PirmetClearance)
class PirmetClearanceAdmin(admin.ModelAdmin):
    list_display = ('id', 'permit_no', 'permit_type', 'company', 'status', 'dateOfCreation')
    list_filter = ('permit_type', 'status')
    search_fields = ('id', 'permit_no', 'PaymentNumber', 'inspection_payment_reference', 'company__name')
    ordering = ('-dateOfCreation',)


admin.site.register(Company)
admin.site.register(Enginer)
admin.site.register(PirmetDocument)
admin.site.register(InspectorReview)
admin.site.register(PirmetChangeLog)
admin.site.register(PesticideTransportPermit)
admin.site.register(WasteDisposalPermit)
admin.site.register(RequirementInsuranceRequest)
admin.site.register(Complaint)

@admin.register(FieldWorkOrder)
class FieldWorkOrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'work_type', 'site_name', 'status', 'work_date', 'created_at')
    list_filter = ('status',)
    search_fields = ('id', 'work_type', 'location', 'company__name')
    ordering = ('-created_at',)

admin.site.register(FieldWorkPhoto)
admin.site.register(ComplaintInspection)
admin.site.register(ComplaintResolution)
admin.site.register(ComplaintVehicle)
admin.site.register(ComplaintPhoto)
admin.site.register(ComplaintMaterial)
