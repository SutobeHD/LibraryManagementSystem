"""Tests for app/xml_generator.py — Rekordbox collection XML export.

Export integrity matters (a broken XML = Rekordbox refuses the whole import).
Covers: special-character escaping produces parseable XML, the produced tree
has the expected structure/values, and generate() does NOT mutate its input
(the DROP-cue append must not leak into the caller's positionMarks list).
"""

from __future__ import annotations

import os
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.xml_generator import RekordboxXML  # noqa: E402


def _gen(tracks):
    out = Path(tempfile.mkdtemp()) / "collection"
    path = RekordboxXML.generate(tracks, out)
    return path, ET.parse(path).getroot()  # parse → raises on malformed XML


def test_hostile_titles_produce_valid_xml():
    """Ampersands / angle brackets / quotes / unicode must not break the XML."""
    tracks = [
        {"Title": 'A & B <feat. C> "x"', "Artist": "DJ <&>", "path": "/m/a.wav"},
        {"Title": "Ümlaut … 🎧", "Artist": "Bär", "path": "/m/b.flac"},
    ]
    _, root = _gen(tracks)  # ET.parse would raise if escaping were wrong
    names = [t.get("Name") for t in root.iter("TRACK")]
    assert 'A & B <feat. C> "x"' in names  # round-trips through escaping
    assert "Ümlaut … 🎧" in names
    assert root.find("COLLECTION").get("Entries") == "2"


def test_beatgrid_and_cues_exported():
    tracks = [
        {
            "Title": "T",
            "path": "/m/t.wav",
            "BPM": "128.00",
            "beatGrid": [{"time": 0.0, "bpm": 128.0, "beat": 1}],
            "positionMarks": [{"Name": "Cue", "Type": "0", "Start": "1.5", "Num": "0"}],
        }
    ]
    _, root = _gen(tracks)
    track = root.find(".//TRACK")
    assert track.get("AverageBpm") == "128.00"
    assert track.find("TEMPO").get("Bpm") == "128.0"
    assert track.find("POSITION_MARK").get("Name") == "Cue"


def test_generate_does_not_mutate_input_positionmarks():
    """Regression: DROP append must copy, not mutate the caller's list."""
    marks: list[dict] = []
    data = {"Title": "T", "path": "/m/t.wav", "dropTime": 12.3, "positionMarks": marks}
    RekordboxXML.generate([data], Path(tempfile.mkdtemp()) / "c")
    RekordboxXML.generate([data], Path(tempfile.mkdtemp()) / "c2")  # second run
    assert marks == []  # caller's list untouched across both runs


def test_missing_path_does_not_crash():
    """A track dict without 'path' must not raise KeyError."""
    _, root = _gen([{"Title": "NoPath"}])
    assert root.find(".//TRACK").get("Name") == "NoPath"
