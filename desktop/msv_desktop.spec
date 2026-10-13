# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the portable desktop build.

Deliberately does NOT try to freeze msv/hcsd (our own Django project) into
the PyInstaller archive. Django resolves its own management commands and
template tag libraries by scanning the filesystem at runtime, which is
invisible to PyInstaller's static import analysis — fighting that with
collect_submodules() for every dynamic mechanism is fragile and only gets
more so as commands/tags are added. Instead, the CI build script
(.github/workflows/build-desktop.yml) copies msv/msv + msv/hcsd verbatim
into dist/app/django_src/ as plain, unfrozen source after this build, and
launcher.py puts that folder on sys.path before calling django.setup() —
Python's normal import machinery then finds everything exactly as it does
in development, with zero PyInstaller involvement.

What *does* need PyInstaller's help:
  - Django's own built-in apps (django.contrib.admin/auth/...) are loaded
    by `importlib.import_module` on the plain strings in INSTALLED_APPS,
    which static analysis also can't see on its own.
  - Third-party packages that only hcsd's own code imports (qrcode for
    permit QR codes, python-docx, pdfplumber, openpyxl for Excel
    import/export) are invisible to PyInstaller for the same reason hcsd
    itself is: launcher.py never imports them, hcsd does, and hcsd isn't
    part of this Analysis at all. Unlike hcsd, these ARE real installed
    packages that need to physically ship inside the frozen bundle, so
    they're listed explicitly below rather than solved by the sys.path
    trick.
"""
from PyInstaller.utils.hooks import collect_submodules

hidden_imports = []
for pkg in (
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.contenttypes',
    'django.template.loaders',
    'qrcode',
    'docx',
    'pdfplumber',
    'openpyxl',
    'PIL',
):
    hidden_imports += collect_submodules(pkg)
hidden_imports += ['django_extensions']

a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

# The normal double-click target: no console window.
exe_gui = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='msv-desktop',
    debug=False,
    console=False,
)

# Same build, console attached — for QA and on-site troubleshooting, since
# a console=False app that fails at startup is otherwise a silent black box.
exe_debug = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='msv-desktop-debug',
    debug=False,
    console=True,
)

coll = COLLECT(
    exe_gui, exe_debug,
    a.binaries, a.zipfiles, a.datas,
    strip=False,
    upx=False,
    name='app',
)
