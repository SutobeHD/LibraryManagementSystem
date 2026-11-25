"""The Rekordbox XML export must never write a live library's tracks without beat grids.

``LiveRekordboxDB.load()`` returns before the grids: a background thread parses the
ANLZ files and adds ``beatGrid`` to every track afterwards (27 s for 5041 tracks).
PC test 2026-11-25 on a copy of the real library: ``POST /api/rekordbox/export`` at
t=0 after the load wrote 4929 of 4929 TRACKs without TEMPO (2.2 MB instead of
265 MB) and answered 200. Here the loader is a fake that blocks until released.
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import live_database, main, rekordbox_bridge  # noqa: E402
from app.database import RekordboxDB  # noqa: E402
from app.live_database import LiveRekordboxDB  # noqa: E402

_GRID = [{"time": 0.1, "bpm": 128.0, "beat": 1}, {"time": 0.56875, "bpm": 128.0, "beat": 2}]


class _SlowLoader:
    """Stands in for ``_load_beatgrids_from_anlz``: one pass per release."""

    def __init__(self, live: LiveRekordboxDB) -> None:
        self.live = live
        self.passes = 0
        self.started = threading.Semaphore(0)
        self.release = threading.Semaphore(0)

    def __call__(self) -> None:
        self.passes += 1
        self.started.release()
        assert self.release.acquire(timeout=10), "test never released the loader"
        for track in self.live.tracks.values():
            track["beatGrid"] = list(_GRID)


def _track(tid: str) -> dict[str, Any]:
    return {"ID": tid, "Title": f"T{tid}", "path": f"C:/Music/t{tid}.aiff", "BPM": 128.0}


@pytest.fixture
def live(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[LiveRekordboxDB]:
    inst = LiveRekordboxDB(str(tmp_path / "master.db"))
    inst.tracks = {tid: _track(tid) for tid in ("1", "2", "3")}
    loader = _SlowLoader(inst)
    monkeypatch.setattr(inst, "_load_beatgrids_from_anlz", loader)
    inst.loader = loader  # type: ignore[attr-defined]
    yield inst
    for _ in range(4):  # never leave a pass blocked behind the test
        loader.release.release()


@pytest.fixture
def library(live: LiveRekordboxDB, monkeypatch: pytest.MonkeyPatch) -> RekordboxDB:
    facade = RekordboxDB.__new__(RekordboxDB)
    facade.mode = "live"
    facade.live_db = live
    monkeypatch.setattr(rekordbox_bridge, "db", facade)
    return facade


@pytest.fixture
def exports(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    out = tmp_path / "exports"
    out.mkdir()
    monkeypatch.setattr(main, "EXPORT_DIR", out)
    return out


def _export(body: dict[str, Any], headers: dict[str, str]) -> httpx.Response:
    async def _go() -> httpx.Response:
        transport = httpx.ASGITransport(app=main.app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            return await ac.post("/api/rekordbox/export", json=body, headers=headers)

    return asyncio.run(_go())


def _tracks_without_tempo(path: Path) -> list[str]:
    root = ET.parse(path).getroot()
    return [t.get("Name") for t in root.iter("TRACK") if t.find("TEMPO") is None]


def test_wait_returns_only_after_the_loader_pass(live: LiveRekordboxDB) -> None:
    live._start_beatgrid_background_load()
    assert live.loader.started.acquire(timeout=5)

    assert live.wait_for_beatgrids(0.05) is False

    live.loader.release.release()
    assert live.wait_for_beatgrids(5) is True
    assert all(t["beatGrid"] == _GRID for t in live.tracks.values())


def test_a_reload_during_a_pass_waits_for_a_second_pass(live: LiveRekordboxDB) -> None:
    live._start_beatgrid_background_load()
    assert live.loader.started.acquire(timeout=5)
    live._start_beatgrid_background_load()  # second load while the first pass runs

    live.loader.release.release()
    assert live.loader.started.acquire(timeout=5)  # the same thread runs again
    assert live.wait_for_beatgrids(0.05) is False

    live.loader.release.release()
    assert live.wait_for_beatgrids(5) is True
    assert live.loader.passes == 2


def test_export_during_the_grid_load_waits_and_writes_every_tempo(
    library: RekordboxDB, live: LiveRekordboxDB, exports: Path, auth_token: dict[str, str]
) -> None:
    live._start_beatgrid_background_load()
    assert live.loader.started.acquire(timeout=5)
    threading.Timer(0.3, live.loader.release.release).start()

    r = _export({"track_ids": ["1", "2", "3"], "filename": "early"}, auth_token)

    assert r.status_code == 200, r.text
    assert r.json()["exported"] == 3
    assert _tracks_without_tempo(exports / "early.xml") == []


def test_export_answers_503_instead_of_a_file_without_grids(
    library: RekordboxDB,
    live: LiveRekordboxDB,
    exports: Path,
    auth_token: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(live_database, "BEATGRID_WAIT_TIMEOUT_S", 0.2)
    live._start_beatgrid_background_load()
    assert live.loader.started.acquire(timeout=5)

    r = _export({"track_ids": ["1", "2", "3"], "filename": "early"}, auth_token)

    assert r.status_code == 503, r.text
    assert "still loading" in r.json()["detail"]
    assert r.headers.get("Retry-After") == "10"
    assert list(exports.iterdir()) == []


def test_tracks_that_carry_their_own_grid_do_not_wait(
    library: RekordboxDB, live: LiveRekordboxDB, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The auto-export after an import: the new track got its grid from the analysis.
    monkeypatch.setattr(live_database, "BEATGRID_WAIT_TIMEOUT_S", 0.0)
    live.tracks["9"] = {**_track("9"), "beatGrid": list(_GRID)}
    live._start_beatgrid_background_load()
    assert live.loader.started.acquire(timeout=5)

    result = rekordbox_bridge.RekordboxBridge.export_collection(["9"], tmp_path / "one")

    assert result.exported == 1
    assert _tracks_without_tempo(Path(result.path)) == []


def test_xml_mode_has_nothing_to_wait_for() -> None:
    facade = RekordboxDB.__new__(RekordboxDB)
    facade.mode = "xml"
    facade.xml_db = object()

    assert facade.wait_for_beatgrids(0) is True
