"""Tests for app/audio_analyzer.py — the pure _normalize_result mapping.

_normalize_result is the one pure function (no I/O, no librosa). It maps the
AnalysisEngine output to the legacy API shape; the rest of AudioAnalyzer drives
a ProcessPoolExecutor and isn't unit-tested here.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.audio_analyzer import AudioAnalyzer  # noqa: E402

_norm = AudioAnalyzer._normalize_result


def test_beats_to_beatgrid_seconds():
    out = _norm({"beats": [{"time_ms": 0}, {"time_ms": 500}, {"time_ms": 1000}]})
    assert out["beatgrid"] == [0.0, 0.5, 1.0]


def test_malformed_beats_are_skipped_not_fatal():
    """Regression: non-dict entries / dicts without time_ms must be skipped,
    not crash an otherwise-good analysis."""
    out = _norm({"beats": [{"time_ms": 250}, 1.5, {"no_time": 1}, None, {"time_ms": 750}]})
    assert out["beatgrid"] == [0.25, 0.75]


def test_empty_result_passthrough():
    assert _norm({}) == {}
    assert _norm(None) is None


def test_existing_beatgrid_not_overwritten():
    out = _norm({"beats": [{"time_ms": 0}], "beatgrid": [9.9]})
    assert out["beatgrid"] == [9.9]  # legacy field already present → left alone


def test_no_beats_key_adds_no_beatgrid():
    out = _norm({"bpm": 128.0})
    assert "beatgrid" not in out


def test_legacy_default_fields_added():
    out = _norm({"bpm": 120.0, "duration": 210.0})
    assert "mode" not in out  # the speed/accuracy knob is gone; depth lives in the engine result
    assert out["duration_analyzed"] == 210.0


def test_does_not_mutate_input():
    src = {"beats": [{"time_ms": 0}]}
    _norm(src)
    assert "beatgrid" not in src  # normalized is a copy


# ---------------------------------------------------------------------------
# depth plumbing (the engine + pool are stubbed; no DSP)
# ---------------------------------------------------------------------------


class _Engine:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def run_full_analysis(self, file_path, duration_cap_arg=None, **kw):
        self.calls.append((file_path, duration_cap_arg, kw))
        return {"bpm": 1.0, "beats": [], "depth": kw.get("depth")}


class _Pool:
    def submit(self, fn, *args, **kwargs):
        from concurrent.futures import Future

        fut: Future = Future()
        fut.set_result(fn(*args, **kwargs))
        return fut


def _stub(monkeypatch):
    import app.audio_analyzer as aa

    eng = _Engine()
    monkeypatch.setattr(aa, "_load_engine", lambda: eng)
    monkeypatch.setattr(AudioAnalyzer, "get_executor", classmethod(lambda cls: _Pool()))
    monkeypatch.setattr(AudioAnalyzer, "_tasks", {})
    return eng


def test_analyze_track_passes_depth_and_no_duration_cap(monkeypatch):
    eng = _stub(monkeypatch)
    AudioAnalyzer.analyze_track("t1", "x.mp3", "high")
    assert eng.calls == [("x.mp3", None, {"depth": "high"})]
    assert AudioAnalyzer.get_status("t1")["result"]["depth"] == "high"


def test_analyze_track_default_depth_is_rekordbox(monkeypatch):
    eng = _stub(monkeypatch)
    AudioAnalyzer.analyze_track("t2", "x.mp3")
    assert eng.calls == [("x.mp3", None, {"depth": "rekordbox"})]


def test_duration_cap_is_an_explicit_argument_only(monkeypatch):
    """B9: no 120 s cap hides behind a mode string any more."""
    eng = _stub(monkeypatch)
    AudioAnalyzer.analyze_sync("x.mp3", "rekordbox", duration_cap=30.0)
    assert eng.calls == [("x.mp3", 30.0, {"depth": "rekordbox"})]
