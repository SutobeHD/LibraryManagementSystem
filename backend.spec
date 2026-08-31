# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for RB_Backend (multi-platform)
#
# Build with:
#   pyinstaller --clean backend.spec
#
# Output: dist/RB_Backend (or dist/RB_Backend.exe on Windows)
# Triple-suffix renaming is handled by the GitHub Actions release workflow.

import importlib.util

from PyInstaller.utils.hooks import collect_all, collect_submodules
import sys

block_cipher = None


# madmom 0.16.1 imports `collections.MutableSequence` and uses `np.float` —
# both removed on Python 3.10+/NumPy 1.24+, so importing it raises without
# these shims. Mirror of app.analysis_engine._apply_madmom_compat_shims
# (additive + guarded).
#
# NB: this does NOT protect collect_all — that never raises for a missing or
# unimportable package, it returns ([], [], []). Presence is checked with
# find_spec below instead.
def _madmom_compat_shims():
    import collections
    import collections.abc

    for _n in ('MutableSequence', 'Iterable', 'MutableMapping', 'Mapping',
               'Sequence', 'Callable', 'Hashable', 'MutableSet'):
        if not hasattr(collections, _n):
            setattr(collections, _n, getattr(collections.abc, _n))
    try:
        import numpy as _np
        for _n, _t in (('float', float), ('int', int), ('bool', bool),
                       ('object', object), ('complex', complex)):
            if not hasattr(_np, _n):
                setattr(_np, _n, _t)
    except ImportError:
        pass


_madmom_compat_shims()

# --- Collect heavy scientific stack (audio analysis) ---
# These libs use lazy imports + native code — PyInstaller misses parts without collect_all.
# madmom ships its RNN/CNN model weights as package data — collect_all bundles them.
hiddenimports = []
datas = []
binaries = []

# REQUIRED: without any one of these the sidecar cannot analyse audio at all.
# They used to sit in the same try/except: pass as the optional packages, so a
# build on a machine missing librosa produced a silently broken binary.
REQUIRED_PKGS = ('librosa', 'numba', 'scipy', 'sklearn', 'soundfile', 'audioread',
                 'lazy_loader')

# OPTIONAL: the engine degrades to documented fallbacks without them —
# librosa beat tracking instead of madmom's RNN, Krumhansl-Schmuckler instead
# of essentia's KeyExtractor. essentia in particular ships as a native wheel
# that does not exist on Windows. Missing them is legal but must be LOUD: a
# build that quietly drops them yields an app whose analysis is worse than the
# developer thinks it is.
OPTIONAL_PKGS = ('madmom', 'essentia')

# collect_all() does NOT raise for a missing package — it logs
# "skipping data collection ... as it is not a package" and returns
# ([], [], []). Verified against a fabricated module name. The previous
# try/except around it therefore never caught anything: a build on a machine
# without madmom produced an empty collection and said nothing. Presence has
# to be tested explicitly.
def _installed(pkg):
    try:
        return importlib.util.find_spec(pkg) is not None
    except (ImportError, ValueError):
        return False


_absent_required = [p for p in REQUIRED_PKGS if not _installed(p)]
if _absent_required:
    raise SystemExit(
        'backend.spec: refusing to build a sidecar that cannot analyse audio.\n'
        'Missing required packages: ' + ', '.join(_absent_required) + '\n'
        'Install them first:  pip install -r requirements.txt'
    )

_missing_optional = [p for p in OPTIONAL_PKGS if not _installed(p)]

for pkg in REQUIRED_PKGS + tuple(p for p in OPTIONAL_PKGS if p not in _missing_optional):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

if _missing_optional:
    print('=' * 78)
    print('WARNING: building WITHOUT optional analysis packages:',
          ', '.join(_missing_optional))
    print('The sidecar will fall back to librosa beat tracking and')
    print('Krumhansl-Schmuckler key detection. Install them for full quality:')
    print('    pip install -r requirements.txt')
    print('=' * 78)

# madmom beat tracking is reached via attribute access
# (madmom.features.beats.RNNBeatProcessor / DBNBeatTrackingProcessor), which
# PyInstaller's static analysis misses. collect_submodules('madmom') is
# unreliable for this package, so list the needed submodules explicitly.
if 'madmom' not in _missing_optional:
    hiddenimports += [
        'madmom',
        'madmom.features',
        'madmom.features.beats',
        'madmom.audio',
        'madmom.audio.signal',
        'madmom.ml',
        'madmom.ml.nn',
        'madmom.processors',
        'madmom.models',
    ]

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
    ['backend_entry.py'],
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
