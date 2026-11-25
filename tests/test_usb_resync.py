"""Re-syncing a stick that already holds an export (PC test 2026-11-22).

Every re-sync used to leave exportLibrary.db / export.pdb on the old state while
`/api/usb/sync` answered "success": `_ensure_usb_structure` opened the SQLCipher
file with plain sqlite3, the failed connection kept it locked on Windows, the
OneLibrary writer could not replace it, and the Legacy-XML stage ended the event
stream on "complete". The diff read the stick the same way and compared against
the whole library instead of the selected playlists.

Uses the real template + rbox where the writer is involved (no hardware).
"""

from __future__ import annotations

import gc
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import usb_manager, usb_one_library
from app.usb_manager import UsbSyncEngine

rbox = pytest.importorskip("rbox")

from tests.test_onelibrary_track_limit import _library, _read_onelibrary  # noqa: E402

pytestmark = pytest.mark.usefixtures("no_analysis")


@pytest.fixture
def no_analysis(monkeypatch):
    from app import anlz_sidecar

    def boom(*_a, **_k):
        raise AssertionError("sync must use the sidecar, not re-analyse")

    monkeypatch.setattr(anlz_sidecar, "write_companion_anlz", boom)


def _sync(stick: Path, source, playlist_filter=None) -> list[dict]:
    writer = usb_one_library.OneLibraryUsbWriter(str(stick))
    return list(
        writer.sync(
            source,
            audio_copy=True,
            copy_anlz=True,
            playlist_filter=playlist_filter,
            write_pdb=True,
        )
    )


def _engine(tmp_path: Path, stick: Path) -> UsbSyncEngine:
    return UsbSyncEngine(str(tmp_path / "master.db"), str(stick))


# --- the stick database is left for the writer -------------------------------


def test_ensure_structure_leaves_an_existing_stick_db_alone(tmp_path):
    stick = tmp_path / "stick"
    engine = _engine(tmp_path, stick)
    engine.usb_db_path.parent.mkdir(parents=True)
    engine.usb_db_path.write_bytes(b"not plain sqlite")

    engine._ensure_usb_structure()

    assert engine.usb_db_path.read_bytes() == b"not plain sqlite"


def test_resync_replaces_the_stick_db_with_the_new_selection(tmp_path):
    source = _library(tmp_path, 6)
    stick = tmp_path / "stick"
    stick.mkdir()
    events = _sync(stick, source, playlist_filter=["third"])
    assert events[-1]["stage"] == "complete", events
    assert len(_read_onelibrary(stick)["rows"]) == 2  # ids[::3] of 6 tracks

    engine = _engine(tmp_path, stick)
    engine._ensure_usb_structure()
    assert len(engine._usb_library()[0]) == 2  # the diff's read must not keep the file

    events = _sync(stick, source, playlist_filter=["third", "all"])
    assert events[-1]["stage"] == "complete", events
    one = _read_onelibrary(stick)
    assert len(one["rows"]) == 6
    assert set(one["playlists"]) == {"All", "Third"}


def test_stick_reader_skips_template_placeholders(tmp_path):
    source = _library(tmp_path, 3)
    stick = tmp_path / "stick"
    stick.mkdir()
    _sync(stick, source)

    tracks, playlists = _engine(tmp_path, stick)._usb_library()
    gc.collect()

    assert sorted(t["Title"] for t in tracks.values()) == ["Track 0000", "Track 0001", "Track 0002"]
    assert set(playlists) == {"All", "Third"}
    assert all(t["BPM"] > 0 and t["Duration"] == 30 for t in tracks.values())


def test_bpm_is_rounded_not_cut(tmp_path):
    source = _library(tmp_path, 1)
    source.tracks[0]["bpm"] = 127.96
    stick = tmp_path / "stick"
    stick.mkdir()
    _sync(stick, source)

    tracks, _ = _engine(tmp_path, stick)._usb_library()
    gc.collect()
    assert [t["BPM"] for t in tracks.values()] == [12796]


def test_a_locked_stick_db_is_an_error_not_an_exception(tmp_path, monkeypatch):
    stick = tmp_path / "stick"
    stick.mkdir()
    db = stick / "PIONEER" / "rekordbox" / "exportLibrary.db"
    real_unlink = Path.unlink

    def locked(self, missing_ok=False):
        if self == db:
            raise PermissionError(32, "in use by another process")
        return real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", locked)
    events = _sync(stick, _library(tmp_path, 2))

    assert events[-1]["stage"] == "error"
    assert "in use by another program" in events[-1]["message"]


# --- a failed stage ends the whole sync on "error" ---------------------------


def _profile(stick: Path) -> dict:
    return {"device_id": "kl", "drive": str(stick), "type": "SetStick"}


