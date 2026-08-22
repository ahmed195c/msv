from django.contrib import admin

from .models import (
    Company,
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
from .views_pkg.common import _inspector_users_qs


@admin.register(PirmetClearance)
class PirmetClearanceAdmin(admin.ModelAdmin):
    list_display = ('id', 'permit_no', 'permit_type', 'company', 'status', 'dateOfCreation')
    list_filter = ('permit_type', 'status')
    search_fields = ('id', 'permit_no', 'PaymentNumber', 'inspection_payment_reference', 'company__name')
    ordering = ('-dateOfCreation',)


@admin.register(InspectorReview)
class InspectorReviewAdmin(admin.ModelAdmin):
    list_display = ('id', 'pirmet', 'inspector_user', 'isApproved', 'reviewDate')
    list_filter = ('isApproved',)
    search_fields = ('pirmet__permit_no', 'pirmet__company__name', 'inspector_user__username')
    ordering = ('-reviewDate',)
    # `inspector` (Enginer FK) is legacy and only read as a fallback for old
    # data — see _inspector_review_name() in views_pkg/common.py. Editing it
    # here would let someone assign a company engineer as the "receiving
    # inspector", which is wrong; the real field is inspector_user.
    exclude = ('inspector',)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'inspector_user':
            kwargs['queryset'] = _inspector_users_qs()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


admin.site.register(Company)
admin.site.register(Enginer)
admin.site.register(PirmetDocument)
admin.site.register(PirmetChangeLog)
admin.site.register(PesticideTransportPermit)
admin.site.register(WasteDisposalPermit)
admin.site.register(RequirementInsuranceRequest)

@admin.register(FieldWorkOrder)
class FieldWorkOrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'work_type', 'site_name', 'status', 'work_date', 'created_at')
    list_filter = ('status',)
    search_fields = ('id', 'work_type', 'location', 'company__name')
    ordering = ('-created_at',)

admin.site.register(FieldWorkPhoto)


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
