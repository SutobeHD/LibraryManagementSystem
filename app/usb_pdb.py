"""USB export.pdb writer — legacy CDJ DeviceLibrary format.

Implements the on-disk layout reverse-engineered by the deepsymmetry
crate-digger project (https://djl-analysis.deepsymmetry.org/rekordbox-
export-analysis/exports.html). Verified byte-by-byte against an actual
Rekordbox-exported stick (F: drive) for header + track row layout.

WRITES (for export.pdb):
    Table 0x00 — tracks      (djmdContent)
    Table 0x02 — artists     (djmdArtist)
    Table 0x03 — albums      (djmdAlbum)
    Table 0x05 — keys        (djmdKey)
    Table 0x07 — playlists   (djmdPlaylist tree)
    Table 0x08 — entries     (djmdSongPlaylist)
Other tables (genres, labels, colors, history, columns) get an empty
sentinel page — present so Rekordbox parses the file but with no rows.

WRITES (for exportExt.pdb):
    Header-only sentinel — extension columns / tag tables are not yet
    populated. Modern Rekordbox + CDJ-3000 read everything they need
    from exportLibrary.db; older firmware just sees an empty-ext file.

DEFERRED FOR LATER (NOT BLOCKERS):
  * Index pages — The I-flagged (page_flags bit 6 set) secondary
    lookup pages real Rekordbox writes for big libraries. Format is
    documented in the Crate Digger spec but isn't trivial to write
    correctly from scratch (B-tree-style key sorting + per-page
    presence bits + cross-page next/prev pointers). For libraries up
    to ~500 tracks CDJs do a linear scan across data pages and play
    fine without indices — just slower to navigate. We deliberately
    chose data-only output to ship a working file in a single session.
    A future PR adding index pages would let us mark first_page in
    the table descriptor as the index head (matching the page_flags
    0x64 we observe on real Rekordbox sticks vs. our 0x24 data-page
    flag) and would speed up CDJ menu paging on libraries > 1k tracks.

  * exportExt.pdb playlist-extension columns — the file currently
    ships MyTag definitions + tag-track links. Some Rekordbox 7+
    builds also use it for per-track waveform colour overrides and
    custom-comment overrides. Not required for playback.

  * History playlist tables (0x11–0x13) — left empty. CDJs write to
    these themselves while playing.

DEVICE-SQL STRINGS:
    The format uses two encodings:
        Short ASCII:  byte `lk` where (lk >> 1) = total field bytes,
                      bit 0 set → ASCII, no null terminator. Used when
                      total <= 0x7F bytes.
        Long string:  byte `lk` (flags), u16 length, u8 pad, then data.
                      Bit 7=endian, bit 6=ASCII, bit 5=UTF-8, bit 4=UTF-16,
                      bit 0=0 (long). We use 0x90 = UTF-16-LE.
"""
from __future__ import annotations

import logging
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

PDB_PAGE_SIZE = 4096
PDB_FILE_HEADER_LEN = 32
PDB_TABLE_DESC_LEN = 16
PDB_PAGE_HEADER_LEN = 0x28  # 32 base + 8 data extension; heap starts here

# Table type ids — matches spec
T_TRACKS    = 0x00
T_GENRES    = 0x01
T_ARTISTS   = 0x02
T_ALBUMS    = 0x03
T_LABELS    = 0x04
T_KEYS      = 0x05
T_COLORS    = 0x06
T_PLAYLISTS = 0x07
T_PL_ENTRIES = 0x08
T_ARTWORK   = 0x0D
T_COLUMNS   = 0x10
T_HIST_PL   = 0x11
T_HIST_E    = 0x12
T_HIST      = 0x13

# Order tables appear in the file header — matches what Rekordbox writes
TABLE_ORDER = [
    T_TRACKS, T_GENRES, T_ARTISTS, T_ALBUMS, T_LABELS, T_KEYS, T_COLORS,
    T_PLAYLISTS, T_PL_ENTRIES, 0x09, 0x0A, 0x0B, 0x0C,
    T_ARTWORK, 0x0E, 0x0F, T_COLUMNS, T_HIST_PL, T_HIST_E, T_HIST,
]

# ─── Pre-populated colour rows (Rekordbox built-in 8 colours) ─────────────
# Color id 0 = none, 1=Pink, 2=Red, …
DEFAULT_COLORS = [
    (1, "Pink"), (2, "Red"), (3, "Orange"), (4, "Yellow"),
    (5, "Green"), (6, "Aqua"), (7, "Blue"), (8, "Purple"),
]

# Set of "real" key names — copied from a real Rekordbox export so the
# CDJ key column shows musical keys without us having to know the user's
# library at template-build time. We don't actually populate per-track
# keys because the source side has them as strings, not stable ints; we
# just create one Key row per unique string seen in the export.


