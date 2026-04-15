from django.contrib import admin

from .models import (
    Company,
    Complaint, ComplaintInspection, ComplaintResolution, ComplaintVehicle, ComplaintPhoto, ComplaintMaterial,
    Enginer,
    InspectorReview,
    PirmetClearance,
    PirmetDocument,
    PirmetChangeLog,
    PesticideTransportPermit,
    RequirementInsuranceRequest,
    WasteDisposalPermit,
)

# Register your models here.


admin.site.register(Company)
admin.site.register(Enginer)
admin.site.register(PirmetClearance)
admin.site.register(PirmetDocument)
admin.site.register(InspectorReview)
admin.site.register(PirmetChangeLog)
admin.site.register(PesticideTransportPermit)
admin.site.register(WasteDisposalPermit)
admin.site.register(RequirementInsuranceRequest)
admin.site.register(Complaint)
admin.site.register(ComplaintInspection)
admin.site.register(ComplaintResolution)
admin.site.register(ComplaintVehicle)
admin.site.register(ComplaintPhoto)
admin.site.register(ComplaintMaterial)
