# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for CodeFuel (single-file, windowed)."""

block_cipher = None

a = Analysis(
    ["run_codefuel.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("codefuel/ui/panel.html", "codefuel/ui"),
    ],
    hiddenimports=[
        "pystray._win32",
        "webview.platforms.edgechromium",
        "clr_loader",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Heavy libs pulled in transitively (e.g. via Pillow/pywebview hooks)
        # that CodeFuel never uses — excluding them shrinks the EXE a lot.
        "numpy", "scipy", "pandas", "matplotlib",
        "torch", "torchvision", "torchgen", "cv2", "transformers",
        "sympy", "networkx", "lxml", "accelerate", "huggingface_hub",
        "docling", "docling_parse", "rapidocr", "faker", "tokenizers",
        # Unused pywebview GUI backends — we only use edgechromium (WebView2).
        "tkinter", "_tkinter", "PyQt5", "PyQt6", "PySide2", "PySide6",
        "IPython", "notebook",
    ],
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
    name="CodeFuel",
    icon="assets/icon.ico",
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
