"""ANLZ binary writer — hot-cue limit + byte-layout tests.

Covers the lift from 8 → 16 hot cues (banks A..P) in the PCOB / PCO2 cue
list builders. Verifies that the wider limit does not disturb the
byte-for-byte layout Rekordbox / CDJ-3000 expect:

  1. REKORDBOX_MAX_HOT_CUES is the 16-slot format ceiling.
  2. PCOB / PCO2 hot-cue lists emit up to 16 entries, excess truncated.
  3. PCPT entries stay 56 bytes; cue_num is 1-indexed (1..16 = A..P).
  4. Memory-cue lists are NOT bound by the hot-cue ceiling.
  5. The legacy <=8 case is byte-identical to before.

Run standalone (no pytest / no FastAPI dep needed):
  python tests/test_anlz_writer.py
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.anlz_writer import (
    REKORDBOX_MAX_HOT_CUES,
    _build_pco2,
    _build_pcob,
    _build_pcpt_entry,
)

PCPT_SIZE = 56
PCOB_HDR = 24


def _hot(number: int, time_ms: int = 1000) -> dict:
    return {"type": "hot_cue", "number": number, "time_ms": time_ms}


def _memory(time_ms: int) -> dict:
    return {"type": "memory_cue", "number": 0, "time_ms": time_ms}


def test_max_hot_cues_constant():
    assert REKORDBOX_MAX_HOT_CUES == 16


def test_pcob_writes_full_16_hot_cue_bank():
    buf = _build_pcob(1, [_hot(i, time_ms=i * 1000) for i in range(16)])
    tag, _hdr_len, total_len, cue_type, count, mem_count, _sentinel = struct.unpack(
        ">4sIIIHHI", buf[:PCOB_HDR]
    )
    assert tag == b"PCOB"
    assert cue_type == 1
    assert count == 16
    assert mem_count == 0  # hot-cue list leaves memory_count zero
    assert total_len == PCOB_HDR + 16 * PCPT_SIZE
    assert len(buf) == total_len


def test_pcob_truncates_excess_hot_cues_to_16():
    buf = _build_pcob(1, [_hot(i) for i in range(25)])
    count = struct.unpack(">H", buf[16:18])[0]
    assert count == REKORDBOX_MAX_HOT_CUES


def test_pco2_truncates_excess_hot_cues_to_16():
    buf = _build_pco2(1, [_hot(i) for i in range(25)])
    tag, _hdr_len, _total_len, _cue_type, count = struct.unpack(">4sIIII", buf[:20])
    assert tag == b"PCO2"
    assert count == REKORDBOX_MAX_HOT_CUES


def test_pcob_hot_cue_numbers_are_1_indexed():
    """Slots A..P must serialize as cue_num 1..16 (0 is reserved for memory)."""
    buf = _build_pcob(1, [_hot(i) for i in range(16)])
    nums = []
    for i in range(16):
        start = PCOB_HDR + i * PCPT_SIZE
        nums.append(struct.unpack(">I", buf[start + 12 : start + 16])[0])
    assert nums == list(range(1, 17))


def test_pcpt_entry_layout_for_last_slot():
    """Hot cue number 15 (slot P) → 56-byte PCPT with cue_num 16."""
    entry = _build_pcpt_entry(_hot(15, time_ms=42000))
    assert len(entry) == PCPT_SIZE
    assert entry[:4] == b"PCPT"
    assert struct.unpack(">I", entry[12:16])[0] == 16
    assert struct.unpack(">I", entry[32:36])[0] == 42000


def test_memory_cue_list_not_capped_by_hot_limit():
    """Memory cues have no 16-slot ceiling; only hot cues do."""
    buf = _build_pcob(0, [_memory(i * 1000) for i in range(30)])
    count, mem_count = struct.unpack(">HH", buf[16:20])
    assert count == 30
    assert mem_count == 30


def test_pcob_legacy_eight_cue_case_unchanged():
    buf = _build_pcob(1, [_hot(i) for i in range(8)])
    count = struct.unpack(">H", buf[16:18])[0]
    assert count == 8
    assert len(buf) == PCOB_HDR + 8 * PCPT_SIZE


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
