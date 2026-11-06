"""Route tests for the genre-atlas hints (app/main.py).

GET /api/genre-atlas/suggest runs against the shipped snapshot; GET
/api/track/{tid}/genre-suggestions gets a stand-in ``db`` facade so no library is loaded.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from app import main
from app.main import app


# fastapi 0.109 + httpx 0.28 break starlette TestClient -> drive the ASGI app directly
# (same pattern as tests/test_phrase_batch.py).
def _get(url: str, params: dict[str, Any] | None = None) -> httpx.Response:
    async def _go() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            return await ac.get(url, params=params)

    return asyncio.run(_go())


class _DB:
    """Minimal stand-in for the ``db`` facade used by the track route."""

    def __init__(
        self,
        *,
        details: dict[str, Any] | None = None,
        genres: list[Any] | None = None,
    ) -> None:
        self._details = details
        self._genres = genres or []

    def get_track_details(self, _tid: str) -> dict[str, Any] | None:
        return self._details

    def get_all_genres(self) -> list[Any]:
        return self._genres


# --- /api/genre-atlas/suggest ----------------------------------------------------------------


def test_suggest_hard_trance_ranks_hard_house_or_trance_techno_first() -> None:
    r = _get("/api/genre-atlas/suggest", {"genre": "Hard Trance", "bpm": 147})
    assert r.status_code == 200
    body = r.json()
    assert body["candidates"], body
    assert body["candidates"][0]["id"] in {"hard-house", "trance-techno"}
    assert {"candidates", "matched", "bpm_only", "atlas"} <= body.keys()


def test_suggest_without_params_returns_no_candidates() -> None:
    r = _get("/api/genre-atlas/suggest")
    assert r.status_code == 200
    assert r.json()["candidates"] == []
    assert r.json()["bpm_only"] is False


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 21},
        {"bpm": 0},
        {"bpm": 400},
        {"genre": "x" * 501},
    ],
)
def test_suggest_rejects_out_of_range_params(params: dict[str, Any]) -> None:
    assert _get("/api/genre-atlas/suggest", params).status_code == 422


def test_suggest_respects_limit() -> None:
    r = _get("/api/genre-atlas/suggest", {"genre": "Hard Trance", "bpm": 147, "limit": 1})
    assert r.status_code == 200
    assert len(r.json()["candidates"]) == 1


# --- /api/track/{tid}/genre-suggestions ------------------------------------------------------


def test_track_route_404_for_unknown_track(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "db", _DB(details=None))
    r = _get("/api/track/does-not-exist/genre-suggestions")
    assert r.status_code == 404
    assert r.json()["detail"] == "Track not found"


def test_track_route_fills_library_spelling(monkeypatch: pytest.MonkeyPatch) -> None:
    track = {
        "ID": "42",
        "Title": "Some Track",
        "Artist": "Marlon Hoffstadt aka DJ Daddy Trance",
        "Genre": "Hard Trance",
        "Comment": None,
        "Label": "",
        "BPM": 147.0,
    }
    genres = [
        {"id": "gen_0", "name": "hard house", "track_count": 3},
        {"id": "gen_1", "name": "Hard Trance", "track_count": 1},
        "Techno",
    ]
    monkeypatch.setattr(main, "db", _DB(details=track, genres=genres))

    r = _get("/api/track/42/genre-suggestions")
    assert r.status_code == 200
    body = r.json()
    assert body["track"] == {"id": "42", "genre": "Hard Trance"}
    by_id = {c["id"]: c for c in body["candidates"]}
    assert body["candidates"][0]["id"] in {"hard-house", "trance-techno"}
    assert by_id["hard-house"]["library_genre"] == "hard house"
    assert all("library_genre" in c for c in body["candidates"])
    assert any(r_["source"] == "bpm" for r_ in by_id["hard-house"]["reasons"])


def test_track_route_library_genre_none_without_match(monkeypatch: pytest.MonkeyPatch) -> None:
    track = {"ID": "7", "Title": "X", "Genre": "Hard Trance", "BPM": "not-a-number"}
    monkeypatch.setattr(main, "db", _DB(details=track, genres=[{"id": "gen_0", "name": "Jazz"}]))

    r = _get("/api/track/7/genre-suggestions")
    assert r.status_code == 200
    body = r.json()
    assert body["candidates"]
    assert all(c["library_genre"] is None for c in body["candidates"])
    # unparsable BPM is dropped, not a 500
    assert not any(r_["source"] == "bpm" for c in body["candidates"] for r_ in c["reasons"])
