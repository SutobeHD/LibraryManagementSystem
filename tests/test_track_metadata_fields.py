"""Track-metadata writes refuse fields and values the backend cannot store (issue K8).

``LiveRekordboxDB.update_track_metadata`` answered True for "BPM", "Key" or a typo
like "ArtistName" and wrote nothing, stored ``None`` as the string ``'None'`` and
accepted any Rating / ColorID. The XML facade merged any key and value into memory,
threw away ``save_xml()``'s result, and ``save_xml`` wrote straight onto the library
file: a value it could not serialise left the file truncated while the edit answered
True. Both backends now raise ``TrackFieldError`` before the first write, and the XML
facade answers False (memory rolled back) when the file cannot be saved.

Every rbox handle is a mock and every XML library lives in ``tmp_path``; no real
``master.db`` or Rekordbox XML is opened.
"""

from __future__ import annotations

import asyncio
import math
import os
import stat
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from app import database, main
from app.database import RekordboxDB, RekordboxXMLDB
from app.live_database import LiveRekordboxDB
from app.track_fields import (
    LIVE_WRITABLE_FIELDS,
    XML_WRITABLE_FIELDS,
    InvalidTrackFieldValue,
    TrackFieldError,
    UnknownTrackIds,
    UnsupportedTrackFields,
    normalise_track_updates,
)


class StrColorItem:
    """A ``DjmdContent`` stand-in whose ``color_id`` takes only str, as rbox 0.1.7 types it."""

    def __init__(self) -> None:
        object.__setattr__(self, "_d", {"title": "t", "commnt": "", "rating": 0, "color_id": "0"})

    def __getattr__(self, name: str) -> Any:
        try:
            return self._d[name]
        except KeyError:
            raise AttributeError(name) from None

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "color_id" and value is not None and not isinstance(value, str):
            raise TypeError(f"'{type(value).__name__}' object cannot be cast as 'str'")
        self._d[name] = value


@pytest.fixture
def conn(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """One mock rbox handle for every thread (routes run in FastAPI's threadpool)."""
    handle = MagicMock()
    handle.get_content_by_id.side_effect = lambda tid: handle.item if tid == "1" else None
    handle.item = StrColorItem()
    monkeypatch.setattr(LiveRekordboxDB, "db", property(lambda self: handle))
    return handle


@pytest.fixture
def live(conn: MagicMock) -> LiveRekordboxDB:
    db = LiveRekordboxDB("does-not-exist.db")
    db.tracks = {"1": {"ID": "1", "Title": "t", "BPM": 120.0, "Key": "Am", "path": ""}}
    return db


def _writes(conn: MagicMock) -> list[str]:
    return [name for name, _, _ in conn.method_calls if name != "get_content_by_id"]


# --- normaliser -------------------------------------------------------------------


def test_normalise_returns_a_coerced_copy() -> None:
    updates = {"Rating": " 4 ", "ColorID": "8", "Title": "x"}
    assert normalise_track_updates(updates, "live") == {"Rating": 4, "ColorID": 8, "Title": "x"}
    assert updates["Rating"] == " 4 "


def test_unsupported_fields_name_every_refused_key() -> None:
    with pytest.raises(UnsupportedTrackFields) as exc:
        normalise_track_updates({"Title": "x", "Key": "8A", "BPM": 1.0}, "live")
    assert exc.value.fields == ["BPM", "Key"]
    assert exc.value.backend == "live"
    assert str(exc.value) == "live library cannot write field(s): BPM, Key"


# --- live backend -----------------------------------------------------------------


@pytest.mark.parametrize(
    "updates",
    [
        {"BPM": 128.0, "Key": "8A"},
        {"ArtistName": "X"},
        {"Label": "L", "ReleaseYear": 2020, "Remixer": "R"},
        {"path": "C:/x.mp3", "TotalTime": 1.0, "beatGrid": [], "positionMarks": []},
        {"Title": "ok", "BPM": 1},  # one bad key refuses the good one too
    ],
)
def test_live_refuses_unknown_keys_before_any_write(live, conn, updates) -> None:
    with pytest.raises(UnsupportedTrackFields) as exc:
        live.update_track_metadata("1", updates)
    assert set(exc.value.fields) == set(updates) - LIVE_WRITABLE_FIELDS
    assert conn.method_calls == []  # not even the row read
    assert live.tracks["1"]["Title"] == "t"


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("Rating", "abc"),
        ("Rating", None),
        ("Rating", ""),
        ("Rating", True),
        ("Rating", 2.5j),
        ("Rating", 3.9),  # was stored as 3
        ("Rating", 3.0),
        ("Rating", "3.0"),
        ("Rating", 6),
        ("Rating", -1),
        ("Rating", "\u00b3"),  # str.isdigit() is True for a superscript three
        ("Rating", 10**400),
        ("ColorID", "abc"),
        ("ColorID", None),
        ("ColorID", ""),  # what BatchEditBar sent for a deselected colour
        ("ColorID", False),
        ("ColorID", 9),
        ("ColorID", 42),
        ("ColorID", -1),
        ("Title", None),  # was stored as the string 'None'
        ("Comment", None),
        ("Title", 5),
        ("Artist", 5),
        ("Genre", ["x"]),
        ("Album", {}),
    ],
)
def test_live_refuses_bad_values_before_any_write(live, conn, key, value) -> None:
    with pytest.raises(InvalidTrackFieldValue):
        live.update_track_metadata("1", {key: value})
    assert conn.method_calls == []