# ─── DeviceSQL strings ────────────────────────────────────────────────────

def encode_devicesql_string(s: str) -> bytes:
    """Encode a string as DeviceSQL.

    Pioneer's DeviceSQL accepts two layouts:
      Short ASCII (≤63 ASCII chars): single byte header + ASCII bytes.
      Long string: 4-byte header (flags + length + pad) + payload.

    For maximum CDJ compatibility we use:
      * short ASCII for plain ASCII strings ≤ 63 characters
      * long UTF-16-LE (lk = 0x90) for everything else
    """
    if not s:
        # Spec: empty string still needs a header. Use shortest valid form
        # — a short ASCII of length 1 (just the lk byte itself = 0x03).
        return b"\x03"

    # Try short ASCII path
    if len(s) < 64 and all(ord(c) < 0x80 for c in s):
        total = 1 + len(s)            # lk byte + payload
        lk = (total << 1) | 1         # bit 0 set, (lk>>1)=total
        if lk < 0x100:
            return bytes([lk]) + s.encode("ascii")

    # Long UTF-16-LE
    payload = s.encode("utf-16-le") + b"\x00\x00"  # null-terminated
    total_len = 4 + len(payload)                    # header + payload
    return struct.pack("<BHB", 0x90, total_len, 0x00) + payload


def _aligned(b: bytes, align: int = 2) -> bytes:
    """Pad to alignment so the next row starts on a word boundary."""
    pad = (-len(b)) % align
    return b + b"\x00" * pad


# ─── Page assembly ────────────────────────────────────────────────────────

@dataclass
class _Page:
    page_index: int
    table_type: int
    next_page: int = 0
    seqpage: int = 0
    # Data-page flag MUST be 0x34, not 0x24. Bit 4 (0x10) is present on every
    # data page Rekordbox writes (verified F: drive). Without it Rekordbox
    # flags the device library as corrupted on stick insert.
    page_flags: int = 0x34
    rows_data: List[bytes] = field(default_factory=list)

    def build(self) -> bytes:
        """Assemble the on-disk page image, spec-compliant layout.

        Index pages (page_flags & 0x40 set) have NO data heap and NO row
        index footer — header reports free_size=0, used_size=0, and u6/u7
        carry the magic constants Rekordbox stamps on every index page.

        Data pages have:
          * heap of row bytes growing forward from offset 0x28
          * row index footer growing BACKWARD from end of page in 36-byte
            groups of up to 16 rows. Footer layout per group (start of
            block in physical bytes, group 0 closest to page tail):
              block[0:32]   = row 15..0 offsets (reversed)
              block[32:34]  = row_present_flags (bit i = row i present)
              block[34:36]  = trailing pad (zero)
        """
        is_index = (self.page_flags & 0x40) != 0

        if is_index:
            # Index pages keep heap empty and footer absent — Rekordbox
            # writes them this way (verified F: drive byte-for-byte on
            # page 1). u6=0x03EC and u7=0x0003 are the constants F:
            # uses on every index page, almost certainly a Rekordbox
            # internal "page kind" or write-state hash.
            page_header = struct.pack(
                "<IIIIIII",
                0, self.page_index, self.table_type,
                self.next_page, self.seqpage, 0, 0,
            )
            row_counts_bytes = (0).to_bytes(3, "little")
            page_header = page_header[:0x18] + row_counts_bytes + bytes([self.page_flags])
            page_header += struct.pack("<HH", 0, 0)
            page_header += struct.pack("<HHHH", 0x1FFF, 0x1FFF, 0x03EC, 0x0003)
            assert len(page_header) == PDB_PAGE_HEADER_LEN

            body = bytearray(PDB_PAGE_SIZE)
            body[0:PDB_PAGE_HEADER_LEN] = page_header
            return bytes(body)

        heap = bytearray()
        offsets: List[int] = []
        for row in self.rows_data:
            offsets.append(len(heap))
            heap.extend(row)
            if len(heap) & 1:
                heap.append(0)

        num_rows = len(self.rows_data)
        num_row_offsets = num_rows

        groups: List[bytes] = []
        for g_start in range(0, max(num_rows, 1), 16):
            g_offsets = offsets[g_start : g_start + 16]
            while len(g_offsets) < 16:
                g_offsets.append(0)
            rows_in_group = min(16, num_rows - g_start)
            present_flags = ((1 << rows_in_group) - 1) & 0xFFFF

            block = bytearray(36)
            for i in range(16):
                block[30 - 2 * i : 30 - 2 * i + 2] = struct.pack(
                    "<H", g_offsets[i] & 0xFFFF
                )
            struct.pack_into("<H", block, 32, present_flags)
            groups.append(bytes(block))

        index_bytes = b"".join(reversed(groups))

        used_size = len(heap)
        free_size = PDB_PAGE_SIZE - PDB_PAGE_HEADER_LEN - len(index_bytes) - used_size
        if free_size < 0:
            raise ValueError(
                f"Page overflow: rows={num_rows} heap={used_size} "
                f"index={len(index_bytes)} budget={PDB_PAGE_SIZE - PDB_PAGE_HEADER_LEN}"
            )

        rc = (num_rows << 13) | num_row_offsets
        row_counts_bytes = rc.to_bytes(3, "little")

        page_header = struct.pack(
            "<IIIIIII",
            0, self.page_index, self.table_type,
            self.next_page, self.seqpage, 0, 0,
        )
        page_header = page_header[:0x18] + row_counts_bytes + bytes([self.page_flags])
        page_header += struct.pack("<HH", free_size & 0xFFFF, used_size & 0xFFFF)
        # Data pages: tx_count/tx_idx = 0x1FFF sentinel (no transaction),
        # u6/u7 = 0 per F: drive observation.
        page_header += struct.pack("<HHHH", 0x1FFF, 0x1FFF, 0, 0)
        assert len(page_header) == PDB_PAGE_HEADER_LEN

        body = bytearray(PDB_PAGE_SIZE)
        body[0:PDB_PAGE_HEADER_LEN] = page_header
        body[PDB_PAGE_HEADER_LEN : PDB_PAGE_HEADER_LEN + used_size] = heap
        body[PDB_PAGE_SIZE - len(index_bytes):] = index_bytes
        return bytes(body)


