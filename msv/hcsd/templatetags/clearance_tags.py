from django import template

register = template.Library()


def _active_stripe(c):
    if c.active_waste_request:
        s = c.active_waste_request.status
        if s == 'payment_pending':   return 's-action'
        if s == 'inspection_pending': return 's-process'
        return 's-waiting'
    s = c.status
    if s == 'issued':                                   return 's-issued'
    if s in ('needs_completion', 'rejected',
             'violation_payment_link_pending',
             'violation_payment_pending', 'disposal_rejected'): return 's-error'
    if s in ('payment_pending', 'inspection_payment_pending'):  return 's-action'
    if s == 'head_approved':                            return 's-head'
    if s == 'disposal_approved':                        return 's-done'
    if s in ('inspection_pending', 'inspection_completed',
             'review_pending', 'approved'):             return 's-process'
    return 's-waiting'


def _active_status_class(c):
    return _active_stripe(c).replace('s-', 'st-')


def _active_label(c):
    if c.active_waste_request:
        s = c.active_waste_request.status
        if s == 'payment_pending':   return 'بانتظار دفع طلب الإتلاف'
        if s == 'inspection_pending':
            name = getattr(c, 'inspection_receiver_name', '')
            return f'تم استلام الطلب — {name}' if name else 'جاهز للاستلام'
        return c.active_waste_request.get_status_display()
    s = c.status
    labels = {
        'order_received':                 'بانتظار رابط دفع التفتيش',
        'inspection_payment_pending':     'بانتظار دفع التفتيش',
        'review_pending':                 'بانتظار المراجعة',
        'approved':                       'معتمد من المفتش',
        'needs_completion':               'غير معتمد',
        'rejected':                       'غير معتمد',
        'payment_pending':                'بانتظار دفع التصريح',
        'violation_payment_link_pending': 'بانتظار رابط دفع المخالفة',
        'violation_payment_pending':      'بانتظار دفع المخالفة',
        'issued':                         'تم إصدار التصريح',
        'inspection_pending':             'جاهز للاستلام',
        'head_approved':                  'تم الاعتماد النهائي',
        'closed_requirements_pending':    'اشتراطات واجبة الاستيفاء',
        'disposal_approved':              'إتلاف معتمد',
        'disposal_rejected':              'إتلاف مرفوض',
    }
    if s == 'inspection_completed':
        decision = getattr(c, 'inspection_report_decision', '')
        permit   = getattr(c, 'permit_type', '')
        if decision == 'approved':
            return 'بانتظار رابط دفع التصريح' if permit == 'pesticide_transport' else 'بانتظار الاعتماد النهائي'
        return 'تم التفتيش'
    return labels.get(s, c.get_status_display())


@register.simple_tag
def clearance_stripe_class(c):
    return _active_stripe(c)


@register.simple_tag
def clearance_status_class(c):
    return _active_status_class(c)


@register.simple_tag
def clearance_status_label(c):
    return _active_label(c)


@register.simple_tag
def finished_stripe_class(c):
    s = c.status
    if s == 'issued':        return 's-issued'
    if s in ('cancelled_admin', 'disposal_rejected'): return 's-error'
    if s == 'disposal_approved': return 's-done'
    return 's-waiting'


@register.simple_tag
def finished_status_class(c):
    return finished_stripe_class(c).replace('s-', 'st-')


@register.simple_tag
def finished_status_label(c):
    s = c.status
    labels = {
        'issued':          'تم إصدار التصريح',
        'cancelled_admin': 'مغلق',
        'disposal_approved': 'إتلاف معتمد',
        'disposal_rejected': 'إتلاف مرفوض',
    }
    return labels.get(s, c.get_status_display())
