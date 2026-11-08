"""Stage D of docs/LIBRARY_ANALYSIS_HANDOVER.md: read Rekordbox's own ANLZ analysis files.

Strictly read-only. Every ANLZ file is opened with mode "rb", master.db is only read through
`app.anlz_safe.resolve_anlz_paths`, and nothing here imports the analysis writer or the cache.

Per track the reader measures:
  PQTZ        grid present, beat count, bars, first downbeat, tempo changes (distinct BPM values)
  PQT2        extended grid present, entry count, anchor tempos (EXT)
  PCOB / PCO2 hot cues, memory cues, loops, colours, comments
  PSSI        masked or plain, mood, phrase count + kind sequence, intro / outro bars, chorus count
  PWV6 / PWV7 3-band waveform: mean low / mid / high, bass share, brightness, 10-segment energy curve
  PWV4 / PWV5 colour waveform presence + RGB means as a second brightness proxy
  PPTH        path stored in the ANLZ vs the real path from the snapshot
  writer      "rekordbox" | "lms" | "unknown" | "conflict" from header fields LMS writes differently

PSSI unmasking: pyrekordbox 0.1.7 parses a masked PSSI into garbage (mood outside 1..3). The XOR
routine below is copied from `app/anlz_usb_export.py:mask_pssi` (PR #60); the XOR is symmetric, so
the same bytes-op unmasks when the "is plain" test is inverted.

3-band byte order (PWV6 / PWV7): [low, mid, high] per 3-byte frame. Measured 2026-11-08 on 30
library tracks: byte 0 correlates +0.75 with the PWV5 red channel, byte 1 +0.44 with green, byte 2
+0.54 with blue (Rekordbox RGB waveform: red = low, green = mid, blue = high). The djl-analysis page
says "mid, high, low"; the numbers here say otherwise, so the measured order is used.

Usage:
  python scripts/library_measure_anlz.py --input tmp/library-analysis/tracks.json --limit 200
  python scripts/library_measure_anlz.py --input tmp/library-analysis/tracks.json \
      --db %APPDATA%/Pioneer/rekordbox/master.db --out tmp/library-analysis/measure/anlz.jsonl
  python scripts/library_measure_anlz.py --summary-only --out tmp/library-analysis/measure/anlz.jsonl
"""

from __future__ import annotations

import argparse
import itertools
import json
import logging
import struct
import sys
import time
from collections import Counter
from collections.abc import Iterable, Sequence
from pathlib import Path, PureWindowsPath
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pyrekordbox.anlz import AnlzFile  # noqa: E402
from pyrekordbox.anlz import structs as anlz_structs  # noqa: E402
from pyrekordbox.anlz.tags import TAGS as ANLZ_TAGS  # noqa: E402

from app.anlz_cue_patch import _walk_tags  # noqa: E402
from app.anlz_writer import PMAI_HEADER_LEN  # noqa: E402

logger = logging.getLogger("library_measure_anlz")

DEFAULT_DB = Path.home() / "AppData" / "Roaming" / "Pioneer" / "rekordbox" / "master.db"
DEFAULT_INPUT = ROOT / "tmp" / "library-analysis" / "tracks.json"
DEFAULT_OUT = ROOT / "tmp" / "library-analysis" / "measure" / "anlz.jsonl"
PROGRESS_EVERY = 500
ANLZ_KINDS = ("DAT", "EXT", "EX2")
TAG_PREFIX_LEN = 12
TEMPO_TOL_BPM = 0.05
CURVE_SEGMENTS = 10

# --------------------------------------------------------------------------- PSSI mask
# Copied from app/anlz_usb_export.py (PR #60, branch claude/dreamy-planck-w7771v): _PSSI_MOOD,
# _PSSI_LEN_ENTRIES, _PSSI_MASK_BASE, _pssi_is_plain, mask_pssi. Replace with
# `from app.anlz_usb_export import mask_pssi` after this branch is rebased onto PR #60.
_PSSI_MASK_BASE = bytes.fromhex("CBE1EEFAE5EEADEEE9D2E9EBE1E9F3E8E9F4E1")
_PSSI_LEN_ENTRIES = 0x10
_PSSI_MOOD = 0x12
_PSSI_END_BEAT = 0x1A
_PSSI_U2 = 0x1C
_PSSI_LMS_END_BEAT = 0x16  # where app/anlz_writer.py:_build_pssi puts end_beat (pyrekordbox's u1)
_PSSI_HEADER_LEN = 32
_PQT2_U3 = 44  # offset of pyrekordbox's PQT2 u3 inside the tag; LMS writes 0, Rekordbox a hash


