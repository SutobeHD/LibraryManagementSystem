"""POST /api/tools/batch-comment.

The route built ``%APPDATA%/Pioneer/rekordbox[6]/master.db`` by hand, whatever
``db.mode`` was: an XML library got its comments written into a Rekordbox db it
does not show, and the app's standalone master.db was never found.

It then ran ``[sys.executable, batch_worker.py, ...]``. In the frozen build
``sys.executable`` is the sidecar exe, which ignores argv: the child booted a second
backend, printed a fresh ``LMS_TOKEN=`` line the route logged, overwrote the
session-token file and died on port 8000. The edit now runs in-process on the live
library's own rbox connection, as a plain ``def`` in the threadpool.

The live backend is a stub; nothing opens a real master.db.
"""

from __future__ import annotations

import asyncio
import inspect
import subprocess
from pathlib import Path
from typing import Any

import httpx
import pytest

from app import main
from app.main import app

URL = "/api/tools/batch-comment"


def _post(headers: dict[str, str], body: dict[str, Any]) -> httpx.Response:
    async def _go() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            return await ac.post(URL, json=body, headers=headers)

    return asyncio.run(_go())


def _on_event_loop() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


class _Content:
    def __init__(self, cid: str, commnt: str) -> None:
        self.id = cid
        self.commnt = commnt


class _FakeMasterDb:
    """The slice of rbox.MasterDb the batch edit uses."""

    def __init__(self, comments: dict[str, str], playlists: dict[str, list[str]]) -> None:
        self.rows = {tid: _Content(tid, c) for tid, c in comments.items()}
        self.playlists = playlists
        self.updated: list[tuple[str, str]] = []
        self.on_loop: list[bool] = []

    def get_contents(self) -> list[_Content]:
        self.on_loop.append(_on_event_loop())
        return list(self.rows.values())

    def get_playlist_contents(self, pid: str) -> list[_Content]:
        self.on_loop.append(_on_event_loop())
        return [self.rows[t] for t in self.playlists.get(pid, [])]

    def get_content_by_id(self, tid: str) -> _Content | None:
        assert isinstance(tid, str), "rbox MasterDb takes the content id as a str"
        return self.rows.get(tid)

    def update_content(self, item: _Content) -> None:
        self.updated.append((item.id, item.commnt))


class _FakeLive:
    def __init__(self, master: _FakeMasterDb) -> None:
        self.db = master
        self.tracks = {tid: {"ID": tid, "Comment": r.commnt} for tid, r in master.rows.items()}
        self.loaded = True


@pytest.fixture
def live(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _FakeLive:
    master = _FakeMasterDb({"1": "intro", "2": "promo only", "3": ""}, {"77": ["2"]})
    fake = _FakeLive(master)
    monkeypatch.setattr(main.db, "mode", "live")
    monkeypatch.setattr(main.db, "live_db_path", tmp_path / "live" / "master.db")
    monkeypatch.setattr(main.db, "live_db", fake)
    monkeypatch.setattr(main, "_is_rekordbox_running", lambda: False)
    return fake


@pytest.fixture
def spawned(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    for name in ("check_output", "run", "call", "Popen"):

        def _record(*_a: Any, _name: str = name, **_k: Any) -> None:
            calls.append(_name)
            raise AssertionError("batch-comment must not start a process")

        monkeypatch.setattr(subprocess, name, _record)
    return calls


def test_edits_the_live_library_in_process(
    live: _FakeLive, spawned: list[str], auth_token: dict[str, str]
) -> None:
    r = _post(auth_token, {"source_id": "LIB", "action": "append", "replace": "[x]"})
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "success", "count": 3}
    assert live.db.updated == [("1", "intro [x]"), ("2", "promo only [x]"), ("3", "[x]")]
    assert spawned == []


def test_refreshes_the_cached_comment_of_each_changed_track(
    live: _FakeLive, auth_token: dict[str, str]
) -> None:
    """The library view reads the in-memory cache, not master.db."""
    r = _post(auth_token, {"source_id": "77", "action": "set", "replace": "new"})
    assert r.status_code == 200, r.text
    assert [live.tracks[t]["Comment"] for t in ("1", "2", "3")] == ["intro", "new", ""]


def test_a_playlist_source_edits_only_its_tracks(
    live: _FakeLive, auth_token: dict[str, str]
) -> None:
    r = _post(auth_token, {"source_id": "77", "action": "remove", "find": "promo "})
    assert r.status_code == 200, r.text
    assert r.json()["count"] == 1
    assert live.db.updated == [("2", "only")]


def test_handler_is_not_a_coroutine() -> None:
    # A coroutine handler runs on the event loop; a plain def goes to the threadpool.
    assert not inspect.iscoroutinefunction(main.batch_comment)


def test_runs_off_the_event_loop(live: _FakeLive, auth_token: dict[str, str]) -> None:
    r = _post(auth_token, {"source_id": "LIB", "action": "set", "replace": "x"})
    assert r.status_code == 200, r.text
    assert live.db.on_loop == [False]


def test_refuses_while_rekordbox_runs(
    live: _FakeLive, monkeypatch: pytest.MonkeyPatch, auth_token: dict[str, str]
) -> None:
    monkeypatch.setattr(main, "_is_rekordbox_running", lambda: True)
    r = _post(auth_token, {"source_id": "LIB", "action": "set", "replace": "x"})
    assert r.status_code == 409
    assert "Rekordbox is running" in r.json()["detail"]
    assert live.db.updated == []


def test_outside_live_mode_is_a_409(
    live: _FakeLive, monkeypatch: pytest.MonkeyPatch, auth_token: dict[str, str]
) -> None:
    monkeypatch.setattr(main.db, "mode", "xml")
    r = _post(auth_token, {"source_id": "LIB", "action": "set", "replace": "x"})
    assert r.status_code == 409
    assert "live Rekordbox library" in r.json()["detail"]
    assert live.db.updated == []


@pytest.mark.no_auth
def test_still_needs_a_session(live: _FakeLive) -> None:
    r = _post({"Authorization": "Bearer wrong"}, {"source_id": "LIB", "action": "set"})
    assert r.status_code == 401
    assert live.db.updated == []
