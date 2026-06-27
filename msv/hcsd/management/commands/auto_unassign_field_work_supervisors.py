"""
Unassign field work supervisors from orders they did not finish on the same
day they were assigned. Intended to run once daily at midnight via cron.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from hcsd.models import FieldWorkOrder, FieldWorkOrderLog


class Command(BaseCommand):
    help = 'Unassign supervisors from field work orders not completed on their assignment day'

    def handle(self, *args, **options):
        today = timezone.localdate()
        stale_orders = FieldWorkOrder.objects.filter(
            status__in=['supervisor_assigned', 'order_received'],
            assigned_at__date__lt=today,
        )

        count = 0
        for order in stale_orders:
            old_sup = order.assigned_supervisor
            old_label = (old_sup.get_full_name() or old_sup.username) if old_sup else ''

            order.assigned_supervisor = None
            order.assigned_at = None
            order.received_by = None
            order.received_at = None
            order.status = 'new'
            order.save(update_fields=[
                'assigned_supervisor', 'assigned_at', 'received_by', 'received_at', 'status',
            ])
            FieldWorkOrderLog.objects.create(
                order=order, action='unassigned', actor=None,
                from_value=old_label,
                note='إلغاء تلقائي — لم تُنجز المهمة في نفس يوم التعيين',
            )
            count += 1

        self.stdout.write(self.style.SUCCESS(f'Unassigned {count} stale field work order(s).'))
