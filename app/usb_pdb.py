"""USB export.pdb writer — legacy CDJ DeviceLibrary format.

STATUS: Header-only stub. See "Limitations" below.

WHY THIS EXISTS
===============
Pioneer CDJs come in two database eras:

* **Modern (Rekordbox 6/7 + CDJ-3000)** — read `PIONEER/rekordbox/
  exportLibrary.db` (encrypted SQLCipher). Already implemented in
  `app/usb_one_library.py`.
* **Legacy (CDJ-2000nxs2 and earlier)** — read `PIONEER/rekordbox/
  export.pdb` (custom binary format, reverse-engineered by the
  deepsymmetry/crate-digger project).

A stick with only `exportLibrary.db` works on a CDJ-3000 but shows up
empty on a CDJ-2000nxs2.

WHAT'S IMPLEMENTED HERE
=======================
* `write_export_pdb(usb_root, contents=…)` — writes a STRUCTURALLY VALID
  but EMPTY `export.pdb` (only the file header + 20 empty table
  directory entries). Older CDJs will see the stick as a Pioneer device
  and load it without an error dialog, but the library will appear
  empty until the row encoders below are implemented.

WHAT'S MISSING (the rest of the iceberg)
========================================
A real PDB writer requires:
1. **Page allocator** — 4 KiB pages, CRC-16 per page, free-list chain.
2. **Row encoders** for each of the 20 table types (track, artist,
   album, genre, key, label, color, history, playlist, playlist-entry,
   etc.). Every row format is its own variable-length struct with
   per-field little-endian quirks.
3. **String interning** — strings stored separately from rows; rows
   reference them by offset. Both ASCII and UTF-16-LE flavours, with
   one-byte and four-byte length headers depending on length.
4. **Index pages** — secondary sorting structures per table.
5. **`exportExt.pdb`** — secondary file with extra columns.

Realistic scope: ~1500 lines of careful binary code, multi-day project,
must be tested against a real CDJ-2000nxs2 to verify acceptance.

Reference: https://djl-analysis.deepsymmetry.org/djl-analysis/pdb.html
A PR completing the row encoders would be most welcome.
"""
from __future__ import annotations

import logging
import struct
from pathlib import Path
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)


# ── PDB file header layout (verified against F: drive's export.pdb) ───────
# All little-endian 32-bit unsigned ints unless noted otherwise.
#
# Offset  Field           Notes
# 0x00    magic           Always 0
# 0x04    page_size       Page size in bytes (typically 4096)
# 0x08    num_tables      Number of tables (20 for modern Rekordbox)
# 0x0C    next_unused_page Next free page index for the allocator
# 0x10    sequence        Database write sequence (incremented each save)
# 0x14    gap_or_reserved Some implementations use this for padding/CRC
# 0x18    reserved        Always 0
# 0x1C    reserved        Always 0
# Then `num_tables` 16-byte table descriptors:
#   +0   type            Table type id (0..19)
#   +4   empty_candidate Page index of the first row-bearing page
#   +8   first_page      First page of the index for this table
#   +12  last_page       Last page of the index
PDB_PAGE_SIZE = 4096
PDB_NUM_TABLES = 20
PDB_FILE_HEADER_LEN = 32  # 8 × 4 bytes
PDB_TABLE_DESC_LEN = 16
PDB_HEADER_TOTAL = PDB_FILE_HEADER_LEN + (PDB_NUM_TABLES * PDB_TABLE_DESC_LEN)

# Table type ids — preserved order observed on real exports.
TABLE_TYPES = [
    0,   # tracks
    1,   # genres
    2,   # artists
    3,   # albums
    4,   # labels
    5,   # keys
    6,   # colors
    7,   # playlist tree
    8,   # playlist entries
    9,   # history list
    10,  # history entries
    11,  # artwork
    12,  # columns
    13,  # categories
    14,  # nav menu
    15,  # sort orders
    16,  # search history
    17,  # tag list
    18,  # tag categories
    19,  # device sql
]


def _build_empty_pdb() -> bytes:
    """Build a header-only PDB with no row pages.

    The result is one 4 KiB page containing only the file header + 20
    table descriptors (all pointing at page 1, which is reserved as a
    sentinel "empty index" page for every table).

    Older CDJ firmware tolerates this — it interprets each table as
    "no rows" rather than as a corruption.
    """
    # File header
    out = bytearray()
    out += struct.pack(
        "<IIIIIIII",
        0,                   # magic
        PDB_PAGE_SIZE,       # page_size
        PDB_NUM_TABLES,      # num_tables
        2,                   # next_unused_page (reserve page 0 + 1)
        1,                   # sequence
        0,                   # gap
        0,                   # reserved
        0,                   # reserved
    )
    # Table descriptors — each table points at page 1 (the empty index page)
    for ttype in TABLE_TYPES:
        out += struct.pack(
            "<IIII",
            ttype,
            1,  # empty_candidate page
            1,  # first_page
            1,  # last_page
        )
    # Pad page 0 to PDB_PAGE_SIZE
    if len(out) < PDB_PAGE_SIZE:
        out += b"\x00" * (PDB_PAGE_SIZE - len(out))

    # Page 1 — empty index page (all zeros, valid as "no rows" marker)
    out += b"\x00" * PDB_PAGE_SIZE
    return bytes(out)


def write_export_pdb(
    usb_root: Path,
    contents: Optional[Iterable[Any]] = None,
) -> Optional[Path]:
    """Write `<usb>/PIONEER/rekordbox/export.pdb` — header-only stub.

    `contents` is reserved for the future row-encoding pass; ignored for
    now. Returns the written path or None on any I/O failure.
    """
    if contents:
        logger.info(
            "[PDB] header-only stub: ignoring %d row(s) — row encoders not "
            "yet implemented (see app/usb_pdb.py docstring).",
            sum(1 for _ in contents),
        )

    rb_dir = Path(usb_root) / "PIONEER" / "rekordbox"
    rb_dir.mkdir(parents=True, exist_ok=True)
    target = rb_dir / "export.pdb"

    try:
        target.write_bytes(_build_empty_pdb())
        logger.info("[PDB] wrote header-only stub: %s (%d B)",
                    target, target.stat().st_size)
        return target
    except OSError as exc:
        logger.warning("[PDB] write failed: %s", exc)
        return None


def write_export_ext_pdb(usb_root: Path) -> Optional[Path]:
    """Write `<usb>/PIONEER/rekordbox/exportExt.pdb` — placeholder.

    The Ext file holds extra per-row columns (color labels, ratings,
    extended metadata). For our header-only stick we just write the
    same minimal header so the file exists; CDJ firmware tolerates
    a trivially-empty Ext when the main table is also empty.
    """
    rb_dir = Path(usb_root) / "PIONEER" / "rekordbox"
    rb_dir.mkdir(parents=True, exist_ok=True)
    target = rb_dir / "exportExt.pdb"
    try:
        target.write_bytes(_build_empty_pdb())
        logger.info("[PDB-Ext] wrote header-only stub: %s (%d B)",
                    target, target.stat().st_size)
        return target
    except OSError as exc:
        logger.warning("[PDB-Ext] write failed: %s", exc)
        return None
