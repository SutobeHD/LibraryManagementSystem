"""Tests for app/anlz_writer.py logic-safety guards + waveform tag headers.

These lock the out-of-range clamp in the waveform builders: PWAV/PWV3 clamp to
0..255 (valid input is byte-identical), PWV2 to its 4-bit range 0..15 and
PWV4/PWV6/PWV7 to 7 bit. The header bytes asserted here are the ones Rekordbox
writes (docs/reference/rbxport/waveform.md section 3.1). Whole-file layout is
covered by tests/test_anlz_reference_parse.py.
"""

from __future__ import annotations

import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.anlz_writer import (  # noqa: E402
    _build_pwav,
    _build_pwv2,
    _build_pwv3,
    _build_pwv4,
    _build_pwv5,
    _build_pwv6,
    _build_pwv7,
)


def test_pwav_valid_values_byte_identical():
    # All-in-range input: the clamp is the identity, payload is the raw bytes.
    data = [0, 1, 127, 255] + [0] * 396
    out = _build_pwav(data)
    assert out[:4] == b"PWAV"
    assert out[20:24] == bytes([0, 1, 127, 255])  # payload starts after 20B header


def test_pwav_out_of_range_does_not_crash():
    """Regression: bytes([300]) / bytes([-1]) would raise ValueError; the
    builder must clamp like PWV4/6/7 instead of crashing the whole .DAT write."""
    out = _build_pwav([300, -5, 1000, 128])
    payload = out[20:24]
    assert payload == bytes([255, 0, 255, 128])  # clamped to 0..255


def test_pwv2_clamped_to_4_bit():
    """PWV2 is height-only 1..15: one byte > 15 makes Nexus-era firmware reject
    the whole preview, so the writer clamps instead of passing it through."""
    out = _build_pwv2([256, -1, 50, 15, 7])
    assert out[:4] == b"PWV2"
    assert out[20:25] == bytes([15, 0, 15, 15, 7])


def test_pwv4_header_and_7_bit_clamp():
    out = _build_pwv4([[200, 0, 0, 127, 128, -3]] * 1200)
    assert out[:24] == b"PWV4" + struct.pack(">IIIIHH", 24, 24 + 1200 * 6, 6, 1200, 0, 0)
    assert out[24:30] == bytes([127, 0, 0, 127, 127, 0])


def test_pwv6_header_and_7_bit_clamp():
    out = _build_pwv6([[255, 127, 64]] * 1200)
    assert out[:20] == b"PWV6" + struct.pack(">IIII", 20, 20 + 1200 * 3, 3, 1200)
    assert out[20:23] == bytes([127, 127, 64])


def test_pwv7_header_and_7_bit_clamp():
    out = _build_pwv7([[0, 128, 300], [1, 2, 3]])
    assert out[:24] == b"PWV7" + struct.pack(">IIIIHH", 24, 24 + 2 * 3, 3, 2, 150, 0)
    assert out[24:30] == bytes([0, 127, 127, 1, 2, 3])


def test_pwv5_header_and_bit_layout():
    # R=low 7, G=mid 5, B=high 1, height 31
    val = (7 << 13) | (5 << 10) | (1 << 7) | (31 << 2)
    out = _build_pwv5([val])
    assert out[:24] == b"PWV5" + struct.pack(">IIIII", 24, 26, 2, 1, 0x00960305)
    assert out[24:26] == struct.pack(">H", val)


def test_pwv3_out_of_range_clamped_preserves_count():
    out = _build_pwv3([10, 300, -2])
    assert out[:4] == b"PWV3"
    # entry_count (offset 16, u32 BE) stays 3 — clamping doesn't drop entries
    assert out[16:20] == (3).to_bytes(4, "big")
    assert out[24:27] == bytes([10, 255, 0])
