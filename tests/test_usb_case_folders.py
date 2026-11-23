"""Folders that differ only in case get one spelling per stick (PC test 2026-11-22).

Tracks by "Stenoz" and "STENOZ" share one folder on a case-insensitive volume. Each
writer kept its own spelling, the rekordbox.xml pass case-renamed the folder, and
three exportLibrary.db paths no longer matched the case on disk. Both writers now
resolve folder names through one `FolderNames` per sync.

The sync tests run the real `UsbSyncEngine.sync_collection()` (OneLibrary + legacy
XML) against a stick folder under `tmp_path`, which is case-insensitive on Windows.
On a case-sensitive volume the same assertions hold: one folder, DB == disk.
"""

from __future__ import annotations

import gc
import os
import time
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from app import anlz_sidecar, library_source, usb_manager
from app.usb_manager import UsbSyncEngine
from app.usb_one_library import FolderNames
from tests.test_anlz_usb_export import _source_trio

rbox = pytest.importorskip("rbox")

from tests.test_onelibrary_track_limit import _Source  # noqa: E402

TRACKS = [
    ("Stenoz", "Intro", "a.mp3"),
    ("STENOZ", "Outro", "b.mp3"),
    ("stenoz", "INTRO", "c.mp3"),
    ("Boys Noize", "Xpress", "d.mp3"),
]


def _case_exact(root: Path, rel: str) -> bool:
    """Every segment of `rel` exists under `root` with exactly this case."""
    cur = root
    for part in [p for p in rel.replace("\\", "/").split("/") if p]:
        if part not in os.listdir(cur):
            return False
        cur = cur / part
    return True


