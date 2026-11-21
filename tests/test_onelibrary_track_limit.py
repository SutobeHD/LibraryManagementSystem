"""B9 regression: a USB sync writes EVERY selected track, not just the 16 template slots.

Runs the full `OneLibraryUsbWriter.sync()` against a fake stick under `tmp_path`
(tiny fake audio files, one shared ANLZ sidecar trio, PDB on) and reads both
databases back: exportLibrary.db through rbox, export.pdb through the small
page reader below. Needs rbox + `app/templates/exportLibrary_template.db`; no
hardware.
"""

from __future__ import annotations

import gc
import shutil
import struct
from pathlib import Path

import pytest

rbox = pytest.importorskip("rbox")

from app import anlz_sidecar, usb_one_library  # noqa: E402
from app.usb_one_library import OneLibraryUsbWriter  # noqa: E402
from tests.test_anlz_usb_export import _source_trio  # noqa: E402

PAGE = 4096
T_TRACKS, T_PLAYLISTS, T_PL_ENTRIES = 0, 7, 8


class _Source:
    mode = "xml"

    def __init__(self, tracks: list[dict], playlists: list[dict], sidecar: Path):
        self.tracks, self.playlists, self.sidecar = tracks, playlists, sidecar

    def iter_tracks(self):
        return iter(self.tracks)

    def iter_playlists(self):
        return iter(self.playlists)

    def get_playlist_track_ids(self, pid):
        return next((p["track_ids"] for p in self.playlists if p["id"] == pid), [])

    def get_anlz_sidecar_dir(self, track):
        return self.sidecar