def pssi_is_plain(tag: bytes) -> bool:
    if len(tag) < _PSSI_MOOD + 2:
        return False
    mood = struct.unpack(">H", tag[_PSSI_MOOD : _PSSI_MOOD + 2])[0]
    return 1 <= mood <= 3


def pssi_is_masked(tag: bytes) -> bool:
    return len(tag) >= _PSSI_MOOD + 2 and not pssi_is_plain(tag)


def _pssi_xor(tag: bytes) -> bytes:
    n = struct.unpack(">H", tag[_PSSI_LEN_ENTRIES : _PSSI_LEN_ENTRIES + 2])[0]
    key = bytes((b + n) & 0xFF for b in _PSSI_MASK_BASE)
    out = bytearray(tag)
    for i in range(_PSSI_MOOD, len(out)):
        out[i] ^= key[(i - _PSSI_MOOD) % len(key)]
    return bytes(out)


def mask_pssi(tag: bytes) -> bytes:
    """Plain PSSI -> masked (the USB-export form). Anything else is returned unchanged."""
    return _pssi_xor(tag) if pssi_is_plain(tag) else tag


def unmask_pssi(tag: bytes) -> bytes:
    """Masked PSSI -> plain. A plain or too-short tag is returned unchanged."""
    return _pssi_xor(tag) if pssi_is_masked(tag) else tag


# --------------------------------------------------------------------------- loading


def unmask_anlz_bytes(data: bytes) -> tuple[bytes, bool | None]:
    """`data` with every PSSI tag unmasked, plus True (was masked) / False (plain) / None (no PSSI).

    Every other tag and any trailing bytes after the last well-formed tag are carried verbatim, so
    the result has the same length as the input.
    """
    tags, end = _walk_tags(data)
    masked: bool | None = None
    body = bytearray()
    for magic, start, total_len in tags:
        tag = data[start : start + total_len]
        if magic == b"PSSI":
            masked = pssi_is_masked(tag)
            tag = unmask_pssi(tag)
        body += tag
    return data[:PMAI_HEADER_LEN] + bytes(body) + data[end:], masked


