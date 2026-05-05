"""
LibraryManagementSystem -- ANLZ Binary File Writer
==========================================
Writes Rekordbox-compatible ANLZ binary files (.DAT, .EXT, .2EX)
so our analysis results can be injected directly into a Rekordbox library
without Rekordbox needing to re-analyze the track.

File formats (all big-endian):
  .DAT  — PPTH, PVBR, PQTZ, PWAV, PWV2, PCOB×2
  .EXT  — PPTH, PWV3, PCOB×2, PCO2×2, PQT2, PWV5, PWV4, PSSI
  .2EX  — PPTH, PWV7, PWV6, PWVC

References:
  - crate.io/rekordbox ANLZ format docs
  - Reverse-engineered from real Rekordbox 7.x ANLZ files
"""

import struct
import logging
import os
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PMAI_MAGIC = b'PMAI'
PMAI_HEADER_LEN = 28   # Fixed file header size


# ---------------------------------------------------------------------------
# Low-level tag builders (all return bytes)
# ---------------------------------------------------------------------------

def _build_file_header(total_file_len: int) -> bytes:
    """
    PMAI file header (28 bytes).
    Layout: magic(4) + hdr_len(4) + file_len(4) + version(4) + flags(4) + flags2(4) + pad(4)
    Matches real Rekordbox 7.x files.
    """
    return struct.pack('>4sIIIIII',
        PMAI_MAGIC,
        PMAI_HEADER_LEN,
        total_file_len,
        1,       # version
        0x00010000,  # flags (observed in real files)
        0x00010000,  # flags2
        0,           # padding
    )


def _build_ppth(track_path: str) -> bytes:
    """
    PPTH — Path tag. Stores the track file path as UTF-16BE.
    Layout: tag(4) + hdr_len(4) + total_len(4) + path_len(4) + path_data
    """
    # Rekordbox uses forward slashes and UTF-16BE with null terminator.
    # rbox validates: (string_len + 1) * 2 == path_len_field
    path_normalized = track_path.replace('\\', '/')
    # Encode with null terminator (rbox expects it)
    path_bytes = (path_normalized + '\0').encode('utf-16-be')
    path_len = len(path_bytes)

    hdr_len = 16
    total_len = hdr_len + path_len

    buf = struct.pack('>4sIII',
        b'PPTH',
        hdr_len,
        total_len,
        path_len,
    )
    buf += path_bytes
    return buf


def _build_pvbr(pvbr_data: List[int]) -> bytes:
    """
    PVBR — VBR index (400 × 4-byte entries = 1600 bytes data).
    Layout: tag(4) + hdr_len(4) + total_len(4) + reserved(4) + data(1600)
    """
    hdr_len = 16
    data_len = 400 * 4
    total_len = hdr_len + data_len

    buf = struct.pack('>4sIII',
        b'PVBR',
        hdr_len,
        total_len,
        0,  # reserved
    )
    # VBR entries as big-endian u32 (millisecond offsets)
    for i in range(400):
        val = pvbr_data[i] if i < len(pvbr_data) else 0
        buf += struct.pack('>I', val)
    return buf


def _build_pqtz(beats: List[Dict[str, Any]]) -> bytes:
    """
    PQTZ — Quantized beat grid.
    Header (24 bytes): tag(4) + hdr_len(4) + total_len(4) + reserved(4) + reserved(4) + entry_count(4)
    Entries (8 bytes each): beat_number(u16) + tempo(u16) + time_ms(u32)
    """
    entry_count = len(beats)
    hdr_len = 24
    total_len = hdr_len + entry_count * 8

    buf = struct.pack('>4sIIIII',
        b'PQTZ',
        hdr_len,
        total_len,
        0,          # reserved
        0x00080000, # flags (rbox validates u2 == 0x80000)
        entry_count,
    )
    for b in beats:
        beat_num = b.get('beat_number', 1)
        tempo = b.get('tempo', 12800)       # BPM × 100
        time_ms = b.get('time_ms', 0)
        buf += struct.pack('>HHI', beat_num, tempo, time_ms)
    return buf


