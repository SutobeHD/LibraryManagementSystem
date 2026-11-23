"""Tests for app/xml_generator.py — Rekordbox collection XML export.

Export integrity matters (a broken XML = Rekordbox refuses the whole import).
Covers: special-character escaping produces parseable XML, the produced tree
has the expected structure/values, and generate() does NOT mutate its input
(the DROP-cue append must not leak into the caller's positionMarks list).

PC test 2026-11-22: PLAYLISTS held only an empty ROOT (an imported playlist lost its
name and order) and ``soundcloud:tracks:123`` got ``file://localhost/<cwd>/...`` as
Location. Playlist/folder NODEs, the streaming skip and ``POST /api/rekordbox/export``
with ``playlist_id`` / ``playlist_name`` are covered at the bottom; the library there is
a stub and every file lives in ``tmp_path``.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import httpx
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.xml_generator import (  # noqa: E402
    RekordboxXML,
    XmlFolder,
    XmlPlaylist,
    is_streaming_path,
)


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


# --- Playlist NODEs + streaming tracks (PC test 2026-11-22) ------------------------


def _root_node(root: ET.Element) -> ET.Element:
    nodes = root.find("PLAYLISTS").findall("NODE")
    assert len(nodes) == 1
    assert (nodes[0].get("Type"), nodes[0].get("Name")) == ("0", "ROOT")
    return nodes[0]


def _keys(node: ET.Element) -> list[str]:
    return [t.get("Key") for t in node.findall("TRACK")]


def test_without_playlists_root_stays_alone_with_count_zero():
    _, root = _gen([{"Title": "T", "path": "/m/a.mp3"}])
    top = _root_node(root)
    assert top.get("Count") == "0"
    assert list(top) == []


def test_playlist_node_keeps_order_and_repeats():
    tracks = [
        {"ID": "11", "Title": "a", "path": "/m/a.mp3"},
        {"ID": "12", "Title": "b", "path": "/m/b.mp3"},
        {"ID": "13", "Title": "c", "path": "/m/c.mp3"},
    ]
    out = Path(tempfile.mkdtemp()) / "pl"
    root = ET.parse(
        RekordboxXML.generate(tracks, out, [XmlPlaylist("Peak", [2, 0, 2, 1])])
    ).getroot()
    top = _root_node(root)
    assert top.get("Count") == "1"
    (node,) = top.findall("NODE")
    assert (node.get("Name"), node.get("Type"), node.get("KeyType"), node.get("Entries")) == (
        "Peak",
        "1",
        "0",
        "4",
    )
    assert _keys(node) == ["13", "11", "13", "12"]  # KeyType 0 = COLLECTION TrackID
    assert root.find("COLLECTION").get("Entries") == "3"


def test_folders_nest_with_child_count():
    tracks = [{"ID": "1", "path": "/m/a.mp3"}, {"ID": "2", "path": "/m/b.mp3"}]
    tree = XmlFolder(
        "Sets",
        [XmlPlaylist("Peak", [1]), XmlFolder("Old", [XmlPlaylist("Warmup", [0, 1])])],
    )
    out = Path(tempfile.mkdtemp()) / "f"
    root = ET.parse(RekordboxXML.generate(tracks, out, [tree])).getroot()
    (sets,) = _root_node(root).findall("NODE")
    assert (sets.get("Type"), sets.get("Name"), sets.get("Count")) == ("0", "Sets", "2")
    peak, old = sets.findall("NODE")
    assert (peak.get("Type"), _keys(peak)) == ("1", ["2"])
    assert (old.get("Type"), old.get("Count")) == ("0", "1")
    (warmup,) = old.findall("NODE")
    assert (warmup.get("Name"), warmup.get("Entries"), _keys(warmup)) == (
        "Warmup",
        "2",
        ["1", "2"],
    )


@pytest.mark.parametrize(
    ("path", "streaming"),
    [
        ("soundcloud:tracks:123", True),
        ("SoundCloud:tracks:9", True),
        ("spotify:track:abc", True),
        ("tidal:track:1", True),
        ("beatport:track:1", True),
        ("https://soundcloud.com/x/y", True),
        ("C:/Music/a.mp3", False),
        ("C:\\Music\\a.mp3", False),
        ("/music/soundcloud:tracks:1.mp3", False),
        ("a.mp3", False),
        ("", False),
        (None, False),
        ("soundcloud", False),
    ],
)
def test_is_streaming_path(path, streaming):
    assert is_streaming_path(path) is streaming


def test_streaming_tracks_left_out_of_collection_and_playlist():
    tracks = [
        {"ID": "1", "Title": "local", "path": "C:/Music/a.mp3"},
        {"ID": "2", "Title": "sc", "path": "soundcloud:tracks:123"},
        {"ID": "3", "Title": "sp", "path": "spotify:track:abc"},
        {"ID": "4", "Title": "local2", "path": "C:\\Music\\b.flac"},
    ]
    out = Path(tempfile.mkdtemp()) / "s"
    root = ET.parse(
        RekordboxXML.generate(tracks, out, [XmlPlaylist("Mix", [1, 0, 2, 3])])
    ).getroot()
    collection = root.find("COLLECTION")
    assert collection.get("Entries") == "2"
    assert [t.get("Name") for t in collection.findall("TRACK")] == ["local", "local2"]
    assert not any("soundcloud" in (t.get("Location") or "") for t in root.iter("TRACK"))
    (node,) = _root_node(root).findall("NODE")
    assert (node.get("Entries"), _keys(node)) == ("2", ["1", "4"])


def test_playlist_export_round_trips_through_the_xml_library_loader(tmp_path):
    from app.database import RekordboxXMLDB

    tracks = [
        {"ID": "501", "Title": "One", "path": "C:/Music/1.mp3"},
        {"ID": "502", "Title": "Two", "path": "C:/Music/2.mp3"},
        {"ID": "503", "Title": "Three", "path": "C:/Music/3.mp3"},
    ]
    tree = XmlFolder("Sets", [XmlPlaylist("Friday", [2, 0, 1])])
    path = RekordboxXML.generate(tracks, tmp_path / "rt", [tree])
    lib = RekordboxXMLDB()
    assert lib.load_xml(path)
    (sets,) = lib.get_playlist_tree()
    assert (sets["Name"], sets["Type"]) == ("Sets", "0")
    (friday,) = sets["Children"]
    assert (friday["Name"], friday["Type"]) == ("Friday", "1")
    assert [t["id"] for t in lib.get_playlist_tracks(friday["ID"])] == ["503", "501", "502"]


# --- POST /api/rekordbox/export -----------------------------------------------------

_LIB_TRACKS: dict[str, dict[str, Any]] = {
    "11": {
        "ID": "11",
        "Title": "Eins",
        "Artist": "Künstler",
        "path": "C:/Music/Ä b #1.aiff",
        "TotalTime": 300,
        "BPM": 128,
        "Key": "8A",
        "StockDate": "2021-03-04",
        "beatGrid": [
            {"time": 0.123, "bpm": 128.0, "beat": 1},
            {"time": 0.592, "bpm": 128.0, "beat": 2},
            {"time": 1.061, "bpm": 128.0, "beat": 3},
        ],
    },
    "12": {"ID": "12", "Title": "Zwei", "path": "C:/Music/zwei.mp3"},
    "13": {"ID": "13", "Title": "Stream", "path": "soundcloud:tracks:123"},
    "14": {"ID": "14", "Title": "Vier", "path": "C:/Music/vier.flac"},
}
_LIB_TREE: list[dict[str, Any]] = [
    {
        "ID": "f1",
        "Name": "Sets",
        "Type": "0",
        "Children": [
            {"ID": "p1", "Name": "Peak", "Type": "1", "Children": []},
            {
                "ID": "f2",
                "Name": "Old",
                "Type": "0",
                "Children": [{"ID": "p2", "Name": "Warmup", "Type": "1", "Children": []}],
            },
        ],
    },
    {"ID": "p3", "Name": "Only SC", "Type": "1", "Children": []},
]
_LIB_CONTENTS = {"p1": ["12", "13", "11", "12"], "p2": ["14", "11"], "p3": ["13"]}


class _Library:
    """RekordboxDB stand-in: the three calls the export makes."""

    def get_track_details(self, tid: str) -> dict[str, Any] | None:
        return _LIB_TRACKS.get(str(tid))

    def get_playlist_tree(self) -> list[dict[str, Any]]:
        return _LIB_TREE

    def get_playlist_tracks(self, pid: str) -> list[dict[str, Any]]:
        return [_LIB_TRACKS[t] for t in _LIB_CONTENTS.get(pid, [])]


@pytest.fixture
def export_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    from app import main, rekordbox_bridge

    out = tmp_path / "exports"
    out.mkdir()
    monkeypatch.setattr(main, "EXPORT_DIR", out)
    monkeypatch.setattr(rekordbox_bridge, "db", _Library())
    return out


def _export(body: dict[str, Any], headers: dict[str, str]) -> httpx.Response:
    from app.main import app

    async def _go() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            return await ac.post("/api/rekordbox/export", json=body, headers=headers)

    return asyncio.run(_go())


def test_route_exports_a_library_playlist_in_order(export_dir, auth_token):
    r = _export({"playlist_id": "p1", "filename": "peak"}, auth_token)

    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["exported"], body["skipped_streaming"], body["playlist"]) == (2, 1, "Peak")
    assert "Skipped 1 streaming" in body["message"]
    root = ET.parse(export_dir / "peak.xml").getroot()
    collection = root.find("COLLECTION")
    assert collection.get("Entries") == "2"
    assert [t.get("TrackID") for t in collection.findall("TRACK")] == ["12", "11"]
    assert not any("soundcloud" in (t.get("Location") or "") for t in root.iter("TRACK"))
    (node,) = _root_node(root).findall("NODE")
    assert (node.get("Name"), node.get("Type"), node.get("KeyType"), node.get("Entries")) == (
        "Peak",
        "1",
        "0",
        "3",
    )
    assert _keys(node) == ["12", "11", "12"]


def test_route_playlist_export_keeps_the_verified_track_fields(export_dir, auth_token):
    assert _export({"playlist_id": "p1"}, auth_token).status_code == 200

    root = ET.parse(export_dir / "rekordbox_export.xml").getroot()
    t = root.find("COLLECTION/TRACK[@TrackID='11']")
    assert {k: t.get(k) for k in ("Name", "Artist", "Kind", "TotalTime", "AverageBpm")} == {
        "Name": "Eins",
        "Artist": "Künstler",
        "Kind": "AIFF File",
        "TotalTime": "300",
        "AverageBpm": "128.00",
    }
    assert (t.get("Tonality"), t.get("DateAdded")) == ("8A", "2021-03-04")
    assert t.get("Location") == "file://localhost/C:/Music/%C3%84%20b%20%231.aiff"
    tempos = t.findall("TEMPO")
    assert [x.get("Inizio") for x in tempos] == ["0.123", "0.592", "1.061"]  # one per beat
    assert [x.get("Battito") for x in tempos] == ["1", "2", "3"]


def test_route_exports_a_folder_as_nested_nodes(export_dir, auth_token):
    r = _export({"playlist_id": "f1"}, auth_token)

    assert r.status_code == 200, r.text
    assert (r.json()["exported"], r.json()["playlist"]) == (3, "Sets")
    root = ET.parse(export_dir / "rekordbox_export.xml").getroot()
    # a track in two playlists is one COLLECTION entry
    assert [t.get("TrackID") for t in root.find("COLLECTION").findall("TRACK")] == [
        "12",
        "11",
        "14",
    ]
    top = _root_node(root)
    assert top.get("Count") == "1"
    (sets,) = top.findall("NODE")
    assert (sets.get("Type"), sets.get("Count")) == ("0", "2")
    peak, old = sets.findall("NODE")
    assert (peak.get("Name"), _keys(peak)) == ("Peak", ["12", "11", "12"])
    assert (old.get("Name"), old.get("Type"), old.get("Count")) == ("Old", "0", "1")
    (warmup,) = old.findall("NODE")
    assert (warmup.get("Name"), warmup.get("Entries"), _keys(warmup)) == (
        "Warmup",
        "2",
        ["14", "11"],
    )


def test_route_playlist_name_overrides_the_library_name(export_dir, auth_token):
    r = _export({"playlist_id": "p2", "playlist_name": "  Friday  "}, auth_token)

    assert r.status_code == 200, r.text
    (node,) = _root_node(ET.parse(r.json()["path"]).getroot()).findall("NODE")
    assert node.get("Name") == "Friday"


def test_route_track_ids_with_a_name_form_one_playlist(export_dir, auth_token):
    r = _export({"track_ids": ["14", "13", "11", "nope"], "playlist_name": "Gig"}, auth_token)

    assert r.status_code == 200, r.text
    assert (r.json()["exported"], r.json()["skipped_streaming"]) == (2, 1)
    (node,) = _root_node(ET.parse(r.json()["path"]).getroot()).findall("NODE")
    assert (node.get("Name"), node.get("Entries"), _keys(node)) == ("Gig", "2", ["14", "11"])


def test_route_track_ids_without_a_name_keep_root_alone(export_dir, auth_token):
    r = _export({"track_ids": ["11", "12"]}, auth_token)

    assert r.status_code == 200, r.text
    assert (r.json()["exported"], r.json()["playlist"]) == (2, None)
    assert r.json()["message"] == "Exported 2 tracks to XML."
    top = _root_node(ET.parse(r.json()["path"]).getroot())
    assert (top.get("Count"), list(top)) == ("0", [])


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"playlist_id": "missing"}, 404),
        ({"playlist_id": "p1", "track_ids": ["11"]}, 400),
        ({"playlist_id": "p3"}, 400),  # only a streaming track
        ({"track_ids": ["13"]}, 400),
        ({"track_ids": []}, 400),
    ],
)
def test_route_refuses_without_writing(export_dir, auth_token, body, status):
    r = _export(body, auth_token)

    assert r.status_code == status, r.text
    assert list(export_dir.iterdir()) == []
