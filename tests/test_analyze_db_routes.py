"""POST /api/track/{tid}/analyze-full and POST /api/library/analyze-batch.

Both routes used to gate on ``hasattr(db, "get_analysis_writer")``. ``db`` is the
``RekordboxDB`` facade, which had no such method, so they answered 400 in every mode.
The facade now hands out the live writer (None outside live mode) and the routes
answer 409 when there is nothing to write into.

No real library: the facade's ``mode`` / ``live_db`` are pinned per test and the
live backend is a stub whose writer records what it was asked to do.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from app import main
from app.database import RekordboxDB
from app.main import app


def _post(url: str, headers: dict[str, str], body: dict[str, Any] | None = None) -> httpx.Response:
    async def _go() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            return await ac.post(url, json=body or {}, headers=headers)

    return asyncio.run(_go())


def _on_event_loop() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


class _FakeWriter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any, bool]] = []
        self.batch_on_loop: list[bool] = []

    def analyze_and_save(self, tid: str, force: bool = False) -> dict[str, Any]:
        self.calls.append(("one", tid, force))
        return {"status": "ok", "track_id": tid, "bpm": 124.0}

    def analyze_batch(self, track_ids: list[str], force: bool = False) -> Iterator[dict[str, Any]]:
        self.calls.append(("batch", list(track_ids), force))
        for i, tid in enumerate(track_ids):
            self.batch_on_loop.append(_on_event_loop())
            yield {"track_id": tid, "index": i + 1, "total": len(track_ids), "status": "ok"}


class _FakeLiveDB:
    def __init__(self) -> None:
        self.writer = _FakeWriter()
        self.loaded = True

    def get_analysis_writer(self) -> _FakeWriter:
        return self.writer

    def get_unanalyzed_track_ids(self) -> list[str]:
        return ["11", "12"]


@pytest.fixture
def live(monkeypatch: pytest.MonkeyPatch) -> _FakeLiveDB:
    fake = _FakeLiveDB()
    monkeypatch.setattr(main.db, "mode", "live")
    monkeypatch.setattr(main.db, "live_db", fake)
    monkeypatch.setattr(main, "_is_rekordbox_running", lambda: False)
    return fake


@pytest.fixture
def xml_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main.db, "mode", "xml")
    monkeypatch.setattr(main.db, "live_db", None)
    monkeypatch.setattr(main, "_is_rekordbox_running", lambda: False)


# --- facade accessor --------------------------------------------------------


def test_facade_hands_out_the_live_writer_only_in_live_mode() -> None:
    facade = RekordboxDB.__new__(RekordboxDB)
    fake = _FakeLiveDB()

    facade.mode, facade.live_db = "live", fake
    assert facade.get_analysis_writer() is fake.writer

    facade.mode, facade.live_db = "xml", fake
    assert facade.get_analysis_writer() is None

    # Live selected but never loaded: no backend to bind a writer to.
    facade.mode, facade.live_db = "live", None
    assert facade.get_analysis_writer() is None

    # Backend created by a stray `active_db` read but never loaded: still nothing.
    fake.loaded = False
    facade.mode, facade.live_db = "live", fake
    assert facade.get_analysis_writer() is None


def test_analyze_full_before_the_live_library_loads_is_a_409(
    live: _FakeLiveDB, auth_token: dict[str, str]
) -> None:
    # `analyze-status` / MyTag reads create the live backend without loading it.
    live.loaded = False
    r = _post("/api/track/42/analyze-full", auth_token)
    assert r.status_code == 409
    assert "live Rekordbox library" in r.json()["detail"]
    assert live.writer.calls == []


# --- analyze-full -----------------------------------------------------------


def test_analyze_full_runs_the_live_writer(live: _FakeLiveDB, auth_token: dict[str, str]) -> None:
    r = _post("/api/track/42/analyze-full", auth_token, {"force": True})
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "ok", "data": {"status": "ok", "track_id": "42", "bpm": 124.0}}
    assert live.writer.calls == [("one", "42", True)]


def test_analyze_full_outside_live_mode_is_a_409(
    xml_mode: None, auth_token: dict[str, str]
) -> None:
    r = _post("/api/track/42/analyze-full", auth_token)
    assert r.status_code == 409
    assert "live Rekordbox library" in r.json()["detail"]


def test_analyze_full_refuses_while_rekordbox_runs(
    live: _FakeLiveDB, monkeypatch: pytest.MonkeyPatch, auth_token: dict[str, str]
) -> None:
    monkeypatch.setattr(main, "_is_rekordbox_running", lambda: True)
    r = _post("/api/track/42/analyze-full", auth_token)
    assert r.status_code == 409
    assert "Rekordbox is running" in r.json()["detail"]
    assert live.writer.calls == []


@pytest.mark.no_auth
def test_analyze_full_still_needs_a_session(live: _FakeLiveDB) -> None:
    r = _post("/api/track/42/analyze-full", {"Authorization": "Bearer wrong"})
    assert r.status_code == 401
    assert live.writer.calls == []


# --- analyze-batch ----------------------------------------------------------


def test_analyze_batch_streams_ndjson_for_the_unanalysed_tracks(
    live: _FakeLiveDB, auth_token: dict[str, str]
) -> None:
    r = _post("/api/library/analyze-batch", auth_token)
    assert r.status_code == 200, r.text
    assert r.headers["x-total-tracks"] == "2"
    lines = [json.loads(line) for line in r.text.splitlines() if line]
    assert [x["track_id"] for x in lines] == ["11", "12"]
    assert live.writer.calls == [("batch", ["11", "12"], False)]


def test_analyze_batch_runs_each_analysis_off_the_event_loop(
    live: _FakeLiveDB, auth_token: dict[str, str]
) -> None:
    """Per-track analysis takes seconds; on the event loop it stalled every request."""
    r = _post("/api/library/analyze-batch", auth_token, {"track_ids": ["1", "2", "3"]})
    assert r.status_code == 200, r.text
    assert live.writer.batch_on_loop == [False, False, False]
    assert main._analyze_batch_active == 0


def test_analyze_batch_outside_live_mode_is_a_409(
    xml_mode: None, auth_token: dict[str, str]
) -> None:
    r = _post("/api/library/analyze-batch", auth_token, {"track_ids": ["1"]})
    assert r.status_code == 409
    assert "live Rekordbox library" in r.json()["detail"]
