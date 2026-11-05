import base64
import datetime
import io
import shutil
import tempfile
from unittest import mock

from django.contrib.auth.models import Group, User
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .medical_waste_pdf import pdf_filename
from .models import MedicalWasteInspection as Report


def _contract_data(**overrides):
    data = {
        'inspector_name': 'مفتش', 'inspection_date': '2026-11-05', 'facility_name': 'عيادة الاختبار',
        'license_number': '123', 'address': 'الشارقة', 'phone': '065000000',
        'inspection_type': Report.TYPE_CONTRACT, 'visit_type': Report.VISIT_PERIODIC,
        'point_1': 'yes', 'point_2': 'no', 'point_3': 'yes', 'point_4': 'no',
        'contract_action': Report.ACTION_NOTICE, 'notice_days': '7', 'submit_action': 'save',
    }
    data.update(overrides)
    return data


class MedicalWasteBase(TestCase):
    def setUp(self):
        media = tempfile.mkdtemp(prefix='msv_mw_test_')
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=media)
        override.enable()
        self.addCleanup(override.disable)
        self.admin = User.objects.create_superuser('mw_admin', password='x')
        self.client.force_login(self.admin)
        # No browser here: the real rendering needs Chrome/Edge on the machine.
        patcher = mock.patch('hcsd.medical_waste_pdf._render_pdf_bytes', return_value=b'%PDF-test')
        self.render_pdf = patcher.start()
        self.addCleanup(patcher.stop)
        browser = mock.patch('hcsd.medical_waste_pdf._find_browser', return_value='browser')
        browser.start()
        self.addCleanup(browser.stop)

    def _report(self, **overrides):
        fields = {
            'inspector_name': 'مفتش', 'inspection_date': datetime.date(2026, 11, 5),
            'facility_name': 'عيادة', 'inspection_type': Report.TYPE_NO_WASTE,
        }
        fields.update(overrides)
        return Report.objects.create(**fields)


class MedicalWasteFormTests(MedicalWasteBase):
    def test_contract_report_is_saved_with_pdf(self):
        response = self.client.post(reverse('medical_waste_create'), _contract_data())
        report = Report.objects.get()
        self.assertRedirects(response, reverse('medical_waste_detail', args=[report.pk]))
        self.assertEqual(report.created_by, self.admin)
        self.assertEqual(
            (report.point_1, report.point_2, report.point_3, report.point_4),
            (True, False, True, False),
        )
        self.assertEqual(report.notice_days, 7)
        self.assertTrue(report.pdf_file.storage.exists(report.pdf_file.name))
        self.assertIn('medical_waste/reports/', report.pdf_file.name)

    def test_save_and_print_goes_to_autoprint(self):
        response = self.client.post(reverse('medical_waste_create'), _contract_data(submit_action='save_print'))
        report = Report.objects.get()
        self.assertEqual(response.url, f"{reverse('medical_waste_print', args=[report.pk])}?autoprint=1")
        self.assertContains(self.client.get(response.url), 'window.print()')

    def test_contract_type_requires_its_fields(self):
        data = _contract_data(visit_type='', point_3='', contract_action='notice', notice_days='')
        response = self.client.post(reverse('medical_waste_create'), data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Report.objects.exists())
        for field in ('visit_type', 'point_3', 'notice_days'):
            self.assertIn(field, response.context['form'].errors)

    def test_expired_waste_requires_a_waste_type(self):
        response = self.client.post(reverse('medical_waste_create'), {
            'inspector_name': 'مفتش', 'inspection_date': '2026-11-05', 'facility_name': 'صيدلية',
            'inspection_type': Report.TYPE_EXPIRED,
        })
        self.assertIn('waste_medicines', response.context['form'].errors)
        self.assertFalse(Report.objects.exists())

    def test_changing_type_drops_the_other_types_answers(self):
        report = self._report(
            inspection_type=Report.TYPE_CONTRACT, visit_type=Report.VISIT_PERIODIC, point_1=True,
            contract_action=Report.ACTION_COMPLIANT,
        )
        self.client.post(reverse('medical_waste_edit', args=[report.pk]), _contract_data(
            inspection_type=Report.TYPE_EXPIRED, waste_cosmetics='on', estimated_weight='5 كجم',
            letter_action='on', notice_days='abc',
        ))
        report.refresh_from_db()
        self.assertEqual(report.inspection_type, Report.TYPE_EXPIRED)
        self.assertTrue(report.waste_cosmetics)
        self.assertEqual((report.visit_type, report.point_1, report.notice_days), ('', None, None))

    def test_only_writers_can_fill_the_form(self):
        viewer = User.objects.create_user('mw_viewer', password='x')
        self.client.force_login(viewer)
        self.assertEqual(self.client.post(reverse('medical_waste_create'), _contract_data()).status_code, 403)
        self.assertFalse(Report.objects.exists())

    def test_anonymous_is_sent_to_login(self):
        self.client.logout()
        for name, args in (('medical_waste_home', []), ('medical_waste_create', [])):
            self.assertIn('/login/', self.client.get(reverse(name, args=args)).url)

    def test_pdf_failure_keeps_the_report_and_says_so(self):
        self.render_pdf.side_effect = OSError('boom')
        response = self.client.post(reverse('medical_waste_create'), _contract_data(), follow=True)
        self.assertEqual(Report.objects.get().pdf_file.name, '')
        self.assertContains(response, 'تعذّر إنشاء نسخة PDF')

    def test_facility_text_is_escaped_in_print(self):
        report = self._report(facility_name='<script>alert(1)</script>')
        response = self.client.get(reverse('medical_waste_print', args=[report.pk]))
        self.assertNotContains(response, '<script>alert(1)')


