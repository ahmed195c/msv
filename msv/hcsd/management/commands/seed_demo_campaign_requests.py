from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone

from hcsd.models import CampaignActionLog, CampaignRequest


class Command(BaseCommand):
    help = 'Seed demo campaign follow-up (متابعة الحملة) requests for local testing/review.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset-demo',
            action='store_true',
            help='Delete existing demo campaign requests (company name starts with [DEMO]) before seeding.',
        )

    def handle(self, *args, **options):
        if options['reset_demo']:
            demo = CampaignRequest.objects.filter(company_name__startswith='[DEMO]')
            count = demo.count()
            demo.delete()
            self.stdout.write(self.style.WARNING(f'Deleted {count} existing demo campaign requests.'))

        creator, _ = User.objects.get_or_create(
            username='demo_data_entry',
            defaults={'first_name': 'DataEntry', 'last_name': 'Demo'},
        )

        CampaignRequest.objects.create(
            company_name='[DEMO] مصنع الأغذية الحديث',
            building_number='45',
            area='الصناعية 3',
            infestation_location='المستودع الخلفي',
            created_by=creator,
        )

        req2 = CampaignRequest.objects.create(
            company_name='[DEMO] مطعم الواحة',
            building_number='12',
            area='الروضة',
            infestation_location='المطبخ الرئيسي',
            note='تم رصد نشاط حشري واضح في منطقة التخزين، تم تحرير مخالفة للمنشأة.',
            action_type='violation',
            noted_by=creator,
            noted_at=timezone.now(),
            created_by=creator,
        )
        CampaignActionLog.objects.create(
            request=req2, action_type='violation', note=req2.note, created_by=creator,
        )

        req3 = CampaignRequest.objects.create(
            company_name='[DEMO] سوبر ماركت النخيل',
            building_number='7',
            area='الخان',
            infestation_location='منطقة الفواكه والخضار',
            note='تم توجيه المنشأة لاتخاذ إجراءات وقائية، سيتم المتابعة الشهر القادم.',
            action_type='followup',
            noted_by=creator,
            noted_at=timezone.now(),
            created_by=creator,
        )
        CampaignActionLog.objects.create(
            request=req3, action_type='followup', note=req3.note, created_by=creator,
        )

        self.stdout.write(self.style.SUCCESS('Created 3 demo campaign requests.'))
