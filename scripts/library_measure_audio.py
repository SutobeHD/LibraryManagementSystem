"""Decode-once audio measurement runner: Stage E of docs/LIBRARY_ANALYSIS_HANDOVER.md (§3.5).

Loads every track ONCE (native rate, stereo) and runs the engine's building blocks in the order of
app.analysis_engine.run_full_analysis, minus waveforms / PVBR / cues, plus the Stage-E extras:

  E1 spectral cutoff + measured quality tier (§5 thresholds)   E5 DC offset per channel
  E2 clipping (runs >= 3 samples at |x| >= 0.999) + true peak    E6 bass share (< 60 Hz, < 120 Hz)
  E3 dynamics (PLR, crest factor, loudness range)               E7 low-band L/R correlation (< 150 Hz)
  E4 silence (leading / trailing below -60 dBFS)                E8 fingerprint: skipped (no fpcalc)

Read-only towards the library: no AnalysisCache, no master.db, no ANLZ, no backend calls.
Output: one JSON line per track, resumable via track_key = ID|path|mtime|size
("key" is the musical key, as in the engine).

Usage:
  python scripts/library_measure_audio.py --limit 50 --seed 1 --workers 12 --depth high
  python scripts/library_measure_audio.py --only-ids 123,456 --out tmp/x.jsonl --inline
"""

from __future__ import annotations

import os

# Must be set before numpy / OpenBLAS load, in the parent AND in every spawned worker (the worker
# re-imports this module as __mp_main__, so the loop below runs there too).
THREAD_ENV_VARS = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMBA_NUM_THREADS",
)
for _var in THREAD_ENV_VARS:
    os.environ.setdefault(_var, "1")

import argparse  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import random  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
import warnings  # noqa: E402
from collections import deque  # noqa: E402
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait  # noqa: E402
from concurrent.futures.process import BrokenProcessPool  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logger = logging.getLogger("library_measure_audio")

DEFAULT_INPUT = ROOT / "tmp" / "library-analysis" / "tracks.json"
DEFAULT_OUT = ROOT / "tmp" / "library-analysis" / "measure" / "audio.jsonl"
STREAM_PREFIXES = ("soundcloud:", "spotify:")
DEPTHS = ("rekordbox", "high")
ANALYSIS_SR = 44100

SILENCE_DBFS = -60.0
CUTOFF_FLOOR_REL_DB = -60.0
HARD_EDGE_DB = 20.0
HARD_EDGE_BAND_HZ = 300.0
HARD_EDGE_SCAN_FROM_HZ = 8000.0
CLIP_THRESHOLD = 0.999
CLIP_MIN_RUN = 3
LOW_BAND_HZ = 150.0
TIER_BOUNDARY_SLACK_HZ = 300.0
# LAME lowpass per bitrate (handover §5): nearest match within LAME_MATCH_HZ names the bitrate.
LAME_LOWPASS: tuple[tuple[int, float], ...] = (
    (128, 17000.0),
    (160, 17500.0),
    (192, 18600.0),
    (256, 19700.0),
    (320, 20500.0),
)
LAME_MATCH_HZ = 400.0
MIN_BUDGET_S = 120.0
BUDGET_FACTOR = 10.0
DEFAULT_BUDGET_S = 600.0
MAX_ATTEMPTS = 2

_ENGINE: Any = None


# --------------------------------------------------------------------------- #
# Engine access (lazy: the parent process never pays for librosa / madmom)
# --------------------------------------------------------------------------- #


def _engine() -> Any:
    """Import app.analysis_engine and load its libraries (applies the madmom py3.11 shim)."""
    global _ENGINE
    if _ENGINE is None:
        warnings.filterwarnings("ignore", category=UserWarning)
        from app import analysis_engine as ae

        if not ae._ensure_libs():
            raise RuntimeError("analysis libraries not available (librosa / scipy)")
        _ENGINE = ae
    return _ENGINE


def _db(x: float, floor: float = -200.0) -> float:
    return float(20.0 * np.log10(x)) if x > 0 else floor


def _channels(y: np.ndarray) -> np.ndarray:
    """(N,) -> (1, N); (C, N) stays."""
    return y if y.ndim == 2 else y[None, :]


# --------------------------------------------------------------------------- #
# E1 / E6: one STFT on the native mono signal
# --------------------------------------------------------------------------- #


