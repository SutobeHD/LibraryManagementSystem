"""Tests for app/rekordbox_bridge.py — Rekordbox XML <-> library.

Import: the fake library enforces the real field allowlist (``app.track_fields``).
The old fake accepted any dict, so it never saw that the import sent ``path``,
``BPM``, grid and cues to a live library that refuses them: PC test 2026-11-25 on a
copy of the real library re-imported a 20-track export with 0 updated, 20 errors and
``status: success``. Paths stored with ``/`` never matched either.

Export: a live track carries its cues as ``Cues``; the export only read
``positionMarks`` and wrote no POSITION_MARK for any live track.
"""

from __future__ import annotations

import asyncio
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import httpx
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import main  # noqa: E402
from app import rekordbox_bridge as rb  # noqa: E402
from app.track_fields import normalise_track_updates, writable_fields  # noqa: E402
from app.xml_generator import RekordboxXML  # noqa: E402


class _FakeDB:
    def __init__(self, existing: dict[str, dict[str, Any]] | None = None, mode: str = "live"):
        self.tracks = existing or {}
        self.mode = mode
        self.updated: list[tuple[list[str], dict[str, Any]]] = []
        self.added: list[dict[str, Any]] = []
        self.saved = False
        self.fail_ids: set[str] = set()

    def writable_track_fields(self) -> frozenset[str]:
        return writable_fields(self.mode)

    def update_tracks_metadata(self, ids: list[str], data: dict[str, Any]) -> bool:
        normalise_track_updates(data, self.mode)  # refuses like the real backends
        if set(ids) & self.fail_ids:
            raise RuntimeError("master.db is locked")
        self.updated.append((list(ids), data))
        return True

    def add_track(self, data: dict[str, Any]) -> str:
        self.added.append(data)
        return f"id-{len(self.added)}"

    def save(self) -> None:
        self.saved = True


_XML = """<?xml version="1.0" encoding="UTF-8"?>
<DJ_PLAYLISTS Version="1.0.0">
  <COLLECTION Entries="2">
    <TRACK TrackID="7" Name="Existing" Artist="A" Album="" Genre="Techno" AverageBpm="128.00"
           TotalTime="200" Rating="204" Tonality="8A"
           Location="file://localhost/C:/Music/My%20Set/existing.mp3">
      <TEMPO Inizio="0.137" Bpm="128.0" Battito="1" Metro="4/4"/>
      <POSITION_MARK Name="Drop" Type="0" Start="64.000" Num="3"/>
    </TRACK>
    <TRACK Name="NewUnanalyzed" Artist="B" AverageBpm="" TotalTime=""
           Location="file://localhost/C:/Music/new.wav"/>
  </COLLECTION>
</DJ_PLAYLISTS>
"""


def _existing(**fields: Any) -> dict[str, Any]:
    # Stored the way the live library holds it: forward slashes, a raw space.
    base = {
        "path": "C:/Music/My Set/existing.mp3",
        "Title": "Existing",
        "Artist": "A",
        "Album": "",
        "Genre": "Techno",
        "Rating": 4,
    }
    return {**base, **fields}


@pytest.fixture
def xml(tmp_path: Path) -> Path:
    path = tmp_path / "lib.xml"
    path.write_text(_XML, encoding="utf-8")
    return path


def test_live_import_matches_forward_slash_paths_and_sends_only_changes(xml, monkeypatch):
    fake = _FakeDB({"T1": _existing(Title="Old title", Genre="House")})
    monkeypatch.setattr(rb, "db", fake)

    results = rb.RekordboxBridge.import_library(str(xml))

    assert results["errors"] == []
    assert (results["updated"], results["added"], results["unchanged"]) == (1, 1, 0)
    assert fake.updated == [(["T1"], {"Title": "Existing", "Genre": "Techno"})]
    assert {"BPM", "beatGrid", "positionMarks", "Key", "TotalTime"} <= set(results["not_written"])
    assert fake.saved is True


def test_reimport_of_identical_tags_writes_nothing(xml, monkeypatch):
    fake = _FakeDB({"T1": _existing()})
    monkeypatch.setattr(rb, "db", fake)

    results = rb.RekordboxBridge.import_library(str(xml))

    assert results["unchanged"] == 1
    assert fake.updated == []


def test_new_unanalysed_track_is_added_without_invented_values(xml, monkeypatch):
    fake = _FakeDB({"T1": _existing()})
    monkeypatch.setattr(rb, "db", fake)

    rb.RekordboxBridge.import_library(str(xml))

    (added,) = fake.added
    assert added["path"] == "C:\\Music\\new.wav"
    assert added["Title"] == "NewUnanalyzed"
    assert "BPM" not in added and "TotalTime" not in added  # was a made-up 120 BPM
    assert None not in added.values()


