"""Edge-case robustness for the analysis engine entry points.

A zero-byte / corrupt-decode file can hand the engine an empty array. Before
the guards, detect_beats/detect_key crashed in scipy sosfilt
("cannot reshape array of size 0"). These run in base Python (no madmom/
essentia) — the empty guard returns before any native call.
"""

from __future__ import annotations

import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import analysis_engine as ae  # noqa: E402


def test_detect_beats_empty_input_no_crash():
    out = ae.detect_beats(np.array([], dtype=np.float32), 44100)
    assert out["method"] == "empty-input"
    assert out["beats"] == []
    assert out["beat_count"] == 0
    assert out["bpm"] == 0.0


def test_detect_key_empty_input_no_crash():
    out = ae.detect_key(np.array([], dtype=np.float32), 44100)
    assert out["method"] == "empty-input"
    assert out["key"] == "Unknown"
    assert out["camelot"] == ""
    assert out["key_id"] == 0


def test_detect_beats_none_input_no_crash():
    out = ae.detect_beats(None, 44100)  # type: ignore[arg-type]
    assert out["beat_count"] == 0


def test_detect_key_none_input_no_crash():
    out = ae.detect_key(None, 44100)  # type: ignore[arg-type]
    assert out["key"] == "Unknown"


def test_empty_returns_have_consistent_shape():
    """The empty-input dicts must carry the same keys as a normal result so
    downstream consumers don't KeyError."""
    b = ae.detect_beats(np.array([], dtype=np.float32), 44100)
    assert {"bpm", "beats", "downbeat_index", "beat_count", "grid_confidence", "method"} <= set(b)
    k = ae.detect_key(np.array([], dtype=np.float32), 44100)
    assert {"key", "camelot", "openkey", "key_id", "confidence", "method"} <= set(k)
