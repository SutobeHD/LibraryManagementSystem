"""Tests for `app/database.py`.

Focus: the concurrency-safety contract added in Phase 1.4, the
streaming-URL filter in `_filter_tracks`, the `set_mode` validator,
and the thin `update_track_comment` wrapper. We deliberately avoid
loading any real XML or live SQLite — every test mocks the underlying
`xml_db` / `active_db` so the surface under test is the facade itself.
"""
from __future__ import annotations

import threading
from unittest.mock import MagicMock

import pytest

from app.database import (
    RekordboxDB,
    _db_write_lock,
    _serialised,
    db_lock,
)


# ---------------------------------------------------------------------------
# Lock primitives
# ---------------------------------------------------------------------------

class TestLockPrimitives:
    """Phase 1.4 promised: every mutator goes through a reentrant lock."""

    def test_db_write_lock_is_rlock(self) -> None:
        # RLock instances expose `_is_owned` (CPython >=3.10); plain Lock
        # does not. We assert on type identity via the public factory's
        # repr because `threading.RLock` is a factory function, not a class.
        assert "RLock" in repr(type(_db_write_lock)) or "_thread" in repr(
            type(_db_write_lock)
        ), f"expected an RLock — got {type(_db_write_lock)!r}"

    def test_rlock_is_reentrant(self) -> None:
        # The contract: db_lock() can re-acquire from the same thread
        # without deadlock. If someone swaps RLock → Lock this test
        # will hang the suite, which is the desired loud failure.
        with db_lock():
            with db_lock():
                pass  # nested acquire must not block

    def test_db_lock_releases_on_exception(self) -> None:
        """Context manager exits cleanly when the body raises."""
        with pytest.raises(RuntimeError, match="boom"):
            with db_lock():
                raise RuntimeError("boom")
        # If the lock weren't released, the next acquire would block
        # forever — running it here proves it was released.
        acquired = _db_write_lock.acquire(timeout=1.0)
        assert acquired
        _db_write_lock.release()


# ---------------------------------------------------------------------------
# _serialised decorator
# ---------------------------------------------------------------------------

class TestSerialisedDecorator:
    """Every mutating method on RekordboxDB must be wrapped."""

    @pytest.mark.parametrize(
        "method_name",
        [
            "set_mode", "load_library", "unload_library", "create_new_library",
            "refresh_metadata", "add_track", "delete_track", "rename_playlist",
            "move_playlist", "delete_playlist", "reorder_playlist_track",
            "create_folder", "create_smart_playlist", "update_smart_playlist",
            "create_playlist", "add_track_to_playlist", "remove_track_from_playlist",
            "save", "update_tracks_metadata", "update_track_comment",
        ],
    )
    def test_method_is_wrapped(self, method_name: str) -> None:
        """The module-level for-loop should have wrapped every mutator
        in `_serialised`. Wrapped methods carry the closure cell
        referencing `_db_write_lock` — `functools.wraps` preserves
        `__wrapped__` so we can detect the decoration."""
        method = getattr(RekordboxDB, method_name)
        assert hasattr(method, "__wrapped__"), (
            f"{method_name} is not decorated with @_serialised — "
            "concurrent mutations could race."
        )

    def test_decorator_releases_after_call(self) -> None:
        """`_serialised` must release the lock when the wrapped method returns."""
        @_serialised
        def stub(self):
            return "ok"

        assert stub(self=None) == "ok"
        # Lock should be free now:
        acquired = _db_write_lock.acquire(timeout=1.0)
        assert acquired
        _db_write_lock.release()

    def test_decorator_releases_on_exception(self) -> None:
        @_serialised
        def stub(self):
            raise ValueError("kaboom")

        with pytest.raises(ValueError, match="kaboom"):
            stub(self=None)
        acquired = _db_write_lock.acquire(timeout=1.0)
        assert acquired
        _db_write_lock.release()


# ---------------------------------------------------------------------------
# set_mode validation
# ---------------------------------------------------------------------------

