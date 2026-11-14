import base64
import io

import qrcode
from django import template
from django.conf import settings

register = template.Library()


@register.simple_tag
def permit_qr_png_b64(url_path):
    """Render a QR code as a base64 PNG data URI for the given URL path."""
    if not url_path:
        return ''
    full_url = settings.SITE_URL.rstrip('/') + url_path
    img = qrcode.make(full_url, box_size=6, border=2)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f'data:image/png;base64,{b64}'
