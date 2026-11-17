"""Tests for app/library_source.py — the Live/XML normalization layer.

The two _normalize static methods are pure and run for every track during
USB sync. Locks: numeric coercion never crashes on garbage tags, and the
Live duration heuristic doesn't 1000x a duration_ms-only track.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.library_source import (  # noqa: E402
    LiveLibrarySource,
    XmlLibrarySource,
    _to_float,
    _to_int,
)

# --- coercion helpers ------------------------------------------------------


def test_to_float_tolerates_garbage():
    assert _to_float("128.0") == 128.0
    assert _to_float(None) == 0.0
    assert _to_float("") == 0.0
    assert _to_float("n/a") == 0.0  # non-numeric → default, never raises
    assert _to_float("x", default=1.0) == 1.0


def test_to_int_tolerates_garbage():
    assert _to_int("5") == 5
    assert _to_int("5.9") == 5  # truncates via float
    assert _to_int(None) == 0
    assert _to_int("bad") == 0


# --- XML _normalize --------------------------------------------------------


def test_xml_normalize_basic_and_duration_seconds():
    out = XmlLibrarySource._normalize(
        "7", {"Title": "T", "Artist": "A", "BPM": "124.0", "TotalTime": "200", "Rating": "4"}
    )
    assert out["id"] == "7"
    assert out["bpm"] == 124.0
    assert out["duration_ms"] == 200_000  # TotalTime seconds → ms
    assert out["rating"] == 4


def test_xml_normalize_does_not_crash_on_garbage():
    """Regression: a non-numeric BPM/Rating must not raise (aborts the sync)."""
    out = XmlLibrarySource._normalize("1", {"BPM": "n/a", "Rating": "", "Bitrate": "??"})
    assert out["bpm"] == 0.0
    assert out["rating"] == 0
    assert out["bitrate"] == 0


# --- Live _normalize -------------------------------------------------------


def test_live_normalize_duration_from_total_time_seconds():
    out = LiveLibrarySource._normalize("1", {"TotalTime": 240})  # seconds
    assert out["duration_ms"] == 240_000


def test_live_normalize_duration_ms_only_not_multiplied():
    """Regression: a duration_ms-only track must NOT be x1000 (was 240_000_000)."""
    out = LiveLibrarySource._normalize("1", {"duration_ms": 240000})
    assert out["duration_ms"] == 240000


def test_live_normalize_lowercase_and_fallback_keys():
    out = LiveLibrarySource._normalize(
        "9", {"title": "lt", "bpm": "126", "folder_path": "/m/x.wav", "BitRate": "320"}
    )
    assert out["title"] == "lt"
    assert out["bpm"] == 126.0
    assert out["path"] == "/m/x.wav"
    assert out["bitrate"] == 320


def test_live_normalize_garbage_does_not_crash():
    out = LiveLibrarySource._normalize("1", {"BPM": "n/a", "TotalTime": "oops"})
    assert out["bpm"] == 0.0
    assert out["duration_ms"] == 0


# --- ANLZ sidecar lookup ----------------------------------------------------


def _sidecar_for(audio):
    from app.anlz_sidecar import sidecar_dir_for

    folder = sidecar_dir_for(audio)
    folder.mkdir(parents=True)
    (folder / "ANLZ0000.DAT").write_bytes(b"PMAI")
    return folder


def test_sidecar_lookup_uses_the_writers_resolved_path_key(tmp_path):
    """The writer hashes str(path.resolve()); a stored path with `..` must still hit."""
    audio = tmp_path / "music" / "Track.mp3"
    (tmp_path / "music" / "sub").mkdir(parents=True)
    audio.write_bytes(b"\xff\xfb")
    folder = _sidecar_for(audio)

    stored = str(tmp_path / "music" / "sub" / ".." / "Track.mp3")
    assert stored != str(audio.resolve())
    found = XmlLibrarySource(None).get_anlz_sidecar_dir({"path": stored})
    assert found is not None and found.resolve() == folder.resolve()


def test_sidecar_lookup_misses_cleanly(tmp_path):
    audio = tmp_path / "Track.mp3"
    audio.write_bytes(b"\xff\xfb")
    src = XmlLibrarySource(None)
    assert src.get_anlz_sidecar_dir({"path": str(audio)}) is None
    assert src.get_anlz_sidecar_dir({"path": ""}) is None
    assert src.get_anlz_sidecar_dir({}) is None


# --- B7: LMS ANLZ never goes into the music folder ------------------------------


def test_sidecar_dir_is_in_the_anlz_cache_never_next_to_the_audio(tmp_path, anlz_cache_sandbox):
    from app.anlz_sidecar import sidecar_dir_for

    audio = tmp_path / "music" / "Track.mp3"
    folder = sidecar_dir_for(audio)
    assert folder.is_relative_to(anlz_cache_sandbox)
    assert not folder.is_relative_to(audio.parent)


def test_write_companion_anlz_leaves_the_music_folder_untouched(tmp_path, monkeypatch):
    from app import anlz_sidecar

    music = tmp_path / "music"
    music.mkdir()
    audio = music / "Track.mp3"
    audio.write_bytes(b"\xff\xfb")
    seen = {}

    def _write(**kw):
        seen.update(kw)
        (Path(kw["anlz_dir"]) / "ANLZ0000.DAT").write_bytes(b"PMAI")
        return {"dat": "x"}

    monkeypatch.setattr("app.anlz_writer.write_anlz_files", _write)

    out = anlz_sidecar.write_companion_anlz(audio, {"status": "ok", "waveform": {}})

    assert out == anlz_sidecar.sidecar_dir_for(audio)
    assert Path(seen["anlz_dir"]) == out
    assert sorted(p.name for p in music.iterdir()) == ["Track.mp3"]


def test_legacy_sidecar_next_to_the_audio_is_still_read(tmp_path):
    from app.anlz_sidecar import legacy_sidecar_dir_for

    audio = tmp_path / "music" / "Track.mp3"
    audio.parent.mkdir()
    audio.write_bytes(b"\xff\xfb")
    legacy = legacy_sidecar_dir_for(audio)
    legacy.mkdir(parents=True)
    (legacy / "ANLZ0000.DAT").write_bytes(b"PMAI")

    assert XmlLibrarySource(None).get_anlz_sidecar_dir({"path": str(audio)}) == legacy


def test_cache_wins_over_the_legacy_sidecar(tmp_path):
    from app.anlz_sidecar import legacy_sidecar_dir_for

    audio = tmp_path / "music" / "Track.mp3"
    audio.parent.mkdir()
    audio.write_bytes(b"\xff\xfb")
    legacy_sidecar_dir_for(audio).mkdir(parents=True)
    cache = _sidecar_for(audio)

    assert XmlLibrarySource(None).get_anlz_sidecar_dir({"path": str(audio)}) == cache


class _Row:
    def __init__(self, rel):
        self.analysis_data_path = rel


class _Master:
    def __init__(self, share, rows):
        self.share, self.rows = share, rows

    def share_directory(self):
        return str(self.share)

    def get_content_by_id(self, tid):
        return self.rows.get(tid)

    def get_content_anlz_dir(self, tid):  # real rbox aborts the process here
        raise AssertionError("aborting rbox helper called")

    get_content_anlz_paths = get_content_anlz_dir


def test_live_source_finds_rekordbox_anlz_from_master_db(tmp_path):
    rel = "/PIONEER/USBANLZ/44d/00cc2-7321/ANLZ0001.DAT"  # re-analysis keeps its own name
    dat = tmp_path / "share" / "PIONEER" / "USBANLZ" / "44d" / "00cc2-7321" / "ANLZ0001.DAT"
    dat.parent.mkdir(parents=True)
    dat.write_bytes(b"PMAI")
    live = SimpleNamespace(
        tracks={},
        db=_Master(tmp_path / "share", {"1": _Row(rel), "2": _Row(None), "3": _Row(rel + "x")}),
    )
    src = LiveLibrarySource(live)

    assert src.get_rekordbox_anlz_dat({"id": "1"}) == dat
    assert src.get_rekordbox_anlz_dat({"id": "2"}) is None  # never analysed
    assert src.get_rekordbox_anlz_dat({"id": "3"}) is None  # recorded but not on disk
    assert src.get_rekordbox_anlz_dat({"id": "9"}) is None  # no row
    assert XmlLibrarySource(None).get_rekordbox_anlz_dat({"id": "1"}) is None
