"""Artist-Hub SoundCloud client tests (T-12 + T-13 — app/soundcloud_api.py).

Covers the hardening (typed 404, one shared paginator, 429 body parsing, no
token-keyed cache) and the four new artist endpoints.

No network: every test replaces `requests.get` with a scripted recorder, so the
suite needs no SoundCloud credentials and never leaves the process. `time.sleep`
is captured rather than executed, which is also how the 429 assertions read the
wait the client chose.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import pytest

from app.soundcloud_api import (
    SC_ARTIST_FIELDS,
    SC_TRACK_FIELDS,
    AuthExpiredError,
    CallBudget,
    NotFoundError,
    SoundCloudPlaylistAPI,
    _parse_reset_time,
    get_related_artists,
    get_user_reposts,
    get_user_tracks,
    normalize_catalogue_track,
    resolve_user,
)

TOKEN = "sc-secret-token-DO-NOT-LOG"
URN = "soundcloud:users:1234567"

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------

_NO_JSON = object()


class _FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        json_data: Any = _NO_JSON,
        text: str = "",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._json = json_data
        self.text = text
        self.headers = headers or {}

    def json(self) -> Any:
        if self._json is _NO_JSON:
            raise ValueError("No JSON object could be decoded")
        return self._json

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _Call:
    def __init__(self, url: str, headers: dict, params: dict) -> None:
        self.url = url
        self.headers = headers or {}
        self.params = params or {}


class _Recorder:
    """Returns scripted responses in order and records every request."""

    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[_Call] = []

    def __call__(self, url, headers=None, params=None, timeout=None, proxies=None):
        self.calls.append(_Call(url, headers, params))
        if not self._responses:
            raise AssertionError(f"unscripted request to {url}")
        return self._responses.pop(0)

    @property
    def urls(self) -> list[str]:
        return [c.url for c in self.calls]


def _raw_track(track_id: int = 1, **overrides: Any) -> dict:
    raw = {
        "id": track_id,
        "title": f"Track {track_id}",
        "permalink_url": f"https://soundcloud.com/boysnoize/track-{track_id}",
        "duration": 278000,
        "genre": "Techno",
        "tag_list": "techno acid",
        "access": "playable",
        "streamable": True,
        "sharing": "public",
        "downloadable": False,
        "created_at": "2026-01-02T03:04:05Z",
        "artwork_url": f"https://i1.sndcdn.com/artworks-{track_id}.jpg",
        "user": {"id": 1234567, "username": "Boys Noize"},
    }
    raw.update(overrides)
    return raw


def _raw_user(user_id: int = 1234567, **overrides: Any) -> dict:
    raw = {
        "id": user_id,
        "kind": "user",
        "username": "Boys Noize",
        "permalink": "boysnoize",
        "permalink_url": "https://soundcloud.com/boysnoize",
        "track_count": 412,
        "followers_count": 900123,
        "avatar_url": "https://i1.sndcdn.com/avatars-boysnoize.jpg",
    }
    raw.update(overrides)
    return raw


@pytest.fixture
def sleeps(monkeypatch):
    """Capture backoff/spacing waits instead of serving them."""
    recorded: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda seconds: recorded.append(seconds))
    return recorded


@pytest.fixture(autouse=True)
def _no_proxy_lookup(monkeypatch):
    """Keep the developer's settings.json out of the HTTP path."""
    monkeypatch.setattr("app.soundcloud_api._get_proxy", lambda: None)


@pytest.fixture
def http(monkeypatch):
    """Install a scripted recorder in place of requests.get."""

    def _install(responses: list[_FakeResponse]) -> _Recorder:
        recorder = _Recorder(responses)
        monkeypatch.setattr("app.soundcloud_api.requests.get", recorder)
        return recorder

    return _install


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


