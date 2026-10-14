# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['kestrel_disk_imager.py'],
    pathex=[],
    binaries=[],
    datas=[('assets/kestrel.ico', 'assets'), ('assets/ICON-LICENSE.txt', 'assets'),
           ('assets/github-mark.svg', 'assets'), ('assets/GITHUB-ICON-LICENSE.txt', 'assets')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='KestrelDiskImager',
    version='version_info.txt',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=True,
    icon=['assets/kestrel.ico'],
)
