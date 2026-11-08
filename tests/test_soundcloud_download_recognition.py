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

from app import download_registry
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


def _download_end_to_end(
    monkeypatch, tmp_path: Path, recognition: recognizer.Recognition | None
) -> dict[str, Any] | None:
    """``download()``'s 'downloading' row, then ``_do_download`` on the real registry SQL.

    Network, save path, tagging and analysis are stubbed; the registry upsert is not.
    """
    monkeypatch.setattr(download_registry, "_REGISTRY_DB", tmp_path / "download_registry.db")
    download_registry.init_registry()
    download_registry.register_download(
        sc_track_id="123",
        title="Boys Noize - Starter",
        artist="Boysnoize Records",
        status="downloading",
    )
    audio = tmp_path / "stream.mp3"
    audio.write_bytes(b"not really audio")
    dl = sdl.SoundCloudDownloader()
    dl.tasks["t1"] = {"id": "t1", "sc_track_id": "123"}
    monkeypatch.setattr(
        sdl,
        "_resolve_stream_via_transcodings",
        lambda *_a, **_kw: {"url": "https://cf-media.sndcdn.com/x.mp3", "protocol": "progressive"},
    )
    monkeypatch.setattr(sdl, "_stream_file_to_temp", lambda url, token: audio)
    monkeypatch.setattr(sdl, "_build_save_path", lambda artist, title, ext: tmp_path / f"f{ext}")
    monkeypatch.setattr(sdl, "_aiff_requested", lambda: False)
    monkeypatch.setattr(dl, "_tag_download", lambda *_a, **_kw: recognition)
    monkeypatch.setattr(dl, "_trigger_analysis_async", lambda *_a, **_kw: None)

    dl._do_download(
        task_id="t1",
        sc_track_id="123",
        sc_permalink_url="https://soundcloud.com/boysnoize-records/starter",
        title="Boys Noize - Starter",
        artist="Boysnoize Records",
        duration_ms=1000,
        downloadable=False,
        auth_token=None,
        sc_playlist_title=None,
        on_complete=None,
    )
    return download_registry.get_record("123")


def test_the_registry_row_takes_the_recognized_names(monkeypatch, tmp_path) -> None:
    """The 'downloaded' upsert keeps names; history + duplicate notice must not show SC's."""
    rec = recognizer.Recognition(
        raw_artist="Boysnoize Records",
        raw_title="Boys Noize - Starter",
        artist=BOYS,
        title="Starter",
        corrections=(recognizer.CORRECTION_KNOWN_ARTIST_PREFIX,),
        credits=(),
    )

    record = _download_end_to_end(monkeypatch, tmp_path, rec)

    assert record is not None
    assert (record["status"], record["artist"], record["title"]) == ("downloaded", BOYS, "Starter")


def test_without_a_recognition_the_registry_keeps_soundclouds_names(monkeypatch, tmp_path) -> None:
    record = _download_end_to_end(monkeypatch, tmp_path, None)

    assert record is not None
    assert (record["status"], record["artist"], record["title"]) == (
        "downloaded",
        "Boysnoize Records",
        "Boys Noize - Starter",
    )


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
