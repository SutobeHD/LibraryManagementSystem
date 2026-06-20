"""Tests for app/rekordbox_bridge.py — Rekordbox XML <-> local DB import.

Drives import_library against a fake DB (the module uses a global `db`
singleton). Locks: existing tracks go through the real update API (not the
removed db.update_track), and empty/absent numeric XML attrs don't drop tracks.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import rekordbox_bridge as rb  # noqa: E402


class _FakeDB:
    def __init__(self, existing=None):
        self.tracks = existing or {}
        self.updated: list = []
        self.added: list = []
        self.saved = False

    def update_tracks_metadata(self, ids, data):
        self.updated.append((list(ids), data))
        return True

    def add_track(self, data):
        self.added.append(data)
        return f"id-{len(self.added)}"

    def save(self):
        self.saved = True


# Location file://localhost/C:/Music/x → clean_path "C:\\Music\\x" (Windows-style)
_XML = """<?xml version="1.0" encoding="UTF-8"?>
<DJ_PLAYLISTS Version="1.0.0">
  <COLLECTION Entries="2">
    <TRACK Name="Existing" Artist="A" AverageBpm="128.00" TotalTime="200"
           Location="file://localhost/C:/Music/existing.mp3">
      <TEMPO Inizio="0.0" Bpm="128.0" Battuta="1" Metro="4/4"/>
    </TRACK>
    <TRACK Name="NewUnanalyzed" Artist="B" AverageBpm="" TotalTime=""
           Location="file://localhost/C:/Music/new.wav"/>
  </COLLECTION>
</DJ_PLAYLISTS>
"""


def test_import_updates_existing_and_adds_new(tmp_path, monkeypatch):
    xml = tmp_path / "lib.xml"
    xml.write_text(_XML, encoding="utf-8")
    fake = _FakeDB(existing={"T1": {"path": "C:\\Music\\existing.mp3"}})
    monkeypatch.setattr(rb, "db", fake)

    results = rb.RekordboxBridge.import_library(str(xml))

    assert results["updated"] == 1
    assert results["added"] == 1
    assert results["errors"] == []  # empty AverageBpm/TotalTime did NOT drop a track
    # existing track went through the real merge API with its id
    assert fake.updated[0][0] == ["T1"]
    # the new (un-analyzed, empty-bpm) track was added with a safe default bpm
    assert fake.added[0]["BPM"] == 120.0
    assert fake.added[0]["TotalTime"] == 0.0
    assert fake.saved is True


def test_import_no_collection_raises(tmp_path, monkeypatch):
    xml = tmp_path / "bad.xml"
    xml.write_text("<DJ_PLAYLISTS></DJ_PLAYLISTS>", encoding="utf-8")
    monkeypatch.setattr(rb, "db", _FakeDB())
    import pytest

    with pytest.raises(ValueError):
        rb.RekordboxBridge.import_library(str(xml))


def test_import_parses_beatgrid(tmp_path, monkeypatch):
    xml = tmp_path / "lib.xml"
    xml.write_text(_XML, encoding="utf-8")
    fake = _FakeDB(existing={"T1": {"path": "C:\\Music\\existing.mp3"}})
    monkeypatch.setattr(rb, "db", fake)
    rb.RekordboxBridge.import_library(str(xml))
    _, data = fake.updated[0]
    assert data["beatGrid"][0]["bpm"] == 128.0
    assert data["beatGrid"][0]["beat"] == 1
