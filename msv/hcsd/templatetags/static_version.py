import os

from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static

register = template.Library()


@register.simple_tag
def static_v(path):
    """Like {% static %}, plus ?v=<file mtime> so a changed file gets a new
    URL — Cloudflare caches /static/ for hours and would otherwise keep
    serving the old copy after a deploy."""
    url = static(path)
    found = finders.find(path)
    if not found:
        return url
    return f'{url}?v={int(os.path.getmtime(found))}'