class TestPagination:
    def test_follows_next_href_and_stops_without_one(self, http, sleeps):
        next_href = "https://api.soundcloud.com/users/1234567/tracks?cursor=abc&limit=200"
        recorder = http(
            [
                _FakeResponse(
                    json_data={
                        "collection": [_raw_track(1), _raw_track(2)],
                        "next_href": next_href,
                    }
                ),
                _FakeResponse(json_data={"collection": [_raw_track(3)]}),
            ]
        )

        tracks = get_user_tracks(URN, TOKEN)

        assert [t["title"] for t in tracks] == ["Track 1", "Track 2", "Track 3"]
        assert len(recorder.calls) == 2
        assert recorder.urls[1] == next_href
        # next_href already carries its own query string — resending params would
        # double the cursor.
        assert recorder.calls[1].params == {}
        assert tracks.truncated is False
        assert tracks.stop_reason == ""

    def test_bare_list_response_is_a_single_page(self, http, sleeps):
        recorder = http([_FakeResponse(json_data=[_raw_track(1)])])

        tracks = get_user_tracks(URN, TOKEN)

        assert len(tracks) == 1
        assert len(recorder.calls) == 1
        assert tracks.truncated is False

    def test_max_items_truncates_and_reports_it(self, http, sleeps):
        recorder = http(
            [
                _FakeResponse(
                    json_data={
                        "collection": [_raw_track(1), _raw_track(2), _raw_track(3)],
                        "next_href": "https://api.soundcloud.com/next",
                    }
                )
            ]
        )

        tracks = get_user_tracks(URN, TOKEN, max_items=2)

        assert len(tracks) == 2
        assert tracks.truncated is True
        assert tracks.stop_reason == "max_items"
        assert len(recorder.calls) == 1

    def test_exact_max_items_without_next_page_is_not_truncated(self, http, sleeps):
        http([_FakeResponse(json_data={"collection": [_raw_track(1), _raw_track(2)]})])

        tracks = get_user_tracks(URN, TOKEN, max_items=2)

        assert len(tracks) == 2
        assert tracks.truncated is False

    def test_offset_is_never_sent(self, http, sleeps):
        recorder = http([_FakeResponse(json_data={"collection": [_raw_track(1)]})])

        get_user_tracks(URN, TOKEN)

        assert "offset" not in recorder.calls[0].params


# ---------------------------------------------------------------------------
# ToU call budget
# ---------------------------------------------------------------------------


class TestCallBudget:
    def _endless_pages(self, count: int) -> list[_FakeResponse]:
        return [
            _FakeResponse(
                json_data={
                    "collection": [_raw_track(i + 1)],
                    "next_href": f"https://api.soundcloud.com/page/{i + 2}",
                }
            )
            for i in range(count)
        ]

    def test_budget_stops_the_walk_and_reports_truncation(self, http, sleeps):
        recorder = http(self._endless_pages(5))
        budget = CallBudget(limit=2, label="artist-hub-run")

        tracks = get_user_tracks(URN, TOKEN, budget=budget)

        assert len(recorder.calls) == 2, "budget must cap the number of HTTP calls"
        assert len(tracks) == 2
        assert tracks.truncated is True
        assert tracks.stop_reason == "budget"
        assert tracks.calls_used == 2
        assert budget.used == 2
        assert budget.exhausted is True
        assert budget.remaining == 0

    def test_budget_is_shared_across_calls_in_one_run(self, http, sleeps):
        recorder = http(
            [
                _FakeResponse(json_data={"collection": [_raw_track(1)]}),
                _FakeResponse(json_data={"collection": [_raw_track(2)]}),
            ]
        )
        budget = CallBudget(limit=2)

        first = get_user_tracks(URN, TOKEN, budget=budget)
        second = get_user_reposts(URN, TOKEN, budget=budget)
        third = get_user_tracks(URN, TOKEN, budget=budget)

        assert len(first) == 1 and len(second) == 1
        assert list(third) == []
        assert third.truncated is True
        assert third.stop_reason == "budget"
        assert len(recorder.calls) == 2

    def test_unbudgeted_walk_still_stops_at_the_page_cap(self, http, sleeps, monkeypatch):
        """A self-referential next_href must not spin the sidecar forever."""
        monkeypatch.setattr("app.soundcloud_api.SC_MAX_PAGES", 3)
        recorder = http(self._endless_pages(10))

        tracks = get_user_tracks(URN, TOKEN)

        assert len(recorder.calls) == 3
        assert tracks.truncated is True
        assert tracks.stop_reason == "max_pages"

    def test_exhausted_budget_blocks_resolve_before_any_request(self, http):
        recorder = http([])
        budget = CallBudget(limit=0)

        assert resolve_user("https://soundcloud.com/boysnoize", TOKEN, budget=budget) is None
        assert recorder.calls == []


# ---------------------------------------------------------------------------
# 404 handling — the bogus "please log in again" per dead artist
# ---------------------------------------------------------------------------


