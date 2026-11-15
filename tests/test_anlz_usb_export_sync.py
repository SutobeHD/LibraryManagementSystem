"""Full `OneLibraryUsbWriter.sync()` with copy_anlz=True against the real template.

Pins what reaches the stick end to end: the row's `analysis_data_file_path`
names a written `.DAT` in the track's own bucket, that file's PPTH equals the
row's audio path, the PSSI is masked, and export.pdb still gets written. Needs
rbox + `app/templates/exportLibrary_template.db`; no hardware.
"""

from __future__ import annotations

import gc
import struct
from pathlib import Path

import pytest

rbox = pytest.importorskip("rbox")

from app import anlz_sidecar  # noqa: E402
from app.usb_one_library import OneLibraryUsbWriter  # noqa: E402
from tests.test_anlz_usb_export import _ppth, _source_trio, _tags  # noqa: E402


class _Source:
    mode = "xml"

    def __init__(self, tracks, sidecars):
        self.tracks, self.sidecars = tracks, sidecars

    def iter_tracks(self):
        return iter(self.tracks)

    def iter_playlists(self):
        return iter([])

    def get_playlist_track_ids(self, pid):
        return []

    def get_anlz_sidecar_dir(self, track):
        return self.sidecars.get(track["id"])


def _track(tid: str, title: str, audio: Path) -> dict:
    return {
        "id": tid,
        "title": title,
        "artist": "Artist",
        "album": "",
        "genre": "",
        "key": "",
        "label": "",
        "bpm": 128.0,
        "duration_ms": 30000,
        "path": str(audio),
    }


@pytest.fixture
def no_analysis(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("sync must use the sidecar, not re-analyse")

    monkeypatch.setattr(anlz_sidecar, "write_companion_anlz", boom)


def _rows(stick: Path) -> dict[str, tuple[str, str]]:
    db = rbox.OneLibrary(str(stick / "PIONEER" / "rekordbox" / "exportLibrary.db"))
    try:
        return {c.title: (c.path, c.analysis_data_file_path) for c in db.get_contents()}
    finally:
        del db
        gc.collect()


def test_sync_ships_the_sidecar_with_stick_ppth_and_masked_pssi(tmp_path, no_analysis):
    audio = tmp_path / "music" / "Track.mp3"
    audio.parent.mkdir()
    audio.write_bytes(b"\xff\xfb" + b"\0" * 4000)
    side = tmp_path / "side"
    _source_trio(side)
    stick = tmp_path / "stick"

    events = list(
        OneLibraryUsbWriter(str(stick)).sync(
            _Source([_track("42", "Track", audio)], {"42": side}),
            audio_copy=True,
            copy_anlz=True,
            write_pdb=True,
        )
    )
    assert not [e for e in events if e.get("stage") == "error"], events

    path, anlz = _rows(stick)["Track"]
    assert path.startswith("/Contents/")
    assert anlz.startswith("/PIONEER/USBANLZ/P000/") and anlz.endswith("/ANLZ0000.DAT")
    dat = stick / anlz.lstrip("/")
    assert _ppth(dat.read_bytes()) == path
    assert sorted(p.name for p in dat.parent.iterdir()) == [
        "ANLZ0000.2EX",
        "ANLZ0000.DAT",
        "ANLZ0000.EXT",
    ]
    ext = dict(_tags(dat.with_suffix(".EXT").read_bytes()))
    plain = dict(_tags((side / "ANLZ0000.EXT").read_bytes()))
    assert ext[b"PQT2"] == plain[b"PQT2"]
    mood = struct.unpack(">H", ext[b"PSSI"][0x12:0x14])[0]
    assert ext[b"PSSI"] != plain[b"PSSI"] and not 1 <= mood <= 3, "PSSI must ship masked"
    assert (stick / "PIONEER" / "rekordbox" / "export.pdb").stat().st_size > 0
