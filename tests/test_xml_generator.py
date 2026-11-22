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


# --- B14: attributes Rekordbox reads ----------------------------------------------


def _track(**kw):
    _, root = _gen([kw])
    return root.find(".//TRACK")


def test_kind_follows_the_real_file_extension():
    kinds = {
        "/m/a.mp3": "MP3 File",
        "/m/a.WAV": "WAV File",
        "/m/a.aiff": "AIFF File",
        "/m/a.aif": "AIFF File",
        "/m/a.flac": "FLAC File",
        "/m/a.m4a": "M4A File",
    }
    for path, kind in kinds.items():
        assert _track(Title="T", path=path).get("Kind") == kind, path
    assert _track(Title="T").get("Kind") is None  # no file, no invented "WAV File"


def test_location_is_percent_encoded_and_round_trips():
    from urllib.parse import unquote

    path = "C:/Music/Ä & B #1 (Remix).mp3"
    loc = _track(Title="T", path=path).get("Location")
    assert loc == "file://localhost/C:/Music/%C3%84%20%26%20B%20%231%20%28Remix%29.mp3"
    assert unquote(loc) == f"file://localhost/{path}"
    assert _track(Title="T", path=r"C:\Music\a b.wav").get("Location") == (
        "file://localhost/C:/Music/a%20b.wav"
    )
    assert _track(Title="T", path="/Users/x/a b.mp3").get("Location") == (
        "file://localhost/Users/x/a%20b.mp3"
    )


def test_date_added_comes_from_stock_date():
    from datetime import datetime

    assert _track(Title="T", StockDate="2021-03-04").get("DateAdded") == "2021-03-04"
    assert _track(Title="T", StockDate="2021-03-04 10:11:12").get("DateAdded") == "2021-03-04"
    today = datetime.now().strftime("%Y-%m-%d")
    for missing in (None, "", "None", "2021-13-40"):
        assert _track(Title="T", StockDate=missing).get("DateAdded") == today, missing


def test_tonality_rating_comments_bitrate_exported_when_present():
    t = _track(Title="T", path="/m/a.mp3", Key="8A", Rating=4, Comment="nice", Bitrate=320)
    assert (t.get("Tonality"), t.get("Rating"), t.get("Comments"), t.get("BitRate")) == (
        "8A",
        "204",
        "nice",
        "320",
    )
    bare = _track(Title="T", path="/m/a.mp3")
    for attr in ("Tonality", "Rating", "Comments", "BitRate"):
        assert bare.get(attr) is None, attr


def test_rating_scale():
    # live/UI stars 0-5 -> Rekordbox raw; raw XML values pass through; nonsense is dropped
    for given, raw in ((0, "0"), (3, "153"), (5, "255"), (102, "102"), (255, "255")):
        assert _track(Title="T", Rating=given).get("Rating") == raw, given
    for bad in (-1, 256, "x"):
        assert _track(Title="T", Rating=bad).get("Rating") is None, bad


def test_track_ids_stay_stable_and_unique():
    tracks = [
        {"Title": "live", "ID": "70001"},
        {"Title": "xml", "id": "2"},
        {"Title": "no id"},
        {"Title": "dup", "id": "2"},
        {"Title": "odd", "id": "abc"},
    ]
    _, root = _gen(tracks)
    ids = [t.get("TrackID") for t in root.iter("TRACK")]
    assert ids[:2] == ["70001", "2"]
    assert len(set(ids)) == len(ids)  # free numbers never collide with kept ids
    assert ids[2:] == ["1", "3", "4"]


def test_xml_library_track_with_none_fields_exports():
    # RekordboxXMLDB._parse_track keeps missing attributes as None
    t = _track(Title=None, Artist=None, Album=None, Genre=None, Key=None, path="/m/x y.mp3")
    assert t.get("Name") == "x y"
    assert t.get("Album") == ""


def test_control_characters_do_not_break_the_file():
    t = _track(Title="A\x13B", Comment="c\x00d", path="/m/a.mp3")
    assert (t.get("Name"), t.get("Comments")) == ("AB", "cd")


def test_tempo_uses_rekordbox_battito_attribute():
    t = _track(Title="T", beatGrid=[{"time": 0.1, "bpm": 128.0, "beat": 2}])
    tempo = t.find("TEMPO")
    assert tempo.get("Battito") == "2"
    assert tempo.get("Battuta") is None


def test_export_round_trips_through_the_xml_library_loader(tmp_path):
    from app.database import RekordboxXMLDB

    src = {
        "ID": "4242",
        "Title": "Round",
        "Artist": "Trip",
        "path": "C:/Music/a b & c.aiff",
        "Key": "Am",
        "Rating": 2,
        "Comment": "hello",
        "Bitrate": 1411,
        "StockDate": "2020-01-02",
        "BPM": 126.5,
    }
    path = RekordboxXML.generate([src], tmp_path / "out")
    lib = RekordboxXMLDB()
    assert lib.load_xml(path)
    got = lib.tracks["4242"]
    assert got["path"].replace("\\", "/") == "C:/Music/a b & c.aiff"  # loader uses os.sep
    assert (got["Key"], got["Comment"], got["Bitrate"]) == ("Am", "hello", 1411)
    assert (got["StockDate"], got["Rating"], got["BPM"]) == ("2020-01-02", 102, 126.5)
