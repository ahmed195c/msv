import datetime

from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand

from hcsd.models import (
    Company,
    CompanyChangeLog,
    Enginer,
    InspectorReview,
    PesticideTransportPermit,
    PirmetChangeLog,
    PirmetClearance,
    WasteDisposalRequest,
)


class Command(BaseCommand):
    help = "Seed demo companies and permits (pest, vehicle, waste) with old/new lifecycle states."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset-demo",
            action="store_true",
            help="Delete existing demo companies (number starts with DEMO-) before seeding.",
        )

    def handle(self, *args, **options):
        today = datetime.date.today()
        if options["reset_demo"]:
            demo_companies = Company.objects.filter(number__startswith="DEMO-")
            count = demo_companies.count()
            demo_companies.delete()
            self.stdout.write(self.style.WARNING(f"Deleted {count} existing demo companies."))

        admin_user = self._ensure_user("demo_admin", "Admin", "Demo")
        inspector_user = self._ensure_user("demo_inspector", "Inspector", "Demo")
        data_entry_user = self._ensure_user("demo_data_entry", "DataEntry", "Demo")
        self._ensure_group(admin_user, "admin")
        self._ensure_group(inspector_user, "inspector")
        self._ensure_group(data_entry_user, "data_entry")

        eng_1 = self._ensure_engineer("مهندس تجريبي 1", "0500000001", "demo.eng1@example.com")
        eng_2 = self._ensure_engineer("مهندس تجريبي 2", "0500000002", "demo.eng2@example.com")

        company_1 = self._ensure_company(
            name="شركة تجريبية ألف",
            number="DEMO-001",
            trade_exp=today + datetime.timedelta(days=220),
            address="الشارقة - المنطقة الصناعية",
            owner_phone="0501111111",
            email="demo.alpha@example.com",
            engineer=eng_1,
        )
        company_2 = self._ensure_company(
            name="شركة تجريبية باء",
            number="DEMO-002",
            trade_exp=today + datetime.timedelta(days=180),
            address="الشارقة - الجرينة",
            owner_phone="0502222222",
            email="demo.beta@example.com",
            engineer=eng_2,
        )
        company_3 = self._ensure_company(
            name="شركة تجريبية جيم",
            number="DEMO-003",
            trade_exp=today + datetime.timedelta(days=120),
            address="الشارقة - النهدة",
            owner_phone="0503333333",
            email="demo.gamma@example.com",
            engineer=eng_1,
        )

        # Company 1: old expired pest + new issued pest, vehicle issued, waste old expired + new issued.
        old_pest = self._create_permit(
            company_1,
            permit_type="pest_control",
            status="issued",
            issue_date=today - datetime.timedelta(days=420),
            expiry_date=today - datetime.timedelta(days=55),
            payment_no="PAY-DEMO-001-OLD-PC",
            request_email="ops.alpha@example.com",
        )
        self._log_lifecycle(old_pest, data_entry_user, "Old pest permit expired.")

        new_pest = self._create_permit(
            company_1,
            permit_type="pest_control",
            status="issued",
            issue_date=today - datetime.timedelta(days=20),
            expiry_date=today + datetime.timedelta(days=345),
            payment_no="PAY-DEMO-001-NEW-PC",
            request_email="ops.alpha@example.com",
        )
        self._log_lifecycle(new_pest, data_entry_user, "New pest permit issued after renewal.")

        vehicle = self._create_permit(
            company_1,
            permit_type="pesticide_transport",
            status="issued",
            issue_date=today - datetime.timedelta(days=15),
            expiry_date=today + datetime.timedelta(days=350),
            payment_no="PAY-DEMO-001-VH",
            request_email="fleet.alpha@example.com",
        )
        PesticideTransportPermit.objects.update_or_create(
            pirmet=vehicle,
            defaults={
                "contact_number": company_1.owner_phone,
                "vehicle_type": "بيك اب",
                "vehicle_color": "أبيض",
                "vehicle_number": "SHJ-12345",
                "issue_authority": "شرطة الشارقة",
                "vehicle_license_expiry": today + datetime.timedelta(days=240),
            },
        )
        self._log_lifecycle(vehicle, data_entry_user, "Vehicle permit fully completed.")

        old_waste = self._create_permit(
            company_1,
            permit_type="waste_disposal",
            status="issued",
            issue_date=today - datetime.timedelta(days=320),
            expiry_date=today - datetime.timedelta(days=130),
            payment_no="PAY-DEMO-001-OLD-WD",
            request_email="waste.alpha@example.com",
        )
        self._log_lifecycle(old_waste, admin_user, "Old waste permit expired.")

        active_waste = self._create_permit(
            company_1,
            permit_type="waste_disposal",
            status="issued",
            issue_date=today - datetime.timedelta(days=40),
            expiry_date=today + datetime.timedelta(days=140),
            payment_no="PAY-DEMO-001-NEW-WD",
            request_email="waste.alpha@example.com",
        )
        self._log_lifecycle(active_waste, admin_user, "Active waste permit issued for 6 months.")
        self._log_company_event(company_1, "waste_permit_issued", admin_user, f"تم إصدار تصريح التخلص #{active_waste.permit_no}.")

        self._create_waste_request(
            active_waste,
            status="completed",
            reference="WD-REQ-001-A",
            notes="تمت عملية التخلص بنجاح.",
            inspected_by=inspector_user,
            changed_by=inspector_user,
        )
        self._create_waste_request(
            active_waste,
            status="rejected",
            reference="WD-REQ-001-B",
            notes="رفض بسبب عدم مطابقة التغليف.",
            inspected_by=inspector_user,
            changed_by=inspector_user,
        )
        self._create_waste_request(
            active_waste,
            status="inspection_pending",
            reference="WD-REQ-001-C",
            notes="بانتظار التفتيش.",
            inspected_by=None,
            changed_by=data_entry_user,
        )

        # Company 2: permits in-progress for workflow demo.
        pest_pending = self._create_permit(
            company_2,
            permit_type="pest_control",
            status="inspection_pending",
            issue_date=None,
            expiry_date=None,
            payment_no=None,
            request_email="ops.beta@example.com",
        )
        InspectorReview.objects.update_or_create(
            pirmet=pest_pending,
            defaults={
                "inspector": eng_2,
                "inspector_user": inspector_user,
                "isApproved": False,
                "comments": "تم استلام الطلب للتفتيش.",
            },
        )
        self._log_status(pest_pending, data_entry_user, "order_received", "inspection_pending", "Moved to inspection.")

        vehicle_payment = self._create_permit(
            company_2,
            permit_type="pesticide_transport",
            status="payment_pending",
            issue_date=None,
            expiry_date=None,
            payment_no="PAY-DEMO-002-VH",
            request_email="fleet.beta@example.com",
        )
        PesticideTransportPermit.objects.update_or_create(
            pirmet=vehicle_payment,
            defaults={
                "contact_number": company_2.owner_phone,
                "vehicle_type": "فان",
                "vehicle_color": "رمادي",
                "vehicle_number": "SHJ-67890",
                "issue_authority": "شرطة الشارقة",
                "vehicle_license_expiry": today + datetime.timedelta(days=180),
            },
        )
        self._log_status(vehicle_payment, admin_user, "inspection_completed", "payment_pending", "Awaiting payment.")

        waste_paid_not_issued = self._create_permit(
            company_2,
            permit_type="waste_disposal",
            status="payment_completed",
            issue_date=None,
            expiry_date=None,
            payment_no="PAY-DEMO-002-WD",
            request_email="waste.beta@example.com",
        )
        self._log_status(waste_paid_not_issued, admin_user, "payment_pending", "payment_completed", "Waste permit paid and awaiting issue.")
        self._log_company_event(company_2, "waste_permit_paid", admin_user, f"تم تأكيد دفع تصريح التخلص #{waste_paid_not_issued.permit_no}.")

        # Company 3: ended waste permit + new draft/payment_pending.
        waste_expired = self._create_permit(
            company_3,
            permit_type="waste_disposal",
            status="issued",
            issue_date=today - datetime.timedelta(days=260),
            expiry_date=today - datetime.timedelta(days=70),
            payment_no="PAY-DEMO-003-OLD-WD",
            request_email="waste.gamma@example.com",
        )
        self._log_lifecycle(waste_expired, admin_user, "Expired waste permit.")

        waste_new_pending = self._create_permit(
            company_3,
            permit_type="waste_disposal",
            status="payment_pending",
            issue_date=None,
            expiry_date=None,
            payment_no="PAY-DEMO-003-NEW-WD",
            request_email="waste.gamma@example.com",
        )
        self._log_status(waste_new_pending, data_entry_user, "order_received", "payment_pending", "New waste renewal request created.")
        self._log_company_event(company_3, "waste_permit_created", data_entry_user, f"تم إنشاء طلب تجديد تصريح التخلص #{waste_new_pending.permit_no}.")

        self.stdout.write(self.style.SUCCESS("Demo data seeded successfully."))

    def _ensure_user(self, username, first_name, last_name):
        user, _ = User.objects.get_or_create(
            username=username,
            defaults={
                "first_name": first_name,
                "last_name": last_name,
                "email": f"{username}@example.com",
                "is_staff": True,
                "is_active": True,
            },
        )
        return user

    def _ensure_group(self, user, group_name):
        group, _ = Group.objects.get_or_create(name=group_name)
        user.groups.add(group)

    def _ensure_engineer(self, name, phone, email):
        eng, _ = Enginer.objects.get_or_create(
            email=email,
            defaults={
                "name": name,
                "phone": phone,
                "national_or_unified_number": phone,
            },
        )
        if eng.name != name or eng.phone != phone:
            eng.name = name
            eng.phone = phone
            eng.save(update_fields=["name", "phone"])
        return eng

    def _ensure_company(self, name, number, trade_exp, address, owner_phone, email, engineer):
        company, created = Company.objects.get_or_create(
            number=number,
            defaults={
                "name": name,
                "trade_license_exp": trade_exp,
                "address": address,
                "owner_phone": owner_phone,
                "email": email,
                "business_activity": "pest_control,buy_sell",
                "pest_control_type": "public_health_pest_control",
                "enginer": engineer,
            },
        )
        if not created:
            company.name = name
            company.trade_license_exp = trade_exp
            company.address = address
            company.owner_phone = owner_phone
            company.email = email
            company.business_activity = "pest_control,buy_sell"
            company.pest_control_type = "public_health_pest_control"
            company.enginer = engineer
            company.save()
        company.engineers.add(engineer)
        return company

    def _create_permit(self, company, permit_type, status, issue_date, expiry_date, payment_no, request_email):
        permit = PirmetClearance.objects.create(
            company=company,
            permit_type=permit_type,
            status=status,
            issue_date=issue_date,
            dateOfExpiry=expiry_date,
            PaymentNumber=payment_no,
            payment_date=issue_date if status in {"payment_completed", "issued"} and issue_date else None,
            request_email=request_email,
        )
        return permit

    def _log_status(self, permit, user, old_status, new_status, notes):
        PirmetChangeLog.objects.create(
            pirmet=permit,
            change_type="status_change",
            old_status=old_status,
            new_status=new_status,
            notes=notes,
            changed_by=user,
        )

    def _log_lifecycle(self, permit, user, notes):
        PirmetChangeLog.objects.create(
            pirmet=permit,
            change_type="created",
            old_status=None,
            new_status=permit.status,
            notes=notes,
            changed_by=user,
        )

    def _log_company_event(self, company, action, user, notes):
        CompanyChangeLog.objects.create(
            company=company,
            action=action,
            notes=notes,
            changed_by=user,
        )

    def _create_waste_request(self, permit, status, reference, notes, inspected_by, changed_by):
        request = WasteDisposalRequest.objects.create(
            permit=permit,
            status=status,
            disposal_reference=reference,
            inspection_notes=notes,
            inspected_by=inspected_by,
        )
        CompanyChangeLog.objects.create(
            company=permit.company,
            action="waste_request_created",
            notes=f"تم إنشاء طلب التخلص رقم {request.id}.",
            changed_by=changed_by,
        )
        CompanyChangeLog.objects.create(
            company=permit.company,
            action="waste_request_inspected",
            notes=f"نتيجة الطلب {request.id}: {request.get_status_display()}",
            changed_by=changed_by,
        )
        PirmetChangeLog.objects.create(
            pirmet=permit,
            change_type="details_update",
            notes=f"waste_disposal_inspection:{request.id}:{status}",
            changed_by=changed_by,
        )
        return request
