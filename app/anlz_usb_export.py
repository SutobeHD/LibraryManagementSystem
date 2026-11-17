"""Ready one track's ANLZ trio for a USB stick: the transform Rekordbox applies on export.

Rekordbox's own export of an analysed track differs from the share copy in two
tags only. Measured against pyrekordbox's paired Rekordbox-6 `share/` vs
`export/` test files (3 tracks x DAT/EXT/2EX, not vendored here): 9 of 9 files
are byte-identical to Rekordbox's export after this transform.

  - PPTH holds the audio path ON THE STICK (`/Contents/...`), not the local one;
  - the PSSI phrase body is XOR-masked (Deep-Symmetry "song structure" mask,
    the key rekordcrate/rbox unmasks with — tests/test_anlz_usb_export.py
    checks the round trip through rbox).

Every other tag (PQTZ/PQT2 grid, PCOB/PCO2 cue lists, PWAV..PWV7 waveforms,
PVBR) rides through byte-for-byte, and so does the 28-byte PMAI header except
`len_file`. Which source the files come from is the caller's choice.
"""

from __future__ import annotations

import contextlib
import logging
import os
import struct
from pathlib import Path

from .anlz_cue_patch import _walk_tags
from .anlz_writer import PMAI_HEADER_LEN, PMAI_MAGIC, _build_ppth

logger = logging.getLogger(__name__)

ANLZ_SUFFIXES = (".DAT", ".EXT", ".2EX")

# Song-structure mask (djl-analysis anlz "Song Structure Tag"; rekordcrate
# `SongStructureData`): every key byte gets `len_entries` added (mod 256) and the
# tag is XORed from the mood field (0x12) to its end.
_PSSI_MASK_BASE = bytes.fromhex("CBE1EEFAE5EEADEEE9D2E9EBE1E9F3E8E9F4E1")
_PSSI_LEN_ENTRIES = 0x10
_PSSI_MOOD = 0x12


class UsbWriteError(Exception):
    """Writing to the stick failed (full, removed, read-only, I/O error).

    Deliberately not an OSError: a source that cannot be read is a reason to try
    the next source, a stick that cannot be written is not, and a broad
    `except OSError` must not turn one into the other.
    """


def is_complete_anlz(data: bytes) -> bool:
    """PMAI root, 28-byte header, `len_file == size`, tag chain ending exactly at EOF.

    Rekordbox and LMS both rewrite these files in place; a half-written copy must
    fall through to the next source, never land on the stick.
    """
    if len(data) < PMAI_HEADER_LEN or data[:4] != PMAI_MAGIC:
        return False
    len_header, len_file = struct.unpack(">II", data[4:12])
    if len_header != PMAI_HEADER_LEN or len_file != len(data):
        return False
    _tags, end = _walk_tags(data)
    return end == len(data)


def _pssi_is_plain(tag: bytes) -> bool:
    if len(tag) < _PSSI_MOOD + 2:
        return False
    mood = struct.unpack(">H", tag[_PSSI_MOOD : _PSSI_MOOD + 2])[0]
    return 1 <= mood <= 3


def mask_pssi(tag: bytes) -> bytes:
    """XOR-mask a plain PSSI tag the way Rekordbox 6+ writes it to a stick.

    A tag whose mood is not a plain 1..3 is returned unchanged, so a source that
    is itself an export is never masked twice (readers tell the two apart by the
    mood value the same way).
    """
    if not _pssi_is_plain(tag):
        return tag
    n = struct.unpack(">H", tag[_PSSI_LEN_ENTRIES : _PSSI_LEN_ENTRIES + 2])[0]
    key = bytes((b + n) & 0xFF for b in _PSSI_MASK_BASE)
    out = bytearray(tag)
    for i in range(_PSSI_MOOD, len(out)):
        out[i] ^= key[(i - _PSSI_MOOD) % len(key)]
    return bytes(out)


def to_usb_bytes(data: bytes, usb_audio_path: str) -> bytes:
    """`data` with PPTH := `usb_audio_path` (kept when that is empty) and PSSI masked."""
    tags, end = _walk_tags(data)
    body = bytearray()
    for magic, start, total_len in tags:
        tag = data[start : start + total_len]
        if magic == b"PPTH" and usb_audio_path:
            tag = _build_ppth(usb_audio_path)
        elif magic == b"PSSI":
            tag = mask_pssi(tag)
        body += tag
    body += data[end:]
    header = bytearray(data[:PMAI_HEADER_LEN])
    struct.pack_into(">I", header, 8, PMAI_HEADER_LEN + len(body))
    return bytes(header) + bytes(body)


def _read_source(src_dat: Path) -> dict[str, bytes]:
    """The `.DAT` and its `.EXT`/`.2EX` siblings, or {} if any present file is bad.

    All-or-nothing: one truncated sibling rejects the whole source, so a stick
    never mixes two analyses. Only these three names are read — a glob would
    also pick up `ANLZ0000.DAT.bak-*` backups.
    """
    sources: dict[str, bytes] = {}
    for suffix in ANLZ_SUFFIXES:
        src = src_dat.with_suffix(suffix)
        try:
            if not src.is_file():
                continue
            data = src.read_bytes()
        except OSError as exc:
            logger.info("[ANLZ-USB] unreadable source %s: %s", src, exc)
            return {}
        if not is_complete_anlz(data):
            logger.info("[ANLZ-USB] rejected incomplete source %s", src)
            return {}
        sources[suffix] = data
    return sources if ".DAT" in sources else {}


def _remove_stale(dst_dir: Path, keep: set[str]) -> None:
    """Delete ANLZ* in `dst_dir` except `keep` (compared case-insensitively).

    Case-insensitive so a fresh `ANLZ0000.DAT` is never deleted for matching an
    older `anlz0000.dat` entry on a FAT/exFAT stick.
    """
    keep_upper = {name.upper() for name in keep}
    for entry in dst_dir.iterdir():
        name = entry.name.upper()
        if name.startswith("ANLZ") and name not in keep_upper:
            entry.unlink()


def export_trio(src_dat: Path, dst_dir: Path, usb_audio_path: str) -> list[str]:
    """Write `src_dat` and its `.EXT`/`.2EX` siblings into `dst_dir`, transformed for USB.

    Returns the written file names (`.DAT` first), or [] when the source is
    missing or invalid — the caller then tries its next source. Raises
    UsbWriteError when the stick cannot be written.

    Every file is staged as `<name>.part` before any is renamed into place, so a
    full stick fails before the old trio is touched. ANLZ* files in `dst_dir`
    this source does not provide are removed afterwards: the bucket is keyed by
    the stick's content id, which another track may have held on the last sync.
    """
    src_dat = Path(src_dat)
    sources = _read_source(src_dat)
    if not sources:
        return []
    staged = {
        f"{src_dat.stem}{sfx}": to_usb_bytes(data, usb_audio_path) for sfx, data in sources.items()
    }

    parts: list[Path] = []
    try:
        dst_dir.mkdir(parents=True, exist_ok=True)
        for name, data in staged.items():
            part = dst_dir / f"{name}.part"
            parts.append(part)
            part.write_bytes(data)
        for name in staged:
            os.replace(dst_dir / f"{name}.part", dst_dir / name)
        _remove_stale(dst_dir, set(staged))
    except OSError as exc:
        for part in parts:
            with contextlib.suppress(OSError):
                part.unlink(missing_ok=True)
        raise UsbWriteError(f"ANLZ write to {dst_dir} failed: {exc}") from exc
    return list(staged)