def power_spectrum_stats(
    y: np.ndarray, sr: int, n_fft: int = 4096, max_frames: int = 4000
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Hann STFT; returns (freqs_hz, median magnitude per bin in dBFS, mean power per bin).

    0 dBFS = full-scale sine. The hop grows so that at most ~max_frames frames are kept
    (bounded memory on long / hi-res files; the median needs all frames).
    """
    y = np.asarray(y, dtype=np.float32)
    if y.ndim != 1:
        y = y.mean(axis=0).astype(np.float32)
    if len(y) < n_fft:
        y = np.pad(y, (0, n_fft - len(y)))
    hop = max(n_fft // 2, (len(y) - n_fft) // max_frames + 1)
    frames = np.lib.stride_tricks.sliding_window_view(y, n_fft)[::hop]
    window = np.hanning(n_fft).astype(np.float32)
    scale = 2.0 / float(window.sum())
    n_bins = n_fft // 2 + 1
    mags = np.empty((frames.shape[0], n_bins), dtype=np.float32)
    chunk = 512
    for start in range(0, frames.shape[0], chunk):
        block = frames[start : start + chunk] * window
        mags[start : start + chunk] = np.abs(np.fft.rfft(block, axis=1)) * scale
    median_db = 20.0 * np.log10(np.median(mags, axis=0) + 1e-12)
    mean_power = np.mean(mags.astype(np.float64) ** 2, axis=0)
    freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)
    return freqs, median_db, mean_power


def spectral_cutoff(freqs: np.ndarray, median_db: np.ndarray) -> dict[str, Any]:
    """E1. Cutoff = hard edge (>= 20 dB step within ~300 Hz, everything above stays down) if one
    exists above 8 kHz, else the highest bin within 60 dB of the peak bin (handover §3.5)."""
    rel = median_db - float(np.max(median_db))
    above = np.nonzero(rel > CUTOFF_FLOOR_REL_DB)[0]
    idx_thr = int(above[-1]) if len(above) else 0
    bin_hz = float(freqs[1] - freqs[0]) if len(freqs) > 1 else 1.0
    nb = max(2, round(HARD_EDGE_BAND_HZ / bin_hz))
    first = int(np.searchsorted(freqs, HARD_EDGE_SCAN_FROM_HZ))
    band_starts = list(range(first, len(rel) - nb + 1, nb))
    levels = np.array([float(np.median(rel[s : s + nb])) for s in band_starts])
    edge_idx: int | None = None
    best_drop = 0.0
    if len(levels) >= 2:
        drops = levels[:-1] - levels[1:]
        for i in np.argsort(drops)[::-1]:
            drop = float(drops[i])
            if drop < HARD_EDGE_DB:
                break
            if np.all(levels[i + 1 :] <= levels[i] - HARD_EDGE_DB):
                best_drop = drop
                lo, hi = band_starts[i], band_starts[i + 1] + nb
                seg = rel[lo:hi]
                below = np.nonzero(seg < levels[i] - 10.0)[0]
                edge_idx = lo + int(below[0]) - 1 if len(below) else band_starts[i + 1]
                break
        if edge_idx is None and len(drops):
            best_drop = float(np.max(drops))
    hard_edge = edge_idx is not None
    idx = edge_idx if edge_idx is not None else idx_thr
    idx = max(0, min(idx, len(freqs) - 1))
    floor_bins = rel[idx + 1 :]
    return {
        "cutoff_hz": round(float(freqs[idx]), 1),
        "cutoff_thr_hz": round(float(freqs[idx_thr]), 1),
        "hard_edge": hard_edge,
        "edge_drop_db": round(best_drop, 1),
        "floor_rel_db": round(float(np.median(floor_bins)), 1) if len(floor_bins) else None,
        "peak_bin_hz": round(float(freqs[int(np.argmax(median_db))]), 1),
        "peak_bin_dbfs": round(float(np.max(median_db)), 1),
    }


def cutoff_tier(cutoff_hz: float, sr: int, hard_edge: bool) -> dict[str, Any]:
    """Measured tier from the cutoff (handover §5). A needs no hard edge; sr < 44.1k is D."""
    thr_a = 20500.0 if sr <= 44100 else 21000.0
    reason = None
    if sr < 44100:
        tier, reason = "D", "sample_rate"
    elif cutoff_hz >= thr_a and not hard_edge:
        tier = "A"
    elif cutoff_hz >= 19000.0:
        tier = "B"
    elif cutoff_hz > 17000.0:
        tier = "C"
    else:
        tier = "D"
    near_boundary = any(
        abs(cutoff_hz - b) <= TIER_BOUNDARY_SLACK_HZ for b in (17000.0, 19000.0, thr_a)
    )
    natural_rolloff = tier != "A" and not hard_edge and reason is None
    lame: int | None = None
    if hard_edge:
        bitrate, lowpass = min(LAME_LOWPASS, key=lambda bl: abs(bl[1] - cutoff_hz))
        if abs(lowpass - cutoff_hz) <= LAME_MATCH_HZ:
            lame = bitrate
    return {
        "tier": tier,
        "tier_reason": reason,
        "pruefen": near_boundary or natural_rolloff,
        "pruefen_reason": "boundary" if near_boundary else ("rolloff" if natural_rolloff else None),
        "lame_bitrate_est": lame,
        "thr_a_hz": thr_a,
    }


def bass_share(freqs: np.ndarray, mean_power: np.ndarray) -> dict[str, float | None]:
    """E6. Energy share below 60 Hz and below 120 Hz."""
    total = float(np.sum(mean_power))
    if total <= 0:
        return {"share_60": None, "share_120": None}
    return {
        "share_60": round(float(np.sum(mean_power[freqs < 60.0])) / total, 4),
        "share_120": round(float(np.sum(mean_power[freqs < 120.0])) / total, 4),
    }


# --------------------------------------------------------------------------- #
# E2 / E3 / E4 / E5 / E7
# --------------------------------------------------------------------------- #


def clipping_stats(y: np.ndarray) -> dict[str, Any]:
    """E2. Samples in runs of >= 3 consecutive |x| >= 0.999, per channel."""
    per: list[dict[str, int]] = []
    for ch in _channels(y):
        mask = np.abs(ch) >= CLIP_THRESHOLD
        if not mask.any():
            per.append({"samples": 0, "runs": 0, "max_run": 0})
            continue
        padded = np.concatenate(([0], mask.astype(np.int8), [0]))
        edges = np.diff(padded)
        lengths = np.nonzero(edges == -1)[0] - np.nonzero(edges == 1)[0]
        long_runs = lengths[lengths >= CLIP_MIN_RUN]
        per.append(
            {
                "samples": int(long_runs.sum()),
                "runs": len(long_runs),
                "max_run": int(lengths.max()),
            }
        )
    return {
        "per_channel": per,
        "samples_total": sum(p["samples"] for p in per),
        "runs_total": sum(p["runs"] for p in per),
    }


def true_peak_dbtp(y: np.ndarray, chunk: int = 1 << 20, pad: int = 256) -> float:
    """4x oversampled peak (chunked so hi-res files don't quadruple in RAM)."""
    from scipy.signal import resample_poly

    peak = 0.0
    for ch in _channels(y):
        n = len(ch)
        for s in range(0, n, chunk):
            lo, hi = max(0, s - pad), min(n, s + chunk + pad)
            up = resample_poly(ch[lo:hi].astype(np.float64), 4, 1)
            a = (s - lo) * 4
            b = a + (min(n, s + chunk) - s) * 4
            peak = max(peak, float(np.max(np.abs(up[a:b]))))
    return round(_db(peak), 2)


def dynamics_stats(y: np.ndarray, lufs: float | None) -> dict[str, float | None]:
    """E3. Sample peak (dBFS), PLR = peak - LUFS, crest factor (dB) over all channels."""
    flat = np.asarray(y, dtype=np.float32).ravel()
    if flat.size == 0:
        return {"peak_dbfs": None, "plr": None, "crest_db": None}
    peak = float(np.max(np.abs(flat)))
    rms = float(np.sqrt(np.mean(flat.astype(np.float64) ** 2)))
    peak_dbfs = _db(peak)
    plr = round(peak_dbfs - lufs, 2) if lufs is not None and lufs > -100.0 else None
    return {
        "peak_dbfs": round(peak_dbfs, 2),
        "plr": plr,
        "crest_db": round(_db(peak / (rms + 1e-12)), 2),
    }


def loudness_range(y: np.ndarray, sr: int) -> float | None:
    """E3 optional. EBU R128 LRA: 3 s short-term loudness, 100 ms hop, -70 LUFS absolute and
    -20 LU relative gate, LRA = P95 - P10. Uses pyloudnorm's K-weighting filters; None when
    pyloudnorm (or its _filters) is missing or the signal is shorter than 3 s."""
    try:
        import pyloudnorm
    except ImportError:
        return None
    filters = getattr(pyloudnorm.Meter(sr), "_filters", None)
    if not filters:
        return None
    chans = _channels(y)
    n = chans.shape[1]
    win, hop = int(3.0 * sr), max(1, int(0.1 * sr))
    if n < win:
        return None
    # BS.1770 channel weights: L/R/C = 1.0, surrounds = 1.41
    weights = [1.0, 1.0, 1.0, 1.41, 1.41] + [1.0] * max(0, chans.shape[0] - 5)
    power = np.zeros(n, dtype=np.float64)
    for i, ch in enumerate(chans):
        x = ch.astype(np.float64)
        for f in filters.values():
            x = f.apply_filter(x)
        power += weights[i] * x**2
    cs = np.concatenate(([0.0], np.cumsum(power)))
    starts = np.arange(0, n - win + 1, hop)
    mean_sq = (cs[starts + win] - cs[starts]) / win
    st = -0.691 + 10.0 * np.log10(mean_sq + 1e-20)
    st = st[st > -70.0]
    if len(st) == 0:
        return None
    rel_gate = -0.691 + 10.0 * np.log10(np.mean(10.0 ** ((st + 0.691) / 10.0))) - 20.0
    st = st[st >= rel_gate]
    if len(st) < 2:
        return None
    return round(float(np.percentile(st, 95) - np.percentile(st, 10)), 2)


def silence_stats(y: np.ndarray, sr: int, thresh_db: float = SILENCE_DBFS) -> dict[str, Any]:
    """E4. Leading / trailing stretch where every channel stays below thresh_db."""
    env = np.max(np.abs(_channels(y)), axis=0)
    thr = 10.0 ** (thresh_db / 20.0)
    loud = np.nonzero(env > thr)[0]
    total_ms = round(len(env) / sr * 1000.0, 1)
    if len(loud) == 0:
        return {"leading_ms": total_ms, "trailing_ms": total_ms, "all_silent": True}
    return {
        "leading_ms": round(float(loud[0]) / sr * 1000.0, 1),
        "trailing_ms": round(float(len(env) - 1 - loud[-1]) / sr * 1000.0, 1),
        "all_silent": False,
    }


def dc_offset(y: np.ndarray) -> list[float]:
    """E5. Mean per channel."""
    return [round(float(np.mean(ch, dtype=np.float64)), 6) for ch in _channels(y)]


def low_band_correlation(y: np.ndarray, sr: int, cutoff_hz: float = LOW_BAND_HZ) -> float | None:
    """E7. Pearson L/R correlation of the < cutoff_hz band (4th-order Butterworth, zero-phase).
    None for mono / multichannel or a silent channel."""
    if y.ndim != 2 or y.shape[0] != 2:
        return None
    from scipy.signal import butter, sosfiltfilt

    sos = butter(4, cutoff_hz, btype="low", fs=sr, output="sos")
    left = sosfiltfilt(sos, y[0].astype(np.float64))
    right = sosfiltfilt(sos, y[1].astype(np.float64))
    if np.std(left) < 1e-10 or np.std(right) < 1e-10:
        return None
    return round(float(np.corrcoef(left, right)[0, 1]), 4)


# --------------------------------------------------------------------------- #
# Compact engine fields
# --------------------------------------------------------------------------- #

PHRASE_KEYS = ("label", "mood", "energy", "start_ms", "end_ms")


def compact_phrases(phrases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: p.get(k) for k in PHRASE_KEYS} for p in phrases]


def compact_anchors(anchors: list[dict[str, Any]]) -> dict[str, Any]:
    bpms = [float(a["bpm"]) for a in anchors if a.get("bpm") is not None]
    return {
        "count": len(anchors),
        "bpm_min": round(min(bpms), 3) if bpms else None,
        "bpm_max": round(max(bpms), 3) if bpms else None,
    }


# --------------------------------------------------------------------------- #
# measure_track: decode once, engine order, extras
# --------------------------------------------------------------------------- #


def measure_track(path: str, depth: str = "high") -> dict[str, Any]:
    """Decode once; run the engine blocks in run_full_analysis order; add E1-E7 at depth 'high'.

    Raises on unreadable audio (the pool wrapper turns that into an error row).
    """
    if depth not in DEPTHS:
        raise ValueError(f"depth must be one of {DEPTHS}, got {depth!r}")
    ae = _engine()
    librosa = ae.librosa
    t_stage: dict[str, float] = {}
    cpu0, wall0 = time.process_time(), time.perf_counter()

    def stage(name: str, start: float) -> None:
        t_stage[name] = round(time.process_time() - start, 3)

    t = time.process_time()
    y_native, sr_native = librosa.load(path, sr=None, mono=False)
    y_native = np.asarray(y_native, dtype=np.float32)
    sr_native = int(sr_native)
    stage("load", t)
    if y_native.size == 0:
        raise ValueError("empty or unreadable audio")
    channels = int(y_native.shape[0]) if y_native.ndim == 2 else 1

    t = time.process_time()
    stereo = ae.compute_stereo_features(y_native, sr_native) if y_native.ndim == 2 else None
    y_mono = librosa.to_mono(y_native) if y_native.ndim == 2 else y_native
    stage("stereo", t)

    t = time.process_time()
    if sr_native != ANALYSIS_SR:
        y = librosa.resample(y_mono, orig_sr=sr_native, target_sr=ANALYSIS_SR)
        sr = ANALYSIS_SR
    else:
        y, sr = y_mono, sr_native
    stage("resample", t)
    duration = len(y) / sr

    t = time.process_time()
    encoder_delay = float(ae.get_encoder_delay(path))
    first_signal_t = float(ae.find_first_signal_onset(y, sr))
    stage("onset", t)

    t = time.process_time()
    beat = ae.detect_beats(y, sr, encoder_delay=encoder_delay, first_signal_t=first_signal_t)
    stage("beats", t)
    t = time.process_time()
    key = ae.detect_key(y, sr)
    stage("key", t)
    t = time.process_time()
    phrases = ae.detect_phrases(y, sr, beat["bpm"], duration)
    stage("phrases", t)
    t = time.process_time()
    anchors = ae.detect_tempo_changes(y, sr, beat["bpm"])
    stage("tempo_grid", t)

    result: dict[str, Any] = {
        "depth": depth,
        "duration": round(duration, 3),
        "sample_rate": sr,
        "sample_rate_native": sr_native,
        "channels": channels,
        "encoder_delay_ms": round(encoder_delay * 1000.0, 2),
        "first_signal_ms": round(first_signal_t * 1000.0, 2),
        "bpm": beat.get("bpm"),
        "bpm_raw": beat.get("bpm_raw"),
        "beat_count": beat.get("beat_count"),
        "downbeat_index": beat.get("downbeat_index"),
        "beat_method": beat.get("method", "unknown"),
        "grid_confidence": beat.get("grid_confidence", 0.0),
        "tempo_anchors": compact_anchors(anchors),
        "key": key.get("key"),
        "camelot": key.get("camelot"),
        "key_confidence": key.get("confidence"),
        "key_method": key.get("method", "unknown"),
        "phrases": compact_phrases(phrases),
        "stereo": stereo,
    }

    if depth == "high":
        t = time.process_time()
        if y_native.ndim == 2:
            lufs = float(ae.calculate_lufs(y_native, sr_native))
        else:
            lufs = float(ae.calculate_lufs(y, sr))
        replay_gain = float(ae.calculate_replay_gain(lufs))
        stage("lufs", t)

        t = time.process_time()
        mood = ae.detect_mood(y, sr, beat["bpm"], lufs)
        genre_hint = ae.hint_genre(beat["bpm"], mood["brightness"], mood["texture"])
        stage("mood", t)

        t = time.process_time()
        freqs, median_db, mean_power = power_spectrum_stats(y_mono, sr_native)
        cutoff = spectral_cutoff(freqs, median_db)
        cutoff.update(cutoff_tier(cutoff["cutoff_hz"], sr_native, cutoff["hard_edge"]))
        bass = bass_share(freqs, mean_power)
        stage("spectrum", t)

        t = time.process_time()
        clipping = clipping_stats(y_native)
        clipping["true_peak_dbtp"] = true_peak_dbtp(y_native)
        stage("clipping", t)

        t = time.process_time()
        dynamics = dynamics_stats(y_native, lufs)
        dynamics["lra"] = loudness_range(y_native, sr_native)
        stage("dynamics", t)

        t = time.process_time()
        silence = silence_stats(y_native, sr_native)
        dc = dc_offset(y_native)
        low_corr = low_band_correlation(y_native, sr_native)
        stage("silence_dc_lowband", t)

        result.update(
            {
                "lufs": lufs,
                "replay_gain": replay_gain,
                "peak": round(float(np.max(np.abs(y))), 4),
                "mood": mood,
                "genre_hint": genre_hint,
                "cutoff": cutoff,
                "clipping": clipping,
                "dynamics": dynamics,
                "silence": silence,
                "dc_offset": dc,
                "bass": bass,
                "low_band_corr": low_corr,
            }
        )

    result["t_stage"] = t_stage
    result["t_cpu_s"] = round(time.process_time() - cpu0, 3)
    result["t_wall_s"] = round(time.perf_counter() - wall0, 3)
    return result


# --------------------------------------------------------------------------- #
# Rows, keys, planning
# --------------------------------------------------------------------------- #


def make_key(track: dict[str, Any], st: os.stat_result | None) -> str:
    mtime = int(st.st_mtime) if st is not None else 0
    size = int(st.st_size) if st is not None else 0
    return f"{track.get('ID')}|{track.get('path')}|{mtime}|{size}"


def base_row(track: dict[str, Any], depth: str) -> dict[str, Any]:
    return {
        "track_key": track.get("_key") or make_key(track, None),
        "id": track.get("ID"),
        "path": track.get("path"),
        "title": track.get("Title"),
        "artist": track.get("Artist"),
        "mtime": track.get("_mtime"),
        "size": track.get("_size"),
        "depth": depth,
        "snapshot": {
            "bpm": track.get("BPM"),
            "key": track.get("Key"),
            "total_time_s": track.get("TotalTime"),
            "bitrate": track.get("Bitrate"),
            "sample_rate": track.get("SampleRate"),
        },
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def error_row(track: dict[str, Any], depth: str, exc: BaseException, status: str = "error") -> dict:
    row = base_row(track, depth)
    row.update(
        {
            "status": status,
            "error_type": type(exc).__name__,
            "error_message": (str(exc) or repr(exc))[:500],
        }
    )
    return row


def _peak_rss() -> tuple[float | None, str | None]:
    """(peak RSS in MB, source). Windows exposes peak_wset; elsewhere current rss; None w/o psutil."""
    try:
        import psutil
    except ImportError:
        return None, None
    info = psutil.Process().memory_info()
    peak = getattr(info, "peak_wset", None)
    if peak is not None:
        return round(peak / 2**20, 1), "peak_wset"
    return round(info.rss / 2**20, 1), "rss"


def measure_task(track: dict[str, Any], depth: str) -> dict[str, Any]:
    """Pool entry point. Never raises: every outcome is a row."""
    cpu0, wall0 = time.process_time(), time.perf_counter()
    row = base_row(track, depth)
    try:
        row.update(measure_track(str(track.get("path")), depth))
        row["status"] = "ok"
    except Exception as exc:  # any decode / DSP failure becomes a row
        row.update(error_row(track, depth, exc))
    row["t_cpu_s"] = round(time.process_time() - cpu0, 3)
    row["t_wall_s"] = round(time.perf_counter() - wall0, 3)
    row["worker_pid"] = os.getpid()
    row["rss_peak_mb"], row["rss_source"] = _peak_rss()
    return row


def load_done_keys(out_path: Path) -> set[str]:
    keys: set[str] = set()
    if not out_path.exists():
        return keys
    with out_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                key = json.loads(line).get("track_key")
            except json.JSONDecodeError:
                continue
            if key:
                keys.add(key)
    return keys


@dataclass
class Plan:
    todo: list[dict[str, Any]] = field(default_factory=list)
    skipped: int = 0
    streams: list[dict[str, Any]] = field(default_factory=list)
    missing: list[dict[str, Any]] = field(default_factory=list)
    candidates: int = 0


def plan_tracks(
    tracks: list[dict[str, Any]],
    done_keys: set[str],
    limit: int | None = None,
    seed: int | None = None,
    only_ids: set[str] | None = None,
) -> Plan:
    """Split the snapshot into streams / missing / local; sample; drop rows already measured.

    The sample (limit + seed) is drawn before the done-filter so a re-run with the same
    arguments sees the same tracks and skips the finished ones.
    """
    plan = Plan()
    local: list[dict[str, Any]] = []
    for track in tracks:
        path = str(track.get("path") or "")
        if not path or path.startswith(STREAM_PREFIXES):
            plan.streams.append(track)
            continue
        if only_ids is not None and str(track.get("ID")) not in only_ids:
            continue
        try:
            st = os.stat(path)
        except OSError:
            plan.missing.append(track)
            continue
        item = dict(track)
        item["_key"] = make_key(track, st)
        item["_mtime"] = int(st.st_mtime)
        item["_size"] = int(st.st_size)
        item["_attempts"] = 0
        local.append(item)
    plan.candidates = len(local)
    if limit is not None and limit < len(local):
        local = random.Random(seed).sample(local, limit) if seed is not None else local[:limit]
    plan.todo = [t for t in local if t["_key"] not in done_keys]
    plan.skipped = len(local) - len(plan.todo)
    return plan


def track_budget_s(track: dict[str, Any]) -> float:
    total = track.get("TotalTime")
    try:
        seconds = float(total) if total is not None else 0.0
    except (TypeError, ValueError):
        seconds = 0.0
    if seconds <= 0:
        return DEFAULT_BUDGET_S
    return max(MIN_BUDGET_S, BUDGET_FACTOR * seconds)


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #


@dataclass
class RunStats:
    total: int = 0
    done: int = 0
    ok: int = 0
    errors: int = 0
    timeouts: int = 0
    cpu_sum_s: float = 0.0
    wall_s: float = 0.0
    recycles: int = 0
    rss_by_pid: dict[int, float] = field(default_factory=dict)
    rss_source: str | None = None

    def as_dict(self) -> dict[str, Any]:
        rss = sorted(self.rss_by_pid.values())
        return {
            "total": self.total,
            "done": self.done,
            "ok": self.ok,
            "errors": self.errors,
            "timeouts": self.timeouts,
            "recycles": self.recycles,
            "cpu_sum_s": round(self.cpu_sum_s, 1),
            "wall_s": round(self.wall_s, 1),
            "tracks_per_min": round(self.done / self.wall_s * 60.0, 2) if self.wall_s else None,
            "cpu_per_track_s": round(self.cpu_sum_s / self.ok, 1) if self.ok else None,
            "workers_seen": len(self.rss_by_pid),
            "rss_peak_mb_max": rss[-1] if rss else None,
            "rss_peak_mb_median": rss[len(rss) // 2] if rss else None,
            "rss_source": self.rss_source,
        }


def _worker_init() -> None:
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger().setLevel(logging.WARNING)
    _engine()


def _kill_pool(executor: ProcessPoolExecutor) -> None:
    procs = list(getattr(executor, "_processes", {}).values())
    for proc in procs:
        proc.kill()
    for proc in procs:
        proc.join(timeout=5)
    executor.shutdown(wait=False, cancel_futures=True)


def _progress(stats: RunStats, start: float) -> str:
    stats.wall_s = time.perf_counter() - start
    rate = stats.done / stats.wall_s * 60.0 if stats.wall_s > 0 else 0.0
    remaining = stats.total - stats.done
    eta_min = remaining / rate if rate > 0 else float("inf")
    return (
        f"[{stats.done}/{stats.total}] ok={stats.ok} err={stats.errors} to={stats.timeouts} "
        f"rate={rate:.2f}/min cpu_sum={stats.cpu_sum_s:.0f}s wall={stats.wall_s:.0f}s "
        f"eta={eta_min:.1f}min"
    )


def _record(row: dict[str, Any], stats: RunStats, fh: Any) -> None:
    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    fh.flush()
    stats.done += 1
    status = row.get("status")
    if status == "ok":
        stats.ok += 1
    elif status == "timeout":
        stats.timeouts += 1
    else:
        stats.errors += 1
    stats.cpu_sum_s += float(row.get("t_cpu_s") or 0.0)
    pid, rss = row.get("worker_pid"), row.get("rss_peak_mb")
    if pid is not None and rss is not None:
        stats.rss_by_pid[int(pid)] = max(stats.rss_by_pid.get(int(pid), 0.0), float(rss))
        stats.rss_source = row.get("rss_source")


def run_inline(todo: list[dict[str, Any]], depth: str, out_path: Path, every: int) -> RunStats:
    stats = RunStats(total=len(todo))
    start = time.perf_counter()
    with out_path.open("a", encoding="utf-8") as fh:
        for track in todo:
            _record(measure_task(track, depth), stats, fh)
            if stats.done % every == 0 or stats.done == stats.total:
                print(_progress(stats, start), flush=True)
    stats.wall_s = time.perf_counter() - start
    return stats


def run_pool(
    todo: list[dict[str, Any]],
    depth: str,
    workers: int,
    out_path: Path,
    every: int = 10,
    max_tasks_per_child: int = 20,
) -> RunStats:
    """Submit one task per worker, watch deadlines, recycle the whole pool on a timeout or a
    broken worker (a running task cannot be cancelled individually)."""
    stats = RunStats(total=len(todo))
    pending: deque[dict[str, Any]] = deque(todo)
    start = time.perf_counter()
    with out_path.open("a", encoding="utf-8") as fh:
        while pending:
            # kwargs dict: max_tasks_per_child is py3.11+, mypy runs with python_version 3.10
            pool_kwargs: dict[str, Any] = {
                "max_workers": workers,
                "initializer": _worker_init,
                "max_tasks_per_child": max_tasks_per_child,
            }
            executor = ProcessPoolExecutor(**pool_kwargs)
            running: dict[Future[dict[str, Any]], tuple[dict[str, Any], float]] = {}
            recycle = False
            try:
                while (pending or running) and not recycle:
                    while pending and len(running) < workers:
                        track = pending.popleft()
                        try:
                            fut = executor.submit(measure_task, track, depth)
                        except BrokenProcessPool:
                            pending.appendleft(track)
                            recycle = True
                            break
                        running[fut] = (track, time.perf_counter() + track_budget_s(track))
                    if recycle or not running:
                        break
                    finished, _ = wait(list(running), timeout=1.0, return_when=FIRST_COMPLETED)
                    for fut in finished:
                        track, _deadline = running.pop(fut)
                        try:
                            row = fut.result()
                        except BrokenProcessPool as exc:
                            recycle = True
                            track["_attempts"] += 1
                            if track["_attempts"] < MAX_ATTEMPTS:
                                pending.appendleft(track)
                                continue
                            row = error_row(track, depth, exc)
                        except Exception as exc:  # pickling / unexpected harness failure
                            row = error_row(track, depth, exc)
                        _record(row, stats, fh)
                        if stats.done % every == 0:
                            print(_progress(stats, start), flush=True)
                    now = time.perf_counter()
                    expired = [f for f, (_t, dl) in running.items() if now > dl]
                    if expired:
                        recycle = True
                        for fut in expired:
                            track, _deadline = running.pop(fut)
                            timeout_exc = TimeoutError(
                                f"budget {track_budget_s(track):.0f}s exceeded"
                            )
                            _record(
                                error_row(track, depth, timeout_exc, status="timeout"), stats, fh
                            )
                    if recycle:
                        for _fut, (track, _deadline) in running.items():
                            track["_attempts"] += 1
                            if track["_attempts"] < MAX_ATTEMPTS:
                                pending.appendleft(track)
                            else:
                                lost_exc = RuntimeError("lost twice to a pool recycle")
                                _record(error_row(track, depth, lost_exc), stats, fh)
                        running = {}
            finally:
                if recycle:
                    stats.recycles += 1
                    _kill_pool(executor)
                else:
                    executor.shutdown(wait=True)
    stats.wall_s = time.perf_counter() - start
    print(_progress(stats, start), flush=True)
    return stats


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="tracks.json snapshot")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="JSONL output (appended)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--seed", type=int, default=None, help="reproducible random sample for --limit")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--only-ids", default=None, help="comma-separated track IDs")
    ap.add_argument("--depth", choices=DEPTHS, default="high")
    ap.add_argument("--progress-every", type=int, default=10)
    ap.add_argument("--max-tasks-per-child", type=int, default=20)
    ap.add_argument("--inline", action="store_true", help="no pool: run in this process")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    with args.input.open(encoding="utf-8") as fh:
        tracks = json.load(fh)
    if isinstance(tracks, dict):
        tracks = tracks.get("tracks", [])
    only_ids = {s.strip() for s in args.only_ids.split(",") if s.strip()} if args.only_ids else None
    args.out.parent.mkdir(parents=True, exist_ok=True)
    done_keys = load_done_keys(args.out)
    plan = plan_tracks(tracks, done_keys, limit=args.limit, seed=args.seed, only_ids=only_ids)
    full_run = args.limit is None and only_ids is None
    print(
        f"snapshot={len(tracks)} local={plan.candidates} streams={len(plan.streams)} "
        f"missing={len(plan.missing)} already_done={plan.skipped} todo={len(plan.todo)} "
        f"depth={args.depth} workers={args.workers} out={args.out}",
        flush=True,
    )
    if full_run:
        with args.out.open("a", encoding="utf-8") as fh:
            for status, items in (("stream", plan.streams), ("missing", plan.missing)):
                for track in items:
                    row = base_row(track, args.depth)
                    if row["track_key"] in done_keys:
                        continue
                    row["status"] = status
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    if not plan.todo:
        print("nothing to do", flush=True)
        return 0
    if args.inline:
        stats = run_inline(plan.todo, args.depth, args.out, args.progress_every)
    else:
        stats = run_pool(
            plan.todo,
            args.depth,
            args.workers,
            args.out,
            every=args.progress_every,
            max_tasks_per_child=args.max_tasks_per_child,
        )
    print(json.dumps({"summary": stats.as_dict()}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