# ─── Row encoders ─────────────────────────────────────────────────────────

def encode_artist_row(artist_id: int, name: str) -> bytes:
    """Subtype 0x0064 (far name) — works for any name length."""
    name_str = encode_devicesql_string(name)
    # Far-name layout: header (12 bytes), then name string follows on heap
    # subtype(2) shift(2) id(4) literal(2) ofs(2) = 12 bytes, name appended
    header = struct.pack("<HHIHH", 0x0064, 0, artist_id, 0x0003, 12)
    return _aligned(header + name_str)


def encode_album_row(album_id: int, name: str, artist_id: int = 0) -> bytes:
    """Subtype 0x0084 (far name)."""
    name_str = encode_devicesql_string(name)
    # 16-byte header + name
    header = struct.pack("<HHIIIHH",
        0x0084, 0, artist_id, album_id, 0, 0x0003, 16)
    return _aligned(header + name_str)


def encode_key_row(key_id: int, name: str) -> bytes:
    """Key table — same shape as Genre/Label: id + name."""
    name_str = encode_devicesql_string(name)
    header = struct.pack("<II", key_id, 1)  # second u32 = ID2 (mirror)
    return _aligned(header + name_str)


def encode_color_row(color_id: int, name: str) -> bytes:
    name_str = encode_devicesql_string(name)
    header = struct.pack("<IBBHB",
        0,                    # padding
        color_id & 0xFF,      # u8 id
        0,                    # u8 unknown
        0,                    # u16 unknown
        0)                    # u8 unknown
    return _aligned(header + name_str)


def encode_label_row(label_id: int, name: str) -> bytes:
    name_str = encode_devicesql_string(name)
    header = struct.pack("<II", label_id, 1)
    return _aligned(header + name_str)


def encode_genre_row(genre_id: int, name: str) -> bytes:
    name_str = encode_devicesql_string(name)
    header = struct.pack("<II", genre_id, 1)
    return _aligned(header + name_str)


