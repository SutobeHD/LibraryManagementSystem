"""POST /api/tools/batch-comment.

The route built ``%APPDATA%/Pioneer/rekordbox[6]/master.db`` by hand, whatever
``db.mode`` was: an XML library got its comments written into a Rekordbox db it
does not show, and the app's standalone master.db was never found.

It was also ``async def`` calling ``subprocess.check_output(..., timeout=600)``
directly, so the whole sidecar (playback stream, polling) stalled while the worker
ran. It is now a plain ``def`` that FastAPI runs in its threadpool, behind the same
Rekordbox-running 409 as analyze-full.

The worker subprocess is a fake; nothing opens a real master.db.
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


class _FakeWorker:
    def __init__(self, output: str = "COUNT:3\n") -> None:
        self.output = output
        self.exc: Exception | None = None
        self.calls: list[list[str]] = []
        self.on_loop: list[bool] = []

    def __call__(self, cmd: list[str], **kwargs: Any) -> str:
        self.calls.append(list(cmd))
        self.on_loop.append(_on_event_loop())
        assert kwargs.get("timeout") == 600
        if self.exc is not None:
            raise self.exc
        return self.output


@pytest.fixture
def live_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_file = tmp_path / "live" / "master.db"
    monkeypatch.setattr(main.db, "mode", "live")
    monkeypatch.setattr(main.db, "live_db_path", db_file)
    monkeypatch.setattr(main, "_is_rekordbox_running", lambda: False)
    return db_file


@pytest.fixture
def worker(monkeypatch: pytest.MonkeyPatch) -> _FakeWorker:
    fake = _FakeWorker()
    monkeypatch.setattr(subprocess, "check_output", fake)
    return fake


def test_worker_gets_the_live_library_master_db(
    live_db: Path, worker: _FakeWorker, auth_token: dict[str, str]
) -> None:
    r = _post(auth_token, {"source_id": "LIB", "action": "append", "replace": "[x]"})
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "success", "count": 3}
    (cmd,) = worker.calls
    assert cmd[cmd.index("--db") + 1] == str(live_db)
    assert cmd[cmd.index("--source") + 1] == "LIB"
    assert cmd[cmd.index("--action") + 1] == "append"
    assert cmd[cmd.index("--replace") + 1] == "[x]"
    assert "--find" not in cmd


def test_handler_is_not_a_coroutine() -> None:
    # A coroutine handler runs on the event loop; a plain def goes to the threadpool.
    assert not inspect.iscoroutinefunction(main.batch_comment)


def test_runs_the_worker_off_the_event_loop(
    live_db: Path, worker: _FakeWorker, auth_token: dict[str, str]
) -> None:
    r = _post(auth_token, {"source_id": "LIB", "action": "set", "replace": "x"})
    assert r.status_code == 200, r.text
    assert worker.on_loop == [False]


def test_refuses_while_rekordbox_runs(
    live_db: Path,
    worker: _FakeWorker,
    monkeypatch: pytest.MonkeyPatch,
    auth_token: dict[str, str],
) -> None:
    monkeypatch.setattr(main, "_is_rekordbox_running", lambda: True)
    r = _post(auth_token, {"source_id": "LIB", "action": "set", "replace": "x"})
    assert r.status_code == 409
    assert "Rekordbox is running" in r.json()["detail"]
    assert worker.calls == []


def test_worker_timeout_is_a_504(
    live_db: Path, worker: _FakeWorker, auth_token: dict[str, str]
) -> None:
    worker.exc = subprocess.TimeoutExpired(cmd="batch_worker", timeout=600)
    r = _post(auth_token, {"source_id": "LIB", "action": "set", "replace": "x"})
    assert r.status_code == 504


def test_outside_live_mode_is_a_409(
    worker: _FakeWorker, monkeypatch: pytest.MonkeyPatch, auth_token: dict[str, str]
) -> None:
    monkeypatch.setattr(main.db, "mode", "xml")
    r = _post(auth_token, {"source_id": "LIB", "action": "set", "replace": "x"})
    assert r.status_code == 409
    assert "live Rekordbox library" in r.json()["detail"]
    assert worker.calls == []


@pytest.mark.no_auth
def test_still_needs_a_session(live_db: Path, worker: _FakeWorker) -> None:
    r = _post({"Authorization": "Bearer wrong"}, {"source_id": "LIB", "action": "set"})
    assert r.status_code == 401
    assert worker.calls == []
