"""Template reference rows do not survive a stick export (PC test 2026-11-22).

The OneLibrary template ships 14 empty-name artists, 16 albums, 1 genre and 10 keys.
They stayed in every exportLibrary.db (13 unreferenced artists, 10 unused keys on
the test stick), and a track without a key / genre / album / artist kept pointing at
one of them. The sync now deletes every template row no track uses; rbox clears the
content FKs that still pointed at it.

Real `OneLibraryUsbWriter.sync()` against a fake stick under `tmp_path`, read back
through rbox (reopened) and the export.pdb page reader.
"""

from __future__ import annotations

import gc
import struct
from pathlib import Path

import pytest

rbox = pytest.importorskip("rbox")

from app import anlz_sidecar  # noqa: E402
from tests.test_onelibrary_track_limit import (  # noqa: E402
    T_TRACKS,
    _decode_string,
    _library,
    _read_pdb,
    _sync,
)

T_GENRES, T_ARTISTS, T_KEYS = 1, 2, 5


@pytest.fixture(autouse=True)
def no_analysis(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("sync must use the sidecar, not re-analyse")

    monkeypatch.setattr(anlz_sidecar, "write_companion_anlz", boom)


def _library_with_gaps(tmp_path: Path, n: int = 20):
    source = _library(tmp_path, n)
    for i, t in enumerate(source.tracks):
        if i % 4 == 0:
            t["key"] = ""
        if i % 5 == 0:
            t["genre"] = ""
        if i % 6 == 0:
            t["album"] = ""
        if i == 3:
            t["artist"] = ""
        t["label"] = "Label A" if i % 2 else ""
    return source


def _read_refs(stick: Path) -> dict:
    db = rbox.OneLibrary(str(stick / "PIONEER" / "rekordbox" / "exportLibrary.db"))
    try:
        tables = {
            "artist": {a.id: a.name for a in db.get_artists()},
            "album": {a.id: a.name for a in db.get_albums()},
            "genre": {g.id: g.name for g in db.get_genres()},
            "key": {k.id: k.name for k in db.get_keys()},
            "label": {lab.id: lab.name for lab in db.get_labels()},
        }
        rows = {
            c.title: {
                "artist": c.artist_id,
                "album": c.album_id,
                "genre": c.genre_id,
                "key": c.key_id,
                "label": c.label_id,
            }
            for c in db.get_contents()
        }
        playlists = {p.name: len(db.get_playlist_contents(int(p.id))) for p in db.get_playlists()}
        return {"tables": tables, "rows": rows, "playlists": playlists}
    finally:
        del db
        gc.collect()


def test_no_template_rows_and_no_dangling_refs(tmp_path: Path) -> None:
    source = _library_with_gaps(tmp_path)
    stick = tmp_path / "stick"
    stick.mkdir()

    events = _sync(stick, source)
    assert events[-1]["stage"] == "complete", events[-1]
    got = _read_refs(stick)  # a fresh rbox handle: the file still opens and reads

    for table, rows in got["tables"].items():
        assert all(name for name in rows.values()), f"empty-name {table} row left: {rows}"
    tracks = {t["title"]: t for t in source.tracks}
    assert set(got["rows"]) == set(tracks)
    assert set(got["tables"]["artist"].values()) == {t["artist"] for t in source.tracks} - {""}
    assert set(got["tables"]["key"].values()) == {t["key"] for t in source.tracks} - {""}
    assert set(got["tables"]["genre"].values()) == {"Techno"}
    assert set(got["tables"]["label"].values()) == {"Label A"}
    for title, refs in got["rows"].items():
        t = tracks[title]
        for table, field in (
            ("artist", "artist"),
            ("album", "album"),
            ("genre", "genre"),
            ("key", "key"),
            ("label", "label"),
        ):
            if t[field]:
                assert got["tables"][table][refs[table]] == t[field], (title, table)
            else:
                assert refs[table] is None, (title, table, refs[table])
    assert got["playlists"] == {"All": 20, "Third": 7}


def test_export_pdb_has_only_the_libraries_rows(tmp_path: Path) -> None:
    source = _library_with_gaps(tmp_path)
    stick = tmp_path / "stick"
    stick.mkdir()
    _sync(stick, source)

    tables = _read_pdb(stick / "PIONEER" / "rekordbox" / "export.pdb")

    def count(ttype: int) -> int:
        return sum(len(rows) for rows in tables.get(ttype, []))

    assert count(T_ARTISTS) == len({t["artist"] for t in source.tracks} - {""})
    assert count(T_KEYS) == len({t["key"] for t in source.tracks} - {""})
    assert count(T_GENRES) == 1
    keys_by_title = {}
    for rows in tables[T_TRACKS]:
        for row in rows:
            offs = struct.unpack_from("<21H", row, 0x5E)
            keys_by_title[_decode_string(row, offs[17])] = struct.unpack_from("<I", row, 0x20)[0]
    for t in source.tracks:
        assert (keys_by_title[t["title"]] == 0) == (not t["key"]), t["title"]


def test_resync_over_a_cleaned_stick(tmp_path: Path) -> None:
    source = _library_with_gaps(tmp_path)
    stick = tmp_path / "stick"
    stick.mkdir()
    _sync(stick, source)

    events = _sync(stick, source)

    assert events[-1]["stage"] == "complete", events[-1]
    assert len(_read_refs(stick)["rows"]) == len(source.tracks)
