"""Route tests for the unified multi-source downloader API.

Covers the four ``/api/downloads/unified/*`` endpoints:

* ``POST /resolve`` / ``POST /search`` / ``POST /fetch`` / ``GET /jobs/{id}``.

What is pinned:

* **Auth** — every route is ``Depends(require_session)``; an unauthenticated
  request is 401 (``@pytest.mark.no_auth``).
* **Input validation** — empty identifier / query and a negative
  ``candidate_index`` are 400 before any orchestration runs.
* **Happy path** — ``unified_resolve`` / ``unified_search`` / ``enqueue_fetch``
  are monkeypatched so the route layer is tested in isolation.
* **Error mapping** — ``enqueue_fetch`` raising ``KeyError`` → 400,
  ``RuntimeError`` → 503; an unknown job id → 404.

Driving the app mirrors ``tests/test_main_security.py`` — httpx
``ASGITransport`` against the live FastAPI graph (no ``TestClient``: the
installed fastapi 0.109 + httpx 0.28 pair mishandles the deprecated ``app=``
kwarg).
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

import app.main as main
from app.downloader.models import (
    Candidate,
    FetchResponse,
    JobStatus,
    MatchResult,
    QualityTier,
    ResolveResponse,
    SearchResponse,
    TrackMatch,
)

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _post(
    url: str,
    json: dict | None = None,
    *,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """Synchronous POST against the ASGI app."""

    async def _go() -> httpx.Response:
        transport = httpx.ASGITransport(
            app=main.app,
            client=("127.0.0.1", 12345),
            raise_app_exceptions=False,
        )
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            return await ac.post(url, json=json, headers=headers)

    return asyncio.run(_go())


def _get(url: str, *, headers: dict[str, str] | None = None) -> httpx.Response:
    """Synchronous GET against the ASGI app."""

    async def _go() -> httpx.Response:
        transport = httpx.ASGITransport(
            app=main.app,
            client=("127.0.0.1", 12345),
            raise_app_exceptions=False,
        )
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            return await ac.get(url, headers=headers)

    return asyncio.run(_go())


def _track() -> TrackMatch:
    """A minimal valid :class:`TrackMatch`."""
    return TrackMatch(
        platform="soundcloud",
        url="https://soundcloud.com/x/y",
        title="Wake Me Up",
        artist="Avicii",
        duration_s=247.0,
        isrc="USUM71304455",
        claimed_format="flac",
        claimed_bit_depth=16,
        claimed_sample_rate_hz=44100,
        quality_tier=QualityTier.CD_LOSSLESS,
    )


def _candidate() -> Candidate:
    return Candidate(
        match=_track(),
        match_result=MatchResult(is_match=True, confidence=1.0, rule_fired="isrc_equality"),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Auth — 401 without a Bearer token
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.no_auth
def test_resolve_requires_auth() -> None:
    """POST /resolve without a Bearer header is 401."""
    r = _post("/api/downloads/unified/resolve", json={"identifier": "x"})
    assert r.status_code == 401


@pytest.mark.no_auth
def test_search_requires_auth() -> None:
    """POST /search without a Bearer header is 401."""
    r = _post("/api/downloads/unified/search", json={"query": "x"})
    assert r.status_code == 401


@pytest.mark.no_auth
def test_fetch_requires_auth() -> None:
    """POST /fetch without a Bearer header is 401."""
    r = _post(
        "/api/downloads/unified/fetch",
        json={"request_id": "r", "candidate_index": 0},
    )
    assert r.status_code == 401


@pytest.mark.no_auth
def test_jobs_poll_requires_auth() -> None:
    """GET /jobs/{id} without a Bearer header is 401."""
    r = _get("/api/downloads/unified/jobs/abc")
    assert r.status_code == 401


# ──────────────────────────────────────────────────────────────────────────────
# Input validation — 400
# ──────────────────────────────────────────────────────────────────────────────


def test_resolve_empty_identifier_is_400(auth_token: dict[str, str]) -> None:
    """A whitespace-only identifier is rejected with 400."""
    r = _post(
        "/api/downloads/unified/resolve",
        json={"identifier": "   "},
        headers=auth_token,
    )
    assert r.status_code == 400


def test_search_empty_query_is_400(auth_token: dict[str, str]) -> None:
    """A whitespace-only query is rejected with 400."""
    r = _post(
        "/api/downloads/unified/search",
        json={"query": ""},
        headers=auth_token,
    )
    assert r.status_code == 400


def test_fetch_negative_candidate_index_is_400(auth_token: dict[str, str]) -> None:
    """A negative candidate_index is rejected with 400."""
    r = _post(
        "/api/downloads/unified/fetch",
        json={"request_id": "r", "candidate_index": -1},
        headers=auth_token,
    )
    assert r.status_code == 400


def test_fetch_empty_request_id_is_400(auth_token: dict[str, str]) -> None:
    """A blank request_id is rejected with 400."""
    r = _post(
        "/api/downloads/unified/fetch",
        json={"request_id": "  ", "candidate_index": 0},
        headers=auth_token,
    )
    assert r.status_code == 400


# ──────────────────────────────────────────────────────────────────────────────
# Happy path — orchestration monkeypatched
# ──────────────────────────────────────────────────────────────────────────────


def test_resolve_happy_path(monkeypatch: pytest.MonkeyPatch, auth_token: dict[str, str]) -> None:
    """A valid identifier returns the resolver's ResolveResponse as JSON."""

    async def _fake_resolve(req: object) -> ResolveResponse:
        return ResolveResponse(
            request_id="req-xyz",
            needle=_track(),
            candidates=[_candidate()],
            auto_pick_index=0,
            near_misses=[],
        )

    monkeypatch.setattr(main, "unified_resolve", _fake_resolve)
    r = _post(
        "/api/downloads/unified/resolve",
        json={"identifier": "https://open.spotify.com/track/abc"},
        headers=auth_token,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["request_id"] == "req-xyz"
    assert body["auto_pick_index"] == 0
    assert len(body["candidates"]) == 1


def test_search_happy_path(monkeypatch: pytest.MonkeyPatch, auth_token: dict[str, str]) -> None:
    """A valid query returns the search SearchResponse as JSON."""

    async def _fake_search(req: object) -> SearchResponse:
        return SearchResponse(request_id="req-search", hits=[])

    monkeypatch.setattr(main, "unified_search", _fake_search)
    r = _post(
        "/api/downloads/unified/search",
        json={"query": "Avicii - Wake Me Up"},
        headers=auth_token,
    )
    assert r.status_code == 200
    assert r.json()["request_id"] == "req-search"


def test_fetch_happy_path(monkeypatch: pytest.MonkeyPatch, auth_token: dict[str, str]) -> None:
    """A valid fetch returns the job handle from enqueue_fetch."""

    def _fake_enqueue(req: object) -> FetchResponse:
        return FetchResponse(job_id="job-1", started_at="2026-05-21T00:00:00+00:00")

    monkeypatch.setattr(main, "enqueue_fetch", _fake_enqueue)
    r = _post(
        "/api/downloads/unified/fetch",
        json={"request_id": "req-xyz", "candidate_index": 0},
        headers=auth_token,
    )
    assert r.status_code == 200
    assert r.json()["job_id"] == "job-1"


# ──────────────────────────────────────────────────────────────────────────────
# Error mapping
# ──────────────────────────────────────────────────────────────────────────────


def test_fetch_keyerror_maps_to_400(
    monkeypatch: pytest.MonkeyPatch, auth_token: dict[str, str]
) -> None:
    """enqueue_fetch raising KeyError → 400 (unknown request_id / bad index)."""

    def _raise_key(req: object) -> FetchResponse:
        raise KeyError("unknown request_id")

    monkeypatch.setattr(main, "enqueue_fetch", _raise_key)
    r = _post(
        "/api/downloads/unified/fetch",
        json={"request_id": "gone", "candidate_index": 0},
        headers=auth_token,
    )
    assert r.status_code == 400


def test_fetch_runtimeerror_maps_to_503(
    monkeypatch: pytest.MonkeyPatch, auth_token: dict[str, str]
) -> None:
    """enqueue_fetch raising RuntimeError → 503 (downloader disabled)."""

    def _raise_runtime(req: object) -> FetchResponse:
        raise RuntimeError("downloader disabled")

    monkeypatch.setattr(main, "enqueue_fetch", _raise_runtime)
    r = _post(
        "/api/downloads/unified/fetch",
        json={"request_id": "r", "candidate_index": 0},
        headers=auth_token,
    )
    assert r.status_code == 503


def test_resolve_transport_failure_maps_to_502(
    monkeypatch: pytest.MonkeyPatch, auth_token: dict[str, str]
) -> None:
    """A provider httpx transport error surfaces as 502."""

    async def _raise_transport(req: object) -> ResolveResponse:
        raise httpx.ConnectError("upstream down")

    monkeypatch.setattr(main, "unified_resolve", _raise_transport)
    r = _post(
        "/api/downloads/unified/resolve",
        json={"identifier": "https://open.spotify.com/track/abc"},
        headers=auth_token,
    )
    assert r.status_code == 502


def test_jobs_poll_happy_path(monkeypatch: pytest.MonkeyPatch, auth_token: dict[str, str]) -> None:
    """GET /jobs/{id} returns the JobStatus for a known job."""

    def _fake_get_job(job_id: str) -> JobStatus:
        return JobStatus(
            job_id=job_id,
            state="downloading",
            progress_pct=35,
        )

    monkeypatch.setattr(main, "get_unified_job", _fake_get_job)
    r = _get("/api/downloads/unified/jobs/job-1", headers=auth_token)
    assert r.status_code == 200
    body = r.json()
    assert body["job_id"] == "job-1"
    assert body["state"] == "downloading"
    assert body["progress_pct"] == 35


def test_jobs_poll_unknown_id_is_404(
    monkeypatch: pytest.MonkeyPatch, auth_token: dict[str, str]
) -> None:
    """GET /jobs/{id} for an unknown job id is 404."""
    monkeypatch.setattr(main, "get_unified_job", lambda _job_id: None)
    r = _get("/api/downloads/unified/jobs/never-existed", headers=auth_token)
    assert r.status_code == 404
