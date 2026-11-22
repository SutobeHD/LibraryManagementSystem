"""BPM from a regression line through all beats, uniform grid for steady tracks (B5).

madmom's DBN places beats on a 10 ms grid, so the median inter-beat interval
quantised BPM (128 -> 127.66, 124/126 -> 125.0). These tests pin the fit, the
integer snap and the steady/tracked decision.
"""

from __future__ import annotations

import numpy as np
import pytest

from app import analysis_engine as ae


def _quantised(bpm: float, n: int = 400, start: float = 0.37, frame: float = 0.01) -> np.ndarray:
    """Beat times of a steady tempo, rounded to the DBN's 10 ms frames."""
    t = start + np.arange(n) * (60.0 / bpm)
    return np.round(t / frame) * frame


@pytest.mark.parametrize("bpm", [124.0, 126.0, 128.0, 140.0, 152.0, 174.0])
def test_fit_recovers_the_exact_tempo_from_quantised_beats(bpm: float) -> None:
    fit = ae._fit_beat_grid(_quantised(bpm))
    assert fit is not None
    assert 60.0 / fit.period == pytest.approx(bpm, abs=0.01)
    assert fit.steady
    assert fit.inlier_frac == 1.0


def test_fit_survives_dropped_and_stray_beats() -> None:
    t = _quantised(128.0)
    t = np.delete(t, [50, 51, 200])  # dropped beats
    t = np.sort(np.append(t, t[100] + 0.11))  # one stray beat off the grid
    fit = ae._fit_beat_grid(t)
    assert fit is not None
    assert 60.0 / fit.period == pytest.approx(128.0, abs=0.01)
    assert fit.steady


def test_tempo_change_is_not_steady() -> None:
    a = 0.37 + np.arange(200) * (60.0 / 124.0)
    b = a[-1] + np.arange(1, 200) * (60.0 / 132.0)
    fit = ae._fit_beat_grid(np.round(np.concatenate([a, b]) / 0.01) * 0.01)
    assert fit is None or not fit.steady


def test_slow_tempo_drift_is_not_steady() -> None:
    # 128.00 -> 128.13 BPM over ~6 min: RMS stays low, but the beats bend away
    # from a straight line, so the outer quarters sit off it on average.
    periods = 60.0 / np.linspace(128.0, 128.13, 768)
    t = 0.37 + np.concatenate(([0.0], np.cumsum(periods[:-1])))
    fit = ae._fit_beat_grid(np.round(t / 0.01) * 0.01)
    assert fit is not None
    assert not fit.steady


def test_too_few_beats() -> None:
    assert ae._fit_beat_grid(_quantised(128.0, n=ae._GRID_MIN_BEATS - 1)) is None


def test_anchor_lies_on_a_tracked_beat() -> None:
    t = _quantised(128.0)
    fit = ae._fit_beat_grid(t)
    k = (fit.anchor - t[0]) / fit.period
    assert k == pytest.approx(round(k), abs=0.05)


@pytest.mark.parametrize(
    ("raw", "out"),
    [(127.97, 128.0), (128.04, 128.0), (127.5, 127.5), (123.45, 123.45), (127.93, 127.93)],
)
def test_integer_snap_only_within_tolerance(raw: float, out: float) -> None:
    assert ae._snap_bpm(raw) == out


def test_snap_is_refused_when_it_would_drift_the_grid() -> None:
    # 127.96 BPM, 3 min either side of the anchor: snapping to 128 moves the
    # outermost beats ~56 ms, so the fitted tempo stays.
    assert ae._snap_bpm(127.96, half_span_s=180.0) == 127.96
    # The same tempo on a 10 s span drifts ~3 ms: snapping is fine.
    assert ae._snap_bpm(127.96, half_span_s=10.0) == 128.0
    # An exact tempo never drifts.
    assert ae._snap_bpm(128.0004, half_span_s=300.0) == 128.0


def test_uniform_beats_cover_the_tracked_span() -> None:
    times = ae._uniform_beats(anchor=10.0, period=0.5, first=1.02, last=19.9)
    assert times[0] == pytest.approx(1.0)
    assert times[-1] == pytest.approx(20.0)
    assert np.allclose(np.diff(times), 0.5)


# --- end to end on synthetic audio -------------------------------------------

SR = 44100


def _kick_track(onsets: list[float], duration_s: float) -> np.ndarray:
    n = int(SR * duration_s)
    y = np.zeros(n, dtype=np.float32)
    m = int(0.12 * SR)
    kick = (
        np.sin(2 * np.pi * 55 * np.arange(m) / SR) * np.exp(-np.linspace(0, 8, m)) * 0.7
    ).astype(np.float32)
    cm = int(0.004 * SR)
    kick[:cm] += (np.random.default_rng(2).standard_normal(cm) * 0.6).astype(np.float32)
    for t in onsets:
        i = round(t * SR)
        y[i : i + m] += kick[: max(0, min(m, n - i))]
    return y


def _even(bpm: float, duration_s: float, start: float = 0.37) -> list[float]:
    bp = 60.0 / bpm
    return [start + i * bp for i in range(int((duration_s - 0.5 - start) / bp))]


@pytest.fixture(scope="module")
def engine():
    ae._ensure_libs()
    if ae.madmom is None:
        pytest.skip("madmom not available")
    return ae


@pytest.mark.slow
def test_steady_128_bpm_track_gets_exact_tempo_and_uniform_grid(engine) -> None:
    r = engine.detect_beats(_kick_track(_even(128.0, 40.0), 40.0), SR)
    assert r["bpm"] == 128.0
    assert r["grid_mode"] == "uniform"
    assert {b["tempo"] for b in r["beats"]} == {12800}
    gaps = np.diff([b["time_ms"] for b in r["beats"]])
    assert gaps.max() - gaps.min() <= 1  # ms rounding only


@pytest.mark.slow
def test_tempo_change_keeps_the_tracked_beats(engine) -> None:
    a = _even(124.0, 20.2)
    bp = 60.0 / 132.0
    b = [a[-1] + (i + 1) * bp for i in range(int((40.0 - 0.5 - a[-1]) / bp))]
    r = engine.detect_beats(_kick_track(a + b, 40.0), SR)
    assert r["grid_mode"] == "tracked"
