"""Tests for `app/soundcloud_api.py`.

Focus: the `_sc_get` HTTP wrapper's retry / auth / parse-failure
behaviour, and the `_fuzzy_match_track` similarity gate. We mock
`requests.get` via `monkeypatch.setattr` rather than pulling in the
`responses` package — the surface is small enough that a fake
Response class is cheaper than a new dev dependency.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from app.soundcloud_api import (
    AuthExpiredError,
    RateLimitError,
    SoundCloudSyncEngine,
    _sc_get,
)

# ---------------------------------------------------------------------------
# Helpers — a minimal fake of the requests.Response surface _sc_get uses
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(
        self,
        status_code: int,
        json_data: Any | None = None,
        text: str = "",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._json = json_data
        self.text = text
        self.headers = headers or {}

    def json(self) -> Any:
        if self._json is None:
            # Mimic real requests.Response.json() on un-parseable body
            raise ValueError("No JSON object could be decoded")
        return self._json

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _make_get_stub(responses: list[_FakeResponse]):
    """Return a callable that returns each response in order on successive
    calls. Tracks call count so tests can assert."""
    state = {"i": 0, "calls": []}

    def _stub(url, headers=None, params=None, timeout=None, proxies=None):
        state["calls"].append({"url": url, "params": params})
        idx = state["i"]
        state["i"] += 1
        return responses[idx]

    _stub.state = state
    return _stub


@pytest.fixture(autouse=True)
def _suppress_sleep(monkeypatch):
    """Don't actually wait during 429-backoff or network-error retries."""
    monkeypatch.setattr(time, "sleep", lambda _t: None)


# ---------------------------------------------------------------------------
# _sc_get — status-code handling
# ---------------------------------------------------------------------------

class TestSCGetStatus:
    """The HTTP helper's job is to translate SC's status codes into our
    domain errors (AuthExpiredError, RateLimitError) or to bubble JSON-
    decode failures as ValueError."""

    def test_200_returns_response(self, monkeypatch) -> None:
        stub = _make_get_stub([_FakeResponse(200, json_data={"hello": "world"})])
        monkeypatch.setattr("app.soundcloud_api.requests.get", stub)
        resp = _sc_get("http://api/test", headers={})
        assert resp.status_code == 200
        assert stub.state["i"] == 1

    def test_401_raises_auth_expired(self, monkeypatch) -> None:
        stub = _make_get_stub(
            [_FakeResponse(401, text="invalid_token")],
        )
        monkeypatch.setattr("app.soundcloud_api.requests.get", stub)
        with pytest.raises(AuthExpiredError, match="invalid or expired"):
            _sc_get("http://api/x", headers={})

    def test_403_raises_auth_expired(self, monkeypatch) -> None:
        stub = _make_get_stub([_FakeResponse(403, text="forbidden")])
        monkeypatch.setattr("app.soundcloud_api.requests.get", stub)
        with pytest.raises(AuthExpiredError):
            _sc_get("http://api/x", headers={})

    def test_404_raises_auth_expired(self, monkeypatch) -> None:
        """Root-cause-fix: SC returns 404 on /me when client_id is wrong.
        This is an auth failure, NOT a missing-resource error."""
        stub = _make_get_stub([_FakeResponse(404, text="not found")])
        monkeypatch.setattr("app.soundcloud_api.requests.get", stub)
        with pytest.raises(AuthExpiredError, match="404"):
            _sc_get("http://api/me", headers={})

    def test_429_then_200_succeeds(self, monkeypatch) -> None:
        """429 then 200 → helper should sleep (we've stubbed it) and retry."""
        stub = _make_get_stub(
            [
                _FakeResponse(429, headers={"Retry-After": "1"}),
                _FakeResponse(200, json_data={"ok": True}),
            ]
        )
        monkeypatch.setattr("app.soundcloud_api.requests.get", stub)
        resp = _sc_get("http://api/x", headers={})
        assert resp.status_code == 200
        assert stub.state["i"] == 2

    def test_429_exhausted_raises_rate_limit(self, monkeypatch) -> None:
        """Persistent 429s beyond max_retries raise RateLimitError."""
        # max_retries=1 means 2 total attempts.
        stub = _make_get_stub(
            [
                _FakeResponse(429, headers={"Retry-After": "0"}),
                _FakeResponse(429, headers={"Retry-After": "0"}),
            ]
        )
        monkeypatch.setattr("app.soundcloud_api.requests.get", stub)
        with pytest.raises(RateLimitError):
            _sc_get("http://api/x", headers={}, max_retries=1)

    def test_200_with_malformed_json_raises_value_error(
        self, monkeypatch
    ) -> None:
        """Status 200 but body isn't JSON → ValueError, not silent success."""
        stub = _make_get_stub(
            [_FakeResponse(200, json_data=None, text="<html>SC down</html>")]
        )
        monkeypatch.setattr("app.soundcloud_api.requests.get", stub)
        with pytest.raises(ValueError, match="non-JSON"):
            _sc_get("http://api/x", headers={})


