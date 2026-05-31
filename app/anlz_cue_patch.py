"""
anlz_cue_patch.py — non-destructive memory-cue injection into existing ANLZ files.

The Phrase Generator writes phrase markers as Rekordbox *memory cues*. Memory
cues live in the track's ANLZ binary files (`.DAT` / `.EXT`) inside the
`PCOB` (and, in `.EXT`, `PCO2`) cue-list containers with `cue_type == 0`.

`anlz_writer.write_anlz_files` rebuilds a whole ANLZ file from a full
analysis_result and would therefore wipe the existing beat grid + waveform if
fed only cues. This module instead patches an *existing* ANLZ in place:

  - walk the flat PMAI tag chain,
  - replace ONLY the memory-cue PCOB/PCO2 tag(s) with freshly built ones,
  - carry every other tag (PQTZ beat grid, PWAV/PWV* waveforms, the hot-cue
    PCOB, PSSI phrase struct, …) through byte-for-byte,
  - recompute the PMAI file length,
  - back up the originals first (rollback safety).

The freshly built tags reuse `anlz_writer`'s own tag builders so the output
format is identical to what the analysis pipeline writes. Existing memory cues
are *replaced* (the generated phrase grid owns the memory-cue layer); the
operation is idempotent across re-runs.
"""

import logging
import struct
from pathlib import Path
from typing import Any

# Intentional reuse of anlz_writer's internal tag builders / backup helpers:
# anlz_cue_patch is a sibling in the same package that must emit byte-identical
# PCOB/PCO2 tags and share the backup/prune policy.
from .anlz_writer import (
    PMAI_HEADER_LEN,
    PMAI_MAGIC,
    _backup_existing_anlz,
    _build_file_header,
    _build_pco2,
    _build_pcob,
    _prune_anlz_backups,
)

logger = logging.getLogger(__name__)

# magic(4) + hdr_len(4) + total_len(4)
_TAG_PREFIX_LEN = 12
# cue_type u32 sits right after the 12-byte prefix in PCOB and PCO2.
_CUE_TYPE_OFFSET = 12
_MEMORY_CUE_TYPE = 0


def _walk_tags(data: bytes) -> tuple[list[tuple[bytes, int, int]], int]:
    """
    Walk the flat ANLZ tag chain after the PMAI header.

    Returns (tags, end) where tags is a list of (magic, start, total_len) and
    end is the offset just past the last well-formed tag. Any bytes from `end`
    to EOF are opaque trailing data the caller must carry verbatim.

    Stops on the first malformed length rather than raising, so a slightly
    unexpected file degrades to "carry the rest unchanged" instead of corrupting.
    """
    tags: list[tuple[bytes, int, int]] = []
    off = PMAI_HEADER_LEN
    n = len(data)
    while off + _TAG_PREFIX_LEN <= n:
        magic = data[off : off + 4]
        total_len = struct.unpack(">I", data[off + 8 : off + 12])[0]
        if total_len < _TAG_PREFIX_LEN or off + total_len > n:
            logger.warning(
                "anlz_cue_patch: malformed tag %r at off=%d total_len=%d — "
                "carrying remaining %d bytes verbatim",
                magic,
                off,
                total_len,
                n - off,
            )
            break
        tags.append((magic, off, total_len))
        off += total_len
    return tags, off


def _tag_cue_type(data: bytes, start: int, total_len: int) -> int | None:
    """Read the cue_type field of a PCOB/PCO2 tag, or None if it doesn't fit."""
    if total_len < _CUE_TYPE_OFFSET + 4:
        return None
    return struct.unpack(">I", data[start + _CUE_TYPE_OFFSET : start + _CUE_TYPE_OFFSET + 4])[0]


