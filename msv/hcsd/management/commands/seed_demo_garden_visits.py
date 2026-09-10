import datetime
import random

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from hcsd.models import GardenVisit

AREAS = [
    'منطقة الجزيرة', 'منطقة الفيصل', 'منطقة النسيم', 'منطقة الخان',
    'منطقة الطلاع', 'منطقة الوحدة', 'منطقة الرولة', 'منطقة الروضة',
    'منطقة المجاز', 'منطقة أبو شغارة',
]

NOTES = [
    'تم رصد نشاط قوارض بسيط بالقرب من المناهيل.',
    'لا توجد إصابة ظاهرة خلال الزيارة.',
    'تم وضع طعوم وقائية في نقاط الإصابة السابقة.',
    '',
]


class Command(BaseCommand):
    help = 'Seed demo area follow-up (متابعة المناطق) visits for local testing.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset-demo',
            action='store_true',
            help='Delete existing demo garden visits (notes tagged [DEMO]) before seeding.',
        )
        parser.add_argument('--count', type=int, default=30)

    def handle(self, *args, **options):
        if options['reset_demo']:
            demo_visits = GardenVisit.objects.filter(notes__contains='[DEMO]')
            count = demo_visits.count()
            demo_visits.delete()
            self.stdout.write(self.style.WARNING(f'Deleted {count} existing demo garden visits.'))

        creator, _ = User.objects.get_or_create(
            username='demo_data_entry',
            defaults={'first_name': 'DataEntry', 'last_name': 'Demo'},
        )

        today = datetime.date.today()
        created = 0
        for i in range(options['count']):
            visit_date = today - datetime.timedelta(days=random.randint(0, 180))
            area_name = random.choice(AREAS)
            note = random.choice(NOTES)
            tagged_note = f'[DEMO] {note}'.strip() if note else '[DEMO]'

            GardenVisit.objects.create(
                visit_date=visit_date,
                area_name=area_name,
                latitude=25.30 + random.uniform(-0.05, 0.05),
                longitude=55.40 + random.uniform(-0.05, 0.05),
                infested_manholes=random.randint(0, 5),
                infested_outside=random.randint(0, 3),
                total_infested_bldg=random.randint(0, 8),
                notes=tagged_note,
                created_by=creator,
            )
            created += 1

        self.stdout.write(self.style.SUCCESS(f'Created {created} demo garden visits.'))
