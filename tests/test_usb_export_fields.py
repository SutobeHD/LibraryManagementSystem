"""Per-track fields of a stick export (PC test 2026-11-22).

Every exported row kept the OneLibrary template's file_type (4 = M4A), sample
rate (48000) and file size, and no track got its album: `create_album` was
called with the artist id as a str, which rbox refuses. Ratings were stored x51,
which CDJ-3000X / XDJ-AZ show as no stars. export.pdb is built from these rows,
so it carried the same values.

Real `OneLibraryUsbWriter.sync()` against a fake stick under `tmp_path`, read back
through rbox. Needs rbox + the template; no hardware.
"""

from __future__ import annotations

import gc
import struct
import wave
from pathlib import Path

import pytest

rbox = pytest.importorskip("rbox")

from app import anlz_sidecar  # noqa: E402
from app.library_format_swap import file_type_for  # noqa: E402
from app.usb_one_library import OneLibraryUsbWriter, _audio_format  # noqa: E402
from tests.test_anlz_usb_export import _source_trio  # noqa: E402
from tests.test_onelibrary_track_limit import (  # noqa: E402
    T_TRACKS,
    _decode_string,
    _read_pdb,
    _Source,
)


@pytest.fixture(autouse=True)
def no_analysis(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("sync must use the sidecar, not re-analyse")

    monkeypatch.setattr(anlz_sidecar, "write_companion_anlz", boom)


def _wav(path: Path, rate: int, width: int, seconds: float = 0.2) -> Path:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(b"\0" * int(rate * seconds) * 2 * width)
    return path


def _track(i: int, path: Path, **extra) -> dict:
    return {
        "id": str(100 + i),
        "title": f"Field {i}",
        "artist": f"Artist {i % 2}",
        "album": f"Album {i % 2}",
        "genre": "Techno",
        "key": "8A",
        "label": "",
        "bpm": 128.0,
        "duration_ms": 200,
        "path": str(path),
        **extra,
    }


def _export(tmp_path: Path, tracks: list[dict]) -> dict:
    sidecar = tmp_path / "side"
    _source_trio(sidecar)
    ids = [t["id"] for t in tracks]
    source = _Source(
        tracks,
        [{"id": "p", "name": "P", "parent_id": "ROOT", "type": "1", "track_ids": ids}],
        sidecar,
    )
    stick = tmp_path / "stick"
    stick.mkdir()
    events = list(
        OneLibraryUsbWriter(str(stick)).sync(
            source, audio_copy=True, copy_anlz=True, write_pdb=True
        )
    )
    assert events[-1]["stage"] == "complete", events
    db = rbox.OneLibrary(str(stick / "PIONEER" / "rekordbox" / "exportLibrary.db"))
    try:
        albums = {a.id: a.name for a in db.get_albums()}
        rows = {
            c.title: {
                "file_type": c.file_type,
                "sampling_rate": c.sampling_rate,
                "bit_depth": c.bit_depth,
                "file_size": c.file_size,
                "rating": c.rating,
                "album": albums.get(c.album_id, ""),
                "path": c.path,
            }
            for c in db.get_contents()
            if c.title and not c.title.startswith("__placeholder_")
        }
    finally:
        del db
        gc.collect()
    return {"rows": rows, "stick": stick}


def test_rows_carry_the_files_own_format_size_and_album(tmp_path):
    music = tmp_path / "music"
    music.mkdir()
    cd = _wav(music / "cd.wav", 44100, 2)
    hires = _wav(music / "hires.wav", 96000, 3)
    mp3 = music / "lossy.mp3"
    mp3.write_bytes(b"\xff\xfb" + b"\0" * 64)

    out = _export(
        tmp_path,
        [_track(0, cd, rating=4), _track(1, hires, rating=5), _track(2, mp3, rating=0)],
    )
    rows, stick = out["rows"], out["stick"]

    for title, src in (("Field 0", cd), ("Field 1", hires), ("Field 2", mp3)):
        on_stick = stick / rows[title]["path"].lstrip("/")
        assert rows[title]["file_size"] == src.stat().st_size == on_stick.stat().st_size
    assert (
        rows["Field 0"]["file_type"],
        rows["Field 0"]["sampling_rate"],
        rows["Field 0"]["bit_depth"],
    ) == (11, 44100, 16)
    assert (
        rows["Field 1"]["file_type"],
        rows["Field 1"]["sampling_rate"],
        rows["Field 1"]["bit_depth"],
    ) == (11, 96000, 24)
    assert (rows["Field 2"]["file_type"], rows["Field 2"]["bit_depth"]) == (1, 16)
    assert [rows[f"Field {i}"]["rating"] for i in range(3)] == [4, 5, 0]
    assert [rows[f"Field {i}"]["album"] for i in range(3)] == ["Album 0", "Album 1", "Album 0"]


def test_export_pdb_rows_carry_the_same_fields(tmp_path):
    music = tmp_path / "music"
    music.mkdir()
    cd = _wav(music / "cd.wav", 44100, 2)
    hires = _wav(music / "hires.wav", 96000, 3)
    out = _export(tmp_path, [_track(0, cd, rating=3), _track(1, hires, rating=5)])

    tables = _read_pdb(out["stick"] / "PIONEER" / "rekordbox" / "export.pdb")
    rows = {}
    for page in tables[T_TRACKS]:
        for row in page:
            offs = struct.unpack_from("<21H", row, 0x5E)
            title = _decode_string(row, offs[17])
            rows[title] = {
                "sample_rate": struct.unpack_from("<I", row, 0x08)[0],
                "file_size": struct.unpack_from("<I", row, 0x10)[0],
                "sample_depth": struct.unpack_from("<H", row, 0x52)[0],
                "rating": row[0x59],
                "file_type": struct.unpack_from("<H", row, 0x5A)[0],
            }
    assert rows["Field 0"] == {
        "sample_rate": 44100,
        "file_size": cd.stat().st_size,
        "sample_depth": 16,
        "rating": 3,
        "file_type": 11,
    }
    assert rows["Field 1"] == {
        "sample_rate": 96000,
        "file_size": hires.stat().st_size,
        "sample_depth": 24,
        "rating": 5,
        "file_type": 11,
    }


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("a.mp3", 1),
        ("a.M4A", 4),
        ("a.aac", 4),
        ("a.flac", 5),
        ("a.wav", 11),
        ("a.aif", 12),
        ("a.aiff", 12),
        ("a.ogg", 0),
    ],
)
def test_file_type_codes(name: str, code: int) -> None:
    assert file_type_for(name) == code


def test_audio_format_of_an_unreadable_file(tmp_path: Path) -> None:
    junk = tmp_path / "x.flac"
    junk.write_bytes(b"not audio")
    assert _audio_format(junk) == (5, 0, 0, 9)
    assert _audio_format(tmp_path / "missing.wav") == (11, 0, 0, 0)
