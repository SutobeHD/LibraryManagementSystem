"""``POST /api/soundcloud/downloads/{sc_track_id}/names`` (artist hub T-31, Threat T18).

The Download Manager's "Übernehmen" / "Rückgängig": set Artist + Title of a track this
app downloaded, keyed by its SoundCloud id. The contracts under test:

* session-gated (threat T3): no bearer or a wrong one is 401 and nothing moves.
* every refusal happens before any write and says why: a malformed id is 400, bad names
  are 422, a track the registry never saw is 404, a row without a usable library id
  (import pending, or the historical tuple-string id) is 409, no library is 409, a
  library id that no longer resolves is 404.
* only the fields that differ are written, and the ``master.db`` write happens inside
  ``db_lock()`` (coding rule: every master.db writer holds it). ``no_change`` leaves
  library and file alone but settles the card (registry row + ``recognition.applied``).
* the library track must still be the downloaded file (threat T16), and a live write
  waits for Rekordbox to close.
* after the library write: file tags on ``POST /api/track/{tid}``'s rules (behind
  ``write_tags_to_files``, cover preserved, never a failed request), the registry row and
  every task of the track carry the new names, ``recognition.applied`` says which won.
* undo is the same call with the raw names.

No real library, no file, no network: the ``db`` facade is a recording stub, the tag
writer is a probe, the registry a throwaway file, the downloader a fresh instance.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import requests

from app import auth, database, download_registry, main
from app import soundcloud_downloader as sdl
from app.artist_store.recognizer import SUGGESTION_UNKNOWN_ARTIST_PREFIX, Recognition, Suggestion
from app.main import app
from tests.conftest import TEST_SESSION_TOKEN

SC_ID = "123456789"
LOCAL_ID = "501"
RAW_ARTIST = "Boysnoize Records"
RAW_TITLE = "Boys Noize - Starter"
BOYS = "Boys Noize"
STARTER = "Starter"
TRACK_PATH = "/music/SoundCloud/Boysnoize Records - Boys Noize - Starter.mp3"
ARTWORK_PATH = "/covers/starter.jpg"
COVER = b"\xff\xd8cover-bytes"
TASK_ID = f"sc_{SC_ID}_1700000000"
OTHER_TASK_ID = "sc_42_1700000001"


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class LockProbe:
    """Stands in for ``main.db_lock``: takes the real lock and counts how deep we are."""

    def __init__(self) -> None:
        self.depth = 0

    @contextlib.contextmanager
    def __call__(self) -> Iterator[None]:
        with database.db_lock():
            self.depth += 1
            try:
                yield
            finally:
                self.depth -= 1


class FakeLibrary:
    """The slice of ``app.database.db`` the route touches. Each write records the lock."""

    def __init__(self, lock: LockProbe) -> None:
        self._lock = lock
        self.loaded = True
        self.result: bool | Exception = True
        self.writes: list[tuple[list[str], dict[str, Any], bool]] = []
        self.tracks: dict[str, dict[str, Any]] = {
            LOCAL_ID: {
                "ID": LOCAL_ID,
                "Title": RAW_TITLE,
                "Artist": RAW_ARTIST,
                "path": TRACK_PATH,
                "Artwork": ARTWORK_PATH,
            },
            # What ``str(None)`` would name: a NULL registry id must never reach it.
            "None": {"ID": "None", "Title": "Decoy", "Artist": "Decoy", "path": "/decoy.mp3"},
        }

    refreshes = 0

    def get_track_details(self, tid: str) -> dict[str, Any] | None:
        return self.tracks.get(tid)

    def refresh_metadata(self) -> None:
        self.refreshes += 1

    def update_tracks_metadata(self, track_ids: list[str], updates: dict[str, Any]) -> bool:
        self.writes.append((list(track_ids), dict(updates), self._lock.depth > 0))
        if isinstance(self.result, Exception):
            raise self.result
        if self.result:
            for tid in track_ids:
                self.tracks[tid].update(updates)
        return self.result


class TagProbe:
    """``audio_tags.write_tags`` / ``load_artwork`` without a file."""

    def __init__(self) -> None:
        self.result: bool | Exception = True
        self.calls: list[tuple[str, dict[str, Any], bytes | None]] = []
        self.artwork_reads: list[str] = []

    def write_tags(self, path: Any, updates: dict[str, Any], artwork: bytes | None = None) -> bool:
        self.calls.append((str(path), dict(updates), artwork))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    def load_artwork(self, image_path: Any) -> bytes | None:
        self.artwork_reads.append(str(image_path))
        return COVER


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _request(
    method: str, url: str, *, json: Any = None, headers: dict[str, str] | None = None
) -> httpx.Response:
    async def _go() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            return await ac.request(method, url, json=json, headers=headers)

    return asyncio.run(_go())


def _names(
    sc_id: str = SC_ID,
    headers: dict[str, str] | None = None,
    *,
    body: Any = None,
    artist: str = BOYS,
    title: str = STARTER,
) -> httpx.Response:
    payload = body if body is not None else {"artist": artist, "title": title}
    return _request(
        "POST", f"/api/soundcloud/downloads/{sc_id}/names", json=payload, headers=headers
    )


def _downloaded(sc_id: str = SC_ID, local: str | None = LOCAL_ID) -> None:
    """A registry row as the downloader leaves it; ``local=None`` = import not done yet."""
    download_registry.register_download(
        sc_track_id=sc_id, title=RAW_TITLE, artist=RAW_ARTIST, status="downloaded"
    )
    if local is not None:
        download_registry.update_analysis(sc_track_id=sc_id, local_track_id=local)


def _registry_names(sc_id: str = SC_ID) -> tuple[str, str] | None:
    record = download_registry.get_record(sc_id)
    return None if record is None else (record["artist"], record["title"])


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _sealed(monkeypatch: pytest.MonkeyPatch) -> None:
    """No device-token lookup, no network."""

    def _no_http(url: Any, *_a: Any, **_kw: Any) -> Any:
        raise AssertionError(f"a test made a real HTTP call: {url}")

    monkeypatch.setattr(auth, "paired_token_valid", lambda _token: False)
    monkeypatch.setattr(requests, "get", _no_http)


@pytest.fixture(autouse=True)
def registry_file(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(download_registry, "_REGISTRY_DB", tmp_path / "download_registry.db")
    download_registry.init_registry()


@pytest.fixture(autouse=True)
def settings(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Never the developer's settings.json; a test flips keys on the returned dict."""
    values: dict[str, Any] = {"write_tags_to_files": True}
    monkeypatch.setattr(main.SettingsManager, "load", classmethod(lambda cls: dict(values)))
    return values


