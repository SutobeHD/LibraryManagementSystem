"""Deleting a track (PC test 2026-11-22).

In live mode "Delete from Collection" only dropped the track from the in-memory
cache, answered 500 (a crash on string entries in the playlist cache) and the
track was back after the next restart — rbox 0.1.7 has no way to delete a
djmdContent row. DELETE /api/track/{tid} now answers 409 in live mode without touching
anything; XML mode keeps deleting.
"""

from __future__ import annotations

import asyncio
import logging

import httpx
import pytest

from app import main
from app.live_database import LiveRekordboxDB
from app.main import app


def _request(
    method: str, url: str, headers: dict[str, str], body: dict | None = None
) -> httpx.Response:
    async def _go() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            return await ac.request(method, url, json=body, headers=headers)

    return asyncio.run(_go())


class _Recorder:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    def __call__(self, tid: str) -> bool:
        self.deleted.append(str(tid))
        return True


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    rec = _Recorder()
    monkeypatch.setattr(main.db, "delete_track", rec)
    monkeypatch.setattr(main, "_is_rekordbox_running", lambda: False)
    return rec


def test_live_mode_refuses_with_409_and_deletes_nothing(
    monkeypatch, recorder, auth_token: dict[str, str]
) -> None:
    monkeypatch.setattr(main.db, "mode", "live")
    r = _request("DELETE", "/api/track/42", auth_token)
    assert r.status_code == 409
    assert "Remove the track in Rekordbox" in r.json()["detail"]
    assert recorder.deleted == []


def test_xml_mode_still_deletes(monkeypatch, recorder, auth_token: dict[str, str]) -> None:
    monkeypatch.setattr(main.db, "mode", "xml")
    r = _request("DELETE", "/api/track/42", auth_token)
    assert r.status_code == 200
    assert recorder.deleted == ["42"]


def test_post_track_delete_is_shadowed_by_the_edit_route(
    monkeypatch, recorder, auth_token: dict[str, str]
) -> None:
    # POST /api/track/{tid} is registered first, so "delete" is taken as a track id
    # and the body is rejected by the edit model. Nothing is deleted either way.
    monkeypatch.setattr(main.db, "mode", "xml")
    r = _request("POST", "/api/track/delete", auth_token, {"track_id": "42"})
    assert r.status_code == 422
    assert recorder.deleted == []


def test_running_rekordbox_still_wins_over_the_mode_check(
    monkeypatch, recorder, auth_token: dict[str, str]
) -> None:
    monkeypatch.setattr(main.db, "mode", "live")
    monkeypatch.setattr(main, "_is_rekordbox_running", lambda: True)
    r = _request("DELETE", "/api/track/42", auth_token)
    assert r.status_code == 409
    assert "Rekordbox is running" in r.json()["detail"]


def test_live_backend_delete_leaves_the_cache_alone(caplog) -> None:
    live = LiveRekordboxDB.__new__(LiveRekordboxDB)
    live.tracks = {"42": {"ID": "42", "Title": "Keep me"}}
    live.playlists_tracks = {"p1": ["42", {"ID": "43"}]}  # mixed entries crashed the old loop

    with caplog.at_level(logging.WARNING):
        assert live.delete_track("42") is False

    assert "42" in live.tracks
    assert live.playlists_tracks["p1"] == ["42", {"ID": "43"}]
    assert "refused" in caplog.text
