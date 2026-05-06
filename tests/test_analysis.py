"""
Regression tests for the analysis pipeline.

Synthetic-track-based: deterministic, no external audio dependencies.
Run with: pytest tests/ -xvs
"""
from __future__ import annotations

import os
import struct
import sys
import tempfile
from pathlib import Path
from typing import Tuple

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _synth_track(
    bpm: float = 130.0,
    duration_s: float = 12.0,
    sr: int = 44100,
    stereo: bool = False,
) -> Tuple[np.ndarray, int]:
    """Generate a synthetic 4/4 track with kick/snare/hihat for tests."""
    n = int(sr * duration_s)
    y = np.zeros(n, dtype=np.float32)
    bp = 60.0 / bpm

    def kick(length: float = 0.12) -> np.ndarray:
        m = int(length * sr)
        env = np.exp(-np.linspace(0, 8, m))
        return (np.sin(2 * np.pi * 60 * np.arange(m) / sr) * env * 0.6).astype(np.float32)

    def snare(length: float = 0.08) -> np.ndarray:
        m = int(length * sr)
        env = np.exp(-np.linspace(0, 12, m))
        return (np.random.randn(m).astype(np.float32) * env * 0.3)

    i = 0
    t = 0.5
    while t < duration_s - 0.5:
        s = int(t * sr)
        if i % 4 in (0, 2):
            samp = kick()
            y[s:s + len(samp)] += samp[: max(0, n - s)]
        else:
            samp = snare()
            y[s:s + len(samp)] += samp[: max(0, n - s)]
        t += bp
        i += 1

    if stereo:
        # Slight L/R difference
        L = y * 0.95
        R = y * 1.05
        return np.stack([L, R]), sr
    return y, sr


def _write_wav(y: np.ndarray, sr: int, suffix: str = ".wav") -> str:
    import soundfile as sf
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    if y.ndim == 2 and y.shape[0] == 2:
        y = y.T  # soundfile expects (n, channels)
    sf.write(path, y, sr)
    return path


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch, tmp_path):
    """Each test gets its own cache dir."""
    from app import analysis_cache
    cache = analysis_cache.AnalysisCache(str(tmp_path / "cache"))
    monkeypatch.setattr(analysis_cache, "_default_cache", cache)
    yield


@pytest.fixture(autouse=True)
def reset_settings():
    """Restore default settings after each test (env vars may have been set)."""
    yield
    # Re-read env (monkeypatch already removed test-only env vars)
    from app import analysis_settings
    analysis_settings.reload_settings()


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def test_settings_defaults():
    from app.analysis_settings import get_settings
    s = get_settings()
    assert s.bpm_detect_min == 60.0
    assert s.bpm_output_max == 180.0
    assert s.color_gamma == 0.65
    assert s.cue_max_hot == 8


def test_settings_env_override(monkeypatch):
    monkeypatch.setenv("RB_ANALYSIS_BPM_OUTPUT_MAX", "175")
    from app.analysis_settings import reload_settings
    s = reload_settings()
    assert s.bpm_output_max == 175.0


# ---------------------------------------------------------------------------
# Format-aware encoder delay
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ext,expected", [
    ("foo.flac", 0.0),
    ("foo.wav", 0.0),
    ("foo.aiff", 0.0),
    ("foo.ogg", 0.0),
    ("foo.opus", 0.0),
    ("foo.mp3", 0.0225),
    ("foo.m4a", 0.0479),
    ("foo.aac", 0.0479),
])
def test_encoder_delay_per_format(ext, expected):
    from app.analysis_engine import get_encoder_delay
    assert get_encoder_delay(ext) == expected


# ---------------------------------------------------------------------------
# Octave correction
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("input_bpm,expected", [
    (30.0, 120.0),    # 30 → 60 → 120
    (60.0, 120.0),    # 60 → 120
    (65.0, 130.0),    # half-time of 130
    (80.0, 80.0),     # already in range
    (130.0, 130.0),
    (180.0, 180.0),
    (181.0, 90.5),    # just over output max
    (220.0, 110.0),   # double-time of 110
])
def test_octave_correct(input_bpm, expected):
    from app.analysis_engine import _octave_correct
    assert _octave_correct(input_bpm) == expected