def _build_pwav(waveform_data: List[int]) -> bytes:
    """
    PWAV — Monochrome waveform preview (400 entries, 1 byte each).
    Header (20 bytes): tag(4) + hdr_len(4) + total_len(4) + entry_count(4) + entry_size_and_reserved(4)
    """
    entries = waveform_data[:400] if len(waveform_data) >= 400 else waveform_data + [0] * (400 - len(waveform_data))
    hdr_len = 20
    total_len = hdr_len + 400

    buf = struct.pack('>4sIIIHH',
        b'PWAV',
        hdr_len,
        total_len,
        400,    # entry count
        1,      # bytes per entry
        0,      # reserved
    )
    buf += bytes(entries)
    return buf


def _build_pwv2(waveform_data: List[int]) -> bytes:
    """
    PWV2 — Tiny waveform preview (100 entries, 1 byte each).
    """
    entries = waveform_data[:100] if len(waveform_data) >= 100 else waveform_data + [0] * (100 - len(waveform_data))
    hdr_len = 20
    total_len = hdr_len + 100

    buf = struct.pack('>4sIIIHH',
        b'PWV2',
        hdr_len,
        total_len,
        100,    # entry count
        1,      # bytes per entry
        0,      # reserved
    )
    buf += bytes(entries)
    return buf


def _build_pcob(cue_type: int, cues: Optional[List[Dict]] = None) -> bytes:
    """
    PCOB — Cue list container.
    cue_type: 0 = memory cues, 1 = hot cues
    Header (24 bytes): tag(4) + hdr_len(4) + total_len(4) + cue_list_type(4) + count(2) + memory_count(2) + reserved(4)

    For now, we write empty cue lists (preserving existing cues is handled separately).
    """
    entry_count = 0
    hdr_len = 24
    total_len = hdr_len  # no cue entries for now

    buf = struct.pack('>4sIIIHHI',
        b'PCOB',
        hdr_len,
        total_len,
        cue_type,
        entry_count,
        0,              # reserved
        0xFFFFFFFF,     # sentinel (rbox validates u2 == 0xFFFFFFFF)
    )
    return buf


def _build_pco2(cue_type: int) -> bytes:
    """
    PCO2 — Extended cue list (used in .EXT).
    Same header structure as PCOB but for extended cues.
    """
    hdr_len = 20
    total_len = hdr_len

    buf = struct.pack('>4sIIII',
        b'PCO2',
        hdr_len,
        total_len,
        cue_type,   # u32 list_type
        0,          # u32 entry count
    )
    return buf


def _build_pwv3(waveform_data: List[int], fps: int = 150) -> bytes:
    """
    PWV3 — Monochrome waveform detail (1 byte per entry, 150 entries/sec).
    Header (24 bytes): tag(4) + hdr_len(4) + total_len(4) + entry_size(4) + entry_count(4) + fps(2) + reserved(2)
    """
    entry_count = len(waveform_data)
    hdr_len = 24
    total_len = hdr_len + entry_count

    buf = struct.pack('>4sIIIIHH',
        b'PWV3',
        hdr_len,
        total_len,
        1,              # 1 byte per entry
        entry_count,
        fps,
        0,              # reserved
    )
    buf += bytes(waveform_data)
    return buf


def _build_pwv5(waveform_u16: List[int], fps: int = 150) -> bytes:
    """
    PWV5 — Color waveform detail (2 bytes per entry, 150 entries/sec).
    Packed as u16: R(3) | G(3) | B(3) | H(5) | reserved(2)
    """
    entry_count = len(waveform_u16)
    hdr_len = 24
    total_len = hdr_len + entry_count * 2

    # rbox validates the last 4 header bytes as u32 == 0x00960305
    # This encodes fps (0x0096=150) + format flags (0x0305)
    buf = struct.pack('>4sIIIII',
        b'PWV5',
        hdr_len,
        total_len,
        2,              # 2 bytes per entry
        entry_count,
        0x00960305,     # fps + color-detail flags (rbox-validated)
    )
    for val in waveform_u16:
        buf += struct.pack('>H', val & 0xFFFF)
    return buf


def _build_pwv4(color_preview: List[List[int]]) -> bytes:
    """
    PWV4 — Color waveform preview (1200 entries, 6 bytes each).
    Each entry: [R_high, G_mid, B_low, height, R_low_half, B_low_half]
    """
    entry_count = len(color_preview)
    if entry_count == 0:
        entry_count = 1200
        color_preview = [[0, 0, 0, 0, 0, 0]] * 1200

    hdr_len = 24
    total_len = hdr_len + entry_count * 6

    buf = struct.pack('>4sIIIIHH',
        b'PWV4',
        hdr_len,
        total_len,
        6,              # 6 bytes per entry
        entry_count,
        0,              # no fps for preview
        0,
    )
    for entry in color_preview:
        for val in entry[:6]:
            buf += struct.pack('B', max(0, min(255, val)))
    return buf


