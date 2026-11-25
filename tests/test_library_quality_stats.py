"""GET /api/library/quality-stats — lossless/lossy counts by file extension (B16)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from app import main, services
from app.database import RekordboxDB
from app.main import app

LOSSLESS = ["a.flac", "b.AIFF", "c.aif", "d.wav"]
LOSSY = ["e.mp3", "f.m4a", "g.ogg"]


def _get() -> httpx.Response:
    async def _go() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            return await ac.get("/api/library/quality-stats")

    return asyncio.run(_go())


@pytest.fixture
def facade(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> RekordboxDB:
    lib = RekordboxDB()
    lib.mode = "xml"
    lib.xml_db.xml_path = tmp_path / "rekordbox.xml"
    tracks = {
        str(i): {"id": str(i), "path": str(tmp_path / name)}
        for i, name in enumerate(LOSSLESS + LOSSY)
    }
    tracks["sc"] = {"id": "sc", "path": "soundcloud:tracks:123"}
    tracks["wma"] = {"id": "wma", "path": str(tmp_path / "h.wma")}
    tracks["empty"] = {"id": "empty", "path": ""}
    lib.xml_db.tracks = tracks
    lib.xml_db.loaded = True
    lib.loaded = True
    monkeypatch.setattr(main, "db", lib)
    monkeypatch.setattr(
        services.SettingsManager, "load", staticmethod(lambda: {"hide_streaming": False})
    )
    return lib


def test_counts_by_extension_without_auth(facade: RekordboxDB) -> None:
    r = _get()
    assert r.status_code == 200, r.text
    assert r.json() == {"lossless": 4, "lossy": 3, "total": 7}


def test_no_library_loaded_returns_zeros(facade: RekordboxDB) -> None:
    facade.loaded = False
    r = _get()
    assert r.status_code == 200, r.text
    assert r.json() == {"lossless": 0, "lossy": 0, "total": 0}