def _signature_data_url(fmt='PNG', size=(120, 40)):
    buffer = io.BytesIO()
    Image.new('RGBA' if fmt == 'PNG' else 'RGB', size, (11, 42, 107)).save(buffer, format=fmt)
    return 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode()


class MedicalWasteSignatureTests(MedicalWasteBase):
    def _create(self, **fields):
        self.client.post(reverse('medical_waste_create'), _contract_data(**fields))
        return Report.objects.get()

    def test_drawn_signature_is_saved_as_an_image(self):
        report = self._create(inspector_signature_data=_signature_data_url())
        self.assertTrue(report.inspector_signature.name.endswith('.png'))
        self.assertEqual(Image.open(report.inspector_signature.path).format, 'PNG')
        self.assertFalse(report.representative_signature)

    def test_bad_signatures_are_rejected(self):
        bad_values = (
            'data:image/png;base64,not-base64!',
            'data:image/svg+xml;base64,' + base64.b64encode(b'<svg onload="x()"/>').decode(),
            'data:image/png;base64,' + base64.b64encode(b'not an image').decode(),
            _signature_data_url('JPEG'),
            _signature_data_url(size=(2000, 40)),
        )
        for value in bad_values:
            response = self.client.post(
                reverse('medical_waste_create'), _contract_data(inspector_signature_data=value),
            )
            self.assertIn('inspector_signature_data', response.context['form'].errors, value[:40])
        self.assertFalse(Report.objects.exists())

    def test_edit_keeps_replaces_and_clears_the_signature(self):
        report = self._create(inspector_signature_data=_signature_data_url())
        first, storage = report.inspector_signature.name, report.inspector_signature.storage
        url = reverse('medical_waste_edit', args=[report.pk])

        self.client.post(url, _contract_data())
        report.refresh_from_db()
        self.assertEqual(report.inspector_signature.name, first)

        self.client.post(url, _contract_data(inspector_signature_data=_signature_data_url(size=(90, 30))))
        report.refresh_from_db()
        second = report.inspector_signature.name
        self.assertNotEqual(second, first)
        self.assertFalse(storage.exists(first))

        self.client.post(url, _contract_data(inspector_signature_clear='1'))
        report.refresh_from_db()
        self.assertFalse(report.inspector_signature)
        self.assertFalse(storage.exists(second))


class MedicalWasteArchiveTests(MedicalWasteBase):
    def test_filters(self):
        wanted = self._report(facility_name='مستشفى النور', inspector_name='سالم', license_number='CN-5521')
        self._report(facility_name='عيادة', inspector_name='خالد', inspection_date=datetime.date(2026, 1, 1))
        for params in ({'facility': 'النور'}, {'license': '5521'}, {'date_from': '2026-06-01'}):
            page = self.client.get(reverse('medical_waste_home'), params).context['page']
            self.assertEqual(list(page.object_list), [wanted], params)

    def test_delete_is_admin_only_post_and_removes_files(self):
        report = self._report()
        report.pdf_file.save('r.pdf', ContentFile(b'x'))
        name, storage = report.pdf_file.name, report.pdf_file.storage
        url = reverse('medical_waste_delete', args=[report.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.force_login(User.objects.create_user('mw_viewer', password='x'))
        self.assertEqual(self.client.post(url).status_code, 403)
        self.assertTrue(Report.objects.filter(pk=report.pk).exists())
        self.client.force_login(self.admin)
        self.client.post(url)
        self.assertFalse(Report.objects.filter(pk=report.pk).exists())
        self.assertFalse(storage.exists(name))

    def test_pdf_filename_has_date_facility_and_number(self):
        report = self._report(facility_name='a/b:c')
        self.assertEqual(pdf_filename(report), f'2026-11-05 - abc - تقرير {report.pk}.pdf')


class MedicalWasteReadAccessTests(TestCase):
    def test_any_logged_in_user_can_read_the_archive(self):
        reader = User.objects.create_user('mw_reader', password='x')
        reader.groups.add(Group.objects.create(name='unrelated'))
        self.client.force_login(reader)
        self.assertEqual(self.client.get(reverse('medical_waste_home')).status_code, 200)