# ---------------------------------------------------------------------------
# Stereo features
# ---------------------------------------------------------------------------

def test_stereo_features_mono():
    from app.analysis_engine import compute_stereo_features
    y_mono = np.random.randn(44100).astype(np.float32)
    assert compute_stereo_features(y_mono, 44100) is None


def test_stereo_features_identical():
    from app.analysis_engine import compute_stereo_features
    chan = np.random.randn(44100).astype(np.float32)
    y = np.stack([chan, chan])
    f = compute_stereo_features(y, 44100)
    assert f is not None
    assert f["width"] < 0.01
    assert f["is_mono"] is True
    assert f["phase_correlation"] == pytest.approx(1.0, abs=0.01)


def test_stereo_features_distinct():
    from app.analysis_engine import compute_stereo_features
    L = np.sin(2 * np.pi * 100 * np.arange(44100) / 44100).astype(np.float32)
    R = np.sin(2 * np.pi * 200 * np.arange(44100) / 44100).astype(np.float32)
    y = np.stack([L, R])
    f = compute_stereo_features(y, 44100)
    assert f["width"] > 0.5
    assert not f["is_mono"]


# ---------------------------------------------------------------------------
# Replay gain
# ---------------------------------------------------------------------------

def test_replay_gain_silent():
    from app.analysis_engine import calculate_replay_gain
    assert calculate_replay_gain(-100.0) == 0.0
    assert calculate_replay_gain(None) == 0.0


def test_replay_gain_loud():
    from app.analysis_engine import calculate_replay_gain
    # Track at -10 LUFS, target -18 → gain -8 dB
    assert calculate_replay_gain(-10.0) == -8.0


def test_replay_gain_quiet():
    from app.analysis_engine import calculate_replay_gain
    assert calculate_replay_gain(-26.0) == 8.0


# ---------------------------------------------------------------------------
# Hot cues
# ---------------------------------------------------------------------------

def test_hot_cues_max_8():
    from app.analysis_engine import generate_hot_cues
    phrases = [
        {"label": "Drop", "start_ms": i * 4000, "end_ms": (i + 1) * 4000,
         "energy": 0.9, "mood": "high", "id": 5}
        for i in range(20)
    ]
    beats = [{"beat_number": (j % 4) + 1, "tempo": 12800, "time_ms": j * 500}
             for j in range(200)]
    cues = generate_hot_cues(phrases, beats, 80.0)
    assert len(cues) <= 8
    assert cues[0]["name"] == "Start"


def test_hot_cues_color_assignment():
    from app.analysis_engine import generate_hot_cues
    phrases = [
        {"label": "Intro", "start_ms": 0, "end_ms": 8000, "energy": 0.2, "mood": "low", "id": 1},
        {"label": "Drop", "start_ms": 8000, "end_ms": 16000, "energy": 0.9, "mood": "high", "id": 5},
    ]
    beats = [{"beat_number": (j % 4) + 1, "tempo": 12800, "time_ms": j * 500} for j in range(40)]
    cues = generate_hot_cues(phrases, beats, 16.0)
    drop_cue = next((c for c in cues if c["name"] == "Drop"), None)
    assert drop_cue is not None
    assert drop_cue["color_id"] == 2  # red


# ---------------------------------------------------------------------------
# ANLZ binary structure
# ---------------------------------------------------------------------------

def test_pcpt_entry_size():
    from app.anlz_writer import _build_pcpt_entry
    cue = {"type": "hot_cue", "number": 0, "time_ms": 1000,
           "color_id": 1, "color_rgb": (0, 0, 0), "loop_len_ms": 0}
    entry = _build_pcpt_entry(cue)
    assert len(entry) == 56
    assert entry[:4] == b'PCPT'


