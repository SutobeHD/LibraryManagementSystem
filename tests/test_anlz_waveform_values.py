"""Value model of the ANLZ waveform tags (app/analysis_engine.py generate_waveform_data).

Locks what the tmp/wf harness measured against Rekordbox's own files: value
ranges per tag, which band lands in which byte (R/low, G/mid, B/high), bucket
pooling instead of point sampling, the squared-peak height curve, the PWAV /
PWV2 floors and the MP3 decoder lead-in. Synthetic audio only; scipy.signal is
patched in so the heavy lazy imports (madmom, essentia) stay out.
"""

from __future__ import annotations

import itertools
import os
import sys
from pathlib import Path

import numpy as np
import pytest
import scipy.signal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import analysis_engine as ae  # noqa: E402

SR = 44100
HOP = SR // 150


@pytest.fixture(autouse=True)
def _scipy_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ae, "signal", scipy.signal)


def _tone(freq: float, seconds: float, amp: float = 0.8) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def _music_like(seconds: float = 12.0) -> np.ndarray:
    """Kick-ish bass + mid tone + hiss, with a quiet break in the middle."""
    rng = np.random.default_rng(7)
    t = np.arange(int(seconds * SR)) / SR
    gate = (np.sin(2 * np.pi * 2 * t) > 0).astype(np.float32)
    y = 0.5 * np.sin(2 * np.pi * 55 * t) * gate + 0.2 * np.sin(2 * np.pi * 700 * t)
    y += 0.08 * rng.standard_normal(len(t))
    y[int(5 * SR) : int(6 * SR)] *= 0.05
    return y.astype(np.float32)