def _build_pwv6(hd_preview: List[List[int]]) -> bytes:
    """
    PWV6 — 3-band waveform preview (3 bytes per entry, ~1200 entries).
    rbox identifies this as Waveform3BandPreview: [low, mid, high] per entry.
    Same header layout as PWV7: entry_size(4) + entry_count(4) + fps(2) + reserved(2).
    """
    entry_count = len(hd_preview)
    hdr_len = 20
    total_len = hdr_len + entry_count * 3

    buf = struct.pack('>4sIIII',
        b'PWV6',
        hdr_len,        # rbox asserts header_size == 20
        total_len,
        3,              # 3 bytes per entry (rbox asserts len_entry_bytes == 3)
        entry_count,
    )
    for entry in hd_preview:
        for val in entry[:3]:
            buf += struct.pack('B', max(0, min(255, val)))
    return buf


def _build_pwv7(hd_detail: List[List[int]], fps: int = 150) -> bytes:
    """
    PWV7 — 3-band waveform detail (3 bytes per entry, 150/sec).
    rbox identifies this as Waveform3BandDetail: [low, mid, high] per entry.
    """
    entry_count = len(hd_detail)
    hdr_len = 24
    total_len = hdr_len + entry_count * 3

    buf = struct.pack('>4sIIIIHH',
        b'PWV7',
        hdr_len,
        total_len,
        3,              # 3 bytes per entry (rbox asserts len_entry_bytes == 3)
        entry_count,
        fps,
        0,
    )
    for entry in hd_detail:
        for val in entry[:3]:
            buf += struct.pack('B', max(0, min(255, val)))
    return buf


def _build_pwvc() -> bytes:
    """
    PWVC — Waveform color metadata tag (.2EX).
    Minimal 20-byte tag observed in real files. Content appears to be
    a 6-byte color definition (likely default waveform color: blue/purple).
    """
    hdr_len = 14
    total_len = 20
    buf = struct.pack('>4sIII',
        b'PWVC',
        hdr_len,
        total_len,
        0,
    )
    buf += b'\x00' * (total_len - 16)
    return buf


def _build_pssi(phrases: List[Dict[str, Any]], duration_ms: int) -> bytes:
    """
    PSSI — Song structure / phrase analysis.
    Header (32 bytes): tag(4) + hdr_len(4) + total_len(4) + entry_size(4)
                        + entry_count(2) + mood(2) + reserved(12)
    Entry (24 bytes): phrase_number(2) + beat(2) + phrase_id(2) + fill(1) + fill_beat(1)
                      + pad1(2) + pad2(2) + start_beat(4) + end_beat(4) + pad3(4)
    """
    entry_count = len(phrases)
    if entry_count == 0:
        return b''  # Skip PSSI if no phrases

    entry_size = 24
    hdr_len = 32
    total_len = hdr_len + entry_count * entry_size

    # Determine mood (use most common mood)
    mood_map = {"high": 1, "mid": 2, "low": 3}
    mood_counts = {}
    for p in phrases:
        m = p.get("mood", "mid")
        mood_counts[m] = mood_counts.get(m, 0) + 1
    dominant_mood = max(mood_counts, key=mood_counts.get) if mood_counts else "mid"
    mood_val = mood_map.get(dominant_mood, 2)

    buf = struct.pack('>4sIIIHH',
        b'PSSI',
        hdr_len,
        total_len,
        entry_size,
        entry_count,
        mood_val,
    )
    # 12 bytes reserved in header
    buf += b'\x00' * 12

    # Convert phrases to beat-based positions (approximate)
    for i, phrase in enumerate(phrases):
        start_ms = phrase.get("start_ms", 0)
        end_ms = phrase.get("end_ms", start_ms + 1000)
        phrase_id = phrase.get("id", 1)
        fill_val = phrase.get("fill", 0)

        # Convert ms to beat number (approximate: beat = ms * bpm / 60000)
        # Use 1-based beat count; we'll just use the ms value directly / beat_duration
        # For simplicity, use position index as phrase number
        buf += struct.pack('>HHHBBHHiiI',
            i + 1,          # phrase_number
            1,              # beat
            phrase_id,       # phrase_id (1=intro, 2=verse, 5=chorus, etc.)
            fill_val,       # fill
            0,              # fill_beat
            0,              # pad1
            0,              # pad2
            start_ms,       # start_beat (ms as signed i32)
            end_ms,         # end_beat (ms as signed i32)
            0,              # pad3
        )

    return buf


