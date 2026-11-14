"""ANLZ trio -> USB stick transform (`app.anlz_usb_export`) and its wiring in
`OneLibraryUsbWriter._generate_or_copy_anlz_for`.

No Rekordbox install, no hardware: the "source" trio is built with the
production ANLZ builders, the library source is a stub. The rbox round trip runs
in a subprocess because rbox aborts the whole process on input it rejects.
"""

from __future__ import annotations

import errno
import json
import os
import struct
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from app import anlz_usb_export as ux
from app.anlz_writer import build_2ex, build_dat, build_ext

LOCAL = "C:/Users/dj/Music/Artist/Track.mp3"
STICK = "/Contents/Artist/Track/Track.mp3"
BEATS = [{"beat_number": (i % 4) + 1, "tempo": 12800, "time_ms": 500 + i * 469} for i in range(64)]
PHRASES = [
    {"start_ms": 0, "end_ms": 15000, "label": "Intro", "mood": "mid"},
    {"start_ms": 15000, "end_ms": 30000, "label": "Chorus", "mood": "mid"},
]
NAMES = ["ANLZ0000.DAT", "ANLZ0000.EXT", "ANLZ0000.2EX"]


def _tags(data: bytes) -> list[tuple[bytes, bytes]]:
    pos, out = struct.unpack(">I", data[4:8])[0], []
    while pos + 12 <= len(data):
        n = struct.unpack(">I", data[pos + 8 : pos + 12])[0]
        out.append((data[pos : pos + 4], data[pos : pos + n]))
        pos += n
    return out


def _ppth(data: bytes) -> str:
    tag = dict(_tags(data))[b"PPTH"]
    n = struct.unpack(">I", tag[12:16])[0]
    return tag[16 : 16 + n].decode("utf-16-be").rstrip("\x00")


