from .dashboard import home
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
from .clearance import clearance_list, permit_types
from .vehicle import vehicle_permit, vehicle_permit_detail
from .waste import waste_permit, waste_permit_detail, waste_disposal_request_detail
from .pest_control import (
    pest_control_permit,
    pest_control_permit_detail,
    pest_control_permit_print,
    pest_control_permit_view,
)
from .misc import register, vehicle_permit_print, waste_disposal_permit_print, printer

__all__ = [
    'home',
    'company_list', 'extension_followup', 'add_company', 'company_detail',
    'requirement_insurance_request_detail', 'requirement_insurance_create',
    'enginer_list', 'enginer_add', 'enginer_detail',
    'public_health_exam_request_list', 'public_health_exam_request_detail',
    'engineer_certificate_request_list', 'engineer_certificate_request_detail',
    'clearance_list', 'permit_types',
    'vehicle_permit', 'vehicle_permit_detail',
    'waste_permit', 'waste_permit_detail', 'waste_disposal_request_detail',
    'pest_control_permit', 'pest_control_permit_detail',
    'pest_control_permit_print', 'pest_control_permit_view',
    'register', 'vehicle_permit_print', 'waste_disposal_permit_print', 'printer',
]
