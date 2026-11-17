"""Booting the sidecar (``import app.main``) must not import librosa / numpy.

``app/audio_analyzer.py`` used to ``import librosa`` + ``numpy`` at module
level and import ``analysis_engine`` (numpy at module level) eagerly; app.main
imports audio_analyzer -> ~1 s of numpy/scipy/numba cold start per sidecar
boot. Checked in a fresh interpreter because this suite imports numpy anyway.

The child imports app.main, which writes a session-token file: it inherits
conftest's sandboxed APPDATA/LOCALAPPDATA/HOME and gets the same platformdirs
env-var resolver, and refuses to import if the sandbox is not in effect.
Its stdout carries the LMS_TOKEN banner; only the marker line is parsed and
stdout is never echoed into assertion messages.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

from tests.conftest import TEST_SANDBOX_ROOT

ROOT = Path(__file__).resolve().parent.parent

_CHILD = r"""
import functools, json, sys
from pathlib import Path
if sys.platform == "win32":
    import platformdirs.windows as _w
    _w.get_win_folder = functools.lru_cache(maxsize=None)(_w.get_win_folder_from_env_vars)
from platformdirs import user_data_dir
sandbox = Path(sys.argv[1]).resolve()
data_dir = Path(user_data_dir("MusicLibraryManager", appauthor=False, roaming=False)).resolve()
if not data_dir.is_relative_to(sandbox):
    print("@@RESULT@@" + json.dumps({"error": "sandbox not applied"}))
    sys.exit(0)
import app.main
from app import audio_analyzer
print("@@RESULT@@" + json.dumps({
    "librosa": "librosa" in sys.modules,
    "numpy": "numpy" in sys.modules,
    "scipy": "scipy" in sys.modules,
    "engine": "app.analysis_engine" in sys.modules,
    "available": audio_analyzer.LIBROSA_AVAILABLE,
    "main_flag": app.main.LIBROSA_AVAILABLE,
}))
"""


def _run_child() -> dict[str, object]:
    proc = subprocess.run(
        [sys.executable, "-c", _CHILD, str(TEST_SANDBOX_ROOT)],
        cwd=str(ROOT),
        env=dict(os.environ),
        capture_output=True,
        text=True,
        timeout=120,
    )
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("@@RESULT@@")]
    failure = f"child failed rc={proc.returncode}: {proc.stderr[-2000:]}"
    assert proc.returncode == 0 and lines, failure
    return json.loads(lines[-1][len("@@RESULT@@") :])


def test_import_app_main_does_not_load_librosa_or_numpy() -> None:
    result = _run_child()
    assert "error" not in result, result
    assert result["librosa"] is False
    assert result["numpy"] is False
    assert result["scipy"] is False
    assert result["engine"] is False

    expected = (
        importlib.util.find_spec("librosa") is not None
        and importlib.util.find_spec("numpy") is not None
    )
    assert result["available"] is expected
    assert result["main_flag"] is expected


def test_flag_is_a_plain_bool_and_engine_loads_on_demand() -> None:
    from app import audio_analyzer

    assert isinstance(audio_analyzer.LIBROSA_AVAILABLE, bool)
    engine = audio_analyzer._load_engine()
    if engine is not None:
        assert engine.__name__ == "app.analysis_engine"
        assert "app.analysis_engine" in sys.modules
        caps = audio_analyzer.AudioAnalyzer.capabilities()
        assert isinstance(caps, dict)
    assert audio_analyzer._load_engine() is engine