@pytest.fixture
def no_analysis(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("sync must use the sidecar, not re-analyse")

    monkeypatch.setattr(anlz_sidecar, "write_companion_anlz", boom)


def _library(tmp_path: Path, n: int) -> _Source:
    music = tmp_path / "music"
    music.mkdir()
    tracks = []
    for i in range(n):
        audio = music / f"track_{i:04d}.mp3"
        audio.write_bytes(b"\xff\xfb" + i.to_bytes(4, "little") + b"\0" * 64)
        tracks.append(
            {
                "id": str(1000 + i),
                "title": f"Track {i:04d}",
                "artist": f"Artist {i % 7}",
                "album": f"Album {i % 5}",
                "genre": "Techno",
                "key": f"{(i % 12) + 1}A",
                "label": "",
                "bpm": 120.0 + (i % 20),
                "duration_ms": 30000,
                "path": str(audio),
            }
        )
    ids = [t["id"] for t in tracks]
    playlists = [
        # Reversed so the test can tell "kept order" from "id order".
        {"id": "all", "name": "All", "parent_id": "ROOT", "type": "1", "track_ids": ids[::-1]},
        {"id": "third", "name": "Third", "parent_id": "ROOT", "type": "1", "track_ids": ids[::3]},
    ]
    sidecar = tmp_path / "side"
    _source_trio(sidecar)
    return _Source(tracks, playlists, sidecar)


def _sync(stick: Path, source: _Source) -> list[dict]:
    writer = OneLibraryUsbWriter(str(stick))
    return list(writer.sync(source, audio_copy=True, copy_anlz=True, write_pdb=True))


def _read_onelibrary(stick: Path) -> dict:
    db = rbox.OneLibrary(str(stick / "PIONEER" / "rekordbox" / "exportLibrary.db"))
    try:
        contents = {c.id: c for c in db.get_contents()}
        rows = {
            cid: {
                "title": c.title,
                "path": c.path,
                "anlz": c.analysis_data_file_path,
                "image_id": c.image_id,
            }
            for cid, c in contents.items()
        }
        playlists = {
            p.name: [int(pc.id) for pc in db.get_playlist_contents(int(p.id))]
            for p in db.get_playlists()
        }
        number_of_contents = db.get_properties()[0].number_of_contents
        return {"rows": rows, "playlists": playlists, "number_of_contents": number_of_contents}
    finally:
        del db
        gc.collect()


def _decode_string(row: bytes, off: int) -> str:
    lk = row[off]
    if lk & 1:
        return row[off + 1 : off + (lk >> 1)].decode("ascii")
    length = struct.unpack_from("<H", row, off + 1)[0]
    body = row[off + 4 : off + length]
    if lk == 0x90:
        return body.decode("utf-16-le").rstrip("\x00")
    return body.decode("ascii")


def _read_pdb(path: Path) -> dict[int, list[list[bytes]]]:
    """Data-page rows per table type, walking each table's page chain."""
    data = path.read_bytes()
    n_tables = struct.unpack_from("<I", data, 0x08)[0]
    tables: dict[int, list[list[bytes]]] = {}
    for t in range(n_tables):
        ttype, empty, first, _last = struct.unpack_from("<IIII", data, 0x1C + 16 * t)
        pages: list[list[bytes]] = []
        cur, seen = first, set()
        while cur != empty and cur not in seen and (cur + 1) * PAGE <= len(data):
            seen.add(cur)
            page = data[cur * PAGE : (cur + 1) * PAGE]
            if not page[0x1B] & 0x40:  # data page
                num_rows = int.from_bytes(page[0x18:0x1B], "little") >> 13
                rows = []
                for r in range(num_rows):
                    g, i = divmod(r, 16)
                    block = PAGE - (g + 1) * 36
                    present = struct.unpack_from("<H", page, block + 32)[0]
                    assert present >> i & 1, f"table {ttype} page {cur} row {r} not present"
                    off = struct.unpack_from("<H", page, block + 30 - 2 * i)[0]
                    rows.append(page[0x28 + off :])
                pages.append(rows)
            cur = struct.unpack_from("<I", page, 0x0C)[0]
        tables[ttype] = pages
    return tables


def _pdb_tracks(tables) -> dict[int, dict]:
    out = {}
    for rows in tables[T_TRACKS]:
        for row in rows:
            offs = struct.unpack_from("<21H", row, 0x5E)
            out[struct.unpack_from("<I", row, 0x48)[0]] = {
                "title": _decode_string(row, offs[17]),
                "path": _decode_string(row, offs[20]),
                "anlz": _decode_string(row, offs[14]),
            }
    return out


def _pdb_playlists(tables) -> dict[str, list[int]]:
    names = {}
    for rows in tables[T_PLAYLISTS]:
        for row in rows:
            names[struct.unpack_from("<I", row, 12)[0]] = _decode_string(row, 20)
    entries: dict[int, list[tuple[int, int]]] = {}
    for rows in tables[T_PL_ENTRIES]:
        for row in rows:
            idx, tid, pid = struct.unpack_from("<III", row, 0)
            entries.setdefault(pid, []).append((idx, tid))
    return {names[pid]: [tid for _, tid in sorted(e)] for pid, e in entries.items()}


def _check_export(stick: Path, source: _Source, events: list[dict]) -> None:
    n = len(source.tracks)
    assert not [e for e in events if e.get("stage") in ("error", "warning")], events
    assert events[-1]["stage"] == "complete"
    assert events[-1]["message"] == f"OneLibrary export written: {n} tracks"

    one = _read_onelibrary(stick)
    rows = one["rows"]
    assert len(rows) == n
    assert one["number_of_contents"] == n
    by_title = {r["title"]: cid for cid, r in rows.items()}
    assert sorted(by_title) == sorted(t["title"] for t in source.tracks)

    for r in rows.values():
        assert r["path"].startswith("/Contents/")
        assert (stick / r["path"].lstrip("/")).is_file()
        assert r["anlz"].startswith("/PIONEER/USBANLZ/") and r["anlz"].endswith(".DAT")
        assert (stick / r["anlz"].lstrip("/")).is_file()
    assert len({r["path"] for r in rows.values()}) == n
    assert len({r["anlz"] for r in rows.values()}) == n
    assert len({r["image_id"] for r in rows.values()}) == n

    cid_of = {t["id"]: by_title[t["title"]] for t in source.tracks}
    expected = {p["name"]: [cid_of[t] for t in p["track_ids"]] for p in source.playlists}
    assert one["playlists"] == expected

    tables = _read_pdb(stick / "PIONEER" / "rekordbox" / "export.pdb")
    pdb_tracks = _pdb_tracks(tables)
    assert set(pdb_tracks) == set(rows)
    for cid, r in rows.items():
        assert pdb_tracks[cid] == {"title": r["title"], "path": r["path"], "anlz": r["anlz"]}
    assert _pdb_playlists(tables) == expected
    for pages in tables.values():
        assert all(len(rows) <= 255 for rows in pages)

    wal = stick / "PIONEER" / "rekordbox" / "exportLibrary.db-wal"
    assert not wal.exists() or wal.stat().st_size == 0


@pytest.mark.parametrize("n", [17, 100, pytest.param(1000, marks=pytest.mark.slow)])
def test_sync_writes_every_track(tmp_path, no_analysis, n):
    source = _library(tmp_path, n)
    stick = tmp_path / "stick"
    stick.mkdir()
    _check_export(stick, source, _sync(stick, source))


def test_small_sync_uses_template_slots_only(tmp_path, no_analysis):
    source = _library(tmp_path, 5)
    stick = tmp_path / "stick"
    stick.mkdir()
    _check_export(stick, source, _sync(stick, source))
    assert set(_read_onelibrary(stick)["rows"]) <= set(range(1, 17))


class _RefusingDb:
    """Real rbox handle whose `update_content` refuses — a failed slot repair."""

    def __init__(self, db):
        self._db = db

    def __getattr__(self, name):
        return getattr(self._db, name)

    def update_content(self, _slot):
        raise RuntimeError("refused")


def test_failed_slot_repair_leaves_no_broken_row(tmp_path):
    """A half-written row left behind makes every later content read fail."""
    path = tmp_path / "exportLibrary.db"
    shutil.copy2(OneLibraryUsbWriter.TEMPLATE_DB, path)
    db = rbox.OneLibrary(str(path))
    try:
        new_id = max(c.id for c in db.get_contents()) + 1
        assert OneLibraryUsbWriter._new_slot(_RefusingDb(db), 1, new_id) is None
        assert len(db.get_contents()) == 16
        slot = OneLibraryUsbWriter._new_slot(db, 1, new_id)
        assert slot is not None and slot.id == new_id
        assert slot.image_id not in {c.image_id for c in db.get_contents() if c.id != new_id}
        assert len(db.get_contents()) == 17
    finally:
        del db
        gc.collect()


def test_failed_growth_falls_back_to_template_cap(tmp_path, no_analysis, monkeypatch):
    monkeypatch.setattr(usb_one_library.OneLibraryUsbWriter, "_new_slot", lambda *_a, **_k: None)
    source = _library(tmp_path, 20)
    stick = tmp_path / "stick"
    stick.mkdir()
    events = _sync(stick, source)
    assert events[-1]["stage"] == "warning"
    assert "16/20 tracks written" in events[-1]["message"]
    one = _read_onelibrary(stick)
    assert len(one["rows"]) == 16
    assert one["number_of_contents"] == 16
    # The 4 skipped tracks open the reversed "All" playlist; the 16 written
    # ones must still be linked, in order.
    cid_of = {r["title"]: cid for cid, r in one["rows"].items()}
    titles = {t["id"]: t["title"] for t in source.tracks}
    all_ids = source.playlists[0]["track_ids"]
    assert one["playlists"]["All"] == [cid_of[titles[t]] for t in all_ids if titles[t] in cid_of]