def test_live_bad_artist_does_not_leave_the_title_half_written(live, conn) -> None:
    # update_content wrote Title, then update_content_artist raised: a 500 after a write.
    with pytest.raises(InvalidTrackFieldValue):
        live.update_track_metadata("1", {"Title": "x", "Artist": 5})
    assert conn.method_calls == []
    assert conn.item.title == "t"


@pytest.mark.parametrize(
    ("key", "value", "stored"),
    [
        ("Rating", 0, 0),
        ("Rating", 5, 5),
        ("Rating", "3", 3),
        ("ColorID", 0, "0"),
        ("ColorID", 8, "8"),
        ("ColorID", "8", "8"),
    ],
)
def test_live_accepts_the_range_edges(live, conn, key, value, stored) -> None:
    assert live.update_track_metadata("1", {key: value}) is True
    attr = "rating" if key == "Rating" else "color_id"
    assert getattr(conn.item, attr) == stored
    assert live.tracks["1"][key] == int(stored)


def test_live_writes_every_allowed_field(live, conn) -> None:
    updates = {
        "Title": "New",
        "Comment": "c",
        "Rating": "4",
        "ColorID": 2,
        "Artist": "A",
        "Genre": "G",
        "Album": "Al",
    }
    assert set(updates) == LIVE_WRITABLE_FIELDS

    assert live.update_track_metadata("1", updates) is True

    item = conn.item
    assert (item.title, item.commnt, item.rating) == ("New", "c", 4)
    assert item.color_id == "2"  # int refused by the str-typed setter, str stored
    conn.update_content.assert_called_once_with(item)
    conn.update_content_artist.assert_called_once_with("1", "A")
    conn.update_content_genre.assert_called_once_with("1", "G")
    conn.update_content_album.assert_called_once_with("1", "Al")
    assert live.tracks["1"]["Rating"] == 4
    assert live.tracks["1"]["ColorID"] == 2


def test_live_add_track_sends_bpm_and_key_outside_the_metadata_update(live, conn) -> None:
    # BPM / key are not user-editable fields, so update_track_metadata never gets them
    # (it refuses the whole update for one); add_track writes them itself (B4).
    conn.create_content.return_value = SimpleNamespace(id="1")
    tid = live.add_track({"path": "C:/a.mp3", "Title": "T", "BPM": 128.0, "Key": "Am"})
    assert tid == "1"
    assert conn.item.title == "T"
    assert conn.item.bpm == 12800
    conn.update_content_key.assert_called_once_with("1", "Am")
    assert live.tracks["1"]["BPM"] == 128.0


