from django.db import migrations, models
from django.db.models import Q
import random


def backfill_card_numbers(apps, schema_editor):
    Enginer = apps.get_model('hcsd', 'Enginer')
    used = set(
        Enginer.objects.exclude(card_number__isnull=True)
        .exclude(card_number='')
        .values_list('card_number', flat=True)
    )

    for engineer in Enginer.objects.filter(Q(card_number__isnull=True) | Q(card_number='')):
        for _ in range(12000):
            candidate = f"{random.randint(0, 9999):04d}"
            if candidate not in used:
                engineer.card_number = candidate
                engineer.save(update_fields=['card_number'])
                used.add(candidate)
                break
        else:
            raise RuntimeError('Unable to generate unique 4-digit card numbers for existing engineers.')


class Migration(migrations.Migration):

    dependencies = [
        ('hcsd', '0038_company_engineers_m2m'),
    ]

    operations = [
        migrations.AddField(
            model_name='enginer',
            name='card_number',
            field=models.CharField(blank=True, editable=False, max_length=4, null=True, unique=True),
        ),
        migrations.RunPython(backfill_card_numbers, migrations.RunPython.noop),
    ]
