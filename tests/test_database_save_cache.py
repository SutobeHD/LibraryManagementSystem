"""Perf contracts of `app/database.py`: cached settings read + coalesced XML saves.

- ``RekordboxDB.tracks`` re-reads ``settings.json`` only when the file changed on
  disk, and memoises the hide-streaming filtered view.
- XML-mode mutations mark the library dirty; one debounced write replaces the
  full-file rewrite per mutation. Explicit saves, reads of ``xml_path``, loads,
  unloads and the exit flush still see a flushed file.
- The written bytes are pinned against the pre-change implementation.
"""

from __future__ import annotations

import hashlib
import itertools
import os
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

# app.database -> app.live_database -> rbox (not installed on Linux CI).
pytest.importorskip("rbox", reason="pyrekordbox not installed on this platform")

import app.database as dbmod
from app.database import RekordboxDB, RekordboxXMLDB, flush_pending_saves
from app.services import SettingsManager

# sha256 + size of the scenario file written by app/database.py at 3dcd5bc, before
# saves were coalesced (one full rewrite per mutation).
_PRE_CHANGE_SHA256 = "30e4bd1b7f7e509da802d54cc1e3316fdded8a244940da52f9421c3c4bde5711"
_PRE_CHANGE_SIZE = 8648


def _wait_until(cond: Callable[[], bool], timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.01)
    return cond()


# ---------------------------------------------------------------------------
# settings.json cache
# ---------------------------------------------------------------------------


@pytest.fixture
def settings_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cfg = tmp_path / "settings.json"
    monkeypatch.setattr(SettingsManager, "CONFIG", cfg)
    return cfg