def _source_trio(folder: Path) -> Path:
    """Analysis-shaped trio: local PPTH, plain PSSI, empty cue lists."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "ANLZ0000.DAT").write_bytes(build_dat(LOCAL, BEATS, [0] * 400, [7] * 400, [3] * 100))
    (folder / "ANLZ0000.EXT").write_bytes(
        build_ext(
            LOCAL,
            BEATS,
            [1] * 900,
            [2] * 900,
            [[1, 2, 3, 4, 5, 6]] * 1200,
            phrases=PHRASES,
            duration_ms=30000,
            bpm=128.0,
        )
    )
    (folder / "ANLZ0000.2EX").write_bytes(build_2ex(LOCAL, [[1, 2, 3]] * 300, [[4, 5, 6]] * 1200))
    return folder / "ANLZ0000.DAT"


# ── transform ────────────────────────────────────────────────────────────


def test_ppth_becomes_stick_path_and_everything_else_rides_verbatim(tmp_path):
    dat = _source_trio(tmp_path / "src")
    written = ux.export_trio(dat, tmp_path / "usb", STICK)
    assert written == NAMES
    for name in written:
        src = (tmp_path / "src" / name).read_bytes()
        out = (tmp_path / "usb" / name).read_bytes()
        assert _ppth(src) == LOCAL
        assert _ppth(out) == STICK
        assert ux.is_complete_anlz(out), f"{name}: len_file / tag chain broken"
        assert out[:8] == src[:8] and out[12:28] == src[12:28], "PMAI header carried verbatim"
        keep = [t for t in _tags(src) if t[0] not in (b"PPTH", b"PSSI")]
        assert keep == [t for t in _tags(out) if t[0] not in (b"PPTH", b"PSSI")]


def test_pssi_is_masked_once_and_unmasks_to_the_original(tmp_path):
    dat = _source_trio(tmp_path / "src")
    ux.export_trio(dat, tmp_path / "usb", STICK)
    plain = dict(_tags((tmp_path / "src" / "ANLZ0000.EXT").read_bytes()))[b"PSSI"]
    masked = dict(_tags((tmp_path / "usb" / "ANLZ0000.EXT").read_bytes()))[b"PSSI"]
    assert masked != plain
    assert masked[:0x12] == plain[:0x12], "tag header + len_entries stay in clear"
    assert ux.mask_pssi(masked) == masked, "an already-masked tag must not be masked twice"
    n = struct.unpack(">H", plain[0x10:0x12])[0]
    key = bytes((b + n) & 0xFF for b in ux._PSSI_MASK_BASE)
    unmasked = bytes(
        b ^ key[(i - 0x12) % len(key)] if i >= 0x12 else b for i, b in enumerate(masked)
    )
    assert unmasked == plain


def test_mask_key_is_the_documented_song_structure_key():
    """djl-analysis / rekordcrate key bytes; each gets len_entries added mod 256."""
    assert list(ux._PSSI_MASK_BASE) == [
        0xCB, 0xE1, 0xEE, 0xFA, 0xE5, 0xEE, 0xAD, 0xEE, 0xE9, 0xD2,
        0xE9, 0xEB, 0xE1, 0xE9, 0xF3, 0xE8, 0xE9, 0xF4, 0xE1,
    ]  # fmt: skip
    assert bytes((b + 19) & 0xFF for b in ux._PSSI_MASK_BASE) == bytes.fromhex(
        "def4010df801c001fce5fcfef4fc06fbfc07f4"
    )


_RBOX_READBACK = textwrap.dedent(
    """
    import json, sys
    import rbox

    out = {}
    for label, path in (("src", sys.argv[1]), ("usb", sys.argv[2])):
        ext = rbox.Anlz(path + "/ANLZ0000.EXT")
        ss = ext.get_song_structure()
        out[label] = {
            "path": rbox.Anlz(path + "/ANLZ0000.DAT").get_path(),
            "mood": ss.mood,
            "phrases": [[p.index, p.beat, p.kind] for p in ss.phrases],
        }
    print(json.dumps(out))
    """
)


def test_rbox_reads_the_stick_path_and_unmasks_the_pssi(tmp_path):
    """Independent reader: rbox (rekordcrate) detects the mask and decodes it back."""
    pytest.importorskip("rbox")
    dat = _source_trio(tmp_path / "src")
    ux.export_trio(dat, tmp_path / "usb", STICK)
    proc = subprocess.run(
        [sys.executable, "-c", _RBOX_READBACK, str(tmp_path / "src"), str(tmp_path / "usb")],
        capture_output=True,
        encoding="utf-8",
        errors="replace",  # rbox panics print non-ASCII box drawing
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    res = json.loads(proc.stdout.strip().splitlines()[-1])
    assert res["src"]["path"] == LOCAL
    assert res["usb"]["path"] == STICK
    assert res["src"]["mood"] == res["usb"]["mood"] == 2
    assert res["usb"]["phrases"] == res["src"]["phrases"]
    assert len(res["usb"]["phrases"]) == len(PHRASES)


def test_empty_stick_path_keeps_the_original_ppth(tmp_path):
    dat = _source_trio(tmp_path / "src")
    ux.export_trio(dat, tmp_path / "usb", "")
    assert _ppth((tmp_path / "usb" / "ANLZ0000.DAT").read_bytes()) == LOCAL


@pytest.mark.parametrize(
    "mangle",
    [
        pytest.param(lambda d: d[:-10], id="truncated"),
        pytest.param(lambda d: d + b"\0" * 8, id="trailing-bytes"),
        pytest.param(lambda d: b"XXXX" + d[4:], id="bad-magic"),
        pytest.param(lambda d: d[:4] + struct.pack(">I", 32) + d[8:], id="header-len"),
    ],
)
def test_is_complete_anlz_rejects_damaged_files(tmp_path, mangle):
    dat = _source_trio(tmp_path / "src")
    good = dat.read_bytes()
    assert ux.is_complete_anlz(good)
    assert not ux.is_complete_anlz(mangle(good))


def test_one_damaged_sibling_rejects_the_whole_source(tmp_path):
    dat = _source_trio(tmp_path / "src")
    ext = tmp_path / "src" / "ANLZ0000.EXT"
    ext.write_bytes(ext.read_bytes()[:-10])  # half-written by a running analysis
    assert ux.export_trio(dat, tmp_path / "usb", STICK) == []
    assert not (tmp_path / "usb").exists()


def test_missing_dat_is_no_source(tmp_path):
    dat = _source_trio(tmp_path / "src")
    dat.unlink()
    assert ux.export_trio(dat, tmp_path / "usb", STICK) == []


def test_backups_and_stale_siblings_never_reach_the_stick(tmp_path):
    usb = tmp_path / "usb"
    usb.mkdir()
    (usb / "ANLZ0000.2EX").write_bytes(b"previous track in this slot")
    (usb / "ANLZ0000.DAT.part").write_bytes(b"left over by a crash")
    (usb / "notes.txt").write_bytes(b"not ours")
    src = tmp_path / "src"
    dat = _source_trio(src)
    (src / "ANLZ0000.2EX").unlink()
    (src / "ANLZ0000.DAT.bak-20260101-000000").write_bytes(b"backup")
    (src / "ANLZ0001.DAT").write_bytes(b"foreign")

    assert ux.export_trio(dat, usb, STICK) == ["ANLZ0000.DAT", "ANLZ0000.EXT"]
    assert sorted(p.name for p in usb.iterdir()) == ["ANLZ0000.DAT", "ANLZ0000.EXT", "notes.txt"]


def test_fresh_file_survives_a_case_variant_of_its_name(tmp_path):
    """FAT/exFAT keep the old entry's case on replace; the cleanup must not delete it."""
    usb = tmp_path / "usb"
    usb.mkdir()
    (usb / "anlz0000.dat").write_bytes(b"old")
    dat = _source_trio(tmp_path / "src")
    ux.export_trio(dat, usb, STICK)
    assert _ppth((usb / "ANLZ0000.DAT").read_bytes()) == STICK


