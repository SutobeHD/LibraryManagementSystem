"""Perf contracts of `app/database.py`: cached settings read + memoised track view.

``RekordboxDB.tracks`` re-reads ``settings.json`` only when the file changed on
disk, and memoises the hide-streaming filtered view.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

# app.database -> app.live_database -> rbox (not installed on Linux CI).
pytest.importorskip("rbox", reason="pyrekordbox not installed on this platform")

from app.database import RekordboxDB
from app.services import SettingsManager

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