@pytest.fixture
def load_calls(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls: list[int] = []
    original = SettingsManager.load

    def counting_load() -> dict[str, Any]:
        calls.append(1)
        return original()

    monkeypatch.setattr(SettingsManager, "load", counting_load)
    return calls


def _write_settings(cfg: Path, hide: bool, mtime_ns: int | None = None) -> None:
    # "true " and "false" have the same length: only the mtime tells them apart.
    cfg.write_text('{"hide_streaming": %s}' % ("true " if hide else "false"), encoding="utf-8")
    if mtime_ns is not None:
        os.utime(cfg, ns=(mtime_ns, mtime_ns))


def _facade(tracks: dict[str, dict[str, Any]]) -> RekordboxDB:
    db = RekordboxDB()
    db.mode = "xml"
    db.xml_db.tracks = tracks
    return db


def _two_tracks() -> dict[str, dict[str, Any]]:
    return {
        "1": {"id": "1", "path": "C:/music/local.mp3"},
        "2": {"id": "2", "path": "soundcloud:tracks/2"},
    }


class TestHideStreamingCache:
    def test_unchanged_file_is_read_at_most_once(self, settings_file, load_calls) -> None:
        _write_settings(settings_file, hide=False)
        tracks = _two_tracks()
        db = _facade(tracks)
        for _ in range(1000):
            assert db.tracks is tracks
        assert len(load_calls) <= 1

    def test_missing_file_is_read_at_most_once(self, settings_file, load_calls) -> None:
        assert not settings_file.exists()
        db = _facade(_two_tracks())
        for _ in range(1000):
            assert set(db.tracks) == {"1", "2"}
        assert len(load_calls) <= 1

    def test_flag_flips_on_first_access_after_mtime_change(self, settings_file, load_calls) -> None:
        _write_settings(settings_file, hide=False, mtime_ns=1_700_000_000_000_000_000)
        db = _facade(_two_tracks())
        assert set(db.tracks) == {"1", "2"}

        _write_settings(settings_file, hide=True, mtime_ns=1_700_000_001_000_000_000)
        assert set(db.tracks) == {"1"}

        _write_settings(settings_file, hide=False, mtime_ns=1_700_000_002_000_000_000)
        assert set(db.tracks) == {"1", "2"}
        assert len(load_calls) == 3

    def test_settings_manager_save_takes_effect_on_next_access(self, settings_file) -> None:
        SettingsManager.save({**SettingsManager.DEFAULT, "hide_streaming": False})
        db = _facade(_two_tracks())
        assert set(db.tracks) == {"1", "2"}
        SettingsManager.save({**SettingsManager.DEFAULT, "hide_streaming": True})
        assert set(db.tracks) == {"1"}


class TestFilteredTracksMemo:
    @pytest.fixture
    def strip_calls(self, monkeypatch: pytest.MonkeyPatch) -> list[int]:
        calls: list[int] = []
        original = RekordboxDB._strip_streaming

        def counting(tracks_source: Any) -> Any:
            calls.append(1)
            return original(tracks_source)

        monkeypatch.setattr(RekordboxDB, "_strip_streaming", staticmethod(counting))
        return calls

    @pytest.fixture
    def hidden(self, settings_file) -> Path:
        _write_settings(settings_file, hide=True)
        return settings_file

    def test_filtered_view_is_built_once(self, hidden, strip_calls) -> None:
        db = _facade(_two_tracks())
        first = db.tracks
        for _ in range(1000):
            assert db.tracks is first
        assert set(first) == {"1"}
        assert len(strip_calls) == 1

    def test_facade_add_and_delete_invalidate(self, hidden, tmp_path: Path) -> None:
        db = _facade(_two_tracks())
        db.xml_db.xml_path = tmp_path / "lib.xml"
        assert set(db.tracks) == {"1"}
        db.add_track({"TrackID": "3", "path": "C:/music/three.mp3"})
        assert set(db.tracks) == {"1", "3"}
        db.delete_track("1")
        assert set(db.tracks) == {"3"}
        db.xml_db._discard_pending()

    def test_path_change_invalidates(self, hidden, tmp_path: Path) -> None:
        db = _facade(_two_tracks())
        db.xml_db.xml_path = tmp_path / "lib.xml"
        assert set(db.tracks) == {"1"}
        assert db.update_track_path("2", "C:/music/downloaded.mp3") is True
        assert set(db.tracks) == {"1", "2"}

    def test_swapped_or_resized_source_invalidates(self, hidden) -> None:
        db = _facade(_two_tracks())
        assert set(db.tracks) == {"1"}
        db.xml_db.tracks["4"] = {"id": "4", "path": "C:/music/four.mp3"}  # bypasses the facade
        assert set(db.tracks) == {"1", "4"}
        db.xml_db.tracks = {"5": {"id": "5", "path": "C:/music/five.mp3"}}
        assert set(db.tracks) == {"5"}


# ---------------------------------------------------------------------------
# Coalesced XML saves
# ---------------------------------------------------------------------------


@pytest.fixture
def writes(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Every target `_write_atomically` was called with (stray writes included)."""
    seen: list[Path] = []
    original = dbmod._write_atomically

    def spy(tree: Any, target: Path) -> None:
        seen.append(Path(target))
        original(tree, target)

    monkeypatch.setattr(dbmod, "_write_atomically", spy)
    return seen


@pytest.fixture
def fake_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Distinct, repeatable millisecond ids for create_playlist / create_smart_playlist."""
    clock = itertools.count(1_700_000_000_000)
    monkeypatch.setattr(dbmod.time, "time", lambda: next(clock) / 1000.0)


@pytest.fixture
def make_xml(tmp_path: Path) -> Iterator[Callable[..., RekordboxXMLDB]]:
    made: list[RekordboxXMLDB] = []

    def factory(name: str = "lib.xml", delay: float = 60.0, max_delay: float = 60.0):
        xml = RekordboxXMLDB()
        xml.xml_path = tmp_path / name
        xml.flush_delay_s = delay
        xml.flush_max_delay_s = max_delay
        made.append(xml)
        return xml

    yield factory
    for xml in made:  # leave nothing for the atexit flush or a later test
        xml._discard_pending()


def _to(writes: list[Path], target: Path) -> int:
    return sum(1 for w in writes if w == target)


def _track(tid: str, path: str, beats: int) -> dict[str, Any]:
    return {
        "TrackID": tid,
        "Title": f"Title {tid}",
        "Artist": f"Artist {tid} feat. Other",
        "Album": "Album & Co",
        "BPM": 120.0 + int(tid),
        "Key": "8A",
        "Genre": "Techno",
        "Label": "Label <x>",
        "TotalTime": 300.5,
        "Comment": 'quote " and ünïcödé',
        "Rating": 204,
        "ColorID": "3" if tid != "3" else "",
        "path": path,
        "beatGrid": [
            {"time": round(i * 0.5, 3), "bpm": 120.0, "beat": (i % 4) + 1, "metro": "4/4"}
            for i in range(beats)
        ],
        "positionMarks": [
            {
                "Name": "Intro",
                "Type": "0",
                "Start": 1.25,
                "Num": 0,
                "Red": 255,
                "Green": 0,
                "Blue": 0,
            },
            {"Name": "", "Type": "4", "Start": 32.0, "End": 48.0, "Num": -1},
        ],
    }


def _scenario(xml: RekordboxXMLDB, after_each: Callable[[], Any] = lambda: None) -> None:
    """Fixed mutation sequence: tracks, folders, playlist edits, smart list, deletes."""

    def step(result: Any) -> Any:
        after_each()
        return result

    step(xml.add_track(_track("1", "C:/Music/a b.mp3", 64)))
    step(xml.add_track(_track("2", "/home/me/music/two.flac", 32)))
    step(xml.add_track(_track("3", "soundcloud:tracks/42", 0)))
    step(xml.add_track(_track("4", "D:/Crates/four.aiff", 16)))
    set_a = step(xml.create_playlist("Set A"))
    crates = step(xml.create_folder("Crates"))
    nested = step(xml.create_playlist("Nested", parent_id=crates["ID"]))
    for tid in ("1", "2", "3", "4"):
        step(xml.add_track_to_playlist(set_a["ID"], tid))
    for tid in ("4", "2"):
        step(xml.add_track_to_playlist(nested["ID"], tid))
    step(xml.add_track_to_playlist(set_a["ID"], "2"))  # duplicate: no-op
    step(xml.reorder_playlist_track(set_a["ID"], "4", 0))
    step(xml.remove_track_from_playlist(set_a["ID"], "3"))
    step(xml.rename_playlist(nested["ID"], "Nested Renamed"))
    step(
        xml.create_smart_playlist(
            "Fast",
            {
                "LogicalOperator": "all",
                "AutomaticUpdate": "1",
                "conditions": [
                    {
                        "Field": "8",
                        "Operator": "0",
                        "ValueLeft": "122",
                        "ValueRight": "130",
                        "ValueUnit": "0",
                    }
                ],
            },
        )
    )
    doomed = step(xml.create_playlist("Doomed"))
    step(xml.add_track_to_playlist(doomed["ID"], "1"))
    step(xml.delete_playlist(doomed["ID"]))
    step(xml.delete_track("3"))


class TestXmlBytes:
    def test_output_matches_pre_change_implementation(self, make_xml, writes, fake_clock) -> None:
        xml = make_xml()
        _scenario(xml)
        assert _to(writes, xml._xml_path) == 0, "mutations must not write on their own"
        data = Path(xml.xml_path).read_bytes()  # the read flushes
        assert _to(writes, xml._xml_path) == 1
        assert len(data) == _PRE_CHANGE_SIZE
        assert hashlib.sha256(data).hexdigest() == _PRE_CHANGE_SHA256

    def test_coalesced_equals_save_after_every_mutation(
        self, make_xml, writes, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        clock = itertools.count(1_700_000_000_000)
        monkeypatch.setattr(dbmod.time, "time", lambda: next(clock) / 1000.0)
        eager = make_xml("eager.xml")
        _scenario(eager, after_each=eager.save_xml)

        clock = itertools.count(1_700_000_000_000)
        lazy = make_xml("lazy.xml")
        _scenario(lazy)
        assert lazy.flush() is True

        assert _to(writes, eager._xml_path) > 20
        assert _to(writes, lazy._xml_path) == 1
        assert eager._xml_path.read_bytes() == lazy._xml_path.read_bytes()


class TestCoalescedSave:
    def test_hundred_mutations_write_at_most_twice(self, make_xml, writes) -> None:
        db = RekordboxDB()
        db.mode = "xml"
        xml = make_xml("hundred.xml", delay=0.2, max_delay=5.0)
        db.xml_db = xml
        pl = db.create_playlist("Imports")
        for i in range(50):  # 1 + 50 * 2 = 101 mutations, like a 50-file import
            tid = db.add_track(_track(str(i + 10), f"C:/Music/{i}.mp3", 8))
            db.add_track_to_playlist(pl["ID"], tid)
        assert _wait_until(lambda: not xml.pending_save)
        assert _wait_until(lambda: xml._flusher is None)
        assert 1 <= _to(writes, xml._xml_path) <= 2

        fresh = RekordboxXMLDB()
        assert fresh.load_xml(str(xml._xml_path))
        assert len(fresh.tracks) == 50
        assert fresh.find_playlist_by_name("Imports") is not None
        fresh._discard_pending()

    def test_explicit_save_writes_immediately(self, make_xml, writes) -> None:
        db = RekordboxDB()
        db.mode = "xml"
        xml = make_xml()
        db.xml_db = xml
        db.add_track(_track("1", "C:/Music/one.mp3", 4))
        assert _to(writes, xml._xml_path) == 0
        assert xml.pending_save

        assert db.save() is True
        assert _to(writes, xml._xml_path) == 1
        assert not xml.pending_save
        assert 'TrackID="1"' in xml._xml_path.read_text(encoding="utf-8")
        assert _wait_until(lambda: xml._flusher is None)
        assert _to(writes, xml._xml_path) == 1

    def test_reading_xml_path_flushes(self, make_xml, writes) -> None:
        xml = make_xml()
        xml.add_track(_track("1", "C:/Music/one.mp3", 4))
        path = xml.xml_path
        assert 'TrackID="1"' in path.read_text(encoding="utf-8")
        assert _to(writes, path) == 1
        assert xml.xml_path == path
        assert _to(writes, path) == 1, "a clean library must not be rewritten"

    def test_facade_xml_path_flushes(self, make_xml) -> None:
        db = RekordboxDB()
        db.mode = "xml"
        db.xml_db = make_xml()
        db.add_track(_track("1", "C:/Music/one.mp3", 4))
        assert 'TrackID="1"' in Path(db.xml_path).read_text(encoding="utf-8")

    def test_repointing_xml_path_flushes_to_old_file(self, make_xml, tmp_path: Path) -> None:
        xml = make_xml("old.xml")
        xml.add_track(_track("1", "C:/Music/one.mp3", 4))
        xml.xml_path = tmp_path / "new.xml"
        assert 'TrackID="1"' in (tmp_path / "old.xml").read_text(encoding="utf-8")
        assert not (tmp_path / "new.xml").exists()

    def test_load_library_flushes_pending_first(self, make_xml, tmp_path: Path) -> None:
        other = make_xml("other.xml")
        assert other.save_xml() is True
        db = RekordboxDB()
        db.mode = "xml"
        xml = make_xml("main.xml")
        db.xml_db = xml
        db.add_track(_track("1", "C:/Music/one.mp3", 4))
        assert db.load_library(str(other._xml_path)) is True
        assert 'TrackID="1"' in (tmp_path / "main.xml").read_text(encoding="utf-8")
        assert db.tracks == {}
        assert not xml.pending_save

    def test_unload_flushes_and_never_writes_the_empty_library(self, make_xml, writes) -> None:
        db = RekordboxDB()
        db.mode = "xml"
        xml = make_xml(delay=0.1, max_delay=0.2)
        db.xml_db = xml
        db.add_track(_track("1", "C:/Music/one.mp3", 4))
        db.unload_library()
        assert not xml.pending_save
        time.sleep(0.4)
        assert _to(writes, xml._xml_path) == 1
        assert 'TrackID="1"' in xml._xml_path.read_text(encoding="utf-8")

    def test_unload_after_failed_flush_leaves_the_file_alone(
        self, make_xml, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        db = RekordboxDB()
        db.mode = "xml"
        xml = make_xml()
        db.xml_db = xml
        db.add_track(_track("1", "C:/Music/one.mp3", 4))
        assert db.save() is True
        db.add_track(_track("2", "C:/Music/two.mp3", 4))
        original = dbmod._write_atomically

        def refuse(tree: Any, target: Path) -> None:
            raise PermissionError("locked by scanner")

        monkeypatch.setattr(dbmod, "_write_atomically", refuse)
        db.unload_library()
        monkeypatch.setattr(dbmod, "_write_atomically", original)

        assert not xml.pending_save
        flush_pending_saves()  # must not write the reset, empty collection
        text = xml._xml_path.read_text(encoding="utf-8")
        assert 'TrackID="1"' in text
        assert 'Entries="1"' in text

    def test_exit_flush_writes_pending_libraries(self, make_xml) -> None:
        xml = make_xml()
        xml.add_track(_track("1", "C:/Music/one.mp3", 4))
        flush_pending_saves()
        assert not xml.pending_save
        assert 'TrackID="1"' in xml._xml_path.read_text(encoding="utf-8")

    def test_exit_flush_gives_up_on_a_wedged_writer(self, make_xml) -> None:
        xml = make_xml()
        xml.add_track(_track("1", "C:/Music/one.mp3", 4))
        holding, release = threading.Event(), threading.Event()

        def wedged_writer() -> None:
            with dbmod.db_lock():
                holding.set()
                release.wait(5.0)

        writer = threading.Thread(target=wedged_writer)
        writer.start()
        try:
            assert holding.wait(5.0)
            started = time.monotonic()
            assert flush_pending_saves(lock_timeout=0.1) is False
            assert time.monotonic() - started < 2.0
            assert xml.pending_save
        finally:
            release.set()
            writer.join(5.0)
        flush_pending_saves()  # other suites' libraries may be dirty too: check ours only
        assert not xml.pending_save

    def test_steady_mutations_are_saved_by_the_max_delay(self, make_xml, writes) -> None:
        xml = make_xml(delay=0.5, max_delay=0.2)
        end = time.monotonic() + 1.0
        i = 0
        while time.monotonic() < end:
            xml.add_track(_track(str(i + 1), f"C:/Music/{i}.mp3", 1))
            i += 1
            time.sleep(0.02)
        assert _to(writes, xml._xml_path) >= 1

    def test_failed_write_stays_dirty_until_a_later_flush(
        self, make_xml, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        xml = make_xml(delay=0.05, max_delay=0.1)
        original = dbmod._write_atomically

        def refuse(tree: Any, target: Path) -> None:
            raise PermissionError("locked by scanner")

        monkeypatch.setattr(dbmod, "_write_atomically", refuse)
        xml.add_track(_track("1", "C:/Music/one.mp3", 4))
        assert _wait_until(lambda: xml._flusher is None)
        assert xml.pending_save, "a failed write must not mark the library clean"

        monkeypatch.setattr(dbmod, "_write_atomically", original)
        assert xml.flush() is True
        assert not xml.pending_save
        assert 'TrackID="1"' in xml._xml_path.read_text(encoding="utf-8")

    def test_mutation_during_write_keeps_library_dirty(
        self, make_xml, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        xml = make_xml()
        original = dbmod._write_atomically
        raced: list[bool] = []

        def racing_write(tree: Any, target: Path) -> None:
            if not raced:  # a change lands while the first file is being written
                raced.append(True)
                xml.tracks["late"] = _track("99", "C:/Music/late.mp3", 1)
                xml._mark_dirty()
            original(tree, target)

        monkeypatch.setattr(dbmod, "_write_atomically", racing_write)
        xml.add_track(_track("1", "C:/Music/one.mp3", 4))
        assert xml.save_xml() is True
        assert xml.pending_save, "the late change is not in the file yet"
        assert 'TrackID="late"' not in xml._xml_path.read_text(encoding="utf-8")
        assert xml.flush() is True
        assert not xml.pending_save
        assert 'TrackID="late"' in xml._xml_path.read_text(encoding="utf-8")
