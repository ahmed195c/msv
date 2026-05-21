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
    UserProfile,
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


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'admin_number', 'get_full_name', 'get_email')
    search_fields = ('admin_number', 'user__username', 'user__first_name', 'user__email')
    ordering = ('admin_number',)

    @admin.display(description='الاسم')
    def get_full_name(self, obj):
        return obj.user.get_full_name() or '—'

    @admin.display(description='البريد الإلكتروني')
    def get_email(self, obj):
        return obj.user.email or '—'
