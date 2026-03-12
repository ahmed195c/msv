from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('hcsd', '0053_wastedisposalrequest_classification_type_state'),
    ]

    operations = [
        migrations.AlterField(
            model_name='pirmetclearance',
            name='status',
            field=models.CharField(
                choices=[
                    ('order_received', 'Order Received'),
                    ('inspection_payment_pending', 'Inspection Payment Pending'),
                    ('review_pending', 'Pending Inspector Review'),
                    ('needs_completion', 'Needs Completion'),
                    ('approved', 'Inspector Approved'),
                    ('payment_pending', 'Waiting for Payment'),
                    ('payment_completed', 'Payment Completed'),
                    ('issued', 'Issued'),
                    ('inspection_pending', 'Inspection Pending'),
                    ('inspection_completed', 'Inspection Completed'),
                    ('head_approved', 'Head of Section Approved'),
                    ('closed_requirements_pending', 'Closed - Requirements Pending'),
                    ('cancelled_admin', 'Cancelled Administratively'),
                    ('disposal_approved', 'Disposal Approved'),
                    ('disposal_rejected', 'Disposal Rejected'),
                ],
                default='order_received',
                max_length=30,
            ),
        ),
    ]