def test_live_add_track_skips_missing_tags(live, conn) -> None:
    conn.create_content.return_value = SimpleNamespace(id="1")
    live.add_track({"path": "C:/a.mp3", "Title": None, "Artist": "A"})
    assert conn.item.title == "t"  # not the string 'None'
    conn.update_content_artist.assert_called_once_with("1", "A")


# --- facade -----------------------------------------------------------------------


def test_writable_fields_follow_the_mode() -> None:
    db = RekordboxDB()
    db.mode = "live"
    assert db.writable_track_fields() == LIVE_WRITABLE_FIELDS
    db.mode = "xml"
    assert db.writable_track_fields() == XML_WRITABLE_FIELDS


def test_facade_live_refuses_before_the_first_track(live, conn) -> None:
    db = RekordboxDB()
    db.mode = "live"
    db.live_db = live
    with pytest.raises(TrackFieldError):
        db.update_tracks_metadata(["1", "2", "3"], {"Rating": 3, "BPM": 1})
    assert conn.method_calls == []


# --- XML backend ------------------------------------------------------------------

# Shaped like a real Rekordbox 6 export: PRODUCT node, Rating on the raw 0-255 scale,
# Colour as hex, no ColorID attribute.
_RB_XML = """<?xml version="1.0" encoding="UTF-8"?>
<DJ_PLAYLISTS Version="1.0.0"><PRODUCT Name="rekordbox" Version="6.8.4" Company="AlphaTheta"/>
<COLLECTION Entries="2">
<TRACK TrackID="1" Name="A" Artist="X" Composer="Comp" Album="Al" Kind="MP3 File" Size="100"
 TotalTime="300" Year="2019" AverageBpm="120.00" DateAdded="2024-01-01" BitRate="320"
 SampleRate="44100" Comments="c" PlayCount="7" Rating="204" Location="file://localhost/C:/a.mp3"
 Remixer="Rmx" Tonality="Am" Label="Lbl" Mix="" Colour="0xFF0000">
  <TEMPO Inizio="0.025" Bpm="120.00" Metro="4/4" Battito="1"/>
</TRACK>
<TRACK TrackID="2" Name="B" Artist="Y" AverageBpm="125.00" Rating="255"
 Location="file://localhost/C:/b.mp3" Colour="0x0000FF"/>
</COLLECTION><PLAYLISTS><NODE Type="0" Name="ROOT" Count="0"/></PLAYLISTS></DJ_PLAYLISTS>
"""


@pytest.fixture
def xml_db(tmp_path: Path) -> RekordboxDB:
    path = tmp_path / "lib.xml"
    path.write_text(_RB_XML, encoding="utf-8")
    db = RekordboxDB()
    db.mode = "xml"
    assert db.xml_db.load_xml(str(path))
    return db


def _lib(db: RekordboxDB) -> Path:
    return Path(db.xml_db.xml_path)


def _reload(db: RekordboxDB) -> RekordboxXMLDB:
    fresh = RekordboxXMLDB()
    assert fresh.load_xml(str(_lib(db)))
    return fresh


def _assert_library_intact(db: RekordboxDB, before: bytes) -> None:
    assert _lib(db).read_bytes() == before
    assert not _lib(db).with_name("lib.xml.tmp").exists()
    _reload(db)


def test_xml_refuses_unknown_key_and_saves_nothing(xml_db) -> None:
    before = _lib(xml_db).read_bytes()
    with pytest.raises(UnsupportedTrackFields) as exc:
        xml_db.update_tracks_metadata(["1"], {"Rating": 5, "Bogus": "z", "ArtistName": "Q"})
    assert exc.value.fields == ["ArtistName", "Bogus"]
    assert xml_db.xml_db.tracks["1"]["Rating"] == 204
    assert "Bogus" not in xml_db.xml_db.tracks["1"]
    _assert_library_intact(xml_db, before)


