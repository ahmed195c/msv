from .portal import portal_landing
from .dashboard import home
from .complaints import (
    complaints_dashboard, complaint_submit, complaint_detail,
    set_complaints_language, complaint_assign_inspector, complaint_inspection_save,
    complaint_assign_supervisor, complaint_resolution_save,
    complaint_add_photos, complaint_photo_delete,
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

__all__ = [
    'portal_landing', 'home', 'complaints_dashboard', 'complaint_submit', 'complaint_detail',
    'set_complaints_language', 'complaint_assign_inspector', 'complaint_inspection_save',
    'complaint_assign_supervisor', 'complaint_resolution_save',
    'complaint_add_photos', 'complaint_photo_delete',
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
]
