# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for all_in_one web app — one-click exe for customers."""

from pathlib import Path

block_cipher = None

_PROJ = Path(SPECPATH)

# Data trees to bundle (source dir → bundle dir)
datas = [
    (str(_PROJ / 'src'), 'src'),
    (str(_PROJ / 'web' / 'templates'), 'web/templates'),
    (str(_PROJ / 'data'), 'data'),
]

a = Analysis(
    [str(_PROJ / 'web' / 'app.py')],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[
        'tkinter',
        'tkinter.ttk',
        'tkinter.filedialog',
        'flask',
        'threading',
        'logging',
        'webbrowser',
        'ipaddress',
        'pathlib',
        'json',
        're',
        'importlib.util',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'pandas',
        'numpy',
        'scipy',
        'PIL',
        'cv2',
        'test',
        'unittest',
        'pytest',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='all_in_one',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
