"""MusicBrainz client tests (T-22, Threat T14 — app/musicbrainz_client.py).

The client is shared by every feature that asks MusicBrainz anything, so its policy is
the load-bearing part: at most one request per second per process, a named
User-Agent on every request, one 503 retry, 404 as "nothing there", and an MBID that
is validated before it can reach a request path. No socket is opened: ``requests.get``
is replaced by a recorder.
"""

from __future__ import annotations

from itertools import pairwise

import pytest
import requests

from app import musicbrainz_client as mb

MBID = "d2f4a968-1f6e-4a4a-9376-ee2b2a50c87a"


class _Resp:
    def __init__(self, status: int, payload=None, headers=None) -> None:
        self.status_code = status
        self._payload = payload
        self.headers = headers or {}

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _Recorder:
    """Stands in for ``requests.get``; replays queued responses and logs every call."""

    def __init__(self, *responses) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def __call__(self, url, params=None, headers=None, timeout=None, proxies=None):
        self.calls.append(
            {"url": url, "params": dict(params or {}), "headers": dict(headers or {})}
        )
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def clock(monkeypatch):
    """A fake monotonic clock; ``time.sleep`` advances it instead of waiting."""
    state = {"now": 1000.0, "slept": []}

    def monotonic() -> float:
        return state["now"]

    def sleep(seconds: float) -> None:
        state["slept"].append(seconds)
        state["now"] += seconds

    monkeypatch.setattr(mb.time, "monotonic", monotonic)
    monkeypatch.setattr(mb.time, "sleep", sleep)
    monkeypatch.setattr(mb, "_last_request_at", 0.0)
    monkeypatch.setattr(mb, "_proxies", lambda: None)
    return state


def _install(monkeypatch, *responses) -> _Recorder:
    recorder = _Recorder(*responses)
    monkeypatch.setattr(mb.requests, "get", recorder)
    return recorder


def test_every_request_carries_the_named_user_agent(clock, monkeypatch) -> None:
    rec = _install(monkeypatch, _Resp(200, {"relations": []}))

    mb.artists_for_url("https://soundcloud.com/boysnoize")

    ua = rec.calls[0]["headers"]["User-Agent"]
    assert ua.startswith("MusicLibraryManager/")
    assert "github.com/SutobeHD/LibraryManagementSystem" in ua
    assert rec.calls[0]["params"]["fmt"] == "json"


def test_requests_are_spaced_at_least_the_minimum_interval(clock, monkeypatch) -> None:
    _install(monkeypatch, *[_Resp(200, {"relations": []}) for _ in range(3)])
    starts: list[float] = []
    real_wait = mb._wait_for_slot

    def recording_wait() -> None:
        real_wait()
        starts.append(clock["now"])

    monkeypatch.setattr(mb, "_wait_for_slot", recording_wait)

    for _ in range(3):
        mb.artists_for_url("https://soundcloud.com/boysnoize")

    gaps = [b - a for a, b in pairwise(starts)]
    assert gaps and all(g >= mb.MIN_INTERVAL_S for g in gaps)


def test_a_503_is_retried_once_honouring_retry_after(clock, monkeypatch) -> None:
    rec = _install(
        monkeypatch,
        _Resp(503, headers={"Retry-After": "3"}),
        _Resp(200, {"relations": []}),
    )

    assert mb.artists_for_url("https://soundcloud.com/boysnoize") == []

    assert len(rec.calls) == 2
    assert 3.0 in clock["slept"]


def test_retry_after_is_capped(clock, monkeypatch) -> None:
    _install(monkeypatch, _Resp(503, headers={"Retry-After": "3600"}), _Resp(200, {}))

    mb.artists_for_url("https://soundcloud.com/boysnoize")

    assert max(clock["slept"]) <= mb.MAX_RETRY_AFTER_S


def test_a_second_503_raises_unavailable(clock, monkeypatch) -> None:
    _install(monkeypatch, _Resp(503), _Resp(503))

    with pytest.raises(mb.MusicBrainzUnavailable):
        mb.artists_for_url("https://soundcloud.com/boysnoize")


