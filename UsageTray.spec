# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for UsageTray (single-file, windowed)."""

block_cipher = None

a = Analysis(
    ["run_usagetray.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("usagetray/ui/panel.html", "usagetray/ui"),
    ],
    hiddenimports=[
        "pystray._win32",
        "webview.platforms.edgechromium",
        "clr_loader",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="UsageTray",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
