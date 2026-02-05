from django.contrib import admin

from .models import (
    Company,
    Enginer,
    InspectorReview,
    PirmetClearance,
    PirmetDocument,
    PirmetChangeLog,
    PesticideTransportPermit,
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
