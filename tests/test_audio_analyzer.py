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
    assert out["mode"] == "accuracy"
    assert out["duration_analyzed"] == 210.0


def test_does_not_mutate_input():
    src = {"beats": [{"time_ms": 0}]}
    _norm(src)
    assert "beatgrid" not in src  # normalized is a copy
