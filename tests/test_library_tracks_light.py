"""GET /api/library/tracks — the optional ``light`` projection (app/main.py).

``light=true`` leaves out the per-track payload no list view reads: beatGrid,
Cues, positionMarks, phrases. The contracts:

* no parameter → the response is exactly what it always was;
* the projection copies, it never mutates the cached track dicts. USB export
  (``library_source``) and ``rekordbox.xml`` (``save_xml``) read grids and cues
  from those same dicts; a mutating projection would strip them from the stick
  and the XML while every payload-only test stayed green;
* ``hide_streaming`` still applies, light or not;
* the beatgrid loader thread inserts ``beatGrid`` into the cached dicts while
  the boot-time list fetches run. The projection must survive that — a
  comprehension over ``t.items()`` raises, and the route's ``except`` turns
  that into an empty library.

The library is a real ``RekordboxDB`` facade in XML mode with hand-filled
tracks; nothing reads a master.db.
"""

from __future__ import annotations

import asyncio
import sys
import threading
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import httpx
import pytest

from app import main, services
from app.database import RekordboxDB
from app.library_source import XmlLibrarySource
from app.main import app

HEAVY = ("beatGrid", "Cues", "positionMarks", "phrases")
GRID_LEN = 700


def _get(params: dict[str, str] | None = None) -> httpx.Response:
    async def _go() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            return await ac.get("/api/library/tracks", params=params)

    return asyncio.run(_go())


def _grid(n: int) -> list[dict[str, Any]]:
    return [
        {"time": round(i * 0.46875, 5), "bpm": 128.0, "beat": (i % 4) + 1, "metro": "4/4"}
        for i in range(n)
    ]


def _track(tid: str, path: str, grid_len: int = GRID_LEN) -> dict[str, Any]:
    return {
        "id": tid,
        "TrackID": tid,
        "Title": f"Title {tid}",
        "Artist": "Some Artist",
        "Album": "",
        "BPM": 128.0,
        "Key": "8A",
        "Genre": "Techno",
        "Label": "",
        "TotalTime": 300,
        "Rating": 3,
        "path": path,
        "beatGrid": _grid(grid_len),
        "Cues": [{"Name": "Drop", "Start": 60.0, "Num": 0, "Type": "0"}],
        "positionMarks": [
            {
                "Name": "Drop",
                "Type": "0",
                "Start": 60.0,
                "Num": 0,
                "Red": 40,
                "Green": 226,
                "Blue": 20,
            }
        ],
        "phrases": [{"start": 0.0, "end": 30.0, "label": "Intro"}],
    }


def _set_hide_streaming(monkeypatch: pytest.MonkeyPatch, hide: bool) -> None:
    monkeypatch.setattr(
        services.SettingsManager, "load", staticmethod(lambda: {"hide_streaming": hide})
    )


@pytest.fixture
def facade(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> RekordboxDB:
    lib = RekordboxDB()
    lib.mode = "xml"
    lib.xml_db.xml_path = tmp_path / "rekordbox.xml"
    lib.xml_db.tracks = {
        "1": _track("1", str(tmp_path / "a.mp3")),
        "2": _track("2", str(tmp_path / "b.mp3")),
        "3": _track("3", "soundcloud:tracks:123"),
    }
    lib.xml_db.loaded = True
    lib.loaded = True
    monkeypatch.setattr(main, "db", lib)
    _set_hide_streaming(monkeypatch, False)
    return lib


def test_no_parameter_returns_the_full_tracks_unchanged(facade: RekordboxDB) -> None:
    r = _get()
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, list)
    assert body == list(facade.xml_db.tracks.values())
    assert all(len(t["beatGrid"]) == GRID_LEN for t in body)


@pytest.mark.parametrize("flag", ["false", "0"])
def test_light_false_is_the_full_response(facade: RekordboxDB, flag: str) -> None:
    assert _get({"light": flag}).json() == list(facade.xml_db.tracks.values())


def test_light_drops_only_the_heavy_fields(facade: RekordboxDB) -> None:
    r = _get({"light": "true"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert [t["id"] for t in body] == ["1", "2", "3"]
    for item in body:
        cached = facade.xml_db.tracks[item["id"]]
        assert not set(HEAVY) & set(item)
        assert item == {k: v for k, v in cached.items() if k not in HEAVY}


def test_light_never_mutates_the_cached_tracks(facade: RekordboxDB) -> None:
    before = dict(facade.xml_db.tracks)

    assert _get({"light": "true"}).status_code == 200

    for tid, t in facade.xml_db.tracks.items():
        assert t is before[tid]
        assert all(k in t for k in HEAVY)
        assert len(t["beatGrid"]) == GRID_LEN
        assert t["Cues"] and t["positionMarks"] and t["phrases"]


def test_hide_streaming_applies_light_or_not(
    facade: RekordboxDB, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_hide_streaming(monkeypatch, True)

    full = _get().json()
    light = _get({"light": "true"}).json()

    assert [t["id"] for t in full] == ["1", "2"]
    assert [t["id"] for t in light] == ["1", "2"]


def test_usb_source_and_rekordbox_xml_keep_grids_after_a_light_fetch(
    facade: RekordboxDB,
) -> None:
    """The CDJ-facing readers of the cached dicts, after a light fetch."""
    assert _get({"light": "true"}).status_code == 200

    exported = XmlLibrarySource(facade.xml_db).get_track("1")
    assert exported is not None
    assert len(exported["beats"]) == GRID_LEN
    assert exported["position_marks"]

    assert facade.xml_db.save_xml() is True
    root = ET.parse(facade.xml_db.xml_path).getroot()
    node = root.find("COLLECTION/TRACK[@TrackID='1']")
    assert node is not None
    assert len(node.findall("TEMPO")) == GRID_LEN
    assert len(node.findall("POSITION_MARK")) == 1


def test_light_survives_the_beatgrid_loader_writing_meanwhile(
    facade: RekordboxDB,
) -> None:
    """A writer keeps removing and re-inserting beatGrid on every cached dict
    while light fetches run, with the GIL switching every microsecond."""
    facade.xml_db.tracks = {str(i): _track(str(i), f"/music/{i}.mp3", 4) for i in range(300)}
    cached = list(facade.xml_db.tracks.values())
    stop = threading.Event()

    def beatgrid_loader() -> None:
        grid = _grid(4)
        while not stop.is_set():
            for t in cached:
                t.pop("beatGrid", None)
                t["beatGrid"] = grid

    old_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    writer = threading.Thread(target=beatgrid_loader, daemon=True)
    writer.start()
    try:
        for _ in range(50):
            out = main.get_library_tracks(light=True)
            assert len(out) == 300
            assert not any("beatGrid" in d for d in out)
    finally:
        stop.set()
        writer.join(timeout=10)
        sys.setswitchinterval(old_interval)
