"""
Management command to seed PesticideTransportPermit records from Form1.xlsx.

Usage:
    python manage.py import_vehicle_permits_from_excel
    python manage.py import_vehicle_permits_from_excel --xlsx /path/to/file.xlsx
    python manage.py import_vehicle_permits_from_excel --dry-run
"""
import re
from pathlib import Path

import openpyxl
from django.core.management.base import BaseCommand, CommandError

from hcsd.models import Company, PesticideTransportPermit, PirmetClearance

DEFAULT_XLSX = Path(__file__).resolve().parents[2] / "static" / "hcsd" / "Form1.xlsx"

# ── Column indices (0-based) ────────────────────────────────────────────────
COL_PERMIT_NO       = 0
COL_ISSUE_DATE      = 1
COL_COMPANY_NAME    = 2
COL_LICENSE_NO      = 3
COL_CONTACT         = 4
COL_ADDRESS         = 5
COL_TRADE_EXP       = 6   # تصنيف الشركة → trade_license_exp
COL_ACTIVITY_TYPE   = 7   # Text36 → نوع النشاط
COL_VEHICLE_TYPE    = 8
COL_VEHICLE_COLOR   = 9
COL_VEHICLE_NUMBER  = 10
COL_ISSUE_AUTHORITY = 11
COL_VEH_LIC_EXP    = 12
COL_PAYMENT_NO      = 13
COL_PAYMENT_DATE    = 14
COL_EXPIRY_DATE     = 15


def _clean(v):
    return str(v).strip() if v is not None else ""


def _normalize_name(v):
    """Strip punctuation/spaces to compare Arabic names loosely."""
    text = _clean(v).upper()
    text = re.sub(r"[\s\u0640]+", "", text)            # remove tatweel/spaces
    text = re.sub(r"[^\u0621-\u064A0-9A-Z]", "", text)
    return text


def _normalize_number(v):
    return re.sub(r"\D", "", _clean(str(v)))


def _as_date(v):
    if v is None:
        return None
    if hasattr(v, "date"):
        return v.date()
    return None


class Command(BaseCommand):
    help = "Import pesticide transport permits (vehicle permits) from Form1.xlsx"

    def add_arguments(self, parser):
        parser.add_argument(
            "--xlsx",
            default=str(DEFAULT_XLSX),
            help="Path to Form1.xlsx (defaults to hcsd/static/hcsd/Form1.xlsx)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse the file and report what would be created/updated without saving",
        )

    def handle(self, *args, **options):
        xlsx_path = Path(options["xlsx"])
        dry_run   = options["dry_run"]

        if not xlsx_path.exists():
            raise CommandError(f"File not found: {xlsx_path}")

        wb = openpyxl.load_workbook(xlsx_path, data_only=True)
        ws = wb.active

        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            raise CommandError("Worksheet is empty.")

        # Skip header row
        data_rows = rows[1:]

        created_companies  = 0
        updated_companies  = 0
        created_permits    = 0
        skipped            = 0
        errors             = []

        for idx, row in enumerate(data_rows, start=2):  # start=2 = Excel row number
            # Skip fully empty rows
            if not any(row):
                continue

            company_name = _clean(row[COL_COMPANY_NAME])
            license_no   = _normalize_number(row[COL_LICENSE_NO]) if row[COL_LICENSE_NO] else ""

            if not company_name and not license_no:
                self.stdout.write(self.style.WARNING(f"  Row {idx}: no name/license, skipping."))
                skipped += 1
                continue

            # ── 1. Find or create Company ───────────────────────────────────
            company = None

            # Try match by license number first (most reliable)
            if license_no:
                company = Company.objects.filter(number=license_no).first()

            # Fall back to normalised name match
            if company is None and company_name:
                norm = _normalize_name(company_name)
                for c in Company.objects.all():
                    if _normalize_name(c.name) == norm:
                        company = c
                        break

            if company is None:
                # Create new company
                self.stdout.write(f"  Row {idx}: creating company '{company_name}'")
                if not dry_run:
                    company = Company.objects.create(
                        name=company_name,
                        number=license_no or _clean(row[COL_LICENSE_NO]),
                        address=_clean(row[COL_ADDRESS]),
                        owner_phone=_clean(row[COL_CONTACT]),
                        trade_license_exp=_as_date(row[COL_TRADE_EXP]),
                    )
                created_companies += 1
            else:
                # Update missing fields only
                changed = False
                updates = {}
                if not company.number and license_no:
                    updates["number"] = license_no
                if not company.address and row[COL_ADDRESS]:
                    updates["address"] = _clean(row[COL_ADDRESS])
                if not company.owner_phone and row[COL_CONTACT]:
                    updates["owner_phone"] = _clean(row[COL_CONTACT])
                if not company.trade_license_exp and row[COL_TRADE_EXP]:
                    updates["trade_license_exp"] = _as_date(row[COL_TRADE_EXP])
                if updates:
                    changed = True
                    self.stdout.write(f"  Row {idx}: updating company '{company.name}' fields: {list(updates)}")
                    if not dry_run:
                        for k, v in updates.items():
                            setattr(company, k, v)
                        company.save(update_fields=list(updates))
                    updated_companies += 1

            if dry_run:
                created_permits += 1
                continue

            # ── 2. Create PirmetClearance ───────────────────────────────────
            pirmet = PirmetClearance.objects.create(
                company=company,
                permit_type="pesticide_transport",
                status="issued",
                issue_date=_as_date(row[COL_ISSUE_DATE]),
                dateOfExpiry=_as_date(row[COL_EXPIRY_DATE]),
                payment_date=_as_date(row[COL_PAYMENT_DATE]),
                PaymentNumber=_clean(row[COL_PAYMENT_NO]),
            )

            # ── 3. Create PesticideTransportPermit ──────────────────────────
            PesticideTransportPermit.objects.create(
                pirmet=pirmet,
                contact_number=_clean(row[COL_CONTACT]),
                activity_type=_clean(row[COL_ACTIVITY_TYPE]),
                vehicle_type=_clean(row[COL_VEHICLE_TYPE]),
                vehicle_color=_clean(row[COL_VEHICLE_COLOR]),
                vehicle_number=_clean(row[COL_VEHICLE_NUMBER]),
                issue_authority=_clean(row[COL_ISSUE_AUTHORITY]),
                vehicle_license_expiry=_as_date(row[COL_VEH_LIC_EXP]),
            )

            created_permits += 1

        # ── Summary ─────────────────────────────────────────────────────────
        mode = "[DRY RUN] " if dry_run else ""
        self.stdout.write(self.style.SUCCESS(
            f"\n{mode}Done: "
            f"{created_companies} companies created, "
            f"{updated_companies} companies updated, "
            f"{created_permits} permits created, "
            f"{skipped} rows skipped."
        ))
        if errors:
            self.stdout.write(self.style.ERROR(f"{len(errors)} errors:"))
            for e in errors:
                self.stdout.write(self.style.ERROR(f"  {e}"))