def test_unreadable_source_is_a_source_error_not_a_stick_error(tmp_path, monkeypatch):
    dat = _source_trio(tmp_path / "src")
    real = Path.read_bytes

    def flaky(self):
        if self.suffix == ".EXT":
            raise PermissionError(errno.EACCES, "locked by Rekordbox")
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", flaky)
    assert ux.export_trio(dat, tmp_path / "usb", STICK) == []


def test_stick_write_failure_raises_and_leaves_the_old_trio_and_no_parts(tmp_path, monkeypatch):
    usb = tmp_path / "usb"
    usb.mkdir()
    (usb / "ANLZ0000.DAT").write_bytes(b"old")
    dat = _source_trio(tmp_path / "src")

    def full(*_a, **_k):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(ux.os, "replace", full)
    with pytest.raises(ux.UsbWriteError) as info:
        ux.export_trio(dat, usb, STICK)
    assert not isinstance(info.value, OSError), "must not be swallowed by `except OSError`"
    assert sorted(p.name for p in usb.iterdir()) == ["ANLZ0000.DAT"]
    assert (usb / "ANLZ0000.DAT").read_bytes() == b"old"


def test_unwritable_bucket_raises_usb_write_error(tmp_path):
    blocker = tmp_path / "usb"
    blocker.write_bytes(b"a file where the bucket folder should go")
    dat = _source_trio(tmp_path / "src")
    with pytest.raises(ux.UsbWriteError):
        ux.export_trio(dat, blocker / "P000" / "00000001", STICK)


# ── wiring: OneLibraryUsbWriter._generate_or_copy_anlz_for ───────────────


class _Src:
    def __init__(self, sidecar=None):
        self.sidecar = sidecar

    def get_anlz_sidecar_dir(self, track):
        return self.sidecar


def _writer(tmp_path):
    from app.usb_one_library import OneLibraryUsbWriter

    return OneLibraryUsbWriter(str(tmp_path / "stick"))


def _no_analysis(monkeypatch):
    from app import anlz_sidecar

    def boom(*_a, **_k):
        raise AssertionError("must not re-analyse")

    monkeypatch.setattr(anlz_sidecar, "write_companion_anlz", boom)


def test_sidecar_ships_with_the_stick_path(tmp_path, monkeypatch):
    _no_analysis(monkeypatch)
    side = tmp_path / "side"
    _source_trio(side)
    (side / "ANLZ0000.EXT.bak-20260101-000000").write_bytes(b"backup")
    w = _writer(tmp_path)

    rel = w._generate_or_copy_anlz_for({"id": "7"}, "7", _Src(side), STICK)

    assert rel == "/PIONEER/USBANLZ/P000/00000007/ANLZ0000.DAT"
    bucket = w.anlz_root / "P000" / "00000007"
    assert sorted(p.name for p in bucket.iterdir()) == sorted(NAMES)
    assert all(_ppth((bucket / n).read_bytes()) == STICK for n in NAMES)


def test_invalid_sidecar_falls_back_to_a_fresh_analysis(tmp_path, monkeypatch):
    from app import anlz_sidecar

    audio = tmp_path / "music" / "Track.mp3"
    audio.parent.mkdir()
    audio.write_bytes(b"\xff\xfb")
    side = tmp_path / "side"
    _source_trio(side)
    (side / "ANLZ0000.DAT").write_bytes(b"PMAI" + b"\0" * 10)
    calls = []

    def fresh(path):
        calls.append(path)
        _source_trio(tmp_path / "fresh")
        return tmp_path / "fresh"

    monkeypatch.setattr(anlz_sidecar, "write_companion_anlz", fresh)
    w = _writer(tmp_path)

    rel = w._generate_or_copy_anlz_for({"id": "7", "path": str(audio)}, "7", _Src(side), STICK)

    assert calls == [audio]
    assert rel == "/PIONEER/USBANLZ/P000/00000007/ANLZ0000.DAT"
    out = (w.anlz_root / "P000" / "00000007" / "ANLZ0000.DAT").read_bytes()
    assert out == ux.to_usb_bytes((tmp_path / "fresh" / "ANLZ0000.DAT").read_bytes(), STICK)


