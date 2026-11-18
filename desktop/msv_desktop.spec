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
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules

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

# webview picks a completely different backend submodule per OS at import
# time (winforms/edgechromium on Windows, gtk/qt/cocoa elsewhere), decided
# by runtime platform checks PyInstaller's static analysis can't follow —
# collect_all pulls in every submodule, data file and binary the package
# ships for whichever platform actually runs this build, not just what a
# plain import-graph walk of launcher.py would find.
webview_datas, webview_binaries, webview_hidden = collect_all('webview')
hidden_imports += webview_hidden

a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=webview_binaries,
    datas=webview_datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

# Linux: Qt's GTK3 theme plugin reads the desktop's GNOME settings through
# the bundled GLib and aborts the window when their schemas differ
# ("Settings schema ... does not contain a key named 'antialiasing'").
# Qt's own theme is used instead; this also keeps GTK out of the bundle.
#
# Also leave out the base system libraries every Linux desktop already has.
# Copies taken from the (older) build machine clash with the PC's newer GPU
# drivers: e.g. Intel's driver needs a newer libstdc++ than the bundled one,
# EGL fails to start, and the window aborts a second after opening.
if sys.platform.startswith('linux'):
    _GTK_PARTS = ('libqgtk3', 'libgtk-3', 'libgdk-3')
    _SYSTEM_LIBS = (
        'libstdc++.so', 'libgcc_s.so', 'libgbm.so', 'libdrm.so', 'libEGL.so', 'libGL.so',
        'libGLX.so', 'libGLdispatch.so', 'libOpenGL.so', 'libva.so', 'libva-',
        'libglib-2.0.so', 'libgio-2.0.so', 'libgobject-2.0.so', 'libgmodule-2.0.so',
        'libX11.so', 'libX11-xcb.so', 'libxcb-glx.so', 'libxcb-randr.so', 'libxcb-render.so',
        'libxcb-shm.so', 'libxcb-sync.so', 'libxcb-xfixes.so', 'libxcb-xkb.so',
        'libxkbcommon.so', 'libdbus-1.so', 'libfontconfig.so', 'libfreetype.so',
        'libharfbuzz.so', 'libffi.so', 'libz.so', 'libwayland-',
    )

    def _keep(entry):
        name = entry[0].rsplit('/', 1)[-1]
        if any(part in entry[0] for part in _GTK_PARTS):
            return False
        return not name.startswith(_SYSTEM_LIBS)

    a.binaries = [b for b in a.binaries if _keep(b)]

pyz = PYZ(a.pure)

# The normal double-click target: no console window.
exe_gui = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='msv-desktop',
    debug=False,
    console=False,
    icon='app.ico',
)

# Same build, console attached — for QA and on-site troubleshooting, since
# a console=False app that fails at startup is otherwise a silent black box.
exe_debug = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='msv-desktop-debug',
    debug=False,
    console=True,
    icon='app.ico',
)

coll = COLLECT(
    exe_gui, exe_debug,
    a.binaries, a.zipfiles, a.datas,
    strip=False,
    upx=False,
    name='app',
)
