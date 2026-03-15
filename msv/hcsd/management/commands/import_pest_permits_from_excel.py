"""
Management command to seed PestControl (مزاولة نشاط) permits from Excel.

Usage:
    python manage.py import_pest_permits_from_excel
    python manage.py import_pest_permits_from_excel --xlsx /path/to/file.xlsx
    python manage.py import_pest_permits_from_excel --dry-run
"""
import re
from pathlib import Path

import openpyxl
from django.core.management.base import BaseCommand, CommandError

from hcsd.models import Company, PirmetClearance

DEFAULT_XLSX = Path("/home/a/Downloads/مزاولة-مهندس - SCM-AGE-ENV-F-85-01.xlsx")

# ── Column indices (0-based) ──────────────────────────────────────────────────
COL_COMPANY_NAME   = 0
COL_LICENSE_NO     = 1
COL_TRADE_EXP      = 2
COL_ADDRESS        = 3
COL_LANDLINE       = 4
COL_OWNER_PHONE    = 5
COL_EMAIL          = 6
COL_ISSUE_DATE     = 7
COL_EXPIRY_DATE    = 8
COL_PAYMENT_NO     = 9
COL_ALLOWED_1      = 16
COL_ALLOWED_2      = 17
COL_ALLOWED_3      = 18
COL_RESTRICTED_1   = 19
COL_RESTRICTED_2   = 20
COL_RESTRICTED_3   = 21

# ── Arabic activity names → model keys ───────────────────────────────────────
ACTIVITY_MAP = {
    'مكافحة افات الصحة العامة':    'public_health_pest_control',
    'مكافحة آفات الصحة العامة':    'public_health_pest_control',
    'مكافحة الحشرات الطائرة':      'flying_insects',
    'مكافحة القوارض':              'rodents',
    'مكافحة النمل الابيض':         'termite_control',
    'مكافحة النمل الأبيض':         'termite_control',
    'مكافحة افات الحبوب':          'grain_pests',
    'مكافحة آفات الحبوب':          'grain_pests',
}


def _clean(v):
    return str(v).strip() if v is not None else ''


def _normalize_name(v):
    text = _clean(v).upper()
    text = re.sub(r'[\s\u0640]+', '', text)
    return re.sub(r'[^\u0621-\u064A0-9A-Z]', '', text)


def _normalize_number(v):
    return re.sub(r'\D', '', _clean(str(v)))


def _as_date(v):
    if v is None:
        return None
    if hasattr(v, 'date'):
        return v.date()
    return None


def _map_activity(text):
    """Map Arabic activity text to model key. Partial match allowed."""
    t = _clean(text)
    if not t:
        return None
    # exact match first
    if t in ACTIVITY_MAP:
        return ACTIVITY_MAP[t]
    # partial match
    for ar, key in ACTIVITY_MAP.items():
        if ar in t or t in ar:
            return key
    return None


def _collect_activities(row, *cols):
    """Gather non-empty mapped activity keys from multiple columns, preserving order."""
    seen = []
    for col in cols:
        val = row[col] if col < len(row) else None
        key = _map_activity(_clean(val))
        if key and key not in seen:
            seen.append(key)
    return ','.join(seen)


class Command(BaseCommand):
    help = 'Import pest control activity permits (مزاولة نشاط) from Excel'

    def add_arguments(self, parser):
        parser.add_argument(
            '--xlsx',
            default=str(DEFAULT_XLSX),
            help='Path to the Excel file',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Parse without saving',
        )

    def handle(self, *args, **options):
        xlsx_path = Path(options['xlsx'])
        dry_run   = options['dry_run']

        if not xlsx_path.exists():
            raise CommandError(f'File not found: {xlsx_path}')

        wb = openpyxl.load_workbook(xlsx_path, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            raise CommandError('Worksheet is empty.')

        data_rows = rows[1:]  # skip header

        created_companies  = 0
        updated_companies  = 0
        created_permits    = 0
        skipped            = 0

        for idx, row in enumerate(data_rows, start=2):
            if not any(row):
                continue

            company_name = _clean(row[COL_COMPANY_NAME])
            license_no   = _normalize_number(row[COL_LICENSE_NO]) if row[COL_LICENSE_NO] else ''

            if not company_name and not license_no:
                self.stdout.write(self.style.WARNING(f'  Row {idx}: no name/license, skipping.'))
                skipped += 1
                continue

            # ── 1. Find or create Company ──────────────────────────────────
            company = None

            if license_no:
                company = Company.objects.filter(number=license_no).first()

            if company is None and company_name:
                norm = _normalize_name(company_name)
                for c in Company.objects.all():
                    if _normalize_name(c.name) == norm:
                        company = c
                        break

            if company is None:
                self.stdout.write(f'  Row {idx}: creating company "{company_name}"')
                if not dry_run:
                    company = Company.objects.create(
                        name=company_name,
                        number=license_no or _clean(row[COL_LICENSE_NO]),
                        address=_clean(row[COL_ADDRESS]),
                        landline=_clean(row[COL_LANDLINE]),
                        owner_phone=_clean(row[COL_OWNER_PHONE]),
                        email=_clean(row[COL_EMAIL]) or None,
                        trade_license_exp=_as_date(row[COL_TRADE_EXP]),
                    )
                created_companies += 1
            else:
                updates = {}
                if not company.number and license_no:
                    updates['number'] = license_no
                if not company.address and row[COL_ADDRESS]:
                    updates['address'] = _clean(row[COL_ADDRESS])
                if not company.landline and row[COL_LANDLINE]:
                    updates['landline'] = _clean(row[COL_LANDLINE])
                if not company.owner_phone and row[COL_OWNER_PHONE]:
                    updates['owner_phone'] = _clean(row[COL_OWNER_PHONE])
                if not company.email and row[COL_EMAIL]:
                    updates['email'] = _clean(row[COL_EMAIL]) or None
                if not company.trade_license_exp and row[COL_TRADE_EXP]:
                    updates['trade_license_exp'] = _as_date(row[COL_TRADE_EXP])
                if updates:
                    self.stdout.write(f'  Row {idx}: updating "{company.name}" {list(updates)}')
                    if not dry_run:
                        for k, v in updates.items():
                            setattr(company, k, v)
                        company.save(update_fields=list(updates))
                    updated_companies += 1

            if dry_run:
                created_permits += 1
                continue

            # ── 2. Create PirmetClearance ──────────────────────────────────
            allowed_activities    = _collect_activities(row, COL_ALLOWED_1, COL_ALLOWED_2, COL_ALLOWED_3)
            restricted_activities = _collect_activities(row, COL_RESTRICTED_1, COL_RESTRICTED_2, COL_RESTRICTED_3)

            PirmetClearance.objects.create(
                company=company,
                permit_type='pest_control',
                status='issued',
                issue_date=_as_date(row[COL_ISSUE_DATE]),
                dateOfExpiry=_as_date(row[COL_EXPIRY_DATE]),
                payment_date=_as_date(row[COL_ISSUE_DATE]),
                PaymentNumber=_clean(row[COL_PAYMENT_NO]),
                allowed_activities=allowed_activities or None,
                restricted_activities=restricted_activities or None,
            )

            created_permits += 1

        mode = '[DRY RUN] ' if dry_run else ''
        self.stdout.write(self.style.SUCCESS(
            f'\n{mode}Done: '
            f'{created_companies} companies created, '
            f'{updated_companies} companies updated, '
            f'{created_permits} permits created, '
            f'{skipped} rows skipped.'
        ))
