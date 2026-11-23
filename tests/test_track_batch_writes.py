"""Track edits are all or nothing and name an unknown id (PC test 2026-11-22).

``PATCH /api/tracks/batch`` with ``[valid_id, unknown_id]`` answered 500 in live mode
after the valid row was already written: the facade looped over the ids and wrote one
row after the other. ``POST /api/track/{tid}`` answered 500 for an unknown id. Now
every id is read before the first write (unknown -> 404 naming it, nothing written),
and a write rbox refuses partway writes the rows already touched back from snapshots
read before the first write, then answers 500.

No real master.db: the rbox handle is a stand-in that hands out detached row copies
(as rbox does) and commits every call on its own.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from app import main
from app.database import RekordboxDB
from app.live_database import LiveRekordboxDB
from app.track_fields import TrackWriteFailed, UnknownTrackIds

_COLUMNS = ("title", "commnt", "rating", "color_id", "artist_id", "genre_id", "album_id")


def _row(n: str) -> dict[str, Any]:
    return {
        "title": f"T{n}",
        "commnt": f"c{n}",
        "rating": 1,
        "color_id": "0",
        "artist_id": f"a{n}",
        "genre_id": f"g{n}",
        "album_id": None,
    }


class _MasterDb:
    """rbox.MasterDb stand-in: three rows, entity tables by name, every write recorded."""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {n: _row(n) for n in ("1", "2", "3")}
        self.entities: dict[str, dict[str, str]] = {
            "artist": {"a1": "A1", "a2": "A2", "a3": "A3"},
            "genre": {"g1": "G1", "g2": "G2", "g3": "G3"},
            "album": {},
        }
        self.writes: list[tuple[str, str]] = []
        #: Called before every write with (method, content id); raise to refuse it.
        self.hook: Callable[[str, str], None] | None = None

    def _write(self, method: str, tid: str) -> None:
        if self.hook is not None:
            self.hook(method, tid)
        self.writes.append((method, tid))

    def get_content_by_id(self, tid: str) -> SimpleNamespace | None:
        row = self.rows.get(str(tid))
        return SimpleNamespace(id=str(tid), **row) if row is not None else None

    def update_content(self, item: SimpleNamespace) -> None:
        self._write("update_content", item.id)
        self.rows[item.id] = {c: getattr(item, c) for c in _COLUMNS}

    def _repoint(self, kind: str, tid: str, name: str) -> None:
        self._write(f"update_content_{kind}", tid)
        table = self.entities[kind]
        eid = next((k for k, v in table.items() if v == name), None)
        if eid is None:
            eid = f"{kind}-new-{len(table)}"
            table[eid] = name
        self.rows[tid][f"{kind}_id"] = eid

    def update_content_artist(self, tid: str, name: str) -> None:
        self._repoint("artist", tid, name)

    def update_content_genre(self, tid: str, name: str) -> None:
        self._repoint("genre", tid, name)

    def update_content_album(self, tid: str, name: str) -> None:
        self._repoint("album", tid, name)


def _fail_on(method: str, tid: str, nth: int = 1) -> Callable[[str, str], None]:
    seen = {"n": 0}

    def hook(m: str, t: str) -> None:
        if (m, t) == (method, tid):
            seen["n"] += 1
            if seen["n"] == nth:
                raise RuntimeError("database is locked")

    return hook


@pytest.fixture
def master(monkeypatch: pytest.MonkeyPatch) -> _MasterDb:
    handle = _MasterDb()
    monkeypatch.setattr(LiveRekordboxDB, "db", property(lambda self: handle))
    return handle


def _cache(n: str) -> dict[str, Any]:
    return {
        "ID": n,
        "Title": f"T{n}",
        "Artist": f"A{n}",
        "Genre": f"G{n}",
        "Album": "",
        "Comment": f"c{n}",
        "Rating": 1,
        "ColorID": 0,
        "path": "",
        "Artwork": "",
    }


@pytest.fixture
def live(master: _MasterDb) -> LiveRekordboxDB:
    db = LiveRekordboxDB("does-not-exist.db")
    db.tracks = {n: _cache(n) for n in ("1", "2", "3")}
    return db


@pytest.fixture
def facade(monkeypatch: pytest.MonkeyPatch, live: LiveRekordboxDB) -> RekordboxDB:
    db = RekordboxDB()
    db.mode = "live"
    db.live_db = live
    db.loaded = True
    monkeypatch.setattr(main, "db", db)
    monkeypatch.setattr(main, "_is_rekordbox_running", lambda: False)
    monkeypatch.setattr(
        main.SettingsManager, "load", staticmethod(lambda: {"write_tags_to_files": False})
    )
    return db


def _req(method: str, url: str, body: dict[str, Any], headers: dict[str, str]) -> httpx.Response:
    async def go() -> httpx.Response:
        transport = httpx.ASGITransport(app=main.app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            return await client.request(method, url, json=body, headers=headers)

    return asyncio.run(go())


def _batch(ids: list[str], updates: dict[str, Any], headers: dict[str, str]) -> httpx.Response:
    return _req("PATCH", "/api/tracks/batch", {"track_ids": ids, "updates": updates}, headers)


def _originals() -> dict[str, dict[str, Any]]:
    return {n: _row(n) for n in ("1", "2", "3")}


# --- unknown ids ------------------------------------------------------------------


def test_live_batch_with_an_unknown_id_writes_nothing(facade, live, master) -> None:
    with pytest.raises(UnknownTrackIds) as exc:
        facade.update_tracks_metadata(["1", "9", "2", "8"], {"Title": "New"})
    assert exc.value.track_ids == ["9", "8"]
    assert master.writes == []
    assert master.rows == _originals()
    assert live.tracks["1"]["Title"] == "T1"


def test_batch_route_unknown_id_is_404_naming_it(facade, live, master, auth_token) -> None:
    r = _batch(["1", "9"], {"Title": "New", "Artist": "X"}, auth_token)
    assert r.status_code == 404, r.text
    assert r.json()["detail"] == "Unknown track id(s): 9"
    assert master.writes == []  # the valid row was written before the fix
    assert master.rows == _originals()
    assert live.tracks["1"]["Title"] == "T1"


def test_batch_route_404_lists_at_most_ten_ids(facade, master, auth_token) -> None:
    unknown = [str(n) for n in range(100, 112)]
    r = _batch(["1", *unknown], {"Title": "New"}, auth_token)
    assert r.status_code == 404, r.text
    assert r.json()["detail"] == f"Unknown track id(s): {', '.join(unknown[:10])} and 2 more"
    assert master.writes == []


def test_batch_route_refuses_a_bad_value_before_reading_any_row(facade, master, auth_token):
    r = _batch(["1", "9"], {"Rating": 9}, auth_token)
    assert r.status_code == 400, r.text
    assert master.writes == []


def test_track_route_unknown_id_is_404(facade, master, auth_token) -> None:
    r = _req("POST", "/api/track/9", {"Rating": 3}, auth_token)
    assert r.status_code == 404, r.text  # was 500 "Track 9 not found in Live DB"
    assert r.json()["detail"] == "Unknown track id(s): 9"
    assert master.writes == []


def test_track_route_unknown_id_is_404_in_xml_mode(monkeypatch, tmp_path, auth_token) -> None:
    lib = tmp_path / "lib.xml"
    lib.write_text(
        '<?xml version="1.0" encoding="UTF-8"?><DJ_PLAYLISTS Version="1.0.0">'
        '<COLLECTION Entries="1"><TRACK TrackID="1" Name="A" Rating="0"'
        ' Location="file://localhost/C:/a.mp3"/></COLLECTION>'
        '<PLAYLISTS><NODE Type="0" Name="ROOT" Count="0"/></PLAYLISTS></DJ_PLAYLISTS>',
        encoding="utf-8",
    )
    db = RekordboxDB()
    db.mode = "xml"
    assert db.xml_db.load_xml(str(lib))
    db.loaded = True
    monkeypatch.setattr(main, "db", db)
    before = lib.read_bytes()

    r = _req("POST", "/api/track/9", {"Rating": 3}, auth_token)

    assert r.status_code == 404, r.text
    assert lib.read_bytes() == before


# --- all or nothing ---------------------------------------------------------------


def test_batch_route_writes_every_row(facade, live, master, auth_token) -> None:
    r = _batch(["1", "2"], {"Title": "New", "Artist": "A2"}, auth_token)
    assert r.status_code == 200, r.text
    assert [master.rows[n]["title"] for n in ("1", "2", "3")] == ["New", "New", "T3"]
    assert [master.rows[n]["artist_id"] for n in ("1", "2")] == ["a2", "a2"]
    assert live.tracks["1"]["Artist"] == "A2"


def test_batch_route_writes_a_repeated_id_once(facade, master, auth_token) -> None:
    r = _batch(["1", "1"], {"Title": "New"}, auth_token)
    assert r.status_code == 200, r.text
    assert master.writes == [("update_content", "1")]
    assert r.json()["file_tags"] == {"1": "skipped"}


def test_rbox_failure_midway_restores_the_rows_already_written(
    facade, live, master, auth_token
) -> None:
    # Row 3's title lands, then its artist write fails: rows 1, 2 and 3 are written.
    master.hook = _fail_on("update_content_artist", "3")

    r = _batch(["1", "2", "3"], {"Title": "New", "Artist": "Somebody"}, auth_token)

    assert r.status_code == 500, r.text
    detail = r.json()["detail"]
    assert "track 3" in detail and "database is locked" in detail
    assert "3 track(s) restored" in detail
    assert master.rows == _originals()
    assert [live.tracks[n]["Title"] for n in ("1", "2", "3")] == ["T1", "T2", "T3"]
    assert [live.tracks[n]["Artist"] for n in ("1", "2", "3")] == ["A1", "A2", "A3"]
    forward = master.writes[: master.writes.index(("update_content", "3")) + 1]
    assert ("update_content_artist", "2") in forward  # row 2 really was written first


def test_rbox_failure_on_the_first_row_restores_it(facade, live, master, auth_token) -> None:
    master.hook = _fail_on("update_content_genre", "1")
    r = _batch(["1", "2"], {"Comment": "x", "Genre": "Techno"}, auth_token)
    assert r.status_code == 500, r.text
    assert master.rows == _originals()
    assert live.tracks["1"]["Comment"] == "c1"
    assert ("update_content", "2") not in master.writes  # row 2 never reached


def test_failed_restore_is_named_in_the_error(facade, live, master, auth_token) -> None:
    calls: list[tuple[str, str]] = []

    def hook(method: str, tid: str) -> None:
        calls.append((method, tid))
        if (method, tid) == ("update_content_artist", "2"):
            raise RuntimeError("database is locked")
        if (method, tid) == ("update_content", "1") and calls.count((method, tid)) == 2:
            raise RuntimeError("disk I/O error")  # the restore of row 1

    master.hook = hook

    r = _batch(["1", "2"], {"Title": "New", "Artist": "Somebody"}, auth_token)

    assert r.status_code == 500, r.text
    assert "Could not restore track(s) 1" in r.json()["detail"]
    assert master.rows["2"] == _row("2")
    assert live.tracks["2"]["Title"] == "T2"
    assert master.rows["1"]["title"] == "New"  # master.db still holds the edit ...
    assert live.tracks["1"]["Title"] == "New"  # ... and the cache says so


def test_live_backend_raises_track_write_failed(facade, master) -> None:
    master.hook = _fail_on("update_content", "2")
    with pytest.raises(TrackWriteFailed) as exc:
        facade.update_tracks_metadata(["1", "2"], {"Rating": 5})
    assert exc.value.track_id == "2"
    assert exc.value.restored == ["2", "1"]
    assert exc.value.unrestored == []
    assert master.rows == _originals()


def test_track_route_rbox_failure_restores_the_row(facade, live, master, auth_token) -> None:
    master.hook = _fail_on("update_content_genre", "1")
    r = _req("POST", "/api/track/1", {"Comment": "x", "Genre": "Techno"}, auth_token)
    assert r.status_code == 500, r.text
    assert master.rows["1"] == _row("1")
    assert live.tracks["1"]["Comment"] == "c1"


def test_restore_drops_a_cache_field_the_track_did_not_have(facade, live, master) -> None:
    del live.tracks["1"]["Album"]
    master.hook = _fail_on("update_content_album", "2")
    with pytest.raises(TrackWriteFailed):
        facade.update_tracks_metadata(["1", "2"], {"Album": "New"})
    assert "Album" not in live.tracks["1"]
    assert master.rows["1"]["album_id"] is None
