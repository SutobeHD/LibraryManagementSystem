"""Tests for app/anlz_writer.py logic-safety guards (NOT byte-layout).

These lock the out-of-range clamp in the 1-byte waveform builders (PWAV/PWV2/
PWV3) — for valid 0..255 input the output is byte-identical; the test only
asserts it no longer raises on out-of-range and that valid bytes round-trip.
Byte-layout itself is covered by tests/test_anlz_reference_parse.py.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.anlz_writer import _build_pwav, _build_pwv2, _build_pwv3  # noqa: E402


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


def test_pwv2_out_of_range_clamped():
    out = _build_pwv2([256, -1, 50])
    assert out[:4] == b"PWV2"
    assert out[20:23] == bytes([255, 0, 50])


def test_pwv3_out_of_range_clamped_preserves_count():
    out = _build_pwv3([10, 300, -2])
    assert out[:4] == b"PWV3"
    # entry_count (offset 16, u32 BE) stays 3 — clamping doesn't drop entries
    assert out[16:20] == (3).to_bytes(4, "big")
    assert out[24:27] == bytes([10, 255, 0])