@pytest.fixture(autouse=True)
def lock(monkeypatch: pytest.MonkeyPatch) -> LockProbe:
    probe = LockProbe()
    monkeypatch.setattr(main, "db_lock", probe)
    return probe


@pytest.fixture(autouse=True)
def library(monkeypatch: pytest.MonkeyPatch, lock: LockProbe) -> FakeLibrary:
    fake = FakeLibrary(lock)
    monkeypatch.setattr(main, "db", fake)
    return fake


@pytest.fixture(autouse=True)
def tags(monkeypatch: pytest.MonkeyPatch) -> TagProbe:
    probe = TagProbe()
    monkeypatch.setattr(main.audio_tags, "write_tags", probe.write_tags)
    monkeypatch.setattr(main.audio_tags, "load_artwork", probe.load_artwork)
    return probe


@pytest.fixture(autouse=True)
def downloader(monkeypatch: pytest.MonkeyPatch) -> sdl.SoundCloudDownloader:
    """The task the recognizer left behind, plus another track's task that must not move."""
    recognition = Recognition(
        raw_artist=RAW_ARTIST,
        raw_title=RAW_TITLE,
        artist=RAW_ARTIST,
        title=RAW_TITLE,
        corrections=(),
        credits=(),
        suggestion=Suggestion(BOYS, STARTER, SUGGESTION_UNKNOWN_ARTIST_PREFIX),
    )
    dl = sdl.SoundCloudDownloader()
    dl.tasks[TASK_ID] = {
        "id": TASK_ID,
        "sc_track_id": SC_ID,
        "title": RAW_TITLE,
        "artist": RAW_ARTIST,
        "status": "Completed",
        "local_track_id": LOCAL_ID,
        "recognition": recognition.as_dict(),
    }
    dl.tasks[OTHER_TASK_ID] = {
        "id": OTHER_TASK_ID,
        "sc_track_id": "42",
        "title": "Other Song",
        "artist": "Someone Else",
        "status": "Completed",
    }
    monkeypatch.setattr(main, "sc_downloader", dl)
    return dl


