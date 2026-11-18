"""Desktop build: the activity permit media folder is now "تجديد تصريح النشاط".
Move the files already saved under the old "تصريح النشاط" folder and update
their stored paths. The server keeps flat paths, so there nothing changes."""
import logging
import shutil
from pathlib import Path

from django.conf import settings
from django.db import migrations

logger = logging.getLogger(__name__)

OLD = 'تصريح النشاط'
NEW = 'تجديد تصريح النشاط'
PERMIT_FILE_FIELDS = (
    'payment_receipt', 'inspection_payment_receipt', 'violation_payment_receipt',
    'insurance_payment_receipt', 'request_documents_bundle',
)


def _move_folder(old, new):
    media = Path(settings.MEDIA_ROOT)
    src, dst = media / old, media / new
    if not src.is_dir():
        return
    for path in sorted(src.rglob('*')):
        if not path.is_file():
            continue
        target = dst / path.relative_to(src)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.move(str(path), str(target))
    if any(p.is_file() for p in src.rglob('*')):
        logger.warning('Some files stayed in %s: a file with the same name was already in %s', src, dst)
        return
    try:
        shutil.rmtree(src)
    except OSError:
        logger.warning('Could not remove the old folder %s', src)


def _update_paths(apps, old, new):
    prefix = old + '/'
    PirmetClearance = apps.get_model('hcsd', 'PirmetClearance')
    PirmetDocument = apps.get_model('hcsd', 'PirmetDocument')
    for field in PERMIT_FILE_FIELDS:
        for permit in PirmetClearance.objects.filter(**{f'{field}__startswith': prefix}).only('pk', field):
            name = getattr(permit, field).name
            PirmetClearance.objects.filter(pk=permit.pk).update(**{field: new + name[len(old):]})
    for doc in PirmetDocument.objects.filter(file__startswith=prefix).only('pk', 'file'):
        PirmetDocument.objects.filter(pk=doc.pk).update(file=new + doc.file.name[len(old):])


def _rename(old, new):
    def run(apps, schema_editor):
        if not getattr(settings, 'DESKTOP_MODE', False):
            return
        _move_folder(old, new)
        _update_paths(apps, old, new)
    return run


class Migration(migrations.Migration):

    dependencies = [
        ('hcsd', '0158_company_activity_default_text'),
    ]

    operations = [
        migrations.RunPython(_rename(OLD, NEW), _rename(NEW, OLD)),
    ]