# --------------------------------------------------------------------------- ranges + counts
def test_tag_ranges_and_entry_counts():
    y = _music_like()
    wf = ae.generate_waveform_data(y, SR)
    n_cols = -(-len(y) // HOP)

    assert len(wf["pwav"]) == 400
    assert len(wf["pwv2"]) == 100
    assert len(wf["pwv4"]) == 1200
    assert len(wf["pwv6"]) == 1200
    assert len(wf["pwv3"]) == len(wf["pwv5"]) == len(wf["pwv7"]) == n_cols
    assert wf["detail_entries"] == n_cols

    pwav = np.array(wf["pwav"])
    assert (pwav & 0x1F).min() >= 2 and (pwav & 0x1F).max() <= 25
    pwv2 = np.array(wf["pwv2"])
    assert pwv2.min() >= 1 and pwv2.max() <= 15  # 4-bit height, no whiteness bits
    pwv3 = np.array(wf["pwv3"])
    assert pwv3.max() <= 255 and (pwv3 & 0x1F).max() <= 31
    pwv4 = np.array(wf["pwv4"])
    assert pwv4.shape == (1200, 6) and pwv4.min() >= 0 and pwv4.max() <= 127
    assert not pwv4[:, 1].any() and not pwv4[:, 2].any()
    for key in ("pwv6", "pwv7"):
        arr = np.array(wf[key])
        assert arr.shape[1] == 3 and arr.min() >= 0 and arr.max() <= 127
    pwv5 = np.array(wf["pwv5"], dtype=np.int64)
    assert pwv5.max() < 1 << 16
    assert not (pwv5 & 0x3).any()  # bits 1-0 unused
    assert ((pwv5 >> 10) & 7).max() <= 5  # green tops out at 5


def test_silence_keeps_preview_floors():
    """A 0 height in PWAV/PWV2 reads as 'unanalysed' on players."""
    y = np.zeros(SR * 4, dtype=np.float32)
    y[SR : SR + 200] = 0.5  # one blip so the track is not all-silent
    wf = ae.generate_waveform_data(y, SR)
    assert (np.array(wf["pwav"]) & 0x1F).min() == 2
    assert min(wf["pwv2"]) >= 1
    pwv3 = np.array(wf["pwv3"])
    assert set((pwv3[:140] >> 5).tolist()) == {7}  # digital silence is fully white


# --------------------------------------------------------------------------- band -> byte order
SEGMENT_S = 4.0
BAND_TONES = (55.0, 800.0, 9000.0)  # low, mid, high


def _segment_means(arr: np.ndarray, n_segments: int = 3) -> np.ndarray:
    """Mean per segment (rows) and channel (cols), segment edges trimmed by 10 %."""
    edges = np.linspace(0, len(arr), n_segments + 1).astype(int)
    out = []
    for a, b in itertools.pairwise(edges.tolist()):
        pad = (b - a) // 10
        out.append(arr[a + pad : b - pad].mean(axis=0))
    return np.array(out)


@pytest.fixture(scope="module")
def three_band_wf() -> dict:
    """Low tone, then mid tone, then high tone. Per-track band scaling makes
    absolute channel levels incomparable, so each channel must peak in ITS
    segment instead."""
    y = np.concatenate([_tone(f, SEGMENT_S) for f in BAND_TONES])
    with pytest.MonkeyPatch.context() as mp:  # module scope: no function monkeypatch
        mp.setattr(ae, "signal", scipy.signal)
        return ae.generate_waveform_data(y, SR)


@pytest.mark.parametrize("key", ["pwv7", "pwv6"])
def test_three_band_channel_order(three_band_wf: dict, key: str):
    seg = _segment_means(np.array(three_band_wf[key], dtype=float))
    for band in range(3):
        assert int(np.argmax(seg[:, band])) == band, (key, band, seg.round(1).tolist())


def test_pwv4_colour_bytes_follow_bands(three_band_wf: dict):
    pwv4 = np.array(three_band_wf["pwv4"], dtype=float)
    seg = _segment_means(pwv4[:, 3:6])  # b3=R=low, b4=G=mid, b5=B=high
    for band in range(3):
        assert int(np.argmax(seg[band])) == band, seg.round(1).tolist()
        assert int(np.argmax(seg[:, band])) == band
    assert seg[:, :].max() <= 127


def test_pwv5_strongest_band_is_full_scale(three_band_wf: dict):
    pwv5 = np.array(three_band_wf["pwv5"], dtype=np.int64)
    rgb = np.stack([(pwv5 >> 13) & 7, (pwv5 >> 10) & 7, (pwv5 >> 7) & 7], axis=1).astype(float)
    seg = _segment_means(rgb)
    for band, full in zip(range(3), (7, 5, 7), strict=True):
        assert int(np.argmax(seg[band])) == band, seg.round(2).tolist()
        assert seg[band, band] == pytest.approx(full, abs=0.25)


def test_pwv5_bass_is_red_not_blue():
    pwv5 = np.array(ae.generate_waveform_data(_tone(50.0, 4.0), SR)["pwv5"], dtype=np.int64)
    core = pwv5[150:-150]
    assert np.median((core >> 13) & 7) == 7  # R
    assert np.median((core >> 7) & 7) <= 1  # B


# --------------------------------------------------------------------------- height curve
def test_detail_height_is_squared_sample_peak():
    for amp, expected in ((1.0, 31), (0.5, 8), (0.25, 2)):
        y = np.full(SR * 2, amp, dtype=np.float32)
        y[::2] *= -1  # full-band square-ish signal, peak == amp in every column
        heights = np.array(ae.generate_waveform_data(y, SR)["pwv3"]) & 0x1F
        assert int(np.median(heights)) == expected
    assert np.array_equal(
        np.array(ae.generate_waveform_data(y, SR)["pwv5"]) >> 2 & 0x1F,
        np.array(ae.generate_waveform_data(y, SR)["pwv3"]) & 0x1F,
    )


# --------------------------------------------------------------------------- pooling
def test_pool_columns_reduces_every_column():
    arr = np.arange(10, dtype=np.float64)
    assert ae._pool_columns(arr, 2, "max").tolist() == [4.0, 9.0]
    assert ae._pool_columns(arr, 2, "mean").tolist() == [2.0, 7.0]
    assert ae._pool_columns(arr, 2, "sum").tolist() == [10.0, 35.0]
    # fewer columns than buckets: every bucket still gets one column
    short = ae._pool_columns(np.array([1.0, 5.0, 3.0]), 6, "max")
    assert len(short) == 6 and set(short.tolist()) <= {1.0, 5.0, 3.0}
    assert ae._pool_columns(np.zeros(0), 4, "max").tolist() == [0.0] * 4


def test_preview_keeps_a_short_transient():
    """Old np.interp point sampling skipped most columns: a click between two
    sample points vanished from the 1200-entry previews."""
    y = np.zeros(SR * 120, dtype=np.float32)
    click = int(60.0037 * SR)
    y[click : click + 30] = 0.9
    wf = ae.generate_waveform_data(y, SR)
    bucket = (click // HOP) * 1200 // (-(-len(y) // HOP))
    pwv4 = np.array(wf["pwv4"])
    assert pwv4[bucket, 0] >= 100  # level byte = bucket max of the sample peak
    assert pwv4[:, 0].sum() == pwv4[bucket, 0]


# --------------------------------------------------------------------------- MP3 lead-in
def _mpeg1_frame(tag: bytes | None, lame_delay: int | None) -> bytes:
    hdr = bytes([0xFF, 0xFB, 0x90, 0x64])  # MPEG-1 L3, 128 kbps, 44.1 kHz, joint stereo
    body = bytearray(413)
    if tag is not None:
        off = 32  # stereo side info
        body[off : off + 4] = tag
        body[off + 4 : off + 8] = (0x0F).to_bytes(4, "big")  # frames+bytes+toc+quality
        lame = off + 8 + 4 + 4 + 100 + 4
        if lame_delay is not None:
            body[lame : lame + 9] = b"LAME3.100"
            body[lame + 21] = (lame_delay >> 4) & 0xFF
            body[lame + 22] = (lame_delay & 0x0F) << 4
    return hdr + bytes(body)


def test_mp3_lead_in_rules():
    assert ae._mp3_lead_in_samples(_mpeg1_frame(None, None)) == (0, 44100)
    assert ae._mp3_lead_in_samples(_mpeg1_frame(b"Info", None)) == (1105, 44100)
    assert ae._mp3_lead_in_samples(_mpeg1_frame(b"Info", 576)) == (1152 + 529 + 576, 44100)
    assert ae._mp3_lead_in_samples(_mpeg1_frame(b"Xing", 1000)) == (1152 + 529 + 1000, 44100)
    assert ae._mp3_lead_in_samples(b"\x00" * 64) is None


def test_waveform_lead_in_reads_past_id3(tmp_path: Path):
    tag_body = b"\x00" * 300_000  # big ID3v2 (embedded artwork) must be skipped by seek
    size = len(tag_body)
    syncsafe = bytes([(size >> 21) & 0x7F, (size >> 14) & 0x7F, (size >> 7) & 0x7F, size & 0x7F])
    mp3 = tmp_path / "x.mp3"
    mp3.write_bytes(b"ID3\x04\x00\x00" + syncsafe + tag_body + _mpeg1_frame(b"Info", 576) * 3)
    assert ae.waveform_lead_in_s(str(mp3)) == pytest.approx(2257 / 44100)
    flac = tmp_path / "x.flac"
    flac.write_bytes(b"fLaC")
    assert ae.waveform_lead_in_s(str(flac)) == 0.0
    assert ae.waveform_lead_in_s(str(tmp_path / "missing.mp3")) == 0.0


def test_lead_in_shifts_columns():
    y = _tone(800.0, 3.0)
    base = ae.generate_waveform_data(y, SR)
    shifted = ae.generate_waveform_data(y, SR, lead_in_s=10 * HOP / SR)
    assert shifted["detail_entries"] == base["detail_entries"] + 10
    assert shifted["pwv3"][10:20] == base["pwv3"][:10]
    assert all(v & 0x1F == 0 for v in shifted["pwv3"][:10])