@pytest.fixture
def untouched(
    library: FakeLibrary, tags: TagProbe, downloader: sdl.SoundCloudDownloader
) -> Iterator[None]:
    """After the test: no library write, no tag write, registry + tasks as they were."""
    yield
    assert library.writes == []
    assert tags.calls == []
    assert library.tracks[LOCAL_ID]["Artist"] == RAW_ARTIST
    assert _registry_names() in (None, (RAW_ARTIST, RAW_TITLE))
    task = downloader.tasks[TASK_ID]
    assert (task["artist"], task["title"]) == (RAW_ARTIST, RAW_TITLE)
    assert "applied" not in task["recognition"]


# ---------------------------------------------------------------------------
# Auth — threat T3
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "headers",
    [None, {"Authorization": "Bearer not-the-session-token"}],
    ids=["no_bearer", "wrong_bearer"],
)
def test_without_the_session_it_is_401_and_nothing_moves(
    headers: dict[str, str] | None, untouched: None
) -> None:
    _downloaded()

    assert _names(headers=headers).status_code == 401


def test_an_unauthenticated_caller_learns_nothing_about_the_body(untouched: None) -> None:
    """Auth runs before body validation: a bad body without a session is 401, not 422."""
    assert _names(body={"artist": ""}).status_code == 401


# ---------------------------------------------------------------------------
# Refusals — each before any write
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sc_id",
    ["abc", "12a", "soundcloud:tracks:123", "-1", "1" * 21, "\u0661\u0662\u0663", "\u00b2"],
    ids=["letters", "mixed", "urn", "negative", "too_long", "arabic_digits", "superscript"],
)
def test_an_id_that_is_not_a_soundcloud_track_id_is_400(
    sc_id: str, auth_token: dict[str, str], untouched: None
) -> None:
    _downloaded()

    res = _names(sc_id, auth_token)

    assert res.status_code == 400
    assert "numeric" in res.json()["detail"]


def test_twenty_digits_is_still_an_id(auth_token: dict[str, str]) -> None:
    res = _names("9" * 20, auth_token)

    assert res.status_code == 404, "the length guard refused a 20-digit id"


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"artist": "", "title": STARTER}, "artist"),
        ({"artist": BOYS, "title": "   "}, "title"),
        ({"artist": BOYS, "title": "t" * 513}, "title"),
        ({"artist": "a" * 513, "title": STARTER}, "artist"),
        ({"artist": "Boys\x00Noize", "title": STARTER}, "artist"),
        ({"artist": BOYS, "title": "Star\nter"}, "title"),
        ({"artist": BOYS, "title": "Star\tter"}, "title"),
        ({"artist": "Boys\x7fNoize", "title": STARTER}, "artist"),
        ({"artist": "Boys\x85Noize", "title": STARTER}, "artist"),
        ({"artist": BOYS, "title": "Star\u2028ter"}, "title"),
        ({"artist": BOYS}, "title"),
        ({"title": STARTER}, "artist"),
        ({"artist": 7, "title": STARTER}, "artist"),
    ],
    ids=[
        "empty_artist",
        "blank_title",
        "long_title",
        "long_artist",
        "nul",
        "newline",
        "tab",
        "del",
        "c1_nel",
        "line_separator",
        "no_title",
        "no_artist",
        "number",
    ],
)
def test_names_that_cannot_be_a_tag_are_422(
    body: dict[str, Any], field: str, auth_token: dict[str, str], untouched: None
) -> None:
    _downloaded()

    res = _names(headers=auth_token, body=body)

    assert res.status_code == 422
    assert [e["field"][-1] for e in res.json()["errors"]] == [field]


def test_a_track_this_app_never_downloaded_is_404(
    auth_token: dict[str, str], untouched: None
) -> None:
    res = _names(headers=auth_token)

    assert res.status_code == 404
    assert res.json()["detail"] == "Not a track this app downloaded."


@pytest.mark.parametrize(
    "local",
    [None, "", "   ", "('502', {'bpm': 128.0})"],
    ids=["import_pending", "empty", "blank", "tuple_string"],
)
def test_a_row_without_a_usable_library_id_is_409(
    local: str | None, auth_token: dict[str, str], untouched: None
) -> None:
    _downloaded(local=local)

    res = _names(headers=auth_token)

    assert res.status_code == 409
    assert res.json()["detail"].startswith("Not in the library yet")
    assert download_registry.get_record(SC_ID)["local_track_id"] == local


