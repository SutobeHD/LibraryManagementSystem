"""POST /api/xml/clean: upload copy + full library reload run off the event loop.

Both used to run inside the ``async def`` handler (``shutil.copyfileobj`` +
``db.load_library`` -> full ET.parse). Now one worker-thread job, holding
``db_lock`` so the overwrite of the live ``rekordbox.xml`` cannot interleave
with a ``save_xml`` elsewhere.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

import httpx
import pytest

import app.main as main
from app import database

XML = b'<?xml version="1.0"?><DJ_PLAYLISTS Version="1.0.0"><COLLECTION Entries="0"/></DJ_PLAYLISTS>'


def test_clean_xml_loads_in_worker_thread_under_db_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, auth_token: dict[str, str]
) -> None:
    monkeypatch.chdir(tmp_path)
    seen: dict[str, Any] = {}

    def fake_load(path: str | None = None) -> bool:
        seen["thread"] = threading.get_ident()
        seen["locked"] = database._db_write_lock._is_owned()  # type: ignore[attr-defined]
        seen["content"] = Path(path or "").read_bytes()
        return True

    monkeypatch.setattr(main.db, "load_library", fake_load)

    async def _go() -> tuple[httpx.Response, int]:
        transport = httpx.ASGITransport(
            app=main.app, client=("127.0.0.1", 12345), raise_app_exceptions=False
        )
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            r = await ac.post(
                "/api/xml/clean",
                files={"file": ("lib.xml", XML, "application/xml")},
                headers=auth_token,
            )
            return r, threading.get_ident()

    r, loop_thread = asyncio.run(_go())
    assert r.status_code == 200, r.text
    assert seen["content"] == XML
    assert seen["thread"] != loop_thread
    assert seen["locked"] is True
    assert (tmp_path / "rekordbox.xml").read_bytes() == XML


def test_clean_xml_rejects_non_xml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, auth_token: dict[str, str]
) -> None:
    monkeypatch.chdir(tmp_path)

    async def _go() -> httpx.Response:
        transport = httpx.ASGITransport(app=main.app, client=("127.0.0.1", 12345))
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            return await ac.post(
                "/api/xml/clean",
                files={"file": ("lib.txt", b"x", "text/plain")},
                headers=auth_token,
            )

    assert asyncio.run(_go()).status_code == 400
    assert not (tmp_path / "rekordbox.xml").exists()
