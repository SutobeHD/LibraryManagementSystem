"""Byte-level assertions for the dict-driven fields introduced in Slice 0
of waveform-editor-extensions.

- ``_build_pcpt_entry`` reads ``status`` from the cue dict.
- ``_build_pcp2_entry`` reads ``loop_numerator`` / ``loop_denominator``
  from the cue dict.

These tests do NOT assert any byte-layout invariants beyond the fields
they introduce — the broader fixtures (``tests/test_pdb_structure.py``
plus real-export comparisons) gate the rest of the ANLZ writer.

Run from the repo root: ``pytest tests/test_anlz_cue_fields.py -v``.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.anlz_writer import _build_pcp2_entry, _build_pcpt_entry

# --- PCPT.status ---------------------------------------------------------

# Layout of the relevant prefix:
#   tag(4) + hdr_len(4) + total_len(4) = 12
#   + cue_num(4) + status(4) + flags(4) = 12  (status at offset 16..19)


def test_pcpt_hot_cue_default_status_is_4():
    """Backward-compat: hot cue with no explicit ``status`` keeps status=4."""
    cue = {"number": 0, "type": "hot_cue", "time_ms": 1000}
    buf = _build_pcpt_entry(cue)
    status = struct.unpack(">I", buf[16:20])[0]
    assert status == 4


def test_pcpt_memory_cue_default_status_is_0():
    """Backward-compat: memory cue with no explicit ``status`` keeps status=0."""
    cue = {"number": 0, "type": "memory_cue", "time_ms": 1000}
    buf = _build_pcpt_entry(cue)
    status = struct.unpack(">I", buf[16:20])[0]
    assert status == 0


def test_pcpt_explicit_status_0_on_hot_cue():
    """New behaviour: hot cue with explicit ``status=0`` (plain cue) is honoured."""
    cue = {"number": 0, "type": "hot_cue", "time_ms": 1000, "status": 0}
    buf = _build_pcpt_entry(cue)
    status = struct.unpack(">I", buf[16:20])[0]
    assert status == 0


def test_pcpt_explicit_status_4_on_memory_cue():
    """New behaviour: memory cue with explicit ``status=4`` (active loop)
    is honoured — enables memory-loops with the active-loop flag."""
    cue = {"number": 0, "type": "memory_cue", "time_ms": 1000, "status": 4}
    buf = _build_pcpt_entry(cue)
    status = struct.unpack(">I", buf[16:20])[0]
    assert status == 4


# --- PCP2.loop_numerator / loop_denominator -----------------------------

# Layout of the relevant prefix:
#   tag(4) + hdr_len(4) + total_len(4) = 12
#   + cue_num(4) + time(4) + loop_end(4) + color_id(1) + r(1) + g(1) + b(1) = 16  (=28)
#   + loop_numerator(4) + loop_denominator(4) = 8  (loop_num at 28..31, loop_den at 32..35)


def _extract_loop_num_den(buf: bytes) -> tuple[int, int]:
    return struct.unpack(">II", buf[28:36])


def test_pcp2_default_loop_numerator_denominator_is_zero():
    """Backward-compat: missing fields default to ``0 / 0``."""
    cue = {"number": 0, "type": "hot_cue", "time_ms": 1000}
    buf = _build_pcp2_entry(cue)
    num, den = _extract_loop_num_den(buf)
    assert (num, den) == (0, 0)


def test_pcp2_explicit_loop_numerator_denominator():
    """New behaviour: dict values flow through verbatim."""
    cue = {
        "number": 0,
        "type": "hot_cue",
        "time_ms": 1000,
        "loop_len_ms": 500,
        "loop_numerator": 4,
        "loop_denominator": 1,
    }
    buf = _build_pcp2_entry(cue)
    num, den = _extract_loop_num_den(buf)
    assert (num, den) == (4, 1)


def test_pcp2_partial_loop_fields():
    """Defensive: setting numerator but not denominator should not crash;
    the unset field defaults to 0."""
    cue = {
        "number": 0,
        "type": "hot_cue",
        "time_ms": 1000,
        "loop_len_ms": 500,
        "loop_numerator": 8,
    }
    buf = _build_pcp2_entry(cue)
    num, den = _extract_loop_num_den(buf)
    assert (num, den) == (8, 0)
