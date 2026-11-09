"""Register the facilities of the reports saved before facilities existed and
link each report to its facility: by license number, or by name when a report
has none. A facility takes the data of its latest report."""
from django.db import migrations


def _facility_key(report):
    license_number = report.license_number.strip()
    return ('license', license_number) if license_number else ('name', report.facility_name.strip())


def link_reports(apps, schema_editor):
    Facility = apps.get_model('hcsd', 'MedicalFacility')
    Report = apps.get_model('hcsd', 'MedicalWasteInspection')
    facilities = {}
    reports = Report.objects.filter(facility__isnull=True).order_by('-inspection_date', '-id')
    for report in reports:
        key = _facility_key(report)
        if key not in facilities:
            facilities[key] = Facility.objects.create(
                name=report.facility_name.strip(), license_number=report.license_number.strip(),
                address=report.address, phone=report.phone, created_by_id=report.created_by_id,
            )
        report.facility = facilities[key]
        report.save(update_fields=['facility'])


class Migration(migrations.Migration):

    dependencies = [
        ('hcsd', '0150_medical_facility'),
    ]

    operations = [
        migrations.RunPython(link_reports, migrations.RunPython.noop),
    ]
