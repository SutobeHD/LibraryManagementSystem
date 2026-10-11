"""POST /api/tools/batch-comment.

The route built ``%APPDATA%/Pioneer/rekordbox[6]/master.db`` by hand, whatever
``db.mode`` was: an XML library got its comments written into a Rekordbox db it
does not show, and the app's standalone master.db was never found.

The worker subprocess is a fake; nothing opens a real master.db.
"""

from __future__ import annotations

import asyncio
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


class _FakeWorker:
    def __init__(self, output: str = "COUNT:3\n") -> None:
        self.output = output
        self.calls: list[list[str]] = []

    def __call__(self, cmd: list[str], **kwargs: Any) -> str:
        self.calls.append(list(cmd))
        assert kwargs.get("timeout") == 600
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
