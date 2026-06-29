"""Tests for app/usb_mysettings.py — Pioneer MYSETTING file schema + I/O.

pyrekordbox is an optional dep. The pure label logic and the schema-integrity
invariants run anywhere; the I/O is exercised only on its graceful-degradation
path (forced via _PYRB_AVAILABLE) so the test is deterministic with or without
pyrekordbox installed.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import usb_mysettings as ms  # noqa: E402

# --- _humanize (pure) ------------------------------------------------------


def test_humanize_db_values():
    assert ms._humanize("minus_18db") == "-18 dB"
    assert ms._humanize("minus_24db") == "-24 dB"


def test_humanize_number_words():
    assert ms._humanize("one") == "1"
    assert ms._humanize("sixteen") == "16"
    assert ms._humanize("thirtytwo") == "32"
    assert ms._humanize("sixtyfour") == "64"


def test_humanize_fractions():
    assert ms._humanize("half") == "1/2"
    assert ms._humanize("quarter") == "1/4"
    assert ms._humanize("eighth") == "1/8"


def test_humanize_general_titlecase():
    assert ms._humanize("fast_cut") == "Fast Cut"
    assert ms._humanize("auto") == "Auto"
    assert ms._humanize("vinyl_speed_adjust") == "Vinyl Speed Adjust"


# --- schema integrity (the invariant that prevents runtime KeyError) -------


def test_schema_file_ids_match_get_schema_classes():
    """get_schema() indexes file_classes by SCHEMA key; an extra SCHEMA file_id
    without a class entry would KeyError at runtime. Lock the exact set."""
    assert set(ms.SCHEMA) == {"MYSETTING", "MYSETTING2", "DJMMYSETTING"}


def test_every_schema_file_id_resolves_in_maps():
    for file_id in ms.SCHEMA:
        assert ms._file_filename(file_id).endswith(".DAT")  # no KeyError
        ms._file_class(file_id)  # no KeyError


def test_every_field_has_required_keys_and_unique():
    required = {"key", "label", "enum", "group", "help"}
    for file_id, fields in ms.SCHEMA.items():
        keys = [f["key"] for f in fields]
        assert len(keys) == len(set(keys)), f"duplicate field key in {file_id}"
        for f in fields:
            assert required <= set(f), f"{file_id}.{f.get('key')} missing {required - set(f)}"


# --- graceful degradation when pyrekordbox absent --------------------------


def test_io_degrades_without_pyrekordbox(tmp_path, monkeypatch):
    monkeypatch.setattr(ms, "_PYRB_AVAILABLE", False)
    assert ms.get_schema()["available"] is False
    assert ms.read_settings(tmp_path) == {}
    assert ms.write_settings(tmp_path, {"MYSETTING": {"auto_cue": "off"}}) == {}
    assert ms.write_defaults(tmp_path) == {}


def test_enum_options_empty_without_pyrekordbox(monkeypatch):
    monkeypatch.setattr(ms, "_PYRB_AVAILABLE", False)
    assert ms._enum_options("AutoCue") == []