def encode_track_row(track: Dict[str, Any]) -> bytes:
    """Build a djmdContent row.

    Layout: 0x5E bytes of fixed-width fields + 21 u16 string offsets.
    Then strings appended on heap. Each string offset is RELATIVE to the
    start of the row (not the page heap).

    `track` keys (all optional, defaults are sane):
        id: int (track id)
        title, artist_id, album_id, genre_id, key_id, label_id, color_id,
        artwork_id, bpm (float, scaled ×100), length_seconds (int),
        bitrate (int), file_path (str, leading slash relative to USB root),
        file_name (str), date_added (str e.g. "2024-12-13"), comment (str),
        sample_rate, year, rating, file_type, isrc.
    """
    title       = track.get("title") or ""
    file_path   = track.get("file_path") or ""
    file_name   = track.get("file_name") or ""
    date_added  = track.get("date_added") or ""
    comment     = track.get("comment") or ""
    isrc        = track.get("isrc") or ""

    # Encode the strings that go on the row's tail. Order MUST match the
    # 21-entry string-offset table indexes 0..20:
    #  0 isrc   1 lyricist  2 us2  3 us3  4 us4  5 message  6 publish_track_info
    #  7 autoload_hotcues  8 us5  9 us6  10 date_added  11 release_date
    #  12 mix_name  13 us7  14 analyze_path  15 analyze_date  16 comment
    #  17 title  18 us8  19 filename  20 file_path
    string_payloads: List[bytes] = []
    for i in range(21):
        if i == 0:
            string_payloads.append(encode_devicesql_string(isrc))
        elif i == 10:
            string_payloads.append(encode_devicesql_string(date_added))
        elif i == 16:
            string_payloads.append(encode_devicesql_string(comment))
        elif i == 17:
            string_payloads.append(encode_devicesql_string(title))
        elif i == 19:
            string_payloads.append(encode_devicesql_string(file_name))
        elif i == 20:
            string_payloads.append(encode_devicesql_string(file_path))
        else:
            string_payloads.append(encode_devicesql_string(""))

    # Header = 0x5E bytes of typed fields + 21 × 2 bytes = 0x5E + 42 = 0x88
    header_size = 0x5E + 42
    # Compute string offsets — each relative to row start
    str_offsets: List[int] = []
    cursor = header_size
    for payload in string_payloads:
        str_offsets.append(cursor)
        cursor += len(payload)

    bpm_x100 = int((track.get("bpm") or 0) * 100)
    duration = int(track.get("length_seconds") or 0)
    file_type = int(track.get("file_type") or 0)

    def u32(v: int) -> int:
        """Mask negative ints to their unsigned 32-bit two's-complement.

        master_db_id values come out of OneLibrary as Python ints that can
        be negative (e.g. -322436710), but the PDB stores them as u32.
        """
        return int(v) & 0xFFFFFFFF

    # Layout: 2H + 18I + 6H + 2B + 2H = 94 bytes (0x5E header).
    # Previously offsets 0x18+0x1A held two "magic" u16s (0x4A38, 0x78D7)
    # — but byte-level diff against F:'s real Rekordbox export proved these
    # are actually master_db_id (a u32) split across the same 4 bytes.
    # u32 at 0x14 is master_content_id (also previously hardcoded to 0).
    fixed = struct.pack(
        "<HHIIIIIIIIIIIIIIIIIIHHHHHHBBHH",
        0x0024,                                        # 0x00 subtype
        int(track.get("index_shift") or 0),            # 0x02 index_shift
        u32(track.get("bitmask") or 0),                # 0x04 bitmask
        int(track.get("sample_rate") or 0),            # 0x08 sample_rate
        0,                                             # 0x0C composer_id
        int(track.get("file_size") or 0),              # 0x10 file_size
        u32(track.get("master_content_id") or 0),      # 0x14 master_content_id
        u32(track.get("master_db_id") or 0),           # 0x18 master_db_id
        int(track.get("artwork_id") or 0),             # 0x1C artwork_id
        int(track.get("key_id") or 0),                 # 0x20 key_id
        0,                                             # 0x24 original_artist_id
        int(track.get("label_id") or 0),               # 0x28 label_id
        0,                                             # 0x2C remixer_id
        int(track.get("bitrate") or 0),                # 0x30 bitrate
        int(track.get("track_number") or 0),           # 0x34 track_number
        bpm_x100,                                      # 0x38 tempo
        int(track.get("genre_id") or 0),               # 0x3C genre_id
        int(track.get("album_id") or 0),               # 0x40 album_id
        int(track.get("artist_id") or 0),              # 0x44 artist_id
        int(track.get("id") or 0),                     # 0x48 id
        int(track.get("disc_number") or 0),            # 0x4C disc_number
        int(track.get("play_count") or 0),             # 0x4E play_count
        int(track.get("year") or 0),                   # 0x50 year
        int(track.get("sample_depth") or 0),           # 0x52 sample_depth
        duration,                                      # 0x54 duration
        0x0029,                                        # 0x56 u5 magic
        int(track.get("color_id") or 0),               # 0x58 color_id
        int(track.get("rating") or 0),                 # 0x59 rating
        file_type,                                     # 0x5A file_type
        0x0003,                                        # 0x5C u7 magic
    )
    assert len(fixed) == 0x5E, f"track fixed header size {len(fixed)} != 0x5E"

    # 21 string offsets
    offset_block = b"".join(struct.pack("<H", o & 0xFFFF) for o in str_offsets)
    payload_block = b"".join(string_payloads)

    return _aligned(fixed + offset_block + payload_block)


def encode_playlist_row(
    playlist_id: int,
    parent_id: int,
    sort_order: int,
    is_folder: bool,
    name: str,
) -> bytes:
    """djmdPlaylist tree row — table 0x07."""
    fixed = struct.pack("<IIIII",
        parent_id,
        0,                  # unknown1
        sort_order,
        playlist_id,
        1 if is_folder else 0)
    return _aligned(fixed + encode_devicesql_string(name))


