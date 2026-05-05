# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for RB_Backend (multi-platform)
#
# Build with:
#   pyinstaller --clean backend.spec
#
# Output: dist/RB_Backend (or dist/RB_Backend.exe on Windows)
# Triple-suffix renaming is handled by the GitHub Actions release workflow.

from PyInstaller.utils.hooks import collect_all, collect_submodules
import sys

block_cipher = None

# --- Collect heavy scientific stack (audio analysis) ---
# These libs use lazy imports + native code — PyInstaller misses parts without collect_all.
hiddenimports = []
datas = []
binaries = []

for pkg in ('librosa', 'numba', 'scipy', 'sklearn', 'soundfile', 'audioread', 'lazy_loader'):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass  # Package may not be installed on all platforms

# --- Uvicorn protocol implementations (loaded dynamically) ---
hiddenimports += [
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
    'uvicorn.workers',
]

# --- Keyring backends (platform-specific) ---
hiddenimports += collect_submodules('keyring.backends')

# --- App-internal modules ---
hiddenimports += collect_submodules('app')


a = Analysis(
    ['app/main.py'],
    pathex=['.'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # Exclude dev/test deps to reduce binary size
        'tkinter',
        'matplotlib',
        'PyQt5',
        'PyQt6',
        'PySide2',
        'PySide6',
        'IPython',
        'jupyter',
        'pytest',
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
    name='RB_Backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,           # UPX compression disabled (causes false-positives in AV scanners)
    runtime_tmpdir=None,
    console=True,        # Backend logs to stdout — keep console attached
    icon=None,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
