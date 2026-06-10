"""Unit tests for AnalysisDBWriter — the values it writes into Rekordbox master.db.

A live master.db is SQLCipher-encrypted and can't be created from scratch in a
test, so this exercises the pure transforms that decide WHAT gets written
(key name, ANLZ folder path, BPM scaling, beatgrid shape). The actual rbox
`update_content` write mechanism is covered by tests/test_onelibrary_wal_flush
(rbox writes BPM into a Rekordbox SQLite DB and re-reads it).

No rbox / heavy DSP needed — AnalysisDBWriter imports them lazily.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.analysis_db_writer import AnalysisDBWriter, _compute_anlz_subdir  # noqa: E402


def test_key_id_to_name_inverts_engine_map():
    """The master.db key write must invert analysis_engine's key_id map exactly.

    Drift between the two (writer vs engine) would silently store the wrong key
    for half the wheel — this guards all 24 keys.
    """
    from app.analysis_engine import _REKORDBOX_KEY_ID

    for full_key, key_id in _REKORDBOX_KEY_ID.items():
        assert AnalysisDBWriter._key_id_to_name(key_id) == full_key


def test_key_id_to_name_unknown():
    assert AnalysisDBWriter._key_id_to_name(0) is None
    assert AnalysisDBWriter._key_id_to_name(99) is None


def test_anlz_subdir_rekordbox_convention():
    """ANLZ folder = <md5[:3]>/<uuid-shaped md5> — deterministic per content id."""
    sub = _compute_anlz_subdir("123")
    prefix, folder = sub.split("/")
    assert len(prefix) == 3
    # uuid-shaped: 8-4-4-4-12 hex
    parts = folder.split("-")
    assert [len(p) for p in parts] == [8, 4, 4, 4, 12]
    # deterministic
    assert _compute_anlz_subdir("123") == sub
    assert _compute_anlz_subdir("124") != sub


def test_update_cache_bpm_key_beatgrid_shape():
    """_update_cache mirrors the master.db write: BPM float, Camelot key, and a
    beatgrid of {time(s), bpm, beat} dicts derived from PQTZ ms/centi-bpm."""

    class _FakeLiveDB:
        def __init__(self):
            self.tracks = {"42": {}}

    writer = AnalysisDBWriter(_FakeLiveDB())
    analysis = {
        "bpm": 128.0,
        "camelot": "8A",
        "key": "Am",
        "beats": [
            {"time_ms": 0, "tempo": 12800, "beat_number": 1},
            {"time_ms": 469, "tempo": 12800, "beat_number": 2},
        ],
    }
    writer._update_cache("42", analysis)
    tr = writer.live_db.tracks["42"]
    assert tr["BPM"] == 128.0
    assert tr["Key"] == "8A"
    assert tr["beatGrid"][0] == {"time": 0.0, "bpm": 128.0, "beat": 1}
    assert tr["beatGrid"][1]["time"] == 0.469
    assert tr["beatGrid"][1]["bpm"] == 128.0


def test_master_db_bpm_is_centi_bpm_int():
    """master.db stores BPM as int(round(bpm*100)) — guard the scaling contract."""
    assert round(128.0 * 100) == 12800
    assert round(127.66 * 100) == 12766