def test_network_error_raises_unavailable(clock, monkeypatch) -> None:
    _install(monkeypatch, requests.ConnectionError("down"))

    with pytest.raises(mb.MusicBrainzUnavailable):
        mb.search_artists("Boys Noize")


def test_404_is_nothing_there(clock, monkeypatch) -> None:
    _install(monkeypatch, _Resp(404))

    assert mb.artists_for_url("https://soundcloud.com/nobody") == []


def test_non_json_is_an_error(clock, monkeypatch) -> None:
    _install(monkeypatch, _Resp(200, ValueError("not json")))

    with pytest.raises(mb.MusicBrainzError):
        mb.search_artists("Boys Noize")


def test_a_malformed_mbid_never_reaches_a_request(clock, monkeypatch) -> None:
    rec = _install(monkeypatch)

    for bad in ("../../admin", "d2f4a968", "", "D2F4A968-1F6E-4A4A-9376-EE2B2A50C87A/../x"):
        with pytest.raises(ValueError):
            mb.artist_with_urls(bad)
    assert rec.calls == []


def test_a_non_web_resource_never_reaches_a_request(clock, monkeypatch) -> None:
    rec = _install(monkeypatch)

    for bad in ("javascript:alert(1)", "file:///etc/passwd", "soundcloud.com/x"):
        with pytest.raises(ValueError):
            mb.artists_for_url(bad)
    assert rec.calls == []


def test_artists_for_url_keeps_only_artist_relations(clock, monkeypatch) -> None:
    payload = {
        "relations": [
            {
                "target-type": "artist",
                "artist": {"id": MBID, "name": "Boys Noize", "country": "DE"},
            },
            {"target-type": "label", "label": {"id": MBID, "name": "BNR"}},
            {"target-type": "artist", "artist": {"id": MBID, "name": "Boys Noize"}},
        ]
    }
    _install(monkeypatch, _Resp(200, payload))

    found = mb.artists_for_url("https://soundcloud.com/boysnoize")

    assert [a["mbid"] for a in found] == [MBID]
    assert found[0]["country"] == "DE"


def test_artist_with_urls_returns_relations(clock, monkeypatch) -> None:
    payload = {
        "id": MBID,
        "name": "Boys Noize",
        "relations": [
            {"type": "social network", "url": {"resource": "https://www.instagram.com/boysnoize/"}},
            {"type": "bandcamp", "ended": True, "url": {"resource": "https://old.bandcamp.com/"}},
            {"type": "lyrics", "url": {}},
        ],
    }
    rec = _install(monkeypatch, _Resp(200, payload))

    artist = mb.artist_with_urls(MBID.upper())

    assert rec.calls[0]["url"].endswith(f"/artist/{MBID}")
    assert rec.calls[0]["params"]["inc"] == "url-rels"
    assert artist["relations"] == [
        {"type": "social network", "url": "https://www.instagram.com/boysnoize/", "ended": False},
        {"type": "bandcamp", "url": "https://old.bandcamp.com/", "ended": True},
    ]


def test_search_escapes_lucene_syntax_and_sorts_by_score(clock, monkeypatch) -> None:
    payload = {
        "artists": [
            {"id": MBID, "name": "AC/DC", "score": 70},
            {
                "id": MBID.replace("d2", "a1"),
                "name": "AC/DC",
                "score": 100,
                "aliases": [{"name": "ACDC"}],
            },
        ]
    }
    rec = _install(monkeypatch, _Resp(200, payload))

    hits = mb.search_artists("AC/DC", limit=5)

    assert rec.calls[0]["params"]["query"] == 'artist:"AC\\/DC" OR alias:"AC\\/DC"'
    assert [h["score"] for h in hits] == [100, 70]
    assert hits[0]["aliases"] == ["ACDC"]


def test_blank_search_costs_nothing(clock, monkeypatch) -> None:
    rec = _install(monkeypatch)

    assert mb.search_artists("   ") == []
    assert rec.calls == []