def _short_error(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {str(exc).splitlines()[0] if str(exc) else ''}"[:200]


def _parse_tolerant(plain: bytes) -> tuple[AnlzFile, dict[str, str]]:
    """Per-tag pyrekordbox parse. A tag that fails (pyrekordbox's `Const` fields are stricter
    than Rekordbox's writer: PQT2 u1 0x02000002, PCPT u1 0x100000 seen 2026-11-08) is dropped
    and recorded; every other tag is still available."""
    anlz = AnlzFile()
    anlz.file_header = anlz_structs.AnlzFileHeader.parse(plain)
    errors: dict[str, str] = {}
    for magic, start, total_len in _walk_tags(plain)[0]:
        name = magic.decode("ascii", "replace")
        cls = ANLZ_TAGS.get(name)
        if cls is None:  # PVB2 etc.: AnlzFile.parse skips these too
            continue
        try:
            anlz.tags.append(cls(plain[start : start + total_len]))
        except Exception as exc:
            errors[name] = _short_error(exc)
    return anlz, errors


def parse_anlz(data: bytes) -> tuple[AnlzFile, bool | None, dict[str, str]]:
    """Unmask PSSI, then parse with pyrekordbox.

    Returns (AnlzFile, pssi_masked, tag_errors). `AnlzFile.parse` is tried first; when it rejects
    the file, the tags are parsed one by one and the failing ones are listed in `tag_errors`.
    """
    plain, masked = unmask_anlz_bytes(data)
    try:
        return AnlzFile.parse(plain), masked, {}
    except Exception as exc:
        anlz, errors = _parse_tolerant(plain)
        if not errors:
            errors["file"] = _short_error(exc)
        return anlz, masked, errors


def _read_anlz(path: str | Path) -> tuple[AnlzFile, bool | None, bytes, dict[str, str]]:
    with open(path, "rb") as fh:  # read-only by contract (handover section 0)
        data = fh.read()
    anlz, masked, tag_errors = parse_anlz(data)
    plain, _ = unmask_anlz_bytes(data)
    return anlz, masked, plain, tag_errors


def load_anlz(path: str | Path) -> AnlzFile:
    """Read an ANLZ file (mode "rb"), unmask PSSI if needed, parse with pyrekordbox."""
    anlz, _masked, _plain, _errors = _read_anlz(path)
    return anlz


def _raw_tags(plain: bytes) -> dict[bytes, list[bytes]]:
    out: dict[bytes, list[bytes]] = {}
    tags, _end = _walk_tags(plain)
    for magic, start, total_len in tags:
        out.setdefault(magic, []).append(plain[start : start + total_len])
    return out


# --------------------------------------------------------------------------- grid


def distinct_tempos(tempos: Iterable[float], tol: float = TEMPO_TOL_BPM) -> list[float]:
    """Sorted cluster starts; a value opens a new cluster when it is more than `tol` BPM above
    the current cluster's start."""
    out: list[float] = []
    for t in sorted({round(float(x), 3) for x in tempos}):
        if not out or t - out[-1] > tol:
            out.append(t)
    return out


def tempo_switches(tempos: Sequence[float], tol: float = TEMPO_TOL_BPM) -> int:
    """How often the tempo changes along the grid (runs - 1); 0 for a constant grid."""
    return sum(1 for prev, cur in itertools.pairwise(tempos) if abs(cur - prev) > tol)


def grid_summary(entries: Sequence[tuple[int, float, int]]) -> dict[str, Any]:
    """`entries` = (beat_in_bar, bpm, time_ms) in grid order."""
    if not entries:
        return {"present": False}
    tempos = [bpm for _, bpm, _ in entries]
    downbeats = [t for b, _, t in entries if b == 1]
    distinct = distinct_tempos(tempos)
    return {
        "present": True,
        "beats": len(entries),
        "bars": len(downbeats),
        "first_beat_ms": entries[0][2],
        "first_downbeat_ms": downbeats[0] if downbeats else None,
        "last_beat_ms": entries[-1][2],
        "bpm_first": tempos[0],
        "bpm_min": min(tempos),
        "bpm_max": max(tempos),
        "tempo_distinct": len(distinct),
        "tempo_changes": len(distinct) - 1,
        "tempo_switches": tempo_switches(tempos),
    }


def _pqtz_entries(anlz: AnlzFile) -> list[tuple[int, float, int]]:
    tags = anlz.getall_tags("PQTZ")
    if not tags:
        return []
    return [(int(e.beat), e.tempo / 100.0, int(e.time)) for e in tags[0].content.entries]


def pqt2_summary(tag: bytes | None) -> dict[str, Any]:
    """PQT2 from raw bytes: pyrekordbox pins `u1` to 0x01000002, but Rekordbox also writes
    0x02000002 (9 of the first 200 library tracks), so the header is read here directly."""
    if tag is None or len(tag) < 56:
        return {"present": False}
    flags = struct.unpack(">I", tag[16:20])[0]
    anchors = [struct.unpack(">HHI", tag[off : off + 8]) for off in (24, 32)]
    return {
        "present": True,
        "beats": struct.unpack(">I", tag[40:44])[0],
        "anchor_bpm": [a[1] / 100.0 for a in anchors],
        "anchor_ms": [a[2] for a in anchors],
        "flags": f"0x{flags:08x}",
    }


# --------------------------------------------------------------------------- cues


_PCOB_CUE_TYPE = 12  # u32 after the 12-byte tag prefix: 0 memory, 1 hot cue
_PCOB_ENTRIES = 24
_PCPT_TYPE = 28  # u8 inside a PCPT entry: 1 single, 2 loop
_PCPT_MIN_LEN = 32


def pcob_counts(tag: bytes) -> tuple[int, int, int]:
    """(hot, memory, loops) from a raw PCOB tag. Raw on purpose: pyrekordbox pins the PCPT
    `u1` field to 0x10000, Rekordbox also writes 0x100000 and the whole tag would be lost."""
    if len(tag) < _PCOB_ENTRIES:
        return 0, 0, 0
    is_hot = struct.unpack(">I", tag[_PCOB_CUE_TYPE : _PCOB_CUE_TYPE + 4])[0] == 1
    hot = memory = loops = 0
    off = _PCOB_ENTRIES
    while off + _PCPT_MIN_LEN <= len(tag) and tag[off : off + 4] == b"PCPT":
        len_entry = struct.unpack(">I", tag[off + 8 : off + 12])[0]
        if len_entry < _PCPT_MIN_LEN or off + len_entry > len(tag):
            break
        if is_hot:
            hot += 1
        else:
            memory += 1
        if tag[off + _PCPT_TYPE] == 2:
            loops += 1
        off += len_entry
    return hot, memory, loops


def cue_summary(pcob_raw: Sequence[bytes], pco2_tags: Sequence[Any]) -> dict[str, Any]:
    """Counts from raw PCOB tags (hot / memory / loop); colours + comments from parsed PCO2."""
    hot = memory = loops = 0
    for tag in pcob_raw:
        h, m, lp = pcob_counts(tag)
        hot += h
        memory += m
        loops += lp
    colours: Counter[str] = Counter()
    comments = 0
    for tag in pco2_tags:
        for e in tag.content.entries:
            if e.comment:
                comments += 1
            if int(e.color_id):
                colours[str(int(e.color_id))] += 1
    return {
        "hot": hot,
        "memory": memory,
        "loops": loops,
        "colours": dict(sorted(colours.items())),
        "comments": comments,
        "pco2_present": bool(pco2_tags),
    }


# --------------------------------------------------------------------------- phrases

MOOD_NAMES = {1: "high", 2: "mid", 3: "low"}
# Handover section 2 / djl-analysis "Song Structure Tag": kind ids are relative to the mood.
PHRASE_LABELS: dict[int, dict[int, str]] = {
    1: {1: "Intro", 2: "Up", 3: "Down", 5: "Chorus", 6: "Outro"},
    2: {
        1: "Intro",
        2: "Verse1",
        3: "Verse2",
        4: "Verse3",
        5: "Verse4",
        6: "Verse5",
        7: "Verse6",
        8: "Bridge",
        9: "Chorus",
        10: "Outro",
    },
    3: {
        1: "Intro",
        2: "Verse1",
        3: "Verse1",
        4: "Verse1",
        5: "Verse2",
        6: "Verse2",
        7: "Verse2",
        8: "Bridge",
        9: "Chorus",
        10: "Outro",
    },
}
INTRO_KIND = 1
CHORUS_KIND = {1: 5, 2: 9, 3: 9}
OUTRO_KIND = {1: 6, 2: 10, 3: 10}


def phrase_label(mood: int, kind: int) -> str:
    return PHRASE_LABELS.get(mood, {}).get(kind, f"?{kind}")


def _run_length(labels: Sequence[str]) -> str:
    parts: list[str] = []
    for label in labels:
        if parts and parts[-1].split("*")[0] == label:
            head, _, count = parts[-1].partition("*")
            parts[-1] = f"{head}*{int(count or 1) + 1}"
        else:
            parts.append(label)
    return ",".join(parts)


def phrase_summary(mood: int, phrases: Sequence[tuple[int, int]], end_beat: int) -> dict[str, Any]:
    """`phrases` = (start_beat, kind) in file order; `end_beat` closes the last phrase."""
    kinds = [k for _, k in phrases]
    starts = [s for s, _ in phrases]
    bounds = [*starts[1:], end_beat] if starts else []
    lengths = [max(0, e - s) for s, e in zip(starts, bounds, strict=True)]
    intro_beats = 0
    for kind, length in zip(kinds, lengths, strict=True):
        if kind != INTRO_KIND:
            break
        intro_beats += length
    outro_beats = 0
    for kind, length in zip(reversed(kinds), reversed(lengths), strict=True):
        if kind != OUTRO_KIND.get(mood):
            break
        outro_beats += length
    labels = [phrase_label(mood, k) for k in kinds]
    return {
        "mood": MOOD_NAMES.get(mood, f"?{mood}"),
        "count": len(phrases),
        "kinds": ",".join(str(k) for k in kinds),
        "labels": _run_length(labels),
        "intro_bars": intro_beats / 4,
        "outro_bars": outro_beats / 4,
        "chorus_count": sum(1 for k in kinds if k == CHORUS_KIND.get(mood)),
        "end_beat": end_beat,
        "bars": end_beat / 4,
        "min_phrase_bars": min(lengths) / 4 if lengths else None,
        "max_phrase_bars": max(lengths) / 4 if lengths else None,
    }


def _pssi_summary(anlz: AnlzFile, masked: bool | None) -> dict[str, Any]:
    tags = anlz.getall_tags("PSSI")
    if not tags:
        return {"present": False, "masked": masked}
    c = tags[0].content
    mood = int.from_bytes(bytes(c.mood), "big")
    end_beat = int.from_bytes(bytes(c.end_beat), "big")
    phrases = [(int(e.beat), int(e.kind)) for e in c.entries]
    out = phrase_summary(mood, phrases, end_beat)
    out.update(
        {
            "present": True,
            "masked": masked,
            "mood_id": mood,
            "bank": int.from_bytes(bytes(c.bank), "big"),
            "fills": sum(1 for e in c.entries if int(e.fill)),
            "kind_variants": ",".join(
                f"{int(e.k1)}{int(e.k2)}{int(e.k3)}" for e in c.entries if int(e.kind) != 0
            ),
        }
    )
    return out


# --------------------------------------------------------------------------- waveforms


def band_summary(payload: bytes, segments: int = CURVE_SEGMENTS) -> dict[str, Any]:
    """3-byte frames [low, mid, high]; byte order measured against PWV5 RGB (module docstring)."""
    n = len(payload) // 3
    if n == 0:
        return {"present": False}
    arr = np.frombuffer(payload[: n * 3], dtype=np.uint8).reshape(n, 3).astype(np.float64)
    means = arr.mean(axis=0)
    total = float(means.sum()) or 1.0
    energy = arr.sum(axis=1)
    peak = float(energy.max()) or 1.0
    curve = [round(float(seg.mean()) / peak, 3) for seg in np.array_split(energy, segments)]
    return {
        "present": True,
        "frames": n,
        "low": round(float(means[0]), 2),
        "mid": round(float(means[1]), 2),
        "high": round(float(means[2]), 2),
        "bass_share": round(float(means[0]) / total, 3),
        "brightness": round(float(means[2]) / total, 3),
        "curve": curve,
        "peak_pos": round(int(energy.argmax()) / n, 3),
        "max_byte": int(arr.max()),
    }


def _pwv_payload(raw: dict[bytes, list[bytes]], magic: bytes, header_len: int) -> bytes | None:
    tags = raw.get(magic)
    if not tags:
        return None
    return tags[0][header_len:]


def color_detail_summary(entries_u16: Sequence[int]) -> dict[str, Any]:
    """PWV5: 3-bit red / green / blue + 5-bit height per 16-bit entry (pyrekordbox layout)."""
    if not entries_u16:
        return {"present": False}
    x = np.asarray(entries_u16, dtype=np.int64)
    r = (x >> 13) & 7
    g = (x >> 10) & 7
    b = (x >> 7) & 7
    h = (x >> 2) & 31
    rgb_total = float(r.mean() + g.mean() + b.mean()) or 1.0
    return {
        "present": True,
        "frames": int(x.size),
        "red": round(float(r.mean()), 3),
        "green": round(float(g.mean()), 3),
        "blue": round(float(b.mean()), 3),
        "height": round(float(h.mean()), 3),
        "brightness": round(float(b.mean()) / rgb_total, 3),
    }


def color_preview_summary(payload: bytes) -> dict[str, Any]:
    """PWV4: 6 bytes per column; d3 red, d4 green, d5 blue (& 0x7F), as pyrekordbox reads them."""
    n = len(payload) // 6
    if n == 0:
        return {"present": False}
    arr = np.frombuffer(payload[: n * 6], dtype=np.uint8).reshape(n, 6).astype(np.int64) & 0x7F
    r, g, b = (float(arr[:, i].mean()) for i in (3, 4, 5))
    total = (r + g + b) or 1.0
    return {
        "present": True,
        "frames": n,
        "red": round(r, 2),
        "green": round(g, 2),
        "blue": round(b, 2),
        "brightness": round(b / total, 3),
    }


# --------------------------------------------------------------------------- path + writer


def ppth_match(anlz_path: str | None, real_path: str | None) -> str:
    """'empty' | 'basename' (Rekordbox 7 writes '?/<file name>') | 'full' | 'ext_mismatch'
    | 'mismatch' | 'no_real_path'."""
    if not anlz_path:
        return "empty"
    if not real_path:
        return "no_real_path"
    a = PureWindowsPath(anlz_path.replace("\\", "/"))
    r = PureWindowsPath(real_path.replace("\\", "/"))
    if a.name.lower() == r.name.lower():
        return "basename" if anlz_path.startswith("?/") else "full"
    if a.stem.lower() == r.stem.lower():
        return "ext_mismatch"
    return "mismatch"


def _ppth(anlz: AnlzFile) -> str | None:
    tags = anlz.getall_tags("PPTH")
    if not tags:
        return None
    return str(tags[0].content.path)


def writer_guess(
    pssi_tag: bytes | None, pwvc_tag: bytes | None, pqt2_tag: bytes | None
) -> dict[str, Any]:
    """Who wrote the ANLZ set, from fields app/anlz_writer.py fills differently than Rekordbox.

    - PSSI header: Rekordbox puts end_beat at 0x1A and 1 at 0x1C; LMS puts end_beat at 0x16 and
      zeros from 0x18 on (`_build_pssi`). `pssi_tag` must already be unmasked.
    - PWVC payload: Rekordbox writes non-zero colour values; LMS writes all zeros (`_build_pwvc`).
    - PQT2 u3 (offset 44): Rekordbox writes a non-zero value; LMS pads with zeros (`_build_pqt2`).
    """
    votes: dict[str, str] = {}
    if pssi_tag is not None and len(pssi_tag) >= _PSSI_HEADER_LEN:
        end_rb = struct.unpack(">H", pssi_tag[_PSSI_END_BEAT : _PSSI_END_BEAT + 2])[0]
        u2 = struct.unpack(">H", pssi_tag[_PSSI_U2 : _PSSI_U2 + 2])[0]
        end_lms = struct.unpack(">H", pssi_tag[_PSSI_LMS_END_BEAT : _PSSI_LMS_END_BEAT + 2])[0]
        if end_rb == 0 and end_lms != 0:
            votes["pssi"] = "lms"
        elif end_rb != 0 and u2 == 1:
            votes["pssi"] = "rekordbox"
    if pwvc_tag is not None and len(pwvc_tag) > TAG_PREFIX_LEN:
        payload = pwvc_tag[TAG_PREFIX_LEN:]
        votes["pwvc"] = "lms" if not any(payload) else "rekordbox"
    if pqt2_tag is not None and len(pqt2_tag) >= _PQT2_U3 + 4:
        u3 = struct.unpack(">I", pqt2_tag[_PQT2_U3 : _PQT2_U3 + 4])[0]
        votes["pqt2"] = "lms" if u3 == 0 else "rekordbox"
    kinds = set(votes.values())
    if not kinds:
        guess = "unknown"
    elif len(kinds) == 1:
        guess = kinds.pop()
    else:
        guess = "conflict"
    return {"guess": guess, "votes": votes}


# --------------------------------------------------------------------------- per track


def measure_track_anlz(paths: dict[str, str], real_path: str | None = None) -> dict[str, Any]:
    """Measure one track's DAT / EXT / EX2. Never raises for a bad file: per-file errors are
    recorded under `errors` and `status` becomes 'partial' or 'error'."""
    row: dict[str, Any] = {"files": {}, "errors": {}, "tag_errors": {}, "tags": {}}
    parsed: dict[str, tuple[AnlzFile, bool | None, bytes, dict[str, str]]] = {}
    for kind in ANLZ_KINDS:
        p = paths.get(kind)
        if not p or not Path(p).is_file():
            row["files"][kind] = False
            continue
        row["files"][kind] = True
        try:
            parsed[kind] = _read_anlz(p)
        except Exception as exc:  # a parse failure is itself a finding
            row["errors"][kind] = _short_error(exc)
    for kind, (anlz, _m, _plain, tag_errors) in parsed.items():
        row["tags"][kind] = list(anlz.tag_types)
        if tag_errors:
            row["tag_errors"][kind] = tag_errors

    dat = parsed.get("DAT")
    ext = parsed.get("EXT")
    ex2 = parsed.get("EX2")
    raw_dat = _raw_tags(dat[2]) if dat else {}
    raw_ext = _raw_tags(ext[2]) if ext else {}
    raw_ex2 = _raw_tags(ex2[2]) if ex2 else {}

    grid_source = dat or ext
    row["grid"] = grid_summary(_pqtz_entries(grid_source[0])) if grid_source else {"present": False}
    row["grid2"] = pqt2_summary(raw_ext.get(b"PQT2", [None])[0])

    pcob_raw = raw_dat.get(b"PCOB") or raw_ext.get(b"PCOB") or []
    pco2 = ext[0].getall_tags("PCO2") if ext else []
    row["cues"] = cue_summary(pcob_raw, pco2)

    row["pssi"] = _pssi_summary(ext[0], ext[1]) if ext else {"present": False, "masked": None}

    pwv7 = _pwv_payload(raw_ex2, b"PWV7", 24)
    pwv6 = _pwv_payload(raw_ex2, b"PWV6", 20)
    row["band_detail"] = band_summary(pwv7) if pwv7 is not None else {"present": False}
    row["band_preview"] = band_summary(pwv6) if pwv6 is not None else {"present": False}
    pwv5 = ext[0].getall_tags("PWV5") if ext else []
    row["color_detail"] = (
        color_detail_summary(list(pwv5[0].content.entries)) if pwv5 else {"present": False}
    )
    pwv4 = _pwv_payload(raw_ext, b"PWV4", 24)
    row["color_preview"] = color_preview_summary(pwv4) if pwv4 is not None else {"present": False}

    ppth_dat = _ppth(dat[0]) if dat else None
    ppth_ex2 = _ppth(ex2[0]) if ex2 else None
    row["ppth"] = {
        "dat": ppth_dat,
        "ex2": ppth_ex2,
        "dat_match": ppth_match(ppth_dat, real_path),
        "ex2_match": ppth_match(ppth_ex2, real_path),
    }

    pssi_raw = raw_ext.get(b"PSSI", [None])[0]
    pqt2_raw = raw_ext.get(b"PQT2", [None])[0]
    pwvc_raw = raw_ex2.get(b"PWVC", [None])[0]
    row["writer"] = writer_guess(pssi_raw, pwvc_raw, pqt2_raw)

    if not any(row["files"].values()):
        row["status"] = "missing"
    elif not parsed:
        row["status"] = "error"
    elif row["errors"] or row["tag_errors"]:
        row["status"] = "partial"
    else:
        row["status"] = "ok"
    return row


# --------------------------------------------------------------------------- summary


def summarize(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    status: Counter[str] = Counter()
    files: Counter[str] = Counter()
    errors: Counter[str] = Counter()
    masked: Counter[str] = Counter()
    moods: Counter[str] = Counter()
    writers: Counter[str] = Counter()
    ppth: Counter[str] = Counter()
    tag_sets: Counter[str] = Counter()
    grid_missing = tempo_changed = pqt2_missing = n = 0
    phrase_counts: list[int] = []
    bass: list[float] = []
    bright: list[float] = []
    pwv_frames_ok = pwv_frames_total = 0
    for row in rows:
        n += 1
        status[str(row.get("status"))] += 1
        for kind, present in (row.get("files") or {}).items():
            if present:
                files[kind] += 1
        for kind, msg in (row.get("errors") or {}).items():
            errors[f"{kind}:{msg.split(':', 1)[0]}"] += 1
        if row.get("error"):
            errors[f"row:{str(row['error']).split(':', 1)[0]}"] += 1
        for kind, tags in (row.get("tags") or {}).items():
            tag_sets[f"{kind}:{','.join(tags)}"] += 1
        grid = row.get("grid") or {}
        if row.get("status") in ("ok", "partial"):
            if not grid.get("present"):
                grid_missing += 1
            if grid.get("tempo_changes"):
                tempo_changed += 1
            if not (row.get("grid2") or {}).get("present"):
                pqt2_missing += 1
        pssi = row.get("pssi") or {}
        if pssi.get("present"):
            masked["masked" if pssi.get("masked") else "plain"] += 1
            moods[str(pssi.get("mood"))] += 1
            phrase_counts.append(int(pssi.get("count") or 0))
        elif row.get("status") in ("ok", "partial"):
            masked["no_pssi"] += 1
        writers[str((row.get("writer") or {}).get("guess", "unknown"))] += 1
        ppth[str((row.get("ppth") or {}).get("dat_match"))] += 1
        band = row.get("band_detail") or {}
        if band.get("present"):
            bass.append(float(band["bass_share"]))
            bright.append(float(band["brightness"]))
            pwv_frames_total += 1
            if (row.get("color_detail") or {}).get("frames") == band.get("frames"):
                pwv_frames_ok += 1
    phrase_counts.sort()
    return {
        "tracks": n,
        "status": dict(status),
        "files_present": dict(files),
        "errors": dict(errors),
        "tag_sets": dict(tag_sets),
        "grid_missing": grid_missing,
        "pqt2_missing": pqt2_missing,
        "tempo_changed": tempo_changed,
        "pssi": dict(masked),
        "moods": dict(moods),
        "phrases_median": phrase_counts[len(phrase_counts) // 2] if phrase_counts else None,
        "phrases_min_max": ([phrase_counts[0], phrase_counts[-1]] if phrase_counts else None),
        "writer": dict(writers),
        "ppth_dat_match": dict(ppth),
        "bass_share_mean": round(sum(bass) / len(bass), 3) if bass else None,
        "brightness_mean": round(sum(bright) / len(bright), 3) if bright else None,
        "pwv7_frames_eq_pwv5": [pwv_frames_ok, pwv_frames_total],
    }


# --------------------------------------------------------------------------- CLI


def _base_row(track: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(track.get("ID")),
        "title": track.get("Title"),
        "artist": track.get("Artist"),
        "path": track.get("path"),
    }


def run(
    tracks: Sequence[dict[str, Any]],
    anlz_paths: dict[str, dict[str, str]],
    out_path: Path,
    limit: int | None = None,
) -> dict[str, Any]:
    todo = list(tracks[:limit] if limit else tracks)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    start = time.monotonic()
    with open(out_path, "w", encoding="utf-8") as fh:
        for i, track in enumerate(todo, 1):
            row = _base_row(track)
            paths = anlz_paths.get(row["id"])
            if paths is None:
                row["status"] = "no_anlz_path"
            else:
                try:
                    row.update(measure_track_anlz(paths, track.get("path")))
                except Exception as exc:  # never drop a track silently
                    row["status"] = "error"
                    row["error"] = f"{type(exc).__name__}: {exc}"[:300]
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            rows.append(row)
            if i % PROGRESS_EVERY == 0 or i == len(todo):
                elapsed = time.monotonic() - start
                rate = i / elapsed if elapsed else 0.0
                eta = (len(todo) - i) / rate if rate else 0.0
                logger.info(
                    "%d/%d tracks  %.1f/s  elapsed %.0fs  eta %.0fs",
                    i,
                    len(todo),
                    rate,
                    elapsed,
                    eta,
                )
    summary = summarize(rows)
    summary["wall_s"] = round(time.monotonic() - start, 1)
    return summary


def _load_rows(path: Path) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="track snapshot JSON")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB, help="Rekordbox master.db (read-only)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="JSON lines output")
    ap.add_argument("--summary-only", action="store_true", help="summarise an existing --out")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    # pyrekordbox warns "Tag 'PVB2' not supported" once per EXT file; harmless, drowns the log.
    logging.getLogger("pyrekordbox").setLevel(logging.ERROR)

    if args.summary_only:
        summary = summarize(_load_rows(args.out))
    else:
        from app.anlz_safe import resolve_anlz_paths

        with open(args.input, encoding="utf-8") as fh:
            tracks = json.load(fh)
        t0 = time.monotonic()
        anlz_paths = resolve_anlz_paths(str(args.db), None)
        logger.info(
            "resolved %d ANLZ path sets from %s in %.2fs",
            len(anlz_paths),
            args.db,
            time.monotonic() - t0,
        )
        summary = run(tracks, anlz_paths, args.out, args.limit)
        logger.info("wrote %s", args.out)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