def test_pssi_beat_anchoring():
    from app.anlz_writer import _build_pssi
    phrases = [
        {"label": "Intro", "start_ms": 0, "end_ms": 8000, "id": 1},
        {"label": "Drop", "start_ms": 8000, "end_ms": 16000, "id": 5},
    ]
    bpm = 120.0  # 8000ms = 16 beats
    pssi = _build_pssi(phrases, bpm, 16000)
    assert pssi[:4] == b'PSSI'
    # Decode 1st entry start_beat (offset 32 = end of header, then +2)
    start_beat = struct.unpack('>H', pssi[32 + 2: 32 + 4])[0]
    assert start_beat == 0
    # 2nd entry should have start_beat=16
    sb2 = struct.unpack('>H', pssi[32 + 24 + 2: 32 + 24 + 4])[0]
    assert sb2 == 16


def test_pqt2_compact_format():
    from app.anlz_writer import _build_pqt2
    beats = [{"beat_number": (i % 4) + 1, "tempo": 13000, "time_ms": i * 462} for i in range(140)]
    pqt2 = _build_pqt2(beats, 130.0)
    assert pqt2[:4] == b'PQT2'
    # Should be 56 header + 140 * 2 entries
    assert len(pqt2) == 56 + 140 * 2


# ---------------------------------------------------------------------------
# E2E with synthetic audio
# ---------------------------------------------------------------------------

def test_e2e_full_analysis_synth():
    from app.analysis_engine import run_full_analysis
    y, sr = _synth_track(bpm=130.0, duration_s=10.0)
    path = _write_wav(y, sr)
    try:
        result = run_full_analysis(path)
        assert result["status"] == "ok"
        assert 125 <= result["bpm"] <= 135
        assert result["pass"] == "full"
        assert result["channels"] == 1
        assert result["sample_rate_native"] == 44100
        assert "stereo" in result
        assert "mood" in result
        assert "genre_hint" in result
        assert "replay_gain" in result
        assert result["grid_confidence"] >= 0.0
        assert all("confidence" in b for b in result["beats"])
    finally:
        os.unlink(path)


def test_e2e_quick_analysis_faster():
    from app.analysis_engine import run_quick_analysis, run_full_analysis, _ensure_libs
    _ensure_libs()  # warm imports
    y, sr = _synth_track(bpm=130.0, duration_s=10.0)
    path = _write_wav(y, sr)
    try:
        import time
        t0 = time.time()
        full = run_full_analysis(path)
        t_full = time.time() - t0

        t0 = time.time()
        quick = run_quick_analysis(path)
        t_quick = time.time() - t0

        assert quick["pass"] == "quick"
        assert "waveform" not in quick
        assert "mood" not in quick
        assert t_quick < t_full   # quick must be faster than full
    finally:
        os.unlink(path)


def test_e2e_cache_hit():
    from app.analysis_engine import run_full_analysis
    y, sr = _synth_track(bpm=130.0, duration_s=8.0)
    path = _write_wav(y, sr)
    try:
        r1 = run_full_analysis(path)
        assert not r1["cache_hit"]
        r2 = run_full_analysis(path)
        assert r2["cache_hit"]
        assert r1["bpm"] == r2["bpm"]
    finally:
        os.unlink(path)


def test_e2e_anlz_write_roundtrip():
    from app.analysis_engine import run_full_analysis
    from app.anlz_writer import write_anlz_files
    y, sr = _synth_track(bpm=130.0, duration_s=8.0)
    path = _write_wav(y, sr)
    out_dir = tempfile.mkdtemp()
    try:
        result = run_full_analysis(path)
        paths = write_anlz_files(out_dir, path, result)
        assert "dat" in paths
        assert "ext" in paths
        assert os.path.getsize(paths["dat"]) > 0
        assert os.path.getsize(paths["ext"]) > 0

        with open(paths["dat"], "rb") as f:
            magic = f.read(4)
        assert magic == b"PMAI"
    finally:
        os.unlink(path)
        import shutil
        shutil.rmtree(out_dir)