def test_xml_mode_import_takes_grid_cues_bpm_key_and_raw_rating(xml, monkeypatch):
    fake = _FakeDB({"T1": _existing(Rating=0)}, mode="xml")
    monkeypatch.setattr(rb, "db", fake)

    rb.RekordboxBridge.import_library(str(xml))

    ((_, changes),) = fake.updated
    assert changes["BPM"] == 128.0
    assert changes["Key"] == "8A"
    assert changes["Rating"] == 204  # XML library keeps Rekordbox's raw 0-255
    assert changes["beatGrid"] == [{"time": 0.137, "bpm": 128.0, "beat": 1, "metro": "4/4"}]
    mark = changes["positionMarks"][0]
    assert (mark["Name"], mark["Start"], mark["Num"]) == ("Drop", 64.0, 3)


def test_live_rating_is_converted_to_stars(xml, monkeypatch):
    fake = _FakeDB({"T1": _existing(Rating=1)})
    monkeypatch.setattr(rb, "db", fake)

    rb.RekordboxBridge.import_library(str(xml))

    assert fake.updated[0][1] == {"Rating": 4}  # 204 / 51


def test_track_without_tempo_keeps_the_library_grid(tmp_path, monkeypatch):
    path = tmp_path / "bare.xml"
    path.write_text(
        '<DJ_PLAYLISTS><COLLECTION><TRACK Name="Existing" Artist="A" '
        'Location="file://localhost/C:/Music/My%20Set/existing.mp3"/></COLLECTION></DJ_PLAYLISTS>',
        encoding="utf-8",
    )
    grid = [{"time": 0.1, "bpm": 128.0, "beat": 1, "metro": "4/4"}]
    fake = _FakeDB({"T1": _existing(beatGrid=grid)}, mode="xml")
    monkeypatch.setattr(rb, "db", fake)

    results = rb.RekordboxBridge.import_library(str(path))

    assert results["unchanged"] == 1 and fake.updated == []


def test_failed_track_is_named_in_errors(xml, monkeypatch):
    fake = _FakeDB({"T1": _existing(Title="Old title")})
    fake.fail_ids = {"T1"}
    monkeypatch.setattr(rb, "db", fake)

    results = rb.RekordboxBridge.import_library(str(xml))

    assert results["updated"] == 0
    assert results["errors"] == ["Existing: master.db is locked"]


def test_import_no_collection_raises(tmp_path, monkeypatch):
    path = tmp_path / "bad.xml"
    path.write_text("<DJ_PLAYLISTS></DJ_PLAYLISTS>", encoding="utf-8")
    monkeypatch.setattr(rb, "db", _FakeDB())

    with pytest.raises(ValueError):
        rb.RekordboxBridge.import_library(str(path))


def _import_route(results: dict[str, Any], xml_path: Path, headers: dict[str, str], monkeypatch):
    monkeypatch.setattr(main, "_reject_while_rekordbox_runs", lambda _action: None)
    monkeypatch.setattr(main.RekordboxBridge, "import_library", staticmethod(lambda _p: results))

    async def _go() -> httpx.Response:
        transport = httpx.ASGITransport(app=main.app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            return await ac.post(
                "/api/rekordbox/import", json={"xml_path": str(xml_path)}, headers=headers
            )

    return asyncio.run(_go())


@pytest.mark.parametrize(
    ("counts", "errors", "status"),
    [
        ((2, 1, 0), [], "success"),
        ((0, 1, 0), ["X: boom"], "partial"),
        ((0, 0, 0), ["X: boom"], "error"),
    ],
)
def test_import_route_status_reflects_failures(
    xml, auth_token, monkeypatch, counts, errors, status
):
    added, updated, unchanged = counts
    results = {
        "added": added,
        "updated": updated,
        "unchanged": unchanged,
        "errors": errors,
        "not_written": [],
    }
    r = _import_route(results, xml, auth_token, monkeypatch)

    assert r.status_code == 200
    assert r.json()["status"] == status
    if errors:
        assert "1 failed (first: X: boom)" in r.json()["message"]


def test_export_writes_live_cues_as_position_marks(tmp_path):
    cues = [
        {"Kind": 1, "Num": 0, "Type": 0, "InMsec": 26, "OutMsec": -1, "Comment": "1.1Bars"},
        {"Kind": 0, "Num": -1, "Type": 0, "InMsec": 1000, "OutMsec": -1, "Comment": ""},
        {"Kind": 9, "Num": 7, "Type": 4, "InMsec": 5000, "OutMsec": 9000, "Comment": "Loop"},
    ]
    track = {"ID": "5", "Title": "T", "path": "C:/Music/t.mp3", "Cues": cues}

    out = RekordboxXML.generate([rb._with_cues(track)], tmp_path / "x")

    marks = [m.attrib for m in ET.parse(out).getroot().iter("POSITION_MARK")]
    assert marks == [
        {"Name": "1.1Bars", "Type": "0", "Start": "0.026", "Num": "0"},
        {"Name": "", "Type": "0", "Start": "1.000", "Num": "-1"},
        {"Name": "Loop", "Type": "4", "Start": "5.000", "Num": "7", "End": "9.000"},
    ]
    assert "positionMarks" not in track  # the library's own dict stays untouched


def test_export_keeps_xml_library_position_marks():
    marks = [{"Name": "A", "Type": "0", "Start": 1.0, "Num": 0}]
    track = {"positionMarks": marks, "Cues": [{"InMsec": 5, "Num": 1}]}

    assert rb._with_cues(track) is track
