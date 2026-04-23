from .portal import portal_landing
from .dashboard import home
from .complaints import (
    complaints_dashboard, complaint_submit, complaint_detail,
    set_complaints_language, complaint_assign_inspector, complaint_inspection_save,
    complaint_assign_supervisor, complaint_resolution_save,
    complaint_add_photos, complaint_photo_delete,
    complaint_pdf_import, complaint_pdf_review,
    all_requests,
)
from .company import (
    company_list,
    extension_followup,
    add_company,
    company_detail,
    requirement_insurance_request_detail,
    requirement_insurance_create,
)
from .engineers import (
    enginer_list,
    enginer_add,
    enginer_detail,
    public_health_exam_request_list,
    public_health_exam_request_detail,
    engineer_certificate_request_list,
    engineer_certificate_request_detail,
)
from .clearance import clearance_list, permit_types, permits_report_excel, inspector_report_excel
from .vehicle import vehicle_permit, vehicle_permit_detail
from .waste import waste_permit, waste_permit_detail, waste_disposal_request_detail
from .pest_control import (
    pest_control_permit,
    pest_control_permit_detail,
    pest_control_permit_print,
    pest_control_permit_view,
)
from .misc import register, vehicle_permit_print, waste_disposal_permit_print, printer
from .engineer_addition import engineer_addition_create, engineer_addition_detail
from .field_work import field_work_list, field_work_create, field_work_detail, field_work_report
from .weed_removal import (
    weed_list, weed_create, weed_detail,
    weed_assign_inspector, weed_inspector_done,
    weed_assign_supervisor, weed_supervisor_start,
    weed_add_vehicle, weed_delete_vehicle,
    weed_upload_photos, weed_supervisor_done,
    weed_reject, weed_close, weed_photo_delete,
)
from .container_transfer import (
    container_list, container_create, container_pdf_import, container_pdf_review, container_detail,
    container_assign_inspector, container_save_location, container_contact_biaa,
    container_mark_transferred, container_submit_report, container_close,
    container_photo_delete, container_reject,
)

__all__ = [
    'portal_landing', 'home', 'complaints_dashboard', 'complaint_submit', 'complaint_detail',
    'set_complaints_language', 'complaint_assign_inspector', 'complaint_inspection_save',
    'complaint_assign_supervisor', 'complaint_resolution_save',
    'complaint_add_photos', 'complaint_photo_delete',
    'complaint_pdf_import', 'complaint_pdf_review',
    'company_list', 'extension_followup', 'add_company', 'company_detail',
    'requirement_insurance_request_detail', 'requirement_insurance_create',
    'enginer_list', 'enginer_add', 'enginer_detail',
    'public_health_exam_request_list', 'public_health_exam_request_detail',
    'engineer_certificate_request_list', 'engineer_certificate_request_detail',
    'clearance_list', 'permit_types', 'permits_report_excel', 'inspector_report_excel',
    'vehicle_permit', 'vehicle_permit_detail',
    'waste_permit', 'waste_permit_detail', 'waste_disposal_request_detail',
    'pest_control_permit', 'pest_control_permit_detail',
    'pest_control_permit_print', 'pest_control_permit_view',
    'register', 'vehicle_permit_print', 'waste_disposal_permit_print', 'printer',
    'engineer_addition_create', 'engineer_addition_detail',
    'field_work_list', 'field_work_create', 'field_work_detail', 'field_work_report',
    'container_list', 'container_create', 'container_pdf_import', 'container_pdf_review', 'container_detail',
    'container_assign_inspector', 'container_save_location', 'container_contact_biaa',
    'container_mark_transferred', 'container_submit_report', 'container_close',
    'container_photo_delete', 'container_reject',
    'weed_list', 'weed_create', 'weed_detail',
    'weed_assign_inspector', 'weed_inspector_done',
    'weed_assign_supervisor', 'weed_supervisor_start',
    'weed_add_vehicle', 'weed_delete_vehicle',
    'weed_upload_photos', 'weed_supervisor_done',
    'weed_reject', 'weed_close', 'weed_photo_delete',
]
