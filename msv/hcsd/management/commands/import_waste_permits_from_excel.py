import re
import zipfile
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from xml.etree import ElementTree

from django.core.management.base import BaseCommand, CommandError

from hcsd.models import Company, PirmetClearance, WasteDisposalPermit


DEFAULT_XLSX = "/home/a/Downloads/2022 form.xlsx"

NS_MAIN = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
NS_REL = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}

ARABIC_DIGITS_TRANS = str.maketrans("٠١٢٣٤٥٦٧٨٩٫،", "0123456789.,")


def _clean(value):
    if value is None:
        return ""
    return str(value).strip()


def _normalize_spaces(value):
    return re.sub(r"\s+", " ", _clean(value))


def _normalize_identifier(value):
    text = _clean(value).translate(ARABIC_DIGITS_TRANS)
    text = text.upper()
    return re.sub(r"[^0-9A-Z\u0621-\u064A]+", "", text)


def _normalize_name(value):
    text = _normalize_spaces(value)
    return re.sub(r"[^0-9A-Z\u0621-\u064A]+", "", text.upper())


def _parse_excel_date(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = _clean(value).translate(ARABIC_DIGITS_TRANS)
    if not text:
        return None

    # Excel serial date.
    if re.fullmatch(r"-?\d+(\.\d+)?", text):
        try:
            serial = int(float(text))
        except ValueError:
            serial = 0
        if serial > 0:
            return date(1899, 12, 30) + timedelta(days=serial)
        return None

    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _parse_decimal(value):
    text = _clean(value).translate(ARABIC_DIGITS_TRANS)
    if not text:
        return None
    m = re.search(r"\d+(?:[.,]\d+)?", text)
    if not m:
        return None
    num = m.group(0).replace(",", ".")
    try:
        return Decimal(num)
    except (InvalidOperation, ValueError):
        return None


def _col_to_index(col_ref):
    result = 0
    for ch in col_ref:
        if ch.isalpha():
            result = result * 26 + (ord(ch.upper()) - 64)
    return result


def _read_first_sheet_rows(xlsx_path):
    with zipfile.ZipFile(xlsx_path) as zf:
        workbook = ElementTree.fromstring(zf.read("xl/workbook.xml"))
        workbook_rels = ElementTree.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        rel_map = {}
        for rel in workbook_rels.findall("r:Relationship", NS_REL):
            rel_map[rel.attrib.get("Id")] = rel.attrib.get("Target")

        shared_strings = []
        if "xl/sharedStrings.xml" in zf.namelist():
            sst = ElementTree.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in sst.findall("a:si", NS_MAIN):
                text = "".join((node.text or "") for node in si.findall(".//a:t", NS_MAIN))
                shared_strings.append(text)

        sheet = workbook.find("a:sheets/a:sheet", NS_MAIN)
        if sheet is None:
            return []
        rel_id = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        target = rel_map.get(rel_id)
        if not target:
            return []
        sheet_path = "xl/" + target.lstrip("/")
        sheet_path = sheet_path.replace("xl//", "xl/")

        sheet_xml = ElementTree.fromstring(zf.read(sheet_path))
        rows = []
        for row in sheet_xml.findall(".//a:sheetData/a:row", NS_MAIN):
            values_map = {}
            max_idx = 0
            for cell in row.findall("a:c", NS_MAIN):
                ref = cell.attrib.get("r", "")
                col_ref = "".join(ch for ch in ref if ch.isalpha())
                idx = _col_to_index(col_ref)
                if idx <= 0:
                    continue
                max_idx = max(max_idx, idx)

                cell_type = cell.attrib.get("t")
                value_node = cell.find("a:v", NS_MAIN)
                inline_node = cell.find("a:is/a:t", NS_MAIN)
                if cell_type == "s" and value_node is not None:
                    raw = value_node.text or ""
                    try:
                        cell_value = shared_strings[int(raw)]
                    except (ValueError, IndexError):
                        cell_value = raw
                elif value_node is not None:
                    cell_value = value_node.text or ""
                elif inline_node is not None:
                    cell_value = inline_node.text or ""
                else:
                    cell_value = ""
                values_map[idx] = cell_value

            if max_idx == 0:
                continue
            ordered = [values_map.get(i, "") for i in range(1, max_idx + 1)]
            if any(v not in ("", None) for v in ordered):
                rows.append(ordered)
        return rows


class Command(BaseCommand):
    help = (
        "Seed waste disposal permits from an Excel file for companies already "
        "registered in the system only."
    )

    def add_arguments(self, parser):
        parser.add_argument("--file", default=DEFAULT_XLSX, help="Path to XLSX file.")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Read and validate without writing to the database.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Import only the first N data rows (0 = all).",
        )
        parser.add_argument(
            "--update-company",
            action="store_true",
            help="Also update company name/address/activity from the sheet.",
        )

    def handle(self, *args, **options):
        file_path = Path(options["file"]).expanduser()
        dry_run = bool(options["dry_run"])
        limit = int(options["limit"] or 0)
        update_company = bool(options["update_company"])
        if not file_path.exists():
            raise CommandError(f"File not found: {file_path}")

        rows = _read_first_sheet_rows(file_path)
        if not rows:
            raise CommandError("No readable rows found in the workbook.")

        header = [_normalize_spaces(v) for v in rows[0]]
        idx = {name: i for i, name in enumerate(header)}

        col_license = self._first_existing_header(idx, ["رقم الرخصة"])
        col_name = self._first_existing_header(idx, ["الإسم التجاري", "الاسم التجاري"])
        col_address = self._first_existing_header(idx, ["العنوان"])
        col_activity = self._first_existing_header(idx, ["النشاط"])
        col_waste_class = self._first_existing_header(idx, ["تصنيف النفايات"])
        col_waste_qty = self._first_existing_header(idx, ["كمية النفايات (طن/شهر)"])
        col_waste_type = self._first_existing_header(idx, ["نوع النفايات"])
        col_material_state = self._first_existing_header(idx, ["Combo62"])
        col_project_number = self._first_existing_header(idx, ["Text67"])
        col_project_type = self._first_existing_header(idx, ["Text69"])
        col_issue_date = self._first_existing_header(idx, ["تاريخ الإصدار"])
        col_expiry_date = self._first_existing_header(idx, ["تاريخ الإنتهاء", "تاريخ الانتهاء"])
        col_payment_no = self._first_existing_header(idx, ["رقم الإيصال"])
        col_payment_date = self._first_existing_header(idx, ["تاريخ الإيصال"])
        col_employee = self._first_existing_header(idx, ["الموظف المختص"])
        col_contractors = self._first_existing_header(idx, ["Text40"])

        required_missing = []
        for name, col in [
            ("رقم الرخصة", col_license),
            ("الإسم التجاري", col_name),
            ("تاريخ الإصدار", col_issue_date),
            ("تاريخ الإنتهاء", col_expiry_date),
        ]:
            if col is None:
                required_missing.append(name)
        if required_missing:
            raise CommandError(
                "Missing required columns: " + ", ".join(required_missing)
            )

        companies = list(Company.objects.all())
        exact_license_map = {}
        norm_license_map = {}
        exact_name_map = {}
        norm_name_map = {}
        for company in companies:
            c_license = _clean(company.number)
            c_name = _normalize_spaces(company.name)
            exact_license_map.setdefault(c_license, []).append(company)
            norm_license_map.setdefault(_normalize_identifier(c_license), []).append(company)
            exact_name_map.setdefault(c_name, []).append(company)
            norm_name_map.setdefault(_normalize_name(c_name), []).append(company)

        counters = {
            "rows_total": 0,
            "rows_processed": 0,
            "rows_skipped_empty": 0,
            "rows_skipped_unregistered_company": 0,
            "rows_skipped_duplicate_in_file": 0,
            "company_updated": 0,
            "permit_created": 0,
            "permit_updated": 0,
            "permit_unchanged": 0,
            "waste_details_created": 0,
            "waste_details_updated": 0,
        }

        seen_file_keys = set()
        data_rows = rows[1:]
        if limit > 0:
            data_rows = data_rows[:limit]

        for row in data_rows:
            counters["rows_total"] += 1

            license_no = self._value_at(row, idx, col_license)
            company_name = self._value_at(row, idx, col_name)
            if not license_no and not company_name:
                counters["rows_skipped_empty"] += 1
                continue
            if license_no in {"0", "-", "—"}:
                counters["rows_skipped_empty"] += 1
                continue

            company = self._find_company(
                license_no=license_no,
                company_name=company_name,
                exact_license_map=exact_license_map,
                norm_license_map=norm_license_map,
                exact_name_map=exact_name_map,
                norm_name_map=norm_name_map,
            )
            if company is None:
                counters["rows_skipped_unregistered_company"] += 1
                continue

            issue_date = _parse_excel_date(self._value_at(row, idx, col_issue_date))
            expiry_date = _parse_excel_date(self._value_at(row, idx, col_expiry_date))
            payment_number = self._value_at(row, idx, col_payment_no) or None
            payment_date = _parse_excel_date(self._value_at(row, idx, col_payment_date))

            file_key = (
                company.id,
                issue_date.isoformat() if issue_date else "",
                expiry_date.isoformat() if expiry_date else "",
                payment_number or "",
            )
            if file_key in seen_file_keys:
                counters["rows_skipped_duplicate_in_file"] += 1
                continue
            seen_file_keys.add(file_key)

            counters["rows_processed"] += 1

            if update_company:
                company_updates = {}
                address = self._value_at(row, idx, col_address) if col_address else ""
                activity = self._value_at(row, idx, col_activity) if col_activity else ""
                normalized_company_name = _normalize_spaces(company_name)
                if normalized_company_name and company.name != normalized_company_name:
                    company_updates["name"] = normalized_company_name
                if address and company.address != address:
                    company_updates["address"] = address
                if activity and company.business_activity != activity:
                    company_updates["business_activity"] = activity
                if company_updates and not dry_run:
                    for field, value in company_updates.items():
                        setattr(company, field, value)
                    company.save(update_fields=list(company_updates.keys()))
                if company_updates:
                    counters["company_updated"] += 1

            permit = self._find_existing_waste_permit(
                company=company,
                issue_date=issue_date,
                expiry_date=expiry_date,
                payment_number=payment_number,
            )
            permit_created = False
            if permit is None:
                permit_created = True
                permit = PirmetClearance(
                    company=company,
                    permit_type="waste_disposal",
                    status="issued",
                    issue_date=issue_date,
                    dateOfExpiry=expiry_date,
                    PaymentNumber=payment_number,
                    payment_date=payment_date,
                    request_email=company.email or None,
                )
                if not dry_run:
                    permit.save()
                counters["permit_created"] += 1
            else:
                changed = []
                target_updates = {
                    "status": "issued",
                    "issue_date": issue_date,
                    "dateOfExpiry": expiry_date,
                    "PaymentNumber": payment_number,
                    "payment_date": payment_date,
                }
                if not permit.request_email and company.email:
                    target_updates["request_email"] = company.email
                for field, value in target_updates.items():
                    if getattr(permit, field) != value:
                        setattr(permit, field, value)
                        changed.append(field)
                if changed:
                    if not dry_run:
                        permit.save(update_fields=changed)
                    counters["permit_updated"] += 1
                else:
                    counters["permit_unchanged"] += 1

            waste_defaults = {
                "waste_classification": self._value_at(row, idx, col_waste_class) or None,
                "waste_quantity_monthly": _parse_decimal(self._value_at(row, idx, col_waste_qty)),
                "waste_types": self._value_at(row, idx, col_waste_type) or None,
                "material_state": self._value_at(row, idx, col_material_state) or None,
                "project_number": self._value_at(row, idx, col_project_number) or None,
                "project_type": self._value_at(row, idx, col_project_type) or None,
                "contractors": self._value_at(row, idx, col_contractors) or None,
                "employee_number": self._value_at(row, idx, col_employee) or None,
            }
            if permit_created and dry_run:
                counters["waste_details_created"] += 1
            elif dry_run:
                counters["waste_details_updated"] += 1
            else:
                _, detail_created = WasteDisposalPermit.objects.update_or_create(
                    pirmet=permit,
                    defaults=waste_defaults,
                )
                if detail_created:
                    counters["waste_details_created"] += 1
                else:
                    counters["waste_details_updated"] += 1

        self.stdout.write(self.style.SUCCESS("Waste permit import finished."))
        self.stdout.write(f"File: {file_path}")
        for key, value in counters.items():
            self.stdout.write(f"{key}: {value}")
        self.stdout.write(
            "Note: only companies already registered in Company table are imported."
        )

    @staticmethod
    def _value_at(row, idx, key):
        if key is None:
            return ""
        i = idx.get(key)
        if i is None or i >= len(row):
            return ""
        return _clean(row[i])

    @staticmethod
    def _first_existing_header(idx_map, candidates):
        for key in candidates:
            if key in idx_map:
                return key
        return None

    @staticmethod
    def _pick_unique(matches):
        if not matches:
            return None
        if len(matches) == 1:
            return matches[0]
        return None

    def _find_company(
        self,
        license_no,
        company_name,
        exact_license_map,
        norm_license_map,
        exact_name_map,
        norm_name_map,
    ):
        # Priority 1: license number exact, then normalized.
        exact_match = self._pick_unique(exact_license_map.get(_clean(license_no), []))
        if exact_match:
            return exact_match
        norm_license = _normalize_identifier(license_no)
        norm_match = self._pick_unique(norm_license_map.get(norm_license, []))
        if norm_match:
            return norm_match

        # Fallback only when license did not match anything.
        exact_name = self._pick_unique(exact_name_map.get(_normalize_spaces(company_name), []))
        if exact_name:
            return exact_name
        norm_name = self._pick_unique(norm_name_map.get(_normalize_name(company_name), []))
        return norm_name

    @staticmethod
    def _find_existing_waste_permit(company, issue_date, expiry_date, payment_number):
        qs = PirmetClearance.objects.filter(company=company, permit_type="waste_disposal")
        if issue_date and expiry_date:
            permit = qs.filter(issue_date=issue_date, dateOfExpiry=expiry_date).order_by("-id").first()
            if permit:
                return permit
        if payment_number:
            permit = qs.filter(PaymentNumber=payment_number).order_by("-id").first()
            if permit:
                return permit
        if issue_date:
            permit = qs.filter(issue_date=issue_date).order_by("-id").first()
            if permit:
                return permit
        return None