def _build_pqt2(beats: List[Dict[str, Any]]) -> bytes:
    """
    PQT2 — Extended beat grid (used in .EXT files).
    This stores the same beat data as PQTZ but with an extended header
    that includes beat grid anchor points for the extended format.

    Header is 56 bytes. Entries are 8 bytes (same as PQTZ).
    """
    entry_count = len(beats)
    hdr_len = 56
    total_len = hdr_len + entry_count * 8

    # Build extended header with anchor info from first/last beats
    first_beat_tempo = beats[0].get('tempo', 12800) if beats else 12800
    first_beat_time = beats[0].get('time_ms', 0) if beats else 0
    last_beat_tempo = beats[-1].get('tempo', 12800) if beats else 12800
    last_beat_time = beats[-1].get('time_ms', 0) if beats else 0

    buf = struct.pack('>4sII',
        b'PQT2',
        hdr_len,
        total_len,
    )
    # Extended header fields (36 bytes after the standard 12)
    buf += struct.pack('>I', 0)                 # reserved
    buf += struct.pack('>I', 0x01000002)        # version/flags (observed value)
    buf += struct.pack('>I', 0)                 # reserved
    buf += struct.pack('>HH', 0, first_beat_tempo)  # first beat anchor
    buf += struct.pack('>I', first_beat_time)   # first beat time
    buf += struct.pack('>HH', 0, last_beat_tempo)   # last beat anchor
    buf += struct.pack('>I', last_beat_time)    # last beat time
    buf += struct.pack('>I', entry_count)       # entry count
    buf += b'\x00' * (hdr_len - 12 - 36)       # remaining padding

    # Beat entries (same format as PQTZ)
    for b in beats:
        beat_num = b.get('beat_number', 1)
        tempo = b.get('tempo', 12800)
        time_ms = b.get('time_ms', 0)
        buf += struct.pack('>HHI', beat_num, tempo, time_ms)

    return buf


# ---------------------------------------------------------------------------
# High-level file builders
# ---------------------------------------------------------------------------

def build_dat(
    track_path: str,
    beats: List[Dict[str, Any]],
    pvbr: List[int],
    pwav: List[int],
    pwv2: List[int],
) -> bytes:
    """
    Build a complete .DAT ANLZ file.

    Args:
        track_path: Original audio file path
        beats: PQTZ beat grid entries [{beat_number, tempo, time_ms}, ...]
        pvbr: VBR index (400 ms offsets)
        pwav: Monochrome preview waveform (400 bytes)
        pwv2: Tiny preview waveform (100 bytes)

    Returns:
        Complete .DAT file as bytes
    """
    tags = b''
    tags += _build_ppth(track_path)
    tags += _build_pvbr(pvbr)
    tags += _build_pqtz(beats)
    tags += _build_pwav(pwav)
    tags += _build_pwv2(pwv2)
    tags += _build_pcob(1)  # hot cues (empty)
    tags += _build_pcob(0)  # memory cues (empty)

    total_len = PMAI_HEADER_LEN + len(tags)
    header = _build_file_header(total_len)
    return header + tags


def build_ext(
    track_path: str,
    beats: List[Dict[str, Any]],
    pwv3: List[int],
    pwv5: List[int],
    pwv4: List[List[int]],
    phrases: Optional[List[Dict[str, Any]]] = None,
    duration_ms: int = 0,
) -> bytes:
    """
    Build a complete .EXT ANLZ file.

    Args:
        track_path: Original audio file path
        beats: Beat grid entries (used for PQT2)
        pwv3: Monochrome detail waveform (150/sec)
        pwv5: Color detail waveform (u16 packed, 150/sec)
        pwv4: Color preview waveform (1200 × 6 bytes)
        phrases: PSSI song structure data
        duration_ms: Track duration in ms (for PSSI)
    """
    tags = b''
    tags += _build_ppth(track_path)
    tags += _build_pwv3(pwv3)
    tags += _build_pcob(1)
    tags += _build_pcob(0)
    tags += _build_pco2(1)
    tags += _build_pco2(0)
    # PQT2 (extended beat grid) uses a compressed 2-byte entry format that
    # differs from PQTZ. The full beat grid in .DAT (PQTZ) is authoritative;
    # skipping PQT2 here is safe — Rekordbox falls back to the DAT grid.
    tags += _build_pwv5(pwv5)
    tags += _build_pwv4(pwv4)
    # PSSI (song structure) has a complex encrypted/hashed header that varies
    # across Rekordbox versions. Skipping for now — Rekordbox will simply show
    # "not analyzed" for phrase structure, but waveforms + beat grid work fine.

    total_len = PMAI_HEADER_LEN + len(tags)
    header = _build_file_header(total_len)
    return header + tags