class TestNotFoundVsAuth:
    def test_artist_tracks_404_raises_not_found(self, http, sleeps):
        http([_FakeResponse(status_code=404, text="not found")])

        with pytest.raises(NotFoundError):
            get_user_tracks(URN, TOKEN)

    def test_not_found_is_not_an_auth_error(self, http, sleeps):
        http([_FakeResponse(status_code=404, text="not found")])

        with pytest.raises(Exception) as excinfo:
            get_user_tracks(URN, TOKEN)

        assert not isinstance(excinfo.value, AuthExpiredError)

    def test_me_404_still_raises_auth_expired(self, http, sleeps):
        http([_FakeResponse(status_code=404, text="not found")])

        with pytest.raises(AuthExpiredError):
            SoundCloudPlaylistAPI.get_user_profile(TOKEN)

    def test_artist_401_still_raises_auth_expired(self, http, sleeps):
        http([_FakeResponse(status_code=401, text="unauthorized")])

        with pytest.raises(AuthExpiredError):
            get_user_tracks(URN, TOKEN)

    def test_related_404_degrades_to_empty_not_an_error(self, http, sleeps):
        http([_FakeResponse(status_code=404, text="not found")])

        related = get_related_artists(URN, TOKEN)

        assert list(related) == []
        assert related.stop_reason == "not_found"

    def test_resolve_404_returns_none(self, http, sleeps):
        http([_FakeResponse(status_code=404, text="not found")])

        assert resolve_user("https://soundcloud.com/gone", TOKEN) is None


# ---------------------------------------------------------------------------
# 429 — the body carries reset_time, there is no documented Retry-After
# ---------------------------------------------------------------------------


class TestRateLimitBackoff:
    def test_reset_time_is_honoured_when_retry_after_is_missing(self, http, sleeps):
        reset_at = time.time() + 42
        http(
            [
                _FakeResponse(
                    status_code=429,
                    json_data={
                        "errors": [
                            {"meta": {"rate_limit": "plays", "reset_time": reset_at}},
                        ]
                    },
                    headers={},  # SoundCloud documents no Retry-After header
                ),
                _FakeResponse(json_data={"collection": [_raw_track(1)]}),
            ]
        )

        tracks = get_user_tracks(URN, TOKEN)

        assert len(tracks) == 1
        assert sleeps, "the client must wait before retrying a 429"
        assert 40.0 <= sleeps[0] <= 42.5, f"expected ~42s from reset_time, slept {sleeps[0]}"

    def test_iso_reset_time_is_parsed(self):
        from datetime import datetime, timedelta, timezone

        reset = datetime.now(timezone.utc) + timedelta(seconds=30)
        wait = _parse_reset_time(reset.isoformat().replace("+00:00", "Z"), time.time())

        assert wait is not None
        assert 28.0 <= wait <= 31.0

    def test_plain_delta_reset_time_is_parsed(self):
        assert _parse_reset_time(12, time.time()) == 12.0

    def test_unparseable_reset_time_is_ignored(self):
        assert _parse_reset_time("soon", time.time()) is None
        assert _parse_reset_time(None, time.time()) is None

    def test_retry_after_header_wins_when_present(self, http, sleeps):
        http(
            [
                _FakeResponse(
                    status_code=429,
                    json_data={"errors": [{"meta": {"reset_time": time.time() + 900}}]},
                    headers={"Retry-After": "7"},
                ),
                _FakeResponse(json_data={"collection": [_raw_track(1)]}),
            ]
        )

        get_user_tracks(URN, TOKEN)

        assert sleeps[0] == 7.0

    def test_backoff_is_clamped(self, http, sleeps):
        http(
            [
                _FakeResponse(
                    status_code=429,
                    json_data={"errors": [{"meta": {"reset_time": time.time() + 99999}}]},
                ),
                _FakeResponse(json_data={"collection": [_raw_track(1)]}),
            ]
        )

        get_user_tracks(URN, TOKEN)

        assert sleeps[0] == 300.0


# ---------------------------------------------------------------------------
# Request shape — access=playable is the legal gate
# ---------------------------------------------------------------------------