def test_no_source_and_no_audio_returns_none(tmp_path, monkeypatch):
    _no_analysis(monkeypatch)
    w = _writer(tmp_path)
    assert w._generate_or_copy_anlz_for({"id": "7", "path": ""}, "7", _Src(), STICK) is None
    missing = str(tmp_path / "gone.mp3")
    assert w._generate_or_copy_anlz_for({"id": "7", "path": missing}, "7", _Src(), STICK) is None
    assert not os.path.exists(w.anlz_root / "P000" / "00000007")


# ── B7: Rekordbox's own analysis first, nothing written into the music folder ──


class _LiveSrc(_Src):
    def __init__(self, rekordbox_dat=None, sidecar=None):
        super().__init__(sidecar)
        self.rekordbox_dat = rekordbox_dat

    def get_rekordbox_anlz_dat(self, track):
        return self.rekordbox_dat


def test_rekordbox_anlz_wins_over_sidecar_and_analysis(tmp_path, monkeypatch):
    _no_analysis(monkeypatch)
    rb = _source_trio(tmp_path / "share" / "PIONEER" / "USBANLZ" / "44d" / "abc")
    side = _source_trio(tmp_path / "side").parent  # a valid LMS sidecar too
    # Make the two sources distinguishable: the Rekordbox DAT gets one more beat.
    rb.write_bytes(build_dat(LOCAL, [*BEATS, BEATS[-1]], [0] * 400, [7] * 400, [3] * 100))
    w = _writer(tmp_path)

    rel = w._generate_or_copy_anlz_for({"id": "7"}, "7", _LiveSrc(rb, side), STICK)

    assert rel == "/PIONEER/USBANLZ/P000/00000007/ANLZ0000.DAT"
    out = (w.anlz_root / "P000" / "00000007" / "ANLZ0000.DAT").read_bytes()
    assert out == ux.to_usb_bytes(rb.read_bytes(), STICK)


def test_invalid_rekordbox_anlz_falls_back_to_the_lms_sidecar(tmp_path, monkeypatch):
    _no_analysis(monkeypatch)
    rb = tmp_path / "share" / "ANLZ0000.DAT"
    rb.parent.mkdir(parents=True)
    rb.write_bytes(b"PMAI" + b"\0" * 10)
    side = tmp_path / "side"
    _source_trio(side)
    w = _writer(tmp_path)

    rel = w._generate_or_copy_anlz_for({"id": "7"}, "7", _LiveSrc(rb, side), STICK)

    assert rel == "/PIONEER/USBANLZ/P000/00000007/ANLZ0000.DAT"
    out = (w.anlz_root / "P000" / "00000007" / "ANLZ0000.DAT").read_bytes()
    assert out == ux.to_usb_bytes((side / "ANLZ0000.DAT").read_bytes(), STICK)


def test_fresh_analysis_fallback_never_writes_into_the_music_folder(
    tmp_path, monkeypatch, anlz_cache_sandbox
):
    from app import anlz_sidecar

    music = tmp_path / "music"
    music.mkdir()
    audio = music / "Track.mp3"
    audio.write_bytes(b"\xff\xfb")

    def _write(**kw):
        _source_trio(Path(kw["anlz_dir"]))
        return {"dat": "x"}

    monkeypatch.setattr("app.anlz_writer.write_anlz_files", _write)
    monkeypatch.setattr(
        "app.analysis_engine.run_full_analysis", lambda p: {"status": "ok", "waveform": {}}
    )
    w = _writer(tmp_path)

    rel = w._generate_or_copy_anlz_for(
        {"id": "7", "path": str(audio)}, "7", _LiveSrc(None, None), STICK
    )

    assert rel == "/PIONEER/USBANLZ/P000/00000007/ANLZ0000.DAT"
    assert sorted(p.name for p in music.iterdir()) == ["Track.mp3"]
    assert anlz_sidecar.sidecar_dir_for(audio).is_relative_to(anlz_cache_sandbox)