@pytest.mark.parametrize(
    "updates",
    [
        {"Key": 8},  # truncated the file to 199 B before the fix
        {"Title": 5},
        {"Title": None},
        {"Artist": ["a"]},
        {"Comment": {}},
        {"BPM": "abc"},  # was written as AverageBpm="abc": the next load failed
        {"BPM": -1},
        {"BPM": math.nan},
        {"BPM": math.inf},
        {"BPM": True},
        {"TotalTime": 10**400},
        {"beatGrid": [120.0]},
        {"beatGrid": {"bpm": 120.0}},
        {"positionMarks": "x"},
        {"Rating": 256},
        {"Rating": -1},
        {"Rating": 2.5},
        {"ColorID": 9},
        {"Title": "a\x01b"},  # ElementTree writes it raw; the reload fails
        {"Comment": "lone \ud800 surrogate"},
        {"positionMarks": [{"Name": "cue\x00", "Start": 1.0}]},
    ],
)
def test_xml_refuses_values_that_would_break_the_file(xml_db, updates) -> None:
    before = _lib(xml_db).read_bytes()
    track = dict(xml_db.xml_db.tracks["1"])
    with pytest.raises(InvalidTrackFieldValue):
        xml_db.update_tracks_metadata(["1"], updates)
    assert xml_db.xml_db.tracks["1"] == track
    _assert_library_intact(xml_db, before)


def test_xml_edit_keeps_every_track_rating(xml_db) -> None:
    assert xml_db.update_tracks_metadata(["1"], {"Title": "New"}) is True
    fresh = _reload(xml_db)
    assert fresh.tracks["1"]["Title"] == "New"
    # save_xml dropped Rating on every save; now every track keeps its raw value.
    assert fresh.tracks["1"]["Rating"] == 204
    assert fresh.tracks["2"]["Rating"] == 255


def test_xml_rating_color_and_bpm_survive_a_save(xml_db) -> None:
    assert xml_db.update_tracks_metadata(["1"], {"Rating": "255", "ColorID": 2, "BPM": 130})
    fresh = _reload(xml_db)
    assert fresh.tracks["1"]["Rating"] == 255
    assert fresh.tracks["1"]["ColorID"] == "2"
    assert fresh.tracks["1"]["BPM"] == 130.0
    assert fresh.tracks["2"]["ColorID"] is None  # no ColorID attribute invented


def test_xml_ui_rating_is_stored_on_the_ui_scale(xml_db) -> None:
    # Known gap (follow-up D): the UI sends 0-5 stars, Rekordbox XML holds 0-255.
    # The value is kept as sent, next to Rekordbox's own raw ratings.
    assert xml_db.update_tracks_metadata(["1"], {"Rating": 3}) is True
    text = _lib(xml_db).read_text(encoding="utf-8")
    assert 'TrackID="1"' in text and 'Rating="3"' in text and 'Rating="255"' in text


def test_xml_unknown_track_changes_nothing(xml_db) -> None:
    before = _lib(xml_db).read_bytes()
    with pytest.raises(UnknownTrackIds) as exc:
        xml_db.update_tracks_metadata(["1", "nope"], {"Title": "Z"})
    assert exc.value.track_ids == ["nope"]
    assert xml_db.xml_db.tracks["1"]["Title"] == "A"
    _assert_library_intact(xml_db, before)


def test_xml_read_only_library_is_false_and_rolled_back(xml_db) -> None:
    lib = _lib(xml_db)
    before = lib.read_bytes()
    os.chmod(lib, stat.S_IREAD)
    try:
        assert xml_db.update_tracks_metadata(["1", "2"], {"Title": "Z", "Rating": 3}) is False
    finally:
        os.chmod(lib, stat.S_IREAD | stat.S_IWRITE)
    assert [xml_db.xml_db.tracks[t]["Title"] for t in ("1", "2")] == ["A", "B"]
    assert [xml_db.xml_db.tracks[t]["Rating"] for t in ("1", "2")] == [204, 255]
    _assert_library_intact(xml_db, before)


