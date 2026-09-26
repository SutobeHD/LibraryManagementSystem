"""Downloader hook for the artist recognizer (artist hub T-29, plan row T41).

The SoundCloud downloader asks the recognizer who a track is by between its metadata
fetch and its tag write. Pins: the file gets the recognized names, the task carries
the answer for the Download Manager, and a recognizer failure costs nothing — the tags
then say what SoundCloud says, exactly as before (Threat T19). No network: the v2
metadata fetch, the artwork fetch and the tag writer are replaced.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app import soundcloud_downloader as sdl
from app.artist_store import recognizer, registry, schema

BOYS = "Boys Noize"
LABEL_UPLOAD = {
    "title": "Boys Noize - Starter",
    "user": {"id": 7, "username": "Boysnoize Records"},
    "publisher_metadata": {},
    "genre": "Techno",
    "permalink_url": "https://soundcloud.com/boysnoize-records/starter",
}


def _close_thread_conn() -> None:
    conn = getattr(schema._local, "conn", None)
    if conn is not None:
        conn.close()
        del schema._local.conn


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(schema, "_db_path", lambda: tmp_path / "artists.db")
    monkeypatch.setattr(schema, "_initialised", False)
    _close_thread_conn()
    schema.init_db()
    yield schema
    _close_thread_conn()


@pytest.fixture(autouse=True)
def no_library(monkeypatch) -> None:
    """Whatever another test left in the global library, only the store vouches here."""
    import app.database as database

    class _Unloaded:
        loaded = False

    monkeypatch.setattr(database, "db", _Unloaded())


@pytest.fixture
def written(monkeypatch) -> list[dict[str, Any]]:
    """Every tag write, instead of touching a file."""
    from app import audio_tags

    calls: list[dict[str, Any]] = []

    def fake_write(path, updates, artwork=None):
        calls.append(dict(updates))
        return True

    monkeypatch.setattr(audio_tags, "write_tags", fake_write)
    monkeypatch.setattr(sdl, "_fetch_artwork_bytes", lambda url: None)
    return calls


@pytest.fixture
def downloader() -> sdl.SoundCloudDownloader:
    dl = sdl.SoundCloudDownloader()
    dl.tasks["t1"] = {"id": "t1", "title": "Boys Noize - Starter", "artist": "Boysnoize Records"}
    return dl


def _metadata(monkeypatch, payload: dict[str, Any] | None) -> None:
    monkeypatch.setattr(sdl, "_fetch_sc_metadata", lambda sc_id, token: payload)


def _tag(dl: sdl.SoundCloudDownloader, tmp_path: Path) -> recognizer.Recognition | None:
    return dl._tag_download("t1", tmp_path / "Starter.mp3", "123", None, None)


def test_the_file_is_tagged_with_the_recognized_names(
    monkeypatch, tmp_path, written, downloader
) -> None:
    registry.favourite_artist_by_name(BOYS)
    _metadata(monkeypatch, LABEL_UPLOAD)

    rec = _tag(downloader, tmp_path)

    assert rec is not None
    assert (written[0]["Artist"], written[0]["Title"]) == (BOYS, "Starter")
    assert written[0]["Genre"] == "Techno"
    task = downloader.tasks["t1"]
    assert (task["artist"], task["title"]) == (BOYS, "Starter")
    assert task["recognition"]["raw_artist"] == "Boysnoize Records"
    assert task["recognition"]["credits"][0]["favourite"] is True


def test_an_unknown_prefix_leaves_the_tags_and_offers_a_suggestion(
    monkeypatch, tmp_path, written, downloader
) -> None:
    _metadata(monkeypatch, LABEL_UPLOAD)

    rec = _tag(downloader, tmp_path)

    assert (written[0]["Artist"], written[0]["Title"]) == (
        "Boysnoize Records",
        "Boys Noize - Starter",
    )
    assert rec is not None and rec.suggestion is not None
    assert downloader.tasks["t1"]["recognition"]["suggestion"]["artist"] == BOYS


def test_a_recognizer_failure_keeps_soundclouds_names(
    monkeypatch, tmp_path, written, downloader, caplog
) -> None:
    registry.favourite_artist_by_name(BOYS)
    _metadata(monkeypatch, LABEL_UPLOAD)

    def broken(*_args: Any, **_kwargs: Any) -> recognizer.Recognition:
        raise RuntimeError("store unreadable")

    monkeypatch.setattr(recognizer, "recognize", broken)

    assert _tag(downloader, tmp_path) is None
    assert (written[0]["Artist"], written[0]["Title"]) == (
        "Boysnoize Records",
        "Boys Noize - Starter",
    )
    assert "recognition" not in downloader.tasks["t1"]
    assert "Artist recognition skipped" in caplog.text


def test_no_metadata_means_no_tagging_and_no_recognition(
    monkeypatch, tmp_path, written, downloader
) -> None:
    _metadata(monkeypatch, None)

    assert _tag(downloader, tmp_path) is None
    assert written == []
    assert "recognition" not in downloader.tasks["t1"]


def test_without_overrides_the_tags_are_what_they_always_were(tmp_path, written) -> None:
    sdl._apply_sc_metadata(
        tmp_path / "x.mp3",
        {"title": "Song", "user": {"username": "Uploader"}, "publisher_metadata": {}},
        None,
    )
    sdl._apply_sc_metadata(
        tmp_path / "y.mp3",
        {
            "title": "Song",
            "user": {"username": "Uploader"},
            "publisher_metadata": {"artist": "Label Artist", "release_title": "Release"},
        },
        None,
    )

    assert [(w["Artist"], w["Title"]) for w in written] == [
        ("Uploader", "Song"),
        ("Label Artist", "Release"),
    ]


@pytest.mark.parametrize("loaded", [True, False])
def test_the_library_is_consulted_only_when_loaded(monkeypatch, loaded: bool) -> None:
    import app.database as database

    class _FakeDb:
        pass

    fake = _FakeDb()
    fake.loaded = loaded
    monkeypatch.setattr(database, "db", fake)
    seen: list[Any] = []

    def spy(meta: Any, db: Any = None, **_kwargs: Any) -> str:
        seen.append(db)
        return "recognized"

    monkeypatch.setattr(recognizer, "recognize", spy)

    assert sdl._recognize_download(LABEL_UPLOAD) == "recognized"
    assert seen == [fake if loaded else None]


def test_note_names_moves_every_task_of_the_track_and_marks_what_was_applied() -> None:
    """Apply / undo from the Download Manager (artist hub T-31)."""
    rec = recognizer.Recognition(
        raw_artist="Boysnoize Records",
        raw_title="Boys Noize - Starter",
        artist="Boysnoize Records",
        title="Boys Noize - Starter",
        corrections=(),
        credits=(),
        suggestion=recognizer.Suggestion(
            BOYS, "Starter", recognizer.SUGGESTION_UNKNOWN_ARTIST_PREFIX
        ),
    ).as_dict()
    dl = sdl.SoundCloudDownloader()
    dl.tasks["a"] = {
        "id": "a",
        "sc_track_id": "123",
        "title": "x",
        "artist": "y",
        "recognition": rec,
    }
    # A later re-queue of the same track: "Skipped"/"Linked", no recognition of its own.
    dl.tasks["b"] = {"id": "b", "sc_track_id": "123", "title": "x", "artist": "y"}
    dl.tasks["c"] = {"id": "c", "sc_track_id": "1234", "title": "other", "artist": "else"}

    assert dl.note_names("123", artist=BOYS, title="Starter") == 2

    a, b, c = dl.tasks["a"], dl.tasks["b"], dl.tasks["c"]
    assert (a["artist"], a["title"]) == (BOYS, "Starter")
    assert a["recognition"]["applied"] == {"artist": BOYS, "title": "Starter"}
    assert a["recognition"]["suggestion"] == rec["suggestion"]
    assert a["recognition"]["raw_artist"] == "Boysnoize Records"
    # Replaced, not mutated: a serialiser already iterating the old dict sees no new key.
    assert "applied" not in rec
    assert (b["artist"], b["title"]) == (BOYS, "Starter")
    assert "recognition" not in b
    assert c == {"id": "c", "sc_track_id": "1234", "title": "other", "artist": "else"}


def test_note_names_for_a_track_without_tasks_touches_nothing() -> None:
    dl = sdl.SoundCloudDownloader()
    dl.tasks["a"] = {"id": "a", "sc_track_id": "123", "title": "x", "artist": "y"}

    assert dl.note_names("999", artist=BOYS, title="Starter") == 0
    assert dl.tasks["a"] == {"id": "a", "sc_track_id": "123", "title": "x", "artist": "y"}