@pytest.fixture
def env(tmp_path: Path, monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("sync must use the sidecar, not re-analyse")

    monkeypatch.setattr(anlz_sidecar, "write_companion_anlz", boom)
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    monkeypatch.setattr(usb_manager, "PROFILES_FILE", tmp_path / "usb_profiles.json")
    monkeypatch.setattr(usb_manager.UsbProfileManager, "save_profile", lambda p: p)

    music = tmp_path / "music"
    music.mkdir()
    tracks = []
    for i, (artist, title, name) in enumerate(TRACKS):
        audio = music / name
        audio.write_bytes(b"\xff\xfb" + bytes([i]) * 64)
        tracks.append(
            {
                "id": str(100 + i),
                "title": title,
                "artist": artist,
                "album": "",
                "genre": "",
                "key": "",
                "label": "",
                "bpm": 128.0,
                "duration_ms": 30000,
                "path": str(audio),
            }
        )
    ids = [t["id"] for t in tracks]
    source = _Source(
        tracks,
        [{"id": "p", "name": "P", "parent_id": "ROOT", "type": "1", "track_ids": ids}],
        _source_trio(tmp_path / "side").parent,
    )
    monkeypatch.setattr(library_source, "from_db", lambda _db: source)
    stick = tmp_path / "stick"
    stick.mkdir()
    return {"tmp": tmp_path, "stick": stick, "music": music}


def _sync(env: dict) -> list[dict]:
    # A fresh engine per sync, as the sync route builds one per request. The .xml
    # local path sends the legacy pass down its LibrarySource (XML-mode) branch.
    engine = UsbSyncEngine(str(env["tmp"] / "library.xml"), str(env["stick"]), "FAT32")
    events = list(engine.sync_collection({"device_id": "d", "drive": str(env["stick"])}))
    assert events[-1]["stage"] == "complete", events[-3:]
    return events


def _db_paths(stick: Path) -> list[str]:
    db = rbox.OneLibrary(str(stick / "PIONEER" / "rekordbox" / "exportLibrary.db"))
    try:
        return [
            c.path for c in db.get_contents() if not (c.title or "").startswith("__placeholder_")
        ]
    finally:
        del db
        gc.collect()


def _xml_paths(stick: Path) -> list[str]:
    root = ET.parse(stick / "PIONEER" / "rekordbox.xml").getroot()
    out = []
    for track in root.iter("TRACK"):
        loc = track.get("Location")
        if loc:
            path = urllib.parse.unquote(loc).removeprefix("file://localhost/")
            out.append(str(Path(path).relative_to(stick)))
    return out


def _assert_one_spelling_and_db_matches_disk(stick: Path) -> None:
    artists = os.listdir(stick / "Contents")
    assert sorted(a.casefold() for a in artists) == ["boys noize", "stenoz"], artists
    db_paths = _db_paths(stick)
    assert len(db_paths) == len(TRACKS)
    for rel in db_paths:
        assert _case_exact(stick, rel), f"exportLibrary.db path {rel} differs from disk"
    xml_paths = _xml_paths(stick)
    assert len(xml_paths) == len(TRACKS)
    for rel in xml_paths:
        assert _case_exact(stick, rel), f"rekordbox.xml path {rel} differs from disk"
    # One title folder for Intro/INTRO under the one artist folder.
    stenoz = next(a for a in artists if a.casefold() == "stenoz")
    titles = os.listdir(stick / "Contents" / stenoz)
    assert sorted(t.casefold() for t in titles) == ["intro", "outro"], titles


def test_both_writers_agree_on_one_spelling(env) -> None:
    _sync(env)

    _assert_one_spelling_and_db_matches_disk(env["stick"])
    # First spelling asked for wins on a fresh stick.
    assert "Stenoz" in os.listdir(env["stick"] / "Contents")


def test_resync_keeps_the_spelling_and_moves_nothing(env) -> None:
    _sync(env)
    events = _sync(env)

    assert not [e for e in events if e.get("stage") == "relocate"], "re-sync moved files"
    _assert_one_spelling_and_db_matches_disk(env["stick"])


def test_a_stick_left_in_the_other_spelling_is_kept(env) -> None:
    """A stick an older sync left as STENOZ/ keeps it — STENOZ is one of the asked spellings."""
    old = env["stick"] / "Contents" / "STENOZ" / "Intro"
    old.mkdir(parents=True)
    (old / "a.mp3").write_bytes((env["music"] / "a.mp3").read_bytes())

    _sync(env)

    assert "STENOZ" in os.listdir(env["stick"] / "Contents")
    _assert_one_spelling_and_db_matches_disk(env["stick"])


# ---------------------------------------------------------------------------
# FolderNames rules (no rbox)
# ---------------------------------------------------------------------------


def _names(tmp_path: Path) -> tuple[FolderNames, Path]:
    contents = tmp_path / "Contents"
    contents.mkdir(exist_ok=True)
    return FolderNames(contents), contents


def test_first_spelling_wins_on_an_empty_stick(tmp_path: Path) -> None:
    names, c = _names(tmp_path)
    names.settle([c / "STENOZ" / "T" / "b.mp3", c / "Stenoz" / "U" / "a.mp3"])

    assert names.apply(c / "Stenoz" / "U" / "a.mp3") == c / "STENOZ" / "U" / "a.mp3"


def test_on_disk_spelling_wins_when_asked_for(tmp_path: Path) -> None:
    names, c = _names(tmp_path)
    (c / "Stenoz").mkdir()
    names.settle([c / "STENOZ" / "T" / "b.mp3", c / "Stenoz" / "U" / "a.mp3"])

    assert str(names.apply(c / "STENOZ" / "T" / "b.mp3")) == str(c / "Stenoz" / "T" / "b.mp3")


def test_a_restyle_nobody_still_asks_against_renames(tmp_path: Path) -> None:
    """All tracks now say "Boys Noize": the old "boys noize/" folder is not kept."""
    names, c = _names(tmp_path)
    (c / "boys noize").mkdir()
    names.settle([c / "Boys Noize" / "X" / "x.aiff"])

    assert str(names.apply(c / "Boys Noize" / "X" / "x.aiff")) == str(
        c / "Boys Noize" / "X" / "x.aiff"
    )


def test_unplanned_folder_takes_the_disk_spelling(tmp_path: Path) -> None:
    names, c = _names(tmp_path)
    (c / "Stenoz" / "Intro").mkdir(parents=True)

    got = names.apply(c / "STENOZ" / "INTRO" / "a.mp3")

    assert str(got) == str(c / "Stenoz" / "Intro" / "a.mp3")
    # ... and keeps it, even once the folder is gone.
    os.rmdir(c / "Stenoz" / "Intro")
    os.rmdir(c / "Stenoz")
    assert str(names.apply(c / "stenoz" / "intro" / "b.mp3")) == str(
        c / "Stenoz" / "Intro" / "b.mp3"
    )


def test_title_folders_settle_under_the_settled_artist(tmp_path: Path) -> None:
    names, c = _names(tmp_path)
    (c / "Stenoz" / "intro").mkdir(parents=True)
    names.settle([c / "STENOZ" / "INTRO" / "a.mp3", c / "Stenoz" / "intro" / "b.mp3"])

    assert str(names.apply(c / "STENOZ" / "INTRO" / "a.mp3")) == str(
        c / "Stenoz" / "intro" / "a.mp3"
    )


def test_paths_outside_contents_and_flat_files_pass_through(tmp_path: Path) -> None:
    names, c = _names(tmp_path)
    outside = tmp_path / "Elsewhere" / "A" / "x.mp3"
    flat = c / "track_1a2b3c4d.mp3"

    assert names.apply(outside) == outside
    assert names.apply(flat) == flat