class TestRequestShape:
    def test_user_tracks_request(self, http, sleeps):
        recorder = http([_FakeResponse(json_data={"collection": []})])

        get_user_tracks(URN, TOKEN)

        call = recorder.calls[0]
        assert call.url == f"https://api.soundcloud.com/users/{URN}/tracks"
        assert call.params["access"] == "playable"
        assert call.params["limit"] == 200
        assert call.params["linked_partitioning"] == "true"
        assert call.params["sort"] == "desc"
        assert call.headers["Authorization"] == f"OAuth {TOKEN}"

    def test_numeric_id_is_converted_to_a_urn(self, http, sleeps):
        recorder = http([_FakeResponse(json_data={"collection": []})])

        get_user_tracks(1234567, TOKEN)

        assert recorder.calls[0].url.endswith("/users/soundcloud:users:1234567/tracks")

    def test_reposts_is_a_separate_path_and_still_gates_on_access(self, http, sleeps):
        recorder = http([_FakeResponse(json_data={"collection": [_raw_track(9)]})])

        reposts = get_user_reposts(URN, TOKEN)

        assert recorder.calls[0].url == f"https://api.soundcloud.com/users/{URN}/reposts/tracks"
        assert recorder.calls[0].params["access"] == "playable"
        # `sort` is documented on /tracks only.
        assert "sort" not in recorder.calls[0].params
        assert len(reposts) == 1

    def test_likes_use_the_replacement_endpoint_not_favorites(self, http, sleeps):
        recorder = http(
            [
                _FakeResponse(json_data={"id": 1234567}),  # /me
                _FakeResponse(json_data={"collection": [_raw_track(1)]}),
            ]
        )

        likes = SoundCloudPlaylistAPI.get_likes(TOKEN)

        assert recorder.urls[1] == f"https://api.soundcloud.com/users/{URN}/likes/tracks"
        assert "favorites" not in recorder.urls[1]
        assert "offset" not in recorder.calls[1].params
        assert likes["track_count"] == 1

    def test_missing_token_raises_a_typed_auth_error_before_any_request(self, http):
        recorder = http([])

        with pytest.raises(AuthExpiredError):
            get_user_tracks(URN, "")
        with pytest.raises(AuthExpiredError):
            resolve_user("https://soundcloud.com/boysnoize", "")

        assert recorder.calls == []


# ---------------------------------------------------------------------------
# The normalised contract
# ---------------------------------------------------------------------------


class TestNormalisedContract:
    def test_exactly_the_contract_keys(self, http, sleeps):
        http(
            [
                _FakeResponse(
                    json_data={
                        "collection": [
                            _raw_track(42, waveform_url="https://…", label_name="Boysnoize Rec.")
                        ]
                    }
                )
            ]
        )

        track = get_user_tracks(URN, TOKEN)[0]

        assert set(track) == set(SC_TRACK_FIELDS)

    def test_field_values_and_types(self, http, sleeps):
        http([_FakeResponse(json_data={"collection": [_raw_track(42)]})])

        track = get_user_tracks(URN, TOKEN)[0]

        assert track["sc_id"] == "soundcloud:tracks:42"
        assert track["title"] == "Track 42"
        assert track["duration_ms"] == 278000
        assert track["uploader_urn"] == URN
        assert track["uploader_name"] == "Boys Noize"
        assert track["access"] == "playable"
        assert track["streamable"] is True
        assert track["sharing"] == "public"
        assert track["downloadable"] is False
        assert track["genre"] == "Techno"
        assert isinstance(track["duration_ms"], int)

    def test_uploader_urn_survives_a_urn_shaped_payload(self):
        track = normalize_catalogue_track(
            _raw_track(7, user={"urn": "soundcloud:users:9988776", "username": "Someone Else"})
        )

        assert track is not None
        assert track["uploader_urn"] == "soundcloud:users:9988776"

    def test_missing_fields_become_empty_never_guessed(self):
        track = normalize_catalogue_track({"id": 5, "title": "Bare", "user": {"id": 1}})

        assert track is not None
        assert set(track) == set(SC_TRACK_FIELDS)
        assert track["access"] == "", "unknown access must not be reported as playable"
        assert track["duration_ms"] == 0
        assert track["artwork_url"] == ""
        assert track["streamable"] is False

    def test_dead_and_malformed_entries_are_dropped(self, http, sleeps):
        http(
            [
                _FakeResponse(
                    json_data={
                        "collection": [
                            _raw_track(1),
                            {"id": 2, "title": "", "user": {}},  # deleted stub
                            {"title": "no id at all"},
                            "not a dict",
                        ]
                    }
                )
            ]
        )

        tracks = get_user_tracks(URN, TOKEN)

        assert [t["sc_id"] for t in tracks] == ["soundcloud:tracks:1"]

    def test_repost_envelopes_are_unwrapped(self, http, sleeps):
        http(
            [
                _FakeResponse(
                    json_data={"collection": [{"type": "track-repost", "track": _raw_track(3)}]}
                )
            ]
        )

        reposts = get_user_reposts(URN, TOKEN)

        assert len(reposts) == 1
        assert reposts[0]["sc_id"] == "soundcloud:tracks:3"


# ---------------------------------------------------------------------------
# Related artists + resolve
# ---------------------------------------------------------------------------