def encode_playlist_entry_row(entry_index: int, track_id: int, playlist_id: int) -> bytes:
    """djmdSongPlaylist row — table 0x08. 12 bytes, no strings."""
    return struct.pack("<III", entry_index, track_id, playlist_id)


# ─── Top-level builder ────────────────────────────────────────────────────

class PdbBuilder:
    """Assembles a complete export.pdb from per-table row collections.

    Usage:
        b = PdbBuilder()
        b.add_track({"id": 1, "title": "...", ...})
        b.add_artist(1, "Artist")
        b.add_playlist(1, 0, "My PL", is_folder=False)
        b.add_playlist_entry(0, track_id=1, playlist_id=1)
        bytes_out = b.build()
    """

    def __init__(self) -> None:
        self.tracks: List[bytes] = []
        self.artists: List[bytes] = []
        self.albums: List[bytes] = []
        self.keys: List[bytes] = []
        self.genres: List[bytes] = []
        self.labels: List[bytes] = []
        self.playlists: List[bytes] = []
        self.playlist_entries: List[bytes] = []
        # Pre-populate static colour rows so PCOB-color FKs from track rows
        # have someone to point at.
        self.colors: List[bytes] = [
            encode_color_row(cid, name) for cid, name in DEFAULT_COLORS
        ]

    # --- public adders ----------------------------------------------------

    def add_track(self, track: Dict[str, Any]) -> None:
        self.tracks.append(encode_track_row(track))

    def add_artist(self, artist_id: int, name: str) -> None:
        self.artists.append(encode_artist_row(artist_id, name))

    def add_album(self, album_id: int, name: str, artist_id: int = 0) -> None:
        self.albums.append(encode_album_row(album_id, name, artist_id))

    def add_key(self, key_id: int, name: str) -> None:
        self.keys.append(encode_key_row(key_id, name))

    def add_genre(self, genre_id: int, name: str) -> None:
        self.genres.append(encode_genre_row(genre_id, name))

    def add_label(self, label_id: int, name: str) -> None:
        self.labels.append(encode_label_row(label_id, name))

    def add_playlist(
        self, pl_id: int, parent_id: int, name: str,
        sort_order: int = 0, is_folder: bool = False,
    ) -> None:
        self.playlists.append(
            encode_playlist_row(pl_id, parent_id, sort_order, is_folder, name)
        )

    def add_playlist_entry(self, entry_index: int, track_id: int, playlist_id: int) -> None:
        self.playlist_entries.append(
            encode_playlist_entry_row(entry_index, track_id, playlist_id)
        )

    # --- pagination -------------------------------------------------------

    @staticmethod
    def _pages_for_rows(rows: List[bytes], table_type: int) -> List[_Page]:
        """Pack rows into as many 4-KiB pages as they need.

        Greedy: fill page until adding the next row would overflow once
        the row index footer is included. Each row needs 2 bytes of
        offset; each 16-row group needs +4 bytes of flags.
        """
        if not rows:
            # Sentinel single empty page
            return [_Page(page_index=0, table_type=table_type)]

        budget = PDB_PAGE_SIZE - PDB_PAGE_HEADER_LEN
        pages: List[_Page] = []
        current = _Page(page_index=0, table_type=table_type)
        used = 0
        index_overhead = 4   # at least one group's flags

        for r in rows:
            r_size = len(r) + (len(r) & 1)  # pad to even
            row_count_after = len(current.rows_data) + 1
            # Index size: ceil(row_count / 16) groups × 36 bytes
            groups = (row_count_after + 15) // 16
            new_index = groups * 36
            if used + r_size + new_index > budget:
                pages.append(current)
                current = _Page(page_index=len(pages), table_type=table_type)
                used = 0
            current.rows_data.append(r)
            used += r_size
            index_overhead = ((len(current.rows_data) + 15) // 16) * 36

        pages.append(current)
        return pages

    # --- output -----------------------------------------------------------

    def build(self) -> bytes:
        """Assemble the binary file.

        Layout per Crate-Digger / verified against F: drive Rekordbox export:

          page 0   = file header + 20 table descriptors
          page 1   = INDEX page for table 0 (flags=0x64), next_page → 2
          page 2   = data page for table 0 (rows live here, flags=0x24/0x34)
          page 3+  = additional data pages for table 0 (chained via next_page)
          …        = same pattern for subsequent tables

        The first_page in each table descriptor MUST point to an INDEX
        page; data pages follow via next_page. Without this Rekordbox
        flags every page as "transaction in progress" / "corrupted".
        """
        all_pages: List[_Page] = []
        first_page_per_type: Dict[int, int] = {}
        last_page_per_type: Dict[int, int] = {}

        page_seq = 0  # incrementing seqpage across the whole file

        for table_type in TABLE_ORDER:
            rows = {
                T_TRACKS:    self.tracks,
                T_GENRES:    self.genres,
                T_ARTISTS:   self.artists,
                T_ALBUMS:    self.albums,
                T_LABELS:    self.labels,
                T_KEYS:      self.keys,
                T_COLORS:    self.colors,
                T_PLAYLISTS: self.playlists,
                T_PL_ENTRIES: self.playlist_entries,
            }.get(table_type, [])

            data_pages = self._pages_for_rows(rows, table_type)

            # Prepend an empty INDEX page (flags=0x64) — Rekordbox expects
            # first_page in table descriptor to point at an index, not raw
            # data. Even tables with zero rows get an index page.
            index_page = _Page(
                page_index=0,        # patched below
                table_type=table_type,
                next_page=0,         # patched below if data follows
                page_flags=0x64,     # I-bit set (index page)
                rows_data=[],
            )

            first_idx = len(all_pages) + 1
            index_page.page_index = first_idx
            page_seq += 1
            index_page.seqpage = page_seq
            if data_pages:
                # Index page chains to the FIRST data page
                index_page.next_page = first_idx + 1
            all_pages.append(index_page)

            for i, p in enumerate(data_pages):
                p.page_index = first_idx + 1 + i
                page_seq += 1
                p.seqpage = page_seq
                # Data pages chain forward; last one terminates with 0
                p.next_page = (first_idx + 1 + i + 1) if (i + 1 < len(data_pages)) else 0
                all_pages.append(p)

            first_page_per_type[table_type] = first_idx
            last_page_per_type[table_type] = (
                first_idx + len(data_pages) if data_pages else first_idx
            )

        num_tables = len(TABLE_ORDER)
        next_unused = 1 + len(all_pages)

        # File header — match real Rekordbox values where they're known
        header = struct.pack(
            "<IIIIIIII",
            0,                  # 0x00 magic
            PDB_PAGE_SIZE,      # 0x04 page_size
            num_tables,         # 0x08 num_tables
            next_unused,        # 0x0C next_unused_page
            5,                  # 0x10 unknown (real exports have ~5)
            177,                # 0x14 sequence (real exports have higher
                                #      values — 177 lets Rekordbox treat
                                #      this as a "mature" export)
            0, 0,               # 0x18, 0x1C
        )
        header = header[:0x1C]

        for table_type in TABLE_ORDER:
            first = first_page_per_type.get(table_type, 0)
            last = last_page_per_type.get(table_type, 0)
            # empty_candidate MUST NOT be 0 — page 0 is the file header, not
            # a valid candidate for "next available empty page". Rekordbox
            # validates this and flags the device library as corrupted when
            # it sees empty_candidate=0. Real Rekordbox exports always set
            # this to a real page number; for our linear-allocation writer
            # the safest choice is last_page (which is the data page that
            # has free heap space for additional rows).
            header += struct.pack("<IIII", table_type, last, first, last)

        if len(header) > PDB_PAGE_SIZE:
            raise ValueError(f"File header overflow: {len(header)} bytes")
        header += b"\x00" * (PDB_PAGE_SIZE - len(header))

        out = bytearray(header)
        for p in all_pages:
            out.extend(p.build())
        return bytes(out)


# ─── Public sync-time API ─────────────────────────────────────────────────

def write_export_pdb(
    usb_root: Path,
    contents: Optional[List[Dict[str, Any]]] = None,
    artists: Optional[Dict[int, str]] = None,
    albums: Optional[Dict[int, Tuple[str, int]]] = None,
    keys: Optional[Dict[int, str]] = None,
    genres: Optional[Dict[int, str]] = None,
    labels: Optional[Dict[int, str]] = None,
    playlists: Optional[List[Dict[str, Any]]] = None,
    playlist_entries: Optional[List[Tuple[int, int, int]]] = None,
) -> Optional[Path]:
    """Build + write `<usb>/PIONEER/rekordbox/export.pdb`.

    Args:
        contents: list of track dicts (see encode_track_row docstring).
        artists / albums / keys: id → name lookups.
        playlists: list of {id, parent_id, sort_order, is_folder, name}.
        playlist_entries: list of (entry_index, track_id, playlist_id).

    Returns the written path or None on failure. Empty inputs produce a
    minimal-but-valid file (Rekordbox shows "Device Library: 0 tracks").
    """
    rb_dir = Path(usb_root) / "PIONEER" / "rekordbox"
    rb_dir.mkdir(parents=True, exist_ok=True)
    target = rb_dir / "export.pdb"

    builder = PdbBuilder()

    for tr in (contents or []):
        builder.add_track(tr)
    for aid, name in (artists or {}).items():
        builder.add_artist(int(aid), name)
    for aid, payload in (albums or {}).items():
        if isinstance(payload, tuple):
            name, artist_id = payload
        else:
            name, artist_id = payload, 0
        builder.add_album(int(aid), name, int(artist_id))
    for kid, name in (keys or {}).items():
        builder.add_key(int(kid), name)
    for gid, name in (genres or {}).items():
        builder.add_genre(int(gid), name)
    for lid, name in (labels or {}).items():
        builder.add_label(int(lid), name)
    for pl in (playlists or []):
        builder.add_playlist(
            int(pl["id"]),
            int(pl.get("parent_id") or 0),
            pl.get("name") or "",
            int(pl.get("sort_order") or 0),
            bool(pl.get("is_folder")),
        )
    for entry in (playlist_entries or []):
        builder.add_playlist_entry(*entry)

    try:
        data = builder.build()
        target.write_bytes(data)
        logger.info("[PDB] wrote %s (%d B, %d tracks)",
                    target, len(data), len(contents or []))
        return target
    except Exception as exc:
        logger.error("[PDB] write failed: %s", exc, exc_info=True)
        return None


EXT_TABLE_ORDER = [0x00, 0x01, 0x02, 0x03, 0x04]
"""exportExt.pdb has its own 5-entry table directory: 0x03 = tags,
0x04 = tag_tracks (matches reverse-engineered Rekordbox 6 sticks).
Tables 0..2 exist as placeholders for forward-compat — Rekordbox
allocates them but leaves them empty on libraries with no MyTags."""


def encode_tag_row(tag_id: int, name: str, category_id: int = 0,
                   category_pos: int = 0, is_category: bool = False) -> bytes:
    """Tag row (subtype 0x0684 — far name).

    Layout (from Crate Digger spec):
      0x00 u16 subtype     (0x0684 = far-name variant)
      0x02 u16 tag_index   (filled by parent — leave 0)
      0x04 u32 unknown1    (typically zero)
      0x08 u32 unknown2    (typically zero)
      0x0C u32 category_id (0 if this row IS the category)
      0x10 u32 category_pos
      0x14 u32 id
      0x18 u32 raw_is_category (non-zero ⇒ folder)
      0x1C u32 unknown3    (always ends in 0x03 byte 0x1D — empirical)
      0x1E ofs_name_far  (offset to DeviceSQL name string on heap)
      …    name payload
    """
    name_str = encode_devicesql_string(name)
    empty_str = encode_devicesql_string("")
    # u32 fields are unsigned — mask negatives just in case (rbox tag IDs
    # can be in the high u32 range).
    def u32(v: int) -> int:
        return v & 0xFFFFFFFF

    # Layout per Crate Digger spec for far-name variant (subtype 0x0684):
    #   0x00 H subtype           0x18 I raw_is_category
    #   0x02 H tag_index         0x1C H unknown3 (low byte = 0x03)
    #   0x04 I unknown1          0x1E H ofs_name_far
    #   0x08 I unknown2          0x20 H ofs_unknown_far
    #   0x0C I category_id       — header total: 34 bytes (0x22)
    #   0x10 I category_pos      Then name string + empty unknown string
    #   0x14 I id                  on the heap.
    header_size = 0x22
    ofs_name = header_size
    ofs_unknown = ofs_name + len(name_str)
    header = struct.pack(
        "<HHIIIIIIHHH",
        0x0684,                       # 0x00 subtype
        0,                            # 0x02 tag_index
        0,                            # 0x04 unknown1
        0,                            # 0x08 unknown2
        u32(category_id),             # 0x0C category_id
        u32(category_pos),            # 0x10 category_pos
        u32(tag_id),                  # 0x14 id
        1 if is_category else 0,      # 0x18 raw_is_category
        0x0003,                       # 0x1C unknown3 (Rekordbox always 0x0003)
        ofs_name,                     # 0x1E ofs_name_far
        ofs_unknown,                  # 0x20 ofs_unknown_far
    )
    assert len(header) == header_size, f"tag header size {len(header)} != {header_size}"
    return _aligned(header + name_str + empty_str)


def encode_tag_track_row(track_id: int, tag_id: int) -> bytes:
    """Tag-Track association row — 16 bytes flat."""
    return struct.pack("<IIII", 0, track_id, tag_id, 0)


class PdbExtBuilder:
    """exportExt.pdb has its own table layout (5 tables).

    Most users ship a stick with no MyTags so all tables stay empty; the
    file just exists as a sentinel for older firmware. When tags ARE
    populated we write tag rows in table 0x03 and tag-track associations
    in table 0x04.
    """

    def __init__(self) -> None:
        self.tags: List[bytes] = []
        self.tag_tracks: List[bytes] = []

    def add_tag(self, tag_id: int, name: str,
                category_id: int = 0, category_pos: int = 0,
                is_category: bool = False) -> None:
        self.tags.append(
            encode_tag_row(tag_id, name, category_id, category_pos, is_category)
        )

    def add_tag_track(self, track_id: int, tag_id: int) -> None:
        self.tag_tracks.append(encode_tag_track_row(track_id, tag_id))

    def build(self) -> bytes:
        # Same index-page-then-data layout as the main builder so
        # Rekordbox accepts the file without a corruption warning.
        all_pages: List[_Page] = []
        first_page_per_type: Dict[int, int] = {}
        last_page_per_type: Dict[int, int] = {}
        page_seq = 0

        for table_type in EXT_TABLE_ORDER:
            rows = {0x03: self.tags, 0x04: self.tag_tracks}.get(table_type, [])
            data_pages = PdbBuilder._pages_for_rows(rows, table_type)

            index_page = _Page(
                page_index=0, table_type=table_type, next_page=0,
                page_flags=0x64, rows_data=[],
            )
            first_idx = len(all_pages) + 1
            index_page.page_index = first_idx
            page_seq += 1
            index_page.seqpage = page_seq
            if data_pages:
                index_page.next_page = first_idx + 1
            all_pages.append(index_page)

            for i, p in enumerate(data_pages):
                p.page_index = first_idx + 1 + i
                page_seq += 1
                p.seqpage = page_seq
                p.next_page = (first_idx + 1 + i + 1) if (i + 1 < len(data_pages)) else 0
                all_pages.append(p)

            first_page_per_type[table_type] = first_idx
            last_page_per_type[table_type] = (
                first_idx + len(data_pages) if data_pages else first_idx
            )

        num_tables = len(EXT_TABLE_ORDER)
        next_unused = 1 + len(all_pages)
        header = struct.pack(
            "<IIIIIIII",
            0,                   # magic
            PDB_PAGE_SIZE,
            num_tables,
            next_unused,
            5, 177, 0, 0,        # unknown counters mirroring real exports
        )[:0x1C]
        for table_type in EXT_TABLE_ORDER:
            first = first_page_per_type.get(table_type, 0)
            last = last_page_per_type.get(table_type, 0)
            # See PdbBuilder.build() — empty_candidate=0 fails Rekordbox
            # validation. Use last_page (the data page with free space).
            header += struct.pack("<IIII", table_type, last, first, last)
        if len(header) > PDB_PAGE_SIZE:
            raise ValueError(f"Ext header overflow: {len(header)} bytes")
        header += b"\x00" * (PDB_PAGE_SIZE - len(header))

        out = bytearray(header)
        for p in all_pages:
            out.extend(p.build())
        return bytes(out)


def write_export_ext_pdb(
    usb_root: Path,
    tags: Optional[Dict[int, str]] = None,
    tag_categories: Optional[Dict[int, str]] = None,
    tag_track_links: Optional[List[Tuple[int, int]]] = None,
) -> Optional[Path]:
    """Write `<usb>/PIONEER/rekordbox/exportExt.pdb`.

    Args:
        tags: id → name for MyTag definitions.
        tag_categories: id → name for tag categories (organisational
            parents — show up as folders in CDJ tag-browse view).
        tag_track_links: list of (track_id, tag_id) associations.

    All args optional. Empty inputs produce a valid 5-table sentinel
    that older firmware accepts as "no MyTags on this stick".
    """
    rb_dir = Path(usb_root) / "PIONEER" / "rekordbox"
    rb_dir.mkdir(parents=True, exist_ok=True)
    target = rb_dir / "exportExt.pdb"
    builder = PdbExtBuilder()

    # Categories first (they get IDs in the same id space as tags)
    for cat_id, name in (tag_categories or {}).items():
        builder.add_tag(int(cat_id), name, is_category=True)
    pos = 0
    for tag_id, name in (tags or {}).items():
        builder.add_tag(int(tag_id), name, category_id=0, category_pos=pos)
        pos += 1
    for track_id, tag_id in (tag_track_links or []):
        builder.add_tag_track(int(track_id), int(tag_id))

    try:
        target.write_bytes(builder.build())
        logger.info(
            "[PDB-Ext] wrote %s (%d B, %d tags, %d links)",
            target, target.stat().st_size,
            len(tags or {}) + len(tag_categories or {}),
            len(tag_track_links or []),
        )
        return target
    except Exception as exc:
        logger.warning("[PDB-Ext] write failed: %s", exc)
        return None