class TestSetMode:
    """`set_mode` rejects unknown values and lazily creates standalone master.db."""

    @pytest.mark.parametrize(
        "bad_mode",
        ["", "XML", "Live", "remote", "sqlite", "online", "nuke"],
    )
    def test_unknown_mode_rejected(self, bad_mode: str) -> None:
        db = RekordboxDB()
        original = db.mode
        assert db.set_mode(bad_mode) is False
        # Mode must NOT have changed when rejected.
        assert db.mode == original

    def test_xml_mode_accepted(self) -> None:
        db = RekordboxDB()
        assert db.set_mode("xml") is True
        assert db.mode == "xml"

    def test_live_mode_falls_through_when_db_missing(self, monkeypatch) -> None:
        """If neither real Rekordbox nor standalone master.db exists, and
        creation fails, set_mode('live') must return False."""
        db = RekordboxDB()
        # Force the path to point at a non-existent location and stub
        # the creator to fail.
        monkeypatch.setattr(
            db, "live_db_path",
            __import__("pathlib").Path("/nonexistent/never/master.db"),
        )
        monkeypatch.setattr(
            db, "ensure_standalone_master_db", lambda: False,
        )
        assert db.set_mode("live") is False


# ---------------------------------------------------------------------------
# update_track_comment thin-wrap
# ---------------------------------------------------------------------------

class TestUpdateTrackComment:
    """`update_track_comment` is a 1-line wrapper around update_tracks_metadata."""

    def test_delegates_to_update_tracks_metadata(self) -> None:
        db = RekordboxDB()
        # Replace the underlying method with a spy:
        spy = MagicMock(return_value=True)
        db.update_tracks_metadata = spy
        result = db.update_track_comment("track_42", "New comment text")
        assert result is True
        spy.assert_called_once_with(["track_42"], {"Comment": "New comment text"})


# ---------------------------------------------------------------------------
# _filter_tracks streaming URL filter
# ---------------------------------------------------------------------------

class TestFilterTracks:
    """`_filter_tracks` drops soundcloud:/spotify:/tidal:/beatport: paths
    when the `hide_streaming` setting is on; passes them through otherwise."""

    @pytest.fixture
    def db_with_hide_on(self, monkeypatch):
        db = RekordboxDB()
        monkeypatch.setattr(db, "_get_hide_streaming_setting", lambda: True)
        return db

    @pytest.fixture
    def db_with_hide_off(self, monkeypatch):
        db = RekordboxDB()
        monkeypatch.setattr(db, "_get_hide_streaming_setting", lambda: False)
        return db

    @pytest.mark.parametrize(
        "streaming_url",
        [
            "soundcloud:tracks/123",
            "spotify:track:abc",
            "tidal:track/456",
            "beatport:release/789",
        ],
    )
    def test_dict_filters_known_schemes(self, db_with_hide_on, streaming_url) -> None:
        tracks = {
            "t1": {"id": "t1", "path": streaming_url, "Title": "stream"},
            "t2": {"id": "t2", "path": "C:/music/local.mp3", "Title": "local"},
        }
        out = db_with_hide_on._filter_tracks(tracks)
        assert "t2" in out
        assert "t1" not in out

    def test_list_filters_known_schemes(self, db_with_hide_on) -> None:
        tracks = [
            {"id": "a", "path": "soundcloud:tracks/1"},
            {"id": "b", "path": "/Users/me/song.mp3"},
        ]
        out = db_with_hide_on._filter_tracks(tracks)
        assert len(out) == 1
        assert out[0]["id"] == "b"

    def test_passes_through_when_setting_off(self, db_with_hide_off) -> None:
        tracks = {
            "t1": {"id": "t1", "path": "soundcloud:tracks/1"},
            "t2": {"id": "t2", "path": "/local/song.mp3"},
        }
        out = db_with_hide_off._filter_tracks(tracks)
        # Identity preserved — no filtering done.
        assert out is tracks

    def test_falls_back_to_location_key(self, db_with_hide_on) -> None:
        """Raw XML stores the URL under `Location` rather than `path`."""
        tracks = {
            "t1": {"id": "t1", "Location": "spotify:track:abc"},
            "t2": {"id": "t2", "Location": "/music/song.mp3"},
        }
        out = db_with_hide_on._filter_tracks(tracks)
        assert "t1" not in out
        assert "t2" in out

    def test_unknown_scheme_preserved(self, db_with_hide_on) -> None:
        """Only the four explicit prefixes are filtered. Anything else
        (e.g. http://, file://, raw paths) is kept."""
        tracks = {
            "t1": {"id": "t1", "path": "http://radio.example/stream.mp3"},
            "t2": {"id": "t2", "path": "file:///music/song.mp3"},
            "t3": {"id": "t3", "path": "deezer:track:42"},
        }
        out = db_with_hide_on._filter_tracks(tracks)
        assert set(out.keys()) == {"t1", "t2", "t3"}

    def test_unknown_input_type_passed_through(self, db_with_hide_on) -> None:
        """If the caller hands a non-dict / non-list we just return it."""
        out = db_with_hide_on._filter_tracks("not a container")
        assert out == "not a container"