# ---------------------------------------------------------------------------
# SoundCloudSyncEngine._fuzzy_match_track
# ---------------------------------------------------------------------------

class TestFuzzyMatch:
    """The matcher uses SequenceMatcher >=0.65 with an early-exit on
    normalised title equality. We pin the three failure modes that
    caused user-reported sync misses: exact name in different case,
    typos, and obvious mismatches."""

    @pytest.fixture
    def engine(self) -> SoundCloudSyncEngine:
        # The engine only touches `db.tracks` via the matcher; pass a
        # bare MagicMock so __init__ doesn't error.
        return SoundCloudSyncEngine(MagicMock())

    def test_exact_normalised_title_match(self, engine) -> None:
        local = {
            "t1": {"Title": "Song Name", "Artist": "Artist A"},
            "t2": {"Title": "Other Track", "Artist": "Someone Else"},
        }
        matched = engine._fuzzy_match_track("Song Name", "Artist A", local)
        assert matched == "t1"

    def test_case_insensitive_title(self, engine) -> None:
        local = {
            "t1": {"Title": "song name", "Artist": "artist a"},
        }
        matched = engine._fuzzy_match_track("Song Name", "Artist A", local)
        assert matched == "t1"

    def test_near_match_with_typo(self, engine) -> None:
        """One-character typo in the title should still match via SequenceMatcher."""
        local = {
            "t1": {"Title": "Velvet Shuffle", "Artist": "Some DJ"},
        }
        # SC title with extra char — well above the 0.65 ratio.
        matched = engine._fuzzy_match_track("Velvet Shuffles", "Some DJ", local)
        assert matched == "t1"

    def test_explicit_mismatch_returns_none(self, engine) -> None:
        """Totally unrelated names fall below the 0.65 cutoff."""
        local = {
            "t1": {"Title": "Velvet Shuffle", "Artist": "Some DJ"},
        }
        matched = engine._fuzzy_match_track(
            "Completely Unrelated Banger", "Other Person", local
        )
        assert matched is None

    def test_empty_local_returns_none(self, engine) -> None:
        assert engine._fuzzy_match_track("anything", "anyone", {}) is None

    def test_picks_highest_score_among_candidates(self, engine) -> None:
        """When several candidates pass the threshold, the best wins."""
        local = {
            "t1": {"Title": "Velvet Shuffle Remix", "Artist": "Bad Match"},
            "t2": {"Title": "Velvet Shuffle", "Artist": "Good Match"},
        }
        matched = engine._fuzzy_match_track("Velvet Shuffle", "Good Match", local)
        assert matched == "t2"

    def test_match_with_score_returns_tuple(self, engine) -> None:
        """The underlying API used by the preview endpoint returns (id, score)."""
        local = {"t1": {"Title": "Same", "Artist": "Same"}}
        tid, score = engine._fuzzy_match_with_score("Same", "Same", local)
        assert tid == "t1"
        assert 0.99 <= score <= 1.0