@pytest.mark.parametrize("sync_type", ["playlists", "collection"])
def test_failed_onelibrary_stage_makes_the_sync_fail(tmp_path, monkeypatch, sync_type):
    stick = tmp_path / "stick"
    stick.mkdir()
    engine = _engine(tmp_path, stick)
    monkeypatch.setattr(usb_manager.UsbProfileManager, "save_profile", lambda p: p)

    def one_fails(self, profile, playlist_ids=None):
        yield {"stage": "error", "message": "OneLibrary: exportLibrary.db locked", "progress": -1}

    def legacy_ok(self, profile, playlist_ids=None):
        yield {"stage": "complete", "message": "Synced: 3 copied", "progress": 100}

    monkeypatch.setattr(UsbSyncEngine, "_sync_library_one", one_fails)
    monkeypatch.setattr(UsbSyncEngine, "_sync_library_legacy", legacy_ok)

    if sync_type == "playlists":
        events = list(engine.sync_playlists(_profile(stick), ["p1"]))
    else:
        events = list(engine.sync_collection(_profile(stick)))

    assert events[-1]["stage"] == "error"
    assert events[-1]["errors"] == ["OneLibrary: exportLibrary.db locked"]
    assert "Sync incomplete" in events[-1]["message"]


def test_clean_sync_still_ends_on_complete(tmp_path, monkeypatch):
    stick = tmp_path / "stick"
    stick.mkdir()
    engine = _engine(tmp_path, stick)
    monkeypatch.setattr(usb_manager.UsbProfileManager, "save_profile", lambda p: p)

    def ok(self, profile, playlist_ids=None):
        yield {"stage": "complete", "message": "done", "progress": 100}

    monkeypatch.setattr(UsbSyncEngine, "_sync_library_one", ok)
    monkeypatch.setattr(UsbSyncEngine, "_sync_library_legacy", ok)

    assert list(engine.sync_playlists(_profile(stick), ["p1"]))[-1]["stage"] == "complete"


# --- the diff compares the selection with the stick --------------------------


class _LocalDb:
    def __init__(self, n: int, members: dict[str, list[int]]):
        self._contents = [
            SimpleNamespace(
                id=str(1000 + i),
                title=f"Track {i:04d}",
                artist_id=f"a{i % 7}",
                album_id="",
                genre_id="",
                bpm=round((120.0 + i % 20) * 100),
                rating=0,
                color_id=0,
                key_id="",
                length=30,
                folder_path="",
                file_name_l="",
            )
            for i in range(n)
        ]
        self._artists = [SimpleNamespace(id=f"a{i}", name=f"Artist {i}") for i in range(7)]
        self._playlists = [
            SimpleNamespace(id=pid, name=pid.title(), parent_id="ROOT") for pid in members
        ]
        self._members = members

    def get_contents(self):
        return list(self._contents)

    def get_artists(self):
        return list(self._artists)

    def get_playlists(self):
        return list(self._playlists)

    def get_playlist_contents(self, pid):
        return [self._contents[i] for i in self._members[pid]]


def test_diff_after_a_playlist_sync_is_empty_for_that_selection(tmp_path, monkeypatch):
    source = _library(tmp_path, 6)
    stick = tmp_path / "stick"
    stick.mkdir()
    _sync(stick, source, playlist_filter=["third"])
    engine = _engine(tmp_path, stick)
    monkeypatch.setattr(
        engine, "_open_local_db", lambda: _LocalDb(6, {"third": [0, 3], "all": list(range(6))})
    )

    same = engine.calculate_diff(["third"])
    gc.collect()
    assert same["tracks"] == {"to_add": 0, "to_remove": 0, "to_update": 0, "unchanged": 2}
    assert same["playlists"]["to_add"] == 0
    assert same["total_local"] == 2

    more = engine.calculate_diff(["third", "all"])
    gc.collect()
    assert more["tracks"]["to_add"] == 4
    assert more["playlists"]["to_add"] == 1  # "All" is new; "Third" matched by name

    whole = engine.calculate_diff()
    gc.collect()
    assert whole["total_local"] == 6


# --- copy counter --------------------------------------------------------------


def test_files_already_on_the_stick_are_not_counted_as_copied(tmp_path):
    src = tmp_path / "a.mp3"
    src.write_bytes(b"x" * 100)
    engine = _engine(tmp_path, tmp_path / "stick")
    dest = tmp_path / "stick" / "Contents" / "a.mp3"

    assert engine._copy_into_stick(src, dest) is True
    assert engine._copy_into_stick(src, dest) is False
    assert dest.read_bytes() == src.read_bytes()


def test_diff_counts_the_folders_above_the_selection():
    playlists = {
        "root": {"ID": "root", "Name": "Libary", "ParentID": "ROOT"},
        "sets": {"ID": "sets", "Name": "Sets", "ParentID": "root"},
        "a": {"ID": "a", "Name": "reeeer", "ParentID": "sets"},
        "b": {"ID": "b", "Name": "other", "ParentID": "sets"},
        "loop": {"ID": "loop", "Name": "Loop", "ParentID": "loop"},
    }
    kept = usb_manager._with_ancestor_folders(playlists, {"a", "loop", "gone"})
    assert sorted(kept) == ["a", "loop", "root", "sets"]