class TestRelatedAndResolve:
    def test_related_returns_the_ranking_fields_inline(self, http, sleeps):
        recorder = http(
            [_FakeResponse(json_data={"collection": [_raw_user(999, username="SCNTST")]})]
        )

        related = get_related_artists(URN, TOKEN)

        assert recorder.calls[0].url == f"https://api.soundcloud.com/users/{URN}/related"
        assert len(related) == 1
        assert set(related[0]) == set(SC_ARTIST_FIELDS)
        assert related[0]["urn"] == "soundcloud:users:999"
        assert related[0]["track_count"] == 412
        assert related[0]["followers_count"] == 900123

    def test_related_empty_collection_is_not_an_error(self, http, sleeps):
        http([_FakeResponse(json_data={"collection": []})])

        related = get_related_artists(URN, TOKEN)

        assert list(related) == []
        assert related.truncated is False

    def test_resolve_user_maps_the_account(self, http, sleeps):
        recorder = http([_FakeResponse(json_data=_raw_user())])

        artist = resolve_user("https://soundcloud.com/boysnoize", TOKEN)

        assert artist is not None
        assert set(artist) == set(SC_ARTIST_FIELDS)
        assert artist["urn"] == URN
        assert recorder.calls[0].params["url"] == "https://soundcloud.com/boysnoize"

    def test_resolve_user_accepts_a_bare_permalink(self, http, sleeps):
        recorder = http([_FakeResponse(json_data=_raw_user())])

        resolve_user("boysnoize", TOKEN)

        assert recorder.calls[0].params["url"] == "https://soundcloud.com/boysnoize"

    def test_resolve_user_rejects_a_non_soundcloud_host_without_calling_out(self, http):
        recorder = http([])

        with pytest.raises(ValueError):
            resolve_user("https://evil.example.com/boysnoize", TOKEN)

        assert recorder.calls == []

    def test_resolve_user_returns_none_for_a_track_url(self, http, sleeps):
        http([_FakeResponse(json_data={"kind": "track", "id": 1, "title": "x"})])

        assert resolve_user("https://soundcloud.com/boysnoize/rocket-boy", TOKEN) is None


# ---------------------------------------------------------------------------
# Secrets hygiene + the cache that had to go
# ---------------------------------------------------------------------------


class TestTokenIsNeverLogged:
    def test_no_log_record_contains_the_token(self, http, sleeps, caplog):
        caplog.set_level(logging.DEBUG, logger="app.soundcloud_api")
        http(
            [
                _FakeResponse(
                    status_code=429,
                    json_data={"errors": [{"meta": {"reset_time": time.time() + 5}}]},
                ),
                _FakeResponse(
                    json_data={
                        "collection": [_raw_track(1)],
                        "next_href": "https://api.soundcloud.com/next",
                    }
                ),
                _FakeResponse(json_data={"collection": [_raw_track(2)]}),
            ]
        )

        get_user_tracks(URN, TOKEN)

        assert caplog.records, "expected the fetch to log at all"
        for record in caplog.records:
            assert TOKEN not in record.getMessage()
            assert TOKEN not in str(record.args)
        assert TOKEN not in caplog.text

    def test_token_is_not_logged_on_the_auth_failure_path(self, http, sleeps, caplog):
        caplog.set_level(logging.DEBUG, logger="app.soundcloud_api")
        http([_FakeResponse(status_code=403, text="forbidden")])

        with pytest.raises(AuthExpiredError):
            get_user_tracks(URN, TOKEN)

        assert TOKEN not in caplog.text


class TestNoTokenKeyedCache:
    def test_repeated_fetches_hit_the_api_again(self, http, sleeps):
        recorder = http(
            [
                _FakeResponse(json_data={"collection": [_raw_track(1)]}),
                _FakeResponse(json_data={"collection": [_raw_track(1), _raw_track(2)]}),
            ]
        )

        first = get_user_tracks(URN, TOKEN)
        second = get_user_tracks(URN, TOKEN)

        assert len(first) == 1
        assert len(second) == 2, "a cache keyed on the token would hide the new upload"
        assert len(recorder.calls) == 2

    def test_playlist_fetches_are_no_longer_lru_cached(self, http, sleeps):
        recorder = http(
            [
                _FakeResponse(json_data={"id": 1234567}),
                _FakeResponse(json_data={"collection": []}),
                _FakeResponse(json_data={"id": 1234567}),
                _FakeResponse(json_data={"collection": [{"id": 5, "title": "New Set"}]}),
            ]
        )

        assert SoundCloudPlaylistAPI.get_playlists(TOKEN) == []
        assert len(SoundCloudPlaylistAPI.get_playlists(TOKEN)) == 1
        assert len(recorder.calls) == 4

    def test_cache_clear_shim_survives_for_main_py(self):
        # app/main.py calls these before every fetch; the attribute must exist.
        SoundCloudPlaylistAPI.get_playlists.cache_clear()
        SoundCloudPlaylistAPI.get_likes.cache_clear()