def test_xml_failed_swap_is_false_and_rolled_back(xml_db, monkeypatch) -> None:
    before = _lib(xml_db).read_bytes()
    calls: list[Any] = []

    def locked(src: Any, dst: Any) -> None:
        calls.append(src)
        raise PermissionError("held open by another process")

    monkeypatch.setattr(database.os, "replace", locked)
    monkeypatch.setattr(database, "_REPLACE_RETRY_S", 0)
    assert xml_db.update_tracks_metadata(["1"], {"Genre": "Techno"}) is False
    assert len(calls) == database._REPLACE_ATTEMPTS
    assert xml_db.xml_db.tracks["1"]["Genre"] is None
    _assert_library_intact(xml_db, before)


def test_xml_swap_retries_a_transient_lock(xml_db, monkeypatch) -> None:
    real_replace = os.replace
    calls: list[Any] = []

    def flaky(src: Any, dst: Any) -> None:
        calls.append(src)
        if len(calls) == 1:
            raise PermissionError("scanner has it open")
        real_replace(src, dst)

    monkeypatch.setattr(database.os, "replace", flaky)
    monkeypatch.setattr(database, "_REPLACE_RETRY_S", 0)
    assert xml_db.update_tracks_metadata(["1"], {"Genre": "Techno"}) is True
    assert len(calls) == 2
    assert _reload(xml_db).tracks["1"]["Genre"] == "Techno"


def test_xml_write_that_dies_halfway_leaves_the_library_whole(xml_db, monkeypatch) -> None:
    before = _lib(xml_db).read_bytes()

    def dies_halfway(self: ET.ElementTree, file: Any, *args: Any, **kwargs: Any) -> None:
        Path(file).write_bytes(b"<?xml version='1.0'?><DJ_PLAYLISTS><COLL")
        raise OSError("disk full")

    monkeypatch.setattr(ET.ElementTree, "write", dies_halfway)
    assert xml_db.update_tracks_metadata(["1"], {"Title": "Z"}) is False
    assert xml_db.xml_db.tracks["1"]["Title"] == "A"
    _assert_library_intact(xml_db, before)


def test_xml_unserialisable_nested_value_is_false_and_the_next_save_works(xml_db) -> None:
    before = _lib(xml_db).read_bytes()
    grid = xml_db.xml_db.tracks["1"]["beatGrid"]
    del xml_db.xml_db.tracks["1"]["Label"]  # rollback must pop a key the track lacked
    # An int Metro passes the shape check but ElementTree refuses to serialise it.
    updates = {"Label": "L", "beatGrid": [{"time": 0.0, "bpm": 120.0, "metro": 4}]}

    assert xml_db.update_tracks_metadata(["1"], updates) is False

    assert xml_db.xml_db.tracks["1"]["beatGrid"] is grid
    assert "Label" not in xml_db.xml_db.tracks["1"]
    _assert_library_intact(xml_db, before)
    assert xml_db.save() is True
    _reload(xml_db)


# --- routes -----------------------------------------------------------------------


def _req(method: str, url: str, body: dict[str, Any], headers: dict[str, str]) -> httpx.Response:
    async def go() -> httpx.Response:
        transport = httpx.ASGITransport(app=main.app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            return await client.request(method, url, json=body, headers=headers)

    return asyncio.run(go())


@pytest.fixture
def no_tag_writes(monkeypatch) -> None:
    # The XML fixture names C:/a.mp3: never let the route's tag write-back touch a real file.
    monkeypatch.setattr(
        main.SettingsManager, "load", staticmethod(lambda: {"write_tags_to_files": False})
    )


@pytest.fixture
def live_main(monkeypatch, live, no_tag_writes) -> RekordboxDB:
    db = RekordboxDB()
    db.mode = "live"
    db.live_db = live
    db.loaded = True
    monkeypatch.setattr(main, "db", db)
    # A Rekordbox open on the dev machine must not turn these into 409s.
    monkeypatch.setattr(main, "_is_rekordbox_running", lambda: False)
    return db


@pytest.fixture
def xml_main(monkeypatch, xml_db, no_tag_writes) -> RekordboxDB:
    xml_db.loaded = True
    monkeypatch.setattr(main, "db", xml_db)
    return xml_db


def test_batch_route_400_names_the_refused_fields(live_main, conn, auth_token) -> None:
    body = {"track_ids": ["1"], "updates": {"BPM": 128.0, "Key": "8A"}}
    r = _req("PATCH", "/api/tracks/batch", body, auth_token)
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == "live library cannot write field(s): BPM, Key"
    assert conn.method_calls == []


@pytest.mark.parametrize("updates", [{"ColorID": ""}, {"Rating": 99}, {"Title": None}])
def test_batch_route_400_on_a_bad_value(live_main, conn, auth_token, updates) -> None:
    r = _req("PATCH", "/api/tracks/batch", {"track_ids": ["1"], "updates": updates}, auth_token)
    assert r.status_code == 400, r.text
    assert conn.method_calls == []


def test_batch_route_success(live_main, conn, auth_token) -> None:
    body = {"track_ids": ["1"], "updates": {"Rating": 3, "ColorID": "5"}}
    r = _req("PATCH", "/api/tracks/batch", body, auth_token)
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "success", "file_tags": {"1": "skipped"}}
    assert (conn.item.rating, conn.item.color_id) == (3, "5")


