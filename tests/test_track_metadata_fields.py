"""Track-metadata writes refuse fields and values the backend cannot store (issue K8).

``LiveRekordboxDB.update_track_metadata`` answered True for "BPM", "Key" or a typo
like "ArtistName" and wrote nothing, stored ``None`` as the string ``'None'`` and
accepted any Rating / ColorID. It now raises ``TrackFieldError`` before the row is
even read.

Every rbox handle is a mock; no real ``master.db`` is opened.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.live_database import LiveRekordboxDB
from app.track_fields import (
    LIVE_WRITABLE_FIELDS,
    InvalidTrackFieldValue,
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


def test_live_add_track_does_not_send_bpm(live, conn) -> None:
    conn.create_content.return_value = SimpleNamespace(id="1")
    tid = live.add_track({"path": "C:/a.mp3", "Title": "T", "BPM": 128.0, "Key": "Am"})
    assert tid == "1"
    assert conn.item.title == "T"
    assert "update_content" in _writes(conn)
    assert live.tracks["1"]["BPM"] == 128.0  # cached as before, never sent to master.db


def test_live_add_track_skips_missing_tags(live, conn) -> None:
    conn.create_content.return_value = SimpleNamespace(id="1")
    live.add_track({"path": "C:/a.mp3", "Title": None, "Artist": "A"})
    assert conn.item.title == "t"  # not the string 'None'
    conn.update_content_artist.assert_called_once_with("1", "A")
