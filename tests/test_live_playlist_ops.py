"""Tests for the live-mode playlist primitives in `app/live_database.py`.

Focus: the `delete_playlist_song` arity contract. rbox takes the
`DjmdSongPlaylist` row id, not `(playlist_id, track_id)` — the old code passed
two args, raised TypeError on every call and swallowed it, so removing a track
from a playlist (and therefore reordering one) never worked in live mode.

Everything here mocks the rbox handle; no real `master.db` is opened.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytest.importorskip("rbox", reason="pyrekordbox not installed on this platform")

from app.database import RekordboxDB, _serialised
from app.live_database import LiveRekordboxDB


def _song(row_id: str, content_id: str, track_no: int = 1) -> SimpleNamespace:
    return SimpleNamespace(id=row_id, content_id=content_id, track_no=track_no)


def _playlist(pid="42", name="Artists", parent="root", attribute=1, seq=1, uuid="u-1"):
    return SimpleNamespace(
        id=pid, name=name, parent_id=parent, attribute=attribute, seq=seq, uuid=uuid
    )


@pytest.fixture
def live() -> LiveRekordboxDB:
    """A LiveRekordboxDB whose rbox handle is a mock — __init__ opens nothing."""
    db = LiveRekordboxDB("does-not-exist.db")
    db._local.conn = MagicMock()
    return db


class TestRemoveTrackFromPlaylist:
    def test_calls_delete_playlist_song_with_one_argument(self, live) -> None:
        live.db.get_playlist_songs.return_value = [
            _song("row-1", "track-aaa"),
            _song("row-2", "track-bbb"),
        ]

        assert live.remove_track_from_playlist("pl-9", "track-bbb") is True

        live.db.get_playlist_songs.assert_called_once_with("pl-9")
        # The whole point: one positional arg, and it is the ROW id — not the
        # playlist id and not the content id.
        live.db.delete_playlist_song.assert_called_once_with("row-2")

    def test_never_passes_playlist_and_track(self, live) -> None:
        live.db.get_playlist_songs.return_value = [_song("row-1", "track-aaa")]
        live.remove_track_from_playlist("pl-9", "track-aaa")
        (args, kwargs) = live.db.delete_playlist_song.call_args
        assert len(args) == 1 and not kwargs, (
            "delete_playlist_song must be called with exactly one positional arg; "
            f"got args={args!r} kwargs={kwargs!r}"
        )

    def test_returns_false_when_track_not_in_playlist(self, live) -> None:
        live.db.get_playlist_songs.return_value = [_song("row-1", "track-aaa")]

        assert live.remove_track_from_playlist("pl-9", "track-zzz") is False
        live.db.delete_playlist_song.assert_not_called()

    def test_coerces_ids_to_str_before_comparing(self, live) -> None:
        live.db.get_playlist_songs.return_value = [_song(7, 12345)]

        assert live.remove_track_from_playlist(99, 12345) is True
        live.db.delete_playlist_song.assert_called_once_with("7")

    def test_backend_error_is_contained(self, live) -> None:
        live.db.get_playlist_songs.side_effect = RuntimeError("db locked")

        assert live.remove_track_from_playlist("pl-9", "track-aaa") is False

    def test_reorder_round_trips_through_the_fixed_primitive(self, live) -> None:
        live.db.get_playlist_songs.return_value = [_song("row-1", "track-aaa")]

        assert live.reorder_playlist_track("pl-9", "track-aaa", 0) is True
        live.db.delete_playlist_song.assert_called_once_with("row-1")
        live.db.create_playlist_song.assert_called_once_with("pl-9", "track-aaa")


class TestPlaylistNode:
    def test_exposes_uuid(self, live) -> None:
        node = live._playlist_node(_playlist(uuid="7b11d4d2-382f-45c0-9bab-b50336e020fc"))
        assert node["UUID"] == "7b11d4d2-382f-45c0-9bab-b50336e020fc"

    def test_missing_uuid_is_none_not_an_error(self, live) -> None:
        pl = _playlist()
        del pl.uuid
        assert live._playlist_node(pl)["UUID"] is None

    @pytest.mark.parametrize(
        ("attribute", "expected_type"),
        [(0, "1"), (1, "0"), (4, "4"), (99, "1")],
    )
    def test_attribute_maps_to_frontend_type(self, live, attribute, expected_type) -> None:
        node = live._playlist_node(_playlist(attribute=attribute))
        assert node["Type"] == expected_type

    def test_enum_like_attribute_is_coerced(self, live) -> None:
        # rbox exposes `attribute` as a non-hashable PlaylistType enum object.
        node = live._playlist_node(_playlist(attribute=SimpleNamespace(value=1)))
        assert node["Type"] == "0"

    def test_root_parent_is_normalised(self, live) -> None:
        assert live._playlist_node(_playlist(parent="root"))["ParentID"] == "ROOT"
        assert live._playlist_node(_playlist(parent=None))["ParentID"] == "ROOT"


class TestPlaylistLookups:
    def test_get_playlist_children_delegates_and_normalises_root(self, live) -> None:
        live.db.get_playlist_children.return_value = [_playlist(pid="7", name="Boys Noize")]

        kids = live.get_playlist_children("ROOT")

        live.db.get_playlist_children.assert_called_once_with("root")
        assert kids[0]["ID"] == "7" and kids[0]["Name"] == "Boys Noize"

    def test_get_playlist_by_path_returns_node(self, live) -> None:
        live.db.get_playlist_by_path.return_value = _playlist(pid="9", name="Boys Noize")

        node = live.get_playlist_by_path(["Artists", "Boys Noize"])

        live.db.get_playlist_by_path.assert_called_once_with(["Artists", "Boys Noize"])
        assert node["ID"] == "9"

    def test_get_playlist_by_path_missing_is_none(self, live) -> None:
        live.db.get_playlist_by_path.return_value = None
        assert live.get_playlist_by_path(["Nope"]) is None

    def test_lookup_errors_are_contained(self, live) -> None:
        live.db.get_playlist_children.side_effect = RuntimeError("boom")
        live.db.get_playlist_by_path.side_effect = RuntimeError("boom")

        assert live.get_playlist_children("ROOT") == []
        assert live.get_playlist_by_path(["x"]) is None


class TestFacade:
    """`_serialised` is a decorator, not a registry — probe the wrapper instead.

    `functools.wraps` leaves `__wrapped__` on every method the facade auto-locks,
    so its presence is the observable proof that a call holds `_db_write_lock`.
    """

    def test_removal_stays_serialised(self) -> None:
        assert hasattr(RekordboxDB.remove_track_from_playlist, "__wrapped__"), (
            "remove_track_from_playlist writes to master.db — it must stay in the "
            "auto-serialised list so it holds _db_write_lock"
        )

    def test_lookup_passthroughs_exist(self) -> None:
        for name in ("get_playlist_children", "get_playlist_by_path"):
            assert hasattr(RekordboxDB, name), f"facade is missing {name}"

    def test_lookups_are_reads_not_serialised(self) -> None:
        # Reads deliberately stay outside the write lock.
        for name in ("get_playlist_children", "get_playlist_by_path"):
            assert not hasattr(getattr(RekordboxDB, name), "__wrapped__"), (
                f"{name} is a read — wrapping it in the write lock would serialise "
                "the projection's per-artist verification against every writer"
            )

    def test_facade_delegates_to_the_backend(self) -> None:
        db = RekordboxDB.__new__(RekordboxDB)
        db.mode = "live"
        db.live_db = MagicMock()
        db.live_db.get_playlist_by_path.return_value = {"ID": "3"}
        db.live_db.get_playlist_children.return_value = [{"ID": "4"}]

        assert db.get_playlist_by_path(["Artists"]) == {"ID": "3"}
        assert db.get_playlist_children("ROOT") == [{"ID": "4"}]

    def test_facade_falls_back_to_cache_without_backend_support(self) -> None:
        db = RekordboxDB.__new__(RekordboxDB)
        db.mode = "xml"
        # The XML backend has no playlist-lookup methods — the facade must walk
        # its own cached tree instead of raising.
        db.xml_db = SimpleNamespace(
            playlists=[
                {"ID": "1", "Name": "Artists", "ParentID": "ROOT"},
                {"ID": "2", "Name": "Boys Noize", "ParentID": "1"},
            ]
        )

        assert db.get_playlist_by_path(["Artists", "Boys Noize"])["ID"] == "2"
        assert db.get_playlist_by_path(["Artists", "Nope"]) is None
        assert [p["ID"] for p in db.get_playlist_children("1")] == ["2"]

    def test_facade_signatures_match_the_live_backend(self) -> None:
        for name in ("get_playlist_children", "get_playlist_by_path"):
            facade = list(inspect.signature(getattr(RekordboxDB, name)).parameters)
            live = list(inspect.signature(getattr(LiveRekordboxDB, name)).parameters)
            assert facade == live, f"{name} drifted: facade={facade} live={live}"


class TestCreatePlaylistCaching:
    def test_folder_type_comes_from_the_returned_row(self, live) -> None:
        live.db.create_playlist_folder.return_value = _playlist(pid="5", attribute=1)

        node = live.create_playlist("Artists", "ROOT", is_folder=True)

        assert node["Type"] == "0"  # "0" == folder in the frontend's vocabulary
        assert node["UUID"] == "u-1"
        assert live.playlists[-1] is node

    def test_caller_intent_wins_when_rbox_omits_the_attribute(self, live) -> None:
        row = _playlist(pid="5")
        row.attribute = None
        live.db.create_playlist_folder.return_value = row

        assert live.create_playlist("Artists", "ROOT", is_folder=True)["Type"] == "0"

    def test_root_parent_is_passed_to_rbox_as_none(self, live) -> None:
        live.db.create_playlist.return_value = _playlist(pid="6", attribute=0)

        live.create_playlist("Loose", "ROOT", is_folder=False)

        live.db.create_playlist.assert_called_once_with("Loose", None)