def test_batch_route_xml_value_that_would_corrupt_the_file_is_400(xml_main, auth_token) -> None:
    before = _lib(xml_main).read_bytes()
    r = _req("PATCH", "/api/tracks/batch", {"track_ids": ["1"], "updates": {"Key": 8}}, auth_token)
    assert r.status_code == 400, r.text
    _assert_library_intact(xml_main, before)


def test_batch_route_unknown_track_is_404(xml_main, auth_token) -> None:
    before = _lib(xml_main).read_bytes()
    body = {"track_ids": ["1", "nope"], "updates": {"Rating": 3}}
    r = _req("PATCH", "/api/tracks/batch", body, auth_token)
    assert r.status_code == 404, r.text
    assert r.json()["detail"] == "Unknown track id(s): nope"
    assert xml_main.xml_db.tracks["1"]["Rating"] == 204
    _assert_library_intact(xml_main, before)


def test_batch_route_failed_xml_save_is_500(xml_main, auth_token) -> None:
    lib = _lib(xml_main)
    before = lib.read_bytes()
    os.chmod(lib, stat.S_IREAD)
    try:
        body = {"track_ids": ["1"], "updates": {"Title": "Z"}}
        r = _req("PATCH", "/api/tracks/batch", body, auth_token)
    finally:
        os.chmod(lib, stat.S_IREAD | stat.S_IWRITE)
    assert r.status_code == 500, r.text  # was 200 {"status": "error"}, read by no caller
    assert xml_main.xml_db.tracks["1"]["Title"] == "A"
    _assert_library_intact(xml_main, before)


def test_batch_route_xml_writes_bpm_and_key(xml_main, auth_token) -> None:
    body = {"track_ids": ["1"], "updates": {"BPM": 128.5, "Key": "8A"}}
    r = _req("PATCH", "/api/tracks/batch", body, auth_token)
    assert r.status_code == 200, r.text
    fresh = _reload(xml_main)
    assert (fresh.tracks["1"]["BPM"], fresh.tracks["1"]["Key"]) == (128.5, "8A")


def test_track_route_rejects_an_unknown_body_key(live_main, conn, auth_token) -> None:
    r = _req("POST", "/api/track/1", {"Rating": 3, "BPM": 999}, auth_token)
    assert r.status_code == 422, r.text
    assert conn.method_calls == []


def test_track_route_400_on_an_out_of_range_value(live_main, conn, auth_token) -> None:
    r = _req("POST", "/api/track/1", {"Rating": 9}, auth_token)
    assert r.status_code == 400, r.text
    assert "Rating" in r.json()["detail"]
    assert conn.method_calls == []


def test_track_route_writes_the_ranking_view_fields(live_main, conn, auth_token) -> None:
    body = {"Rating": 3, "ColorID": 4, "Comment": "c", "Genre": "G"}
    r = _req("POST", "/api/track/1", body, auth_token)
    assert r.status_code == 200, r.text
    assert (conn.item.rating, conn.item.color_id, conn.item.commnt) == (3, "4", "c")
    conn.update_content_genre.assert_called_once_with("1", "G")
