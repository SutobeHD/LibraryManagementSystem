"""BPM from a regression line through all beats, uniform grid for steady tracks (B5).

madmom's DBN places beats on a 10 ms grid, so the median inter-beat interval
quantised BPM (128 -> 127.66, 124/126 -> 125.0). These tests pin the fit, the
integer snap and the steady/tracked decision, and the comb refit that takes
over where the tracker slipped on a constant-tempo track.
"""

from __future__ import annotations

from types import SimpleNamespace

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


# --- comb refit: constant-tempo tracks the tracker did not follow all the way ---


def _round10(t: np.ndarray) -> np.ndarray:
    return np.round(np.asarray(t, dtype=float) / 0.01) * 0.01


def _with_slip(
    bpm: float, n: int = 640, at: int = 300, length: int = 40, stretch: float = 1.06
) -> np.ndarray:
    """Steady beats, but the tracker ran ``stretch`` times too slow for ``length`` beats."""
    period = 60.0 / bpm
    grid = 0.37 + np.arange(n) * period
    slipped = np.arange(grid[at], grid[at + length] - 0.2, period * stretch)
    return _round10(np.concatenate([grid[:at], slipped, grid[at + length :]]))


@pytest.mark.parametrize("bpm", [128.0, 135.0, 146.0, 155.0, 170.0])
def test_comb_fit_recovers_the_tempo_across_a_tracker_slip(bpm: float) -> None:
    t = _with_slip(bpm)
    line = ae._fit_beat_grid(t)
    assert line is None or not line.steady  # the gap-by-gap count is lost in the slip
    comb = ae._comb_fit_beat_grid(t)
    assert comb is not None
    assert 60.0 / comb.period == pytest.approx(bpm, abs=0.005)
    assert comb.steady
    assert comb.inlier_frac > 0.9
    k = (comb.anchor - 0.37) / comb.period  # anchor on the beats outside the slip
    assert k == pytest.approx(round(k), abs=0.05)


def test_comb_fit_keeps_the_main_phase_when_the_outro_flips_half_a_beat() -> None:
    period = 60.0 / 138.0
    t = 0.37 + np.arange(400) * period
    t[352:] += period / 2  # last 12 %: tracker on the off-beat
    comb = ae._comb_fit_beat_grid(_round10(t))
    assert comb is not None
    assert comb.steady
    assert 60.0 / comb.period == pytest.approx(138.0, abs=0.005)
    k = (comb.anchor - 0.37) / comb.period
    assert k == pytest.approx(round(k), abs=0.05)


def test_comb_fit_gives_the_tempo_but_no_uniform_grid_when_a_quarter_is_off_phase() -> None:
    period = 60.0 / 138.0
    t = 0.37 + np.arange(400) * period
    t[300:] += period / 2
    comb = ae._comb_fit_beat_grid(_round10(t))
    assert comb is not None
    assert comb.on_one_line
    assert not comb.steady
    assert 60.0 / comb.period == pytest.approx(138.0, abs=0.005)


@pytest.mark.parametrize("split", [0.5, 0.7, 0.8])
def test_comb_fit_tempo_change_is_not_steady(split: float) -> None:
    na = int(400 * split)
    a = 0.37 + np.arange(na) * (60.0 / 124.0)
    b = a[-1] + np.arange(1, 400 - na + 1) * (60.0 / 132.0)
    comb = ae._comb_fit_beat_grid(_round10(np.concatenate([a, b])))
    assert comb is None or not comb.steady


@pytest.mark.parametrize("end_bpm", [128.13, 128.5, 130.0])
def test_comb_fit_tempo_drift_is_not_on_one_line(end_bpm: float) -> None:
    periods = 60.0 / np.linspace(128.0, end_bpm, 768)
    t = 0.37 + np.concatenate(([0.0], np.cumsum(periods[:-1])))
    comb = ae._comb_fit_beat_grid(_round10(t))
    assert comb is None or not comb.on_one_line


def test_comb_fit_wandering_tempo_is_not_on_one_line() -> None:
    periods = 0.46 * (1 + np.cumsum(np.random.default_rng(1).normal(0, 0.002, 500)))
    comb = ae._comb_fit_beat_grid(_round10(0.37 + np.cumsum(periods)))
    assert comb is None or not comb.on_one_line


def test_comb_fit_too_few_beats() -> None:
    assert ae._comb_fit_beat_grid(_quantised(128.0, n=ae._GRID_COMB_MIN_BEATS - 1)) is None


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


def _fake_madmom(beats: np.ndarray) -> SimpleNamespace:
    """Stands in for madmom: the DBN 'tracks' exactly the beats it was given."""
    return SimpleNamespace(
        features=SimpleNamespace(
            beats=SimpleNamespace(
                RNNBeatProcessor=lambda: lambda path: None,
                DBNBeatTrackingProcessor=lambda **kwargs: lambda activations: beats,
            )
        )
    )


@pytest.fixture(scope="module")
def dsp():
    ae._ensure_libs()
    if ae.librosa is None:
        pytest.skip("librosa not available")
    return ae