def _patch_one_file(path: Path, memory_cues: list[dict[str, Any]], include_pco2: bool) -> bool:
    """
    Rewrite a single `.DAT`/`.EXT` with its memory-cue tag(s) replaced.

    `include_pco2` is True for `.EXT` (which carries the colour/label PCO2 list)
    and False for `.DAT` (PCOB only). Returns True on write.
    """
    data = path.read_bytes()
    if data[:4] != PMAI_MAGIC:
        logger.warning("anlz_cue_patch: %s is not a PMAI ANLZ file — skipped", path.name)
        return False

    tags, end = _walk_tags(data)
    new_pcob = _build_pcob(_MEMORY_CUE_TYPE, memory_cues)
    new_pco2 = _build_pco2(_MEMORY_CUE_TYPE, memory_cues)  # unused for .DAT (include_pco2=False)

    out = bytearray()
    replaced_pcob = False
    replaced_pco2 = False

    for magic, start, total_len in tags:
        if magic == b"PCOB" and _tag_cue_type(data, start, total_len) == _MEMORY_CUE_TYPE:
            out += new_pcob
            replaced_pcob = True
        elif (
            include_pco2
            and magic == b"PCO2"
            and _tag_cue_type(data, start, total_len) == _MEMORY_CUE_TYPE
        ):
            out += new_pco2
            replaced_pco2 = True
        else:
            out += data[start : start + total_len]

    # Real Rekordbox files always carry an (often empty) memory PCOB/PCO2, so the
    # replace path normally hits. Append as a last resort if absent.
    if not replaced_pcob:
        logger.info("anlz_cue_patch: %s had no memory PCOB — appending one", path.name)
        out += new_pcob
    if include_pco2 and not replaced_pco2:
        logger.info("anlz_cue_patch: %s had no memory PCO2 — appending one", path.name)
        out += new_pco2

    trailing = data[end:]
    body = bytes(out) + trailing
    new_data = _build_file_header(PMAI_HEADER_LEN + len(body)) + body
    path.write_bytes(new_data)
    logger.info(
        "anlz_cue_patch: wrote %s (%d cues, %d bytes)", path.name, len(memory_cues), len(new_data)
    )
    return True


def patch_memory_cues(
    anlz_dir: str,
    memory_cues: list[dict[str, Any]],
    *,
    backup: bool = True,
) -> dict[str, Any]:
    """
    Inject `memory_cues` into the existing ANLZ files in `anlz_dir`, preserving
    every other tag (beat grid, waveforms, hot cues, phrase struct).

    Args:
        anlz_dir:    Directory holding the track's ANLZ files (e.g. the live
                     Rekordbox `PIONEER/USBANLZ/xx/yy/` folder).
        memory_cues: Cue dicts in `anlz_writer` format:
                     {"type": "memory_cue", "time_ms": int, "number": 0,
                      "name": str?, "color_rgb": (r,g,b)?}.
        backup:      Copy existing files to timestamped `.bak-*` first (default).

    Returns:
        {"dat": bool, "ext": bool, "backups": [paths], "base": str}.

    Raises:
        FileNotFoundError: If the directory holds no `.DAT` (track not analysed).
    """
    directory = Path(anlz_dir)
    dats = sorted(directory.glob("*.DAT"))
    if not dats:
        raise FileNotFoundError(f"No .DAT ANLZ file in {anlz_dir} — track not analysed")

    dat_path = dats[0]
    base = dat_path.stem
    ext_path = dat_path.with_suffix(".EXT")

    backups: list[str] = []
    if backup:
        backups = _backup_existing_anlz(str(directory), base)
        _prune_anlz_backups(str(directory))

    result: dict[str, Any] = {"backups": backups, "base": base, "dat": False, "ext": False}
    result["dat"] = _patch_one_file(dat_path, memory_cues, include_pco2=False)
    if ext_path.exists():
        result["ext"] = _patch_one_file(ext_path, memory_cues, include_pco2=True)

    logger.info(
        "patch_memory_cues: %s base=%s dat=%s ext=%s cues=%d backups=%d",
        anlz_dir,
        base,
        result["dat"],
        result["ext"],
        len(memory_cues),
        len(backups),
    )
    return result
