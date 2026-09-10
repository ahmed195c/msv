"""
One-time historical import of "Follow up map.xlsx" — the source spreadsheet
behind the "متابعة المناطق" (area/manhole follow-up) tracking. The sheet format
evolved over the year: Jan-July only recorded free-text "Activities"/"Qyt"
pairs, while Aug/SEP switched to the current Infested Manholes / Infested
Outside / Total Infested Bldg. breakdown. Older months are imported with
their activity text folded into `notes`, since the specific counts simply
weren't tracked yet — nothing is fabricated to fill the gap.

Safe to re-run — rows are matched on (visit_date, area_name, latitude,
longitude), which is unique in practice since two real observations never
share the same exact date, area, and GPS point.
"""
import datetime

import openpyxl
from django.core.management.base import BaseCommand, CommandError

from hcsd.models import GardenVisit

DEFAULT_PATH = 'hcsd/static/hcsd/excl/buldings/Follow up map.xlsx'

# sheet name -> (year, month). No 'April' sheet exists in the source file.
MONTH_SHEETS = {
    'Jan': (2026, 1), 'Feb': (2026, 2), 'March': (2026, 3), 'May': (2026, 5),
    'June': (2026, 6), 'July': (2026, 7), 'Aug': (2026, 8), 'SEP': (2026, 9),
}

# Aug/SEP use the current Infested Manholes/Outside/Bldg. columns; earlier
# sheets only have free-text Activities/Qyt pairs.
NEW_FORMAT_SHEETS = {'Aug', 'SEP'}


class Command(BaseCommand):
    help = 'One-time import of historical garden follow-up data from "Follow up map.xlsx"'

    def add_arguments(self, parser):
        parser.add_argument('--path', default=DEFAULT_PATH)
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        path = options['path']
        dry_run = options['dry_run']

        try:
            wb = openpyxl.load_workbook(path, data_only=True)
        except FileNotFoundError:
            raise CommandError(f'File not found: {path}')

        created = 0
        updated = 0
        rows_skipped = 0
        skipped_sheets = []

        for sheet_name, (year, month) in MONTH_SHEETS.items():
            if sheet_name not in wb.sheetnames:
                skipped_sheets.append(sheet_name)
                continue
            ws = wb[sheet_name]
            is_new_format = sheet_name in NEW_FORMAT_SHEETS

            for r in range(2, ws.max_row + 1):
                raw_date = ws.cell(row=r, column=2).value
                location = ws.cell(row=r, column=3).value

                if not location or not str(location).strip():
                    rows_skipped += 1
                    continue
                if isinstance(raw_date, str) and raw_date.strip().lower() == 'total':
                    # Spreadsheet subtotal row, not a real site visit.
                    rows_skipped += 1
                    continue

                area_name = str(location).strip()
                if isinstance(raw_date, datetime.datetime):
                    visit_date = raw_date.date()
                elif isinstance(raw_date, datetime.date):
                    visit_date = raw_date
                else:
                    visit_date = datetime.date(year, month, 1)

                def _coord(col):
                    v = ws.cell(row=r, column=col).value
                    try:
                        return float(v) if v is not None and str(v).strip() != '' else None
                    except (TypeError, ValueError):
                        return None

                lat = _coord(4)
                lng = _coord(5)

                defaults = {}

                if is_new_format:
                    def _int(col):
                        v = ws.cell(row=r, column=col).value
                        try:
                            return int(v) if v is not None and str(v).strip() != '' else None
                        except (TypeError, ValueError):
                            return None
                    defaults['infested_manholes']   = _int(6)
                    defaults['infested_outside']    = _int(7)
                    defaults['total_infested_bldg'] = _int(8)
                else:
                    parts = []
                    for c in range(6, ws.max_column + 1, 2):
                        act = ws.cell(row=r, column=c).value
                        qty = ws.cell(row=r, column=c + 1).value if c + 1 <= ws.max_column else None
                        if act and str(act).strip():
                            if qty not in (None, ''):
                                parts.append(f'{str(act).strip()}: {qty}')
                            else:
                                parts.append(str(act).strip())
                    defaults['notes'] = ' | '.join(parts)

                if dry_run:
                    continue

                obj, was_created = GardenVisit.objects.update_or_create(
                    visit_date=visit_date, area_name=area_name,
                    latitude=lat, longitude=lng,
                    defaults=defaults,
                )
                if was_created:
                    created += 1
                else:
                    updated += 1

        self.stdout.write(self.style.SUCCESS(
            f'Visits created: {created}, updated: {updated}. '
            f'Rows skipped: {rows_skipped}. Skipped sheets: {skipped_sheets or "none"}.'
        ))