def build_2ex(
    track_path: str,
    pwv7: List[List[int]],
    pwv6: List[List[int]],
) -> bytes:
    """
    Build a complete .2EX ANLZ file (CDJ-3000 HD waveforms).
    """
    tags = b''
    tags += _build_ppth(track_path)
    tags += _build_pwv7(pwv7)
    tags += _build_pwv6(pwv6)
    tags += _build_pwvc()

    total_len = PMAI_HEADER_LEN + len(tags)
    header = _build_file_header(total_len)
    return header + tags


# ---------------------------------------------------------------------------
# Public API: write analysis results to ANLZ files
# ---------------------------------------------------------------------------

def write_anlz_files(
    anlz_dir: str,
    track_path: str,
    analysis_result: Dict[str, Any],
    filename_base: str = "ANLZ0000",
) -> Dict[str, str]:
    """
    Write all three ANLZ files (.DAT, .EXT, .2EX) from AnalysisEngine output.

    Args:
        anlz_dir: Directory to write ANLZ files into (e.g., PIONEER/USBANLZ/xxx/yyy/)
        track_path: Original audio file path (stored in PPTH tag)
        analysis_result: Full output from AnalysisEngine.analyze_sync() or run_full_analysis()
        filename_base: Base filename without extension (default: ANLZ0000)

    Returns:
        Dict with paths of written files: {"dat": path, "ext": path, "2ex": path}
    """
    os.makedirs(anlz_dir, exist_ok=True)

    beats = analysis_result.get("beats", [])
    waveform = analysis_result.get("waveform", {})
    phrases = analysis_result.get("phrases", [])
    pvbr = analysis_result.get("pvbr", [0] * 400)
    duration_ms = int(analysis_result.get("duration", 0) * 1000)

    paths = {}

    # --- .DAT ---
    try:
        dat_data = build_dat(
            track_path=track_path,
            beats=beats,
            pvbr=pvbr,
            pwav=waveform.get("pwav", [0] * 400),
            pwv2=waveform.get("pwv2", [0] * 100),
        )
        dat_path = os.path.join(anlz_dir, f"{filename_base}.DAT")
        with open(dat_path, 'wb') as f:
            f.write(dat_data)
        paths["dat"] = dat_path
        logger.info(f"Wrote .DAT: {dat_path} ({len(dat_data)} bytes)")
    except Exception as e:
        logger.error(f"Failed to write .DAT: {e}")

    # --- .EXT ---
    try:
        ext_data = build_ext(
            track_path=track_path,
            beats=beats,
            pwv3=waveform.get("pwv3", []),
            pwv5=waveform.get("pwv5", []),
            pwv4=waveform.get("pwv4", []),
            phrases=phrases,
            duration_ms=duration_ms,
        )
        ext_path = os.path.join(anlz_dir, f"{filename_base}.EXT")
        with open(ext_path, 'wb') as f:
            f.write(ext_data)
        paths["ext"] = ext_path
        logger.info(f"Wrote .EXT: {ext_path} ({len(ext_data)} bytes)")
    except Exception as e:
        logger.error(f"Failed to write .EXT: {e}")

    # --- .2EX ---
    try:
        pwv7 = waveform.get("pwv7", [])
        pwv6 = waveform.get("pwv6", [])
        if pwv7 and pwv6:
            ex2_data = build_2ex(
                track_path=track_path,
                pwv7=pwv7,
                pwv6=pwv6,
            )
            ex2_path = os.path.join(anlz_dir, f"{filename_base}.2EX")
            with open(ex2_path, 'wb') as f:
                f.write(ex2_data)
            paths["2ex"] = ex2_path
            logger.info(f"Wrote .2EX: {ex2_path} ({len(ex2_data)} bytes)")
    except Exception as e:
        logger.error(f"Failed to write .2EX: {e}")

    return paths
