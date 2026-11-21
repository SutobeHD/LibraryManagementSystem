"""Unit tests for the pure comparison helpers in scripts/compare_rekordbox.py.

The I/O shell (rbox / audio) is not exercised here — it needs a real
Rekordbox library and is meant to run locally.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import compare_rekordbox as cmp  # noqa: E402

# --- parse_camelot ---------------------------------------------------------


def test_parse_camelot_valid():
    assert cmp.parse_camelot("8A") == (8, "A")
    assert cmp.parse_camelot("12b") == (12, "B")
    assert cmp.parse_camelot(" 1A ") == (1, "A")


def test_parse_camelot_invalid():
    for bad in [None, "", "X", "13A", "0B", "8C", "A8"]:
        assert cmp.parse_camelot(bad) is None


# --- key_relation ----------------------------------------------------------


def test_key_relation_exact():
    assert cmp.key_relation("8A", "8A") == "exact"


def test_key_relation_relative():
    # same number, different letter = relative major/minor
    assert cmp.key_relation("8A", "8B") == "relative"


def test_key_relation_fifth():
    # +/-1 on the wheel, same letter = perfect 4th/5th
    assert cmp.key_relation("8A", "9A") == "fifth"
    assert cmp.key_relation("8A", "7A") == "fifth"
    # wheel wrap-around 12 <-> 1
    assert cmp.key_relation("12A", "1A") == "fifth"


def test_key_relation_clash():
    assert cmp.key_relation("8A", "2A") == "clash"
    assert cmp.key_relation("8A", "3B") == "clash"


def test_key_relation_unknown():
    assert cmp.key_relation("", "8A") == "unknown"
    assert cmp.key_relation("8A", None) == "unknown"


def test_compatible_relations_set():
    assert "exact" in cmp.COMPATIBLE_KEY_RELATIONS
    assert "relative" in cmp.COMPATIBLE_KEY_RELATIONS
    assert "fifth" in cmp.COMPATIBLE_KEY_RELATIONS
    assert "clash" not in cmp.COMPATIBLE_KEY_RELATIONS


# --- bpm_relation ----------------------------------------------------------


def test_bpm_relation_match():
    rel, err = cmp.bpm_relation(128.0, 128.0)
    assert rel == "match"
    assert err < 0.01


def test_bpm_relation_within_tolerance():
    rel, _ = cmp.bpm_relation(128.0, 128.5)  # ~0.4%
    assert rel == "match"


def test_bpm_relation_double():
    rel, err = cmp.bpm_relation(85.0, 170.0)
    assert rel == "double"
    assert err < 0.01


def test_bpm_relation_half():
    rel, _ = cmp.bpm_relation(170.0, 85.0)
    assert rel == "half"


def test_bpm_relation_other():
    rel, _ = cmp.bpm_relation(120.0, 145.0)
    assert rel == "other"


def test_bpm_relation_zero():
    assert cmp.bpm_relation(0.0, 120.0)[0] == "other"


# --- beatgrid_metrics ------------------------------------------------------


def test_beatgrid_metrics_aligned():
    beats = [0.0, 500.0, 1000.0, 1500.0, 2000.0]
    m = cmp.beatgrid_metrics(beats, beats)
    assert m["first_offset_ms"] == 0.0
    assert m["mean_abs_err_ms"] == 0.0
    assert m["matched"] == 5


def test_beatgrid_metrics_offset():
    rb = [0.0, 500.0, 1000.0, 1500.0]
    ours = [10.0, 510.0, 1010.0, 1510.0]  # +10 ms shift
    m = cmp.beatgrid_metrics(rb, ours)
    assert m["first_offset_ms"] == 10.0
    # only RB beats within [10, 1510] count; each is 10ms from nearest
    assert m["mean_abs_err_ms"] == 10.0


def test_beatgrid_metrics_empty():
    m = cmp.beatgrid_metrics([], [1.0, 2.0])
    assert m["matched"] == 0
    assert m["mean_abs_err_ms"] == -1.0


# --- Rekordbox key names (B15) ----------------------------------------------


def test_rb_key_name_camelot_passes_through():
    assert cmp.rb_key_name_to_camelot("11A") == "11A"
    assert cmp.rb_key_name_to_camelot("8b") == "8B"


def test_rb_key_name_musical_notation():
    assert cmp.rb_key_name_to_camelot("Am") == "8A"
    assert cmp.rb_key_name_to_camelot("C") == "8B"
    assert cmp.rb_key_name_to_camelot("F#m") == "11A"
    assert cmp.rb_key_name_to_camelot("Dbm") == "12A"
    assert cmp.rb_key_name_to_camelot("Eb") == "5B"


def test_rb_key_name_unknown_is_empty():
    assert cmp.rb_key_name_to_camelot(None) == ""
    assert cmp.rb_key_name_to_camelot("") == ""
    assert cmp.rb_key_name_to_camelot("m") == ""
    assert cmp.rb_key_name_to_camelot("H") == ""


def test_rb_key_names_maps_row_id_to_name():
    class Row:
        def __init__(self, rid, name):
            self.id, self.name = rid, name

    class Db:
        def get_keys(self):
            return [Row(241295350, "Am"), Row(7, "11A")]

    assert cmp._rb_key_names(Db()) == {"241295350": "Am", "7": "11A"}


def test_rb_beats_read_through_pyrekordbox(monkeypatch):
    import app.anlz_safe as anlz_safe

    monkeypatch.setattr(
        anlz_safe,
        "_pqtz_entries_from_dat",
        lambda path: [
            {"time": 0.5, "bpm": 128.0, "beat": 1},
            {"time": 0.96875, "bpm": 128.0, "beat": 2},
        ],
    )
    assert cmp._read_rb_beats_ms("x.DAT") == [500.0, 968.75]