def test_a_padded_library_id_reads_as_the_catalogue_reads_it(
    library: FakeLibrary, auth_token: dict[str, str]
) -> None:
    """Same token rule as ``download_registry.local_track_ids`` (the "downloaded" match)."""
    _downloaded(local=f" {LOCAL_ID} ")

    res = _names(headers=auth_token)

    assert res.status_code == 200
    assert res.json()["local_track_id"] == LOCAL_ID
    assert library.writes == [([LOCAL_ID], {"Artist": BOYS, "Title": STARTER}, True)]


def test_no_loaded_library_is_409(
    library: FakeLibrary, auth_token: dict[str, str], untouched: None
) -> None:
    _downloaded()
    library.loaded = False

    res = _names(headers=auth_token)

    assert res.status_code == 409
    assert res.json()["detail"] == "Library not loaded."


def test_a_library_id_that_no_longer_resolves_is_404(
    auth_token: dict[str, str], untouched: None
) -> None:
    _downloaded(local="999")

    res = _names(headers=auth_token)

    assert res.status_code == 404
    assert res.json()["detail"] == "That track left the library."


# ---------------------------------------------------------------------------
# The write
# ---------------------------------------------------------------------------


def test_applying_the_suggestion_moves_library_tags_registry_and_task(
    library: FakeLibrary,
    tags: TagProbe,
    downloader: sdl.SoundCloudDownloader,
    auth_token: dict[str, str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    _downloaded()
    other_before = dict(downloader.tasks[OTHER_TASK_ID])

    with caplog.at_level(logging.INFO, logger=main.logger.name):
        res = _names(headers=auth_token)

    assert res.status_code == 200
    assert res.json() == {
        "status": "ok",
        "sc_track_id": SC_ID,
        "local_track_id": LOCAL_ID,
        "artist": BOYS,
        "title": STARTER,
        "fields": ["Artist", "Title"],
        "file_tags": "written",
    }
    # One master.db write, the changed fields only, inside db_lock().
    assert library.writes == [([LOCAL_ID], {"Artist": BOYS, "Title": STARTER}, True)]
    # The file follows, cover kept.
    assert tags.calls == [(TRACK_PATH, {"Artist": BOYS, "Title": STARTER}, COVER)]
    assert tags.artwork_reads == [ARTWORK_PATH]
    assert _registry_names() == (BOYS, STARTER)
    task = downloader.tasks[TASK_ID]
    assert (task["artist"], task["title"]) == (BOYS, STARTER)
    assert task["recognition"]["applied"] == {"artist": BOYS, "title": STARTER}
    # The recognizer's own answer stays readable for the undo.
    assert (task["recognition"]["raw_artist"], task["recognition"]["raw_title"]) == (
        RAW_ARTIST,
        RAW_TITLE,
    )
    assert task["recognition"]["suggestion"]["artist"] == BOYS
    assert downloader.tasks[OTHER_TASK_ID] == other_before

    lines = [r.getMessage() for r in caplog.records if "op=download_names" in r.getMessage()]
    assert len(lines) == 1
    assert f"sc_id={SC_ID} local={LOCAL_ID} fields=Artist,Title" in lines[0]
    assert TEST_SESSION_TOKEN not in caplog.text
    assert "Bearer" not in caplog.text


def test_only_the_field_that_differs_is_written(
    library: FakeLibrary, tags: TagProbe, auth_token: dict[str, str]
) -> None:
    _downloaded()
    library.tracks[LOCAL_ID]["Title"] = STARTER

    res = _names(headers=auth_token)

    assert res.status_code == 200
    assert res.json()["fields"] == ["Artist"]
    assert library.writes == [([LOCAL_ID], {"Artist": BOYS}, True)]
    assert tags.calls == [(TRACK_PATH, {"Artist": BOYS}, COVER)]
    assert _registry_names() == (BOYS, STARTER)


def test_names_are_stripped_and_512_characters_still_fit(
    library: FakeLibrary, auth_token: dict[str, str]
) -> None:
    _downloaded()
    long_title = "t" * 512

    res = _names(headers=auth_token, artist=f"  {BOYS} \n", title=long_title)

    assert res.status_code == 200
    assert (res.json()["artist"], res.json()["title"]) == (BOYS, long_title)
    assert library.writes == [([LOCAL_ID], {"Artist": BOYS, "Title": long_title}, True)]


def test_names_the_track_already_has_leave_library_and_file_but_settle_the_card(
    library: FakeLibrary,
    tags: TagProbe,
    downloader: sdl.SoundCloudDownloader,
    auth_token: dict[str, str],
) -> None:
    """The track carries these names already, so the card must stop offering them."""
    _downloaded()

    res = _names(headers=auth_token, artist=RAW_ARTIST, title=RAW_TITLE)

    assert res.status_code == 200
    assert res.json() == {
        "status": "no_change",
        "sc_track_id": SC_ID,
        "local_track_id": LOCAL_ID,
        "artist": RAW_ARTIST,
        "title": RAW_TITLE,
        "fields": [],
        "file_tags": "skipped",
    }
    assert library.writes == []
    assert tags.calls == []
    assert _registry_names() == (RAW_ARTIST, RAW_TITLE)
    assert downloader.tasks[TASK_ID]["recognition"]["applied"] == {
        "artist": RAW_ARTIST,
        "title": RAW_TITLE,
    }


def test_an_id_now_naming_another_file_is_refused(
    library: FakeLibrary, auth_token: dict[str, str], untouched: None
) -> None:
    """Threat T16: a reload handed the imported id to another recording."""
    download_registry.register_download(
        sc_track_id=SC_ID,
        title=RAW_TITLE,
        artist=RAW_ARTIST,
        file_path="/music/SoundCloud/some other file.mp3",
        status="downloaded",
    )
    download_registry.update_analysis(sc_track_id=SC_ID, local_track_id=LOCAL_ID)

    res = _names(headers=auth_token)

    assert res.status_code == 409
    assert "another file" in res.json()["detail"]


def test_the_downloaded_file_itself_is_renamed(
    library: FakeLibrary, auth_token: dict[str, str]
) -> None:
    download_registry.register_download(
        sc_track_id=SC_ID,
        title=RAW_TITLE,
        artist=RAW_ARTIST,
        file_path=TRACK_PATH,
        status="downloaded",
    )
    download_registry.update_analysis(sc_track_id=SC_ID, local_track_id=LOCAL_ID)

    assert _names(headers=auth_token).status_code == 200
    assert library.writes == [([LOCAL_ID], {"Artist": BOYS, "Title": STARTER}, True)]


@pytest.mark.parametrize(("mode", "status"), [("live", 409), ("xml", 200)])
def test_a_running_rekordbox_blocks_only_a_live_write(
    library: FakeLibrary, auth_token: dict[str, str], monkeypatch, mode: str, status: int
) -> None:
    _downloaded()
    library.mode = mode
    monkeypatch.setattr(main, "_is_rekordbox_running", lambda: True)

    res = _names(headers=auth_token)

    assert res.status_code == status
    assert (library.writes == []) is (status == 409)


def test_with_tag_writing_off_the_file_is_left_alone(
    library: FakeLibrary,
    tags: TagProbe,
    settings: dict[str, Any],
    downloader: sdl.SoundCloudDownloader,
    auth_token: dict[str, str],
) -> None:
    _downloaded()
    settings["write_tags_to_files"] = False

    res = _names(headers=auth_token)

    assert res.status_code == 200
    assert res.json()["file_tags"] == "skipped"
    assert tags.calls == []
    assert tags.artwork_reads == []
    assert library.writes == [([LOCAL_ID], {"Artist": BOYS, "Title": STARTER}, True)]
    assert _registry_names() == (BOYS, STARTER)
    assert downloader.tasks[TASK_ID]["recognition"]["applied"] == {"artist": BOYS, "title": STARTER}


@pytest.mark.parametrize(
    ("outcome", "reported"),
    [(False, "failed"), (RuntimeError("file held by Rekordbox"), "error")],
    ids=["writer_says_no", "writer_raises"],
)
def test_a_failed_tag_write_never_fails_the_request(
    outcome: bool | Exception,
    reported: str,
    library: FakeLibrary,
    tags: TagProbe,
    downloader: sdl.SoundCloudDownloader,
    auth_token: dict[str, str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The library already carries the names — a 500 here would read as "nothing changed"."""
    _downloaded()
    tags.result = outcome

    res = _names(headers=auth_token)

    assert res.status_code == 200
    assert res.json()["status"] == "ok"
    assert res.json()["file_tags"] == reported
    assert library.tracks[LOCAL_ID]["Artist"] == BOYS
    assert _registry_names() == (BOYS, STARTER)
    assert downloader.tasks[TASK_ID]["artist"] == BOYS
    if isinstance(outcome, Exception):
        assert "tag write failed" in caplog.text


def test_a_track_without_a_cover_is_tagged_without_one(
    library: FakeLibrary, tags: TagProbe, auth_token: dict[str, str]
) -> None:
    _downloaded()
    del library.tracks[LOCAL_ID]["Artwork"]

    assert _names(headers=auth_token).status_code == 200
    assert tags.artwork_reads == []
    assert tags.calls == [(TRACK_PATH, {"Artist": BOYS, "Title": STARTER}, None)]


@pytest.mark.parametrize(
    "failure", [False, RuntimeError("rbox update_content failed")], ids=["false", "raises"]
)
def test_a_failed_library_write_is_500_and_nothing_else_moves(
    failure: bool | Exception,
    library: FakeLibrary,
    tags: TagProbe,
    downloader: sdl.SoundCloudDownloader,
    auth_token: dict[str, str],
) -> None:
    _downloaded()
    library.result = failure

    res = _names(headers=auth_token)

    assert res.status_code == 500
    assert len(library.writes) == 1
    assert tags.calls == []
    assert _registry_names() == (RAW_ARTIST, RAW_TITLE)
    assert downloader.tasks[TASK_ID]["artist"] == RAW_ARTIST
    assert "applied" not in downloader.tasks[TASK_ID]["recognition"]


def test_undo_puts_the_raw_names_back_everywhere(
    library: FakeLibrary,
    tags: TagProbe,
    downloader: sdl.SoundCloudDownloader,
    auth_token: dict[str, str],
) -> None:
    _downloaded()
    assert _names(headers=auth_token).status_code == 200
    recognition = downloader.tasks[TASK_ID]["recognition"]

    res = _names(
        headers=auth_token, artist=recognition["raw_artist"], title=recognition["raw_title"]
    )

    assert res.status_code == 200
    assert res.json()["fields"] == ["Artist", "Title"]
    assert library.writes[-1] == ([LOCAL_ID], {"Artist": RAW_ARTIST, "Title": RAW_TITLE}, True)
    assert (library.tracks[LOCAL_ID]["Artist"], library.tracks[LOCAL_ID]["Title"]) == (
        RAW_ARTIST,
        RAW_TITLE,
    )
    assert tags.calls[-1] == (TRACK_PATH, {"Artist": RAW_ARTIST, "Title": RAW_TITLE}, COVER)
    assert _registry_names() == (RAW_ARTIST, RAW_TITLE)
    task = downloader.tasks[TASK_ID]
    assert (task["artist"], task["title"]) == (RAW_ARTIST, RAW_TITLE)
    assert task["recognition"]["applied"] == {"artist": RAW_ARTIST, "title": RAW_TITLE}
    assert task["recognition"]["suggestion"]["artist"] == BOYS, "the suggestion is offered again"


@pytest.mark.parametrize(
    ("artist", "title", "refreshes"),
    [(BOYS, STARTER, 1), (RAW_ARTIST, STARTER, 0), (RAW_ARTIST, RAW_TITLE, 0)],
    ids=["artist_changed", "title_only", "no_change"],
)
def test_a_new_artist_name_refreshes_the_artist_list(
    library: FakeLibrary, auth_token: dict[str, str], artist: str, title: str, refreshes: int
) -> None:
    """The hub and the next download's recognizer read db.artists — a cache."""
    _downloaded()

    assert _names(headers=auth_token, artist=artist, title=title).status_code == 200
    assert library.refreshes == refreshes


def test_a_failed_artist_list_refresh_does_not_fail_the_rename(
    library: FakeLibrary, auth_token: dict[str, str], monkeypatch, caplog
) -> None:
    _downloaded()

    def broken() -> None:
        raise RuntimeError("cache rebuild failed")

    monkeypatch.setattr(library, "refresh_metadata", broken)

    res = _names(headers=auth_token)

    assert res.status_code == 200
    assert library.writes == [([LOCAL_ID], {"Artist": BOYS, "Title": STARTER}, True)]
    assert "artist list refresh failed" in caplog.text