def test_slipped_tracker_still_gets_exact_tempo_and_uniform_grid(dsp, monkeypatch) -> None:
    kicks = np.array(_even(135.0, 60.0))
    period = 60.0 / 135.0
    slipped = np.arange(kicks[60], kicks[72] - 0.2, period * 1.06)
    tracked = _round10(np.concatenate([kicks[:60], slipped, kicks[72:]]))
    line = dsp._fit_beat_grid(tracked)
    assert line is None or not line.steady
    monkeypatch.setattr(dsp, "madmom", _fake_madmom(tracked))
    r = dsp.detect_beats_madmom(_kick_track(list(kicks), 60.0), SR)
    assert r is not None
    assert r["bpm"] == 135.0
    assert r["grid_mode"] == "uniform"
    times = np.array([b["time_ms"] for b in r["beats"]]) / 1000.0
    off_kick = np.abs((times - kicks[0] + period / 2) % period - period / 2)
    assert off_kick.max() <= 0.012


# --- half-beat phase: a uniform grid on the off-beat moves onto the kicks ------


def _offbeat_track(kicks: np.ndarray, duration_s: float, period: float) -> np.ndarray:
    """Kicks on the beat; a hi-hat and a soft sub-bass note half a beat after each."""
    from scipy import signal

    y = _kick_track(list(kicks), duration_s)
    n = len(y)
    rng = np.random.default_rng(3)
    m = int(0.05 * SR)
    hat = rng.standard_normal(m) * np.exp(-np.linspace(0, 6, m)) * 0.5
    hat = signal.sosfilt(signal.butter(4, 6000.0, "high", fs=SR, output="sos"), hat)
    b = int(0.15 * SR)
    bass = np.sin(2 * np.pi * 45 * np.arange(b) / SR) * np.hanning(b) * 0.6
    for t in kicks + period / 2:
        i = round(t * SR)
        if i + b < n:
            y[i : i + m] += hat.astype(np.float32)
            y[i : i + b] += bass.astype(np.float32)
    return y


@pytest.fixture(scope="module")
def offbeat_audio(dsp):
    period = 60.0 / 140.0
    kicks = np.array(_even(140.0, 60.0))
    return kicks, period, _offbeat_track(kicks, 60.0, period)


def test_grid_on_the_hats_is_seen_as_off_beat(dsp, offbeat_audio) -> None:
    kicks, period, y = offbeat_audio
    start = dsp.find_first_signal_onset(y, SR)
    assert dsp._grid_on_the_off_beat(y, SR, kicks[:-1] + period / 2, period, start)
    assert not dsp._grid_on_the_off_beat(y, SR, kicks, period, start)


def test_off_beat_needs_the_first_sound_between_the_beats_too(dsp, offbeat_audio) -> None:
    kicks, period, y = offbeat_audio
    grid = kicks[:-1] + period / 2
    # Same audio, but the track is taken to start on a grid beat: no flip.
    assert not dsp._grid_on_the_off_beat(y, SR, grid, period, float(grid[0]))


@pytest.mark.parametrize(("louder", "off_beat"), [(1.5, False), (3.0, True)])
def test_off_beat_needs_a_clear_margin(dsp, louder: float, off_beat: bool) -> None:
    # A kick on every grid beat and a louder one half a beat later. Rekordbox
    # itself is split on real tracks at a 1.4-1.5x margin, so that stays put.
    period = 60.0 / 140.0
    grid = np.array(_even(140.0, 30.0))
    y = _kick_track(list(grid), 30.0) + louder * _kick_track(list(grid[:-1] + period / 2), 30.0)
    between = float(grid[0] + period / 2)
    assert dsp._grid_on_the_off_beat(y, SR, grid[:-1], period, between) is off_beat


def test_tracker_on_the_off_beat_still_gets_a_grid_on_the_kicks(
    dsp, offbeat_audio, monkeypatch
) -> None:
    kicks, period, y = offbeat_audio
    monkeypatch.setattr(dsp, "madmom", _fake_madmom(_round10(kicks[:-1] + period / 2)))
    r = dsp.detect_beats_madmom(y, SR, first_signal_t=dsp.find_first_signal_onset(y, SR))
    assert r is not None
    assert r["bpm"] == 140.0
    assert r["grid_mode"] == "uniform"
    times = np.array([b["time_ms"] for b in r["beats"]]) / 1000.0
    off_kick = np.abs((times - kicks[0] + period / 2) % period - period / 2)
    assert off_kick.max() <= 0.012


def test_tracker_on_the_kicks_keeps_its_phase(dsp, offbeat_audio, monkeypatch) -> None:
    kicks, period, y = offbeat_audio
    monkeypatch.setattr(dsp, "madmom", _fake_madmom(_round10(kicks)))
    r = dsp.detect_beats_madmom(y, SR, first_signal_t=dsp.find_first_signal_onset(y, SR))
    assert r is not None
    times = np.array([b["time_ms"] for b in r["beats"]]) / 1000.0
    off_kick = np.abs((times - kicks[0] + period / 2) % period - period / 2)
    assert off_kick.max() <= 0.012


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
