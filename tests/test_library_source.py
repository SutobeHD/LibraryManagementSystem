"""Tests for app/library_source.py — the Live/XML normalization layer.

The two _normalize static methods are pure and run for every track during
USB sync. Locks: numeric coercion never crashes on garbage tags, and the
Live duration heuristic doesn't 1000x a duration_ms-only track.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.library_source import (  # noqa: E402
    LiveLibrarySource,
    XmlLibrarySource,
    _to_float,
    _to_int,
)

# --- coercion helpers ------------------------------------------------------


def test_to_float_tolerates_garbage():
    assert _to_float("128.0") == 128.0
    assert _to_float(None) == 0.0
    assert _to_float("") == 0.0
    assert _to_float("n/a") == 0.0  # non-numeric → default, never raises
    assert _to_float("x", default=1.0) == 1.0


def test_to_int_tolerates_garbage():
    assert _to_int("5") == 5
    assert _to_int("5.9") == 5  # truncates via float
    assert _to_int(None) == 0
    assert _to_int("bad") == 0


# --- XML _normalize --------------------------------------------------------


def test_xml_normalize_basic_and_duration_seconds():
    out = XmlLibrarySource._normalize(
        "7", {"Title": "T", "Artist": "A", "BPM": "124.0", "TotalTime": "200", "Rating": "4"}
    )
    assert out["id"] == "7"
    assert out["bpm"] == 124.0
    assert out["duration_ms"] == 200_000  # TotalTime seconds → ms
    assert out["rating"] == 4


def test_xml_normalize_does_not_crash_on_garbage():
    """Regression: a non-numeric BPM/Rating must not raise (aborts the sync)."""
    out = XmlLibrarySource._normalize("1", {"BPM": "n/a", "Rating": "", "Bitrate": "??"})
    assert out["bpm"] == 0.0
    assert out["rating"] == 0
    assert out["bitrate"] == 0


# --- Live _normalize -------------------------------------------------------


def test_live_normalize_duration_from_total_time_seconds():
    out = LiveLibrarySource._normalize("1", {"TotalTime": 240})  # seconds
    assert out["duration_ms"] == 240_000


def test_live_normalize_duration_ms_only_not_multiplied():
    """Regression: a duration_ms-only track must NOT be x1000 (was 240_000_000)."""
    out = LiveLibrarySource._normalize("1", {"duration_ms": 240000})
    assert out["duration_ms"] == 240000


def test_live_normalize_lowercase_and_fallback_keys():
    out = LiveLibrarySource._normalize(
        "9", {"title": "lt", "bpm": "126", "folder_path": "/m/x.wav", "BitRate": "320"}
    )
    assert out["title"] == "lt"
    assert out["bpm"] == 126.0
    assert out["path"] == "/m/x.wav"
    assert out["bitrate"] == 320


def test_live_normalize_garbage_does_not_crash():
    out = LiveLibrarySource._normalize("1", {"BPM": "n/a", "TotalTime": "oops"})
    assert out["bpm"] == 0.0
    assert out["duration_ms"] == 0
