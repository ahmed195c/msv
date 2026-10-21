# -*- mode: python ; coding: utf-8 -*-
"""Separate, minimal spec for apply_update.py — stdlib + tkinter only, no
Django/PIL/etc, so this stays a small single file that lives at the TOP
LEVEL of MSV-Desktop/ (sibling to app/), not inside app/ itself.
"""
a = Analysis(
    ['apply_update.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
    name='apply-update',
    debug=False,
    console=False,
    onefile=True,
)
