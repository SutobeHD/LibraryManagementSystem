"""Stage-E audio extras E1-E8 (docs/LIBRARY_ANALYSIS_HANDOVER.md §3.5 + §5 tier rule).

Pure functions on already decoded audio plus one entry point, :func:`compute_extras`, that the
engine calls at depth ``high`` and ``scripts/library_measure_audio.py`` calls per track.

  E1 spectrum   spectral cutoff + measured quality tier       E5 dc        offset per channel
  E2 clipping   runs >= 3 samples at |x| >= 0.999, true peak  E6 bass      energy share < 60 / < 120 Hz
  E3 dynamics   PLR, crest factor, loudness range (R128)      E7 lowband   L/R correlation < 150 Hz
  E4 silence    leading / trailing below -60 dBFS             E8 fingerprint  Chromaprint via fpcalc

Tier rule (decision A1, 2026-11-08): the tier comes ONLY from a hard spectral edge (drop of
HARD_EDGE_DB within HARD_EDGE_BAND_HZ, nothing above comes back up) or from a digital-zero floor
(median above the -60 dB cutoff below DIGITAL_ZERO_REL_DB -> the threshold cutoff is the edge).
A full band without an edge is A. Anything else is a natural roll-off: no tier, flag ``pruefen``.

No engine import, no cache, no DB. Only numpy at import time; scipy / pyloudnorm load lazily.
"""

from __future__ import annotations

import glob
import logging
import math
import os
import shutil
import time
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

EXTRAS_VERSION = 1

SILENCE_DBFS = -60.0
CUTOFF_FLOOR_REL_DB = -60.0
HARD_EDGE_DB = 20.0
HARD_EDGE_BAND_HZ = 500.0
HARD_EDGE_SCAN_FROM_HZ = 8000.0
EDGE_SMOOTH_HZ = 100.0
# Edges above tier-A threshold + this are the ADC / sample-rate-converter anti-alias filter
# (21.5-22 kHz on 44.1 kHz material, also inside 48 kHz files upsampled from CD masters).
EDGE_GUARD_HZ = 400.0
DIGITAL_ZERO_REL_DB = -100.0
TIER_BOUNDARY_SLACK_HZ = 300.0
TIER_B_HZ = 19000.0
TIER_C_HZ = 17000.0
CLIP_THRESHOLD = 0.999
CLIP_MIN_RUN = 3
LOW_BAND_HZ = 150.0
# LAME lowpass per bitrate (handover §5): nearest match within LAME_MATCH_HZ names the bitrate.
LAME_LOWPASS: tuple[tuple[int, float], ...] = (
    (128, 17000.0),
    (160, 17500.0),
    (192, 18600.0),
    (256, 19700.0),
    (320, 20500.0),
)
LAME_MATCH_HZ = 400.0
FPCALC_SAMPLE_SECONDS = 120
FPCALC_TIMEOUT_S = 30.0
FPCALC_WINGET_GLOB = "Microsoft/WinGet/Packages/AcoustID.Chromaprint*/**/fpcalc.exe"


def _db(x: float, floor: float = -200.0) -> float:
    return float(20.0 * np.log10(x)) if x > 0 else floor


def _channels(y: np.ndarray) -> np.ndarray:
    """(N,) -> (1, N); (C, N) stays."""
    return y if y.ndim == 2 else y[None, :]


def _py(obj: Any) -> Any:
    """numpy scalars / arrays / non-finite floats -> JSON-serialisable builtins."""
    if isinstance(obj, dict):
        return {str(k): _py(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_py(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return _py(obj.tolist())
    if isinstance(obj, np.generic):
        return _py(obj.item())
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    return obj


# --------------------------------------------------------------------------- #
# E1 / E6: one STFT on the native-rate mono signal
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


def _sliding_median(x: np.ndarray, width: int) -> np.ndarray:
    """median of x[j:j+width] for every full window j."""
    if width <= 1:
        return x.copy()
    return np.median(np.lib.stride_tricks.sliding_window_view(x, width), axis=1)


def tier_a_threshold_hz(sr: int) -> float:
    """A threshold per handover §5: 20.5 kHz up to 44.1 kHz, 21 kHz above."""
    return 20500.0 if sr <= 44100 else 21000.0


def spectral_cutoff(
    freqs: np.ndarray, median_db: np.ndarray, band_hz: float = HARD_EDGE_BAND_HZ
) -> dict[str, Any]:
    """E1 geometry. Threshold cutoff = highest bin within 60 dB of the peak bin. Hard edge =
    a bin k above HARD_EDGE_SCAN_FROM_HZ where the median of the band_hz below k sits >= HARD_EDGE_DB
    above the median of the band_hz above k, and every band above k stays that far down. The
    lowest such edge wins (a 15 kHz source cut below a 20 kHz encoder lowpass is the one that
    limits quality); its frequency is refined to the -10 dB crossing of the ~100 Hz smoothed
    spectrum. Edges above the A threshold + EDGE_GUARD_HZ are the converter / SRC anti-alias
    filter, not a codec, and are ignored.

    Sliding windows (not aligned bands) so the result does not depend on where the band grid
    happens to fall relative to the edge; ``band_hz`` is then the slope scale: a drop of
    HARD_EDGE_DB per band_hz, i.e. 500 Hz -> 40 dB/kHz, is the minimum steepness that counts.
    """
    rel = np.asarray(median_db, dtype=np.float64) - float(np.max(median_db))
    n = len(rel)
    above = np.nonzero(rel > CUTOFF_FLOOR_REL_DB)[0]
    idx_thr = int(above[-1]) if len(above) else 0
    bin_hz = float(freqs[1] - freqs[0]) if len(freqs) > 1 else 1.0
    nb = max(2, round(band_hz / bin_hz))
    tail_min = max(2, round(EDGE_SMOOTH_HZ / bin_hz))
    first = max(int(np.searchsorted(freqs, HARD_EDGE_SCAN_FROM_HZ)), nb)
    guard_hz = tier_a_threshold_hz(round(2.0 * float(freqs[-1]))) + EDGE_GUARD_HZ
    last = min(n - tail_min, int(np.searchsorted(freqs, guard_hz)) - 1)

    edge_idx: int | None = None
    best_drop = 0.0
    if last > first and n > nb:
        med = _sliding_median(rel, nb)  # med[j] = median(rel[j:j+nb]), j <= n - nb
        suffix_max = np.maximum.accumulate(med[::-1])[::-1]
        ks = np.arange(first, last + 1)
        before = med[ks - nb]
        full = ks <= n - nb
        after = np.empty(len(ks), dtype=np.float64)
        stays_down = np.empty(len(ks), dtype=np.float64)
        after[full] = med[ks[full]]
        stays_down[full] = suffix_max[ks[full]]
        for i in np.nonzero(~full)[0]:  # windows cut by Nyquist: the tail itself is the band
            after[i] = stays_down[i] = float(np.median(rel[ks[i] :]))
        drops = before - after
        best_drop = float(np.max(drops))
        ok_idx = np.nonzero((drops >= HARD_EDGE_DB) & (stays_down <= before - HARD_EDGE_DB))[0]
        if len(ok_idx):
            breaks = np.nonzero(np.diff(ok_idx) > 1)[0]
            run = ok_idx[: breaks[0] + 1] if len(breaks) else ok_idx  # lowest contiguous run
            i_best = int(run[np.argmax(drops[run])])
            k = int(ks[i_best])
            level = float(before[i_best])
            best_drop = float(drops[i_best])
            lo, hi = max(0, k - nb), min(n, k + nb)
            smooth_w = min(tail_min, hi - lo)
            seg = _sliding_median(rel[lo:hi], smooth_w)
            below = np.nonzero(seg < level - 10.0)[0]
            # sliding window j covers bins lo+j .. lo+j+w-1; its centre is the crossing estimate
            edge_idx = lo + int(below[0]) + smooth_w // 2 - 1 if len(below) else k
            edge_idx = max(0, min(edge_idx, n - 1))
            if float(freqs[edge_idx]) >= guard_hz:
                edge_idx = None

    # Digital-zero suffix: lowest bin above which the ~100 Hz smoothed spectrum never comes back
    # over DIGITAL_ZERO_REL_DB. A codec lowpass leaves one even when its slope is too soft for the
    # edge test; a natural master keeps a noise / dither floor up to Nyquist.
    zero_from_idx: int | None = None
    if n > tail_min:
        sm = _sliding_median(rel, tail_min)
        if sm[-1] < DIGITAL_ZERO_REL_DB:
            nonzero = np.nonzero(sm >= DIGITAL_ZERO_REL_DB)[0]
            j0 = int(nonzero[-1]) + 1 if len(nonzero) else 0
            zero_from_idx = min(n - 1, j0 + tail_min // 2)

    hard_edge = edge_idx is not None
    idx = edge_idx if edge_idx is not None else idx_thr
    floor_bins = rel[idx + 1 :]
    return {
        "cutoff_edge_hz": round(float(freqs[edge_idx]), 1) if edge_idx is not None else None,
        "cutoff_thr_hz": round(float(freqs[idx_thr]), 1),
        "zero_from_hz": round(float(freqs[zero_from_idx]), 1)
        if zero_from_idx is not None
        else None,
        "hard_edge": hard_edge,
        "edge_drop_db": round(best_drop, 1),
        "floor_rel_db": round(float(np.median(floor_bins)), 1) if len(floor_bins) else None,
        "peak_bin_hz": round(float(freqs[int(np.argmax(median_db))]), 1),
        "peak_bin_dbfs": round(float(np.max(median_db)), 1),
        "band_hz": float(band_hz),
    }


def cutoff_tier(
    cutoff_edge_hz: float | None,
    cutoff_thr_hz: float,
    floor_rel_db: float | None,
    sr: int,
    zero_from_hz: float | None = None,
) -> dict[str, Any]:
    """Measured tier (handover §5 thresholds, decision A1 rule).

    sr < 44.1 kHz -> D. Hard edge -> tier from the edge (never A). No edge but a digital-zero
    region starting below the A threshold + guard -> its start is the edge (codec lowpass with a
    soft slope); without ``zero_from_hz`` a digital-zero floor above the threshold cutoff makes
    that cutoff the edge. No edge and threshold cutoff >= A threshold -> A. Otherwise natural
    roll-off: tier None, flag ``pruefen``.
    """
    thr_a = tier_a_threshold_hz(sr)
    flags: list[str] = []
    tier: str | None = None
    reason: str
    edge_hz: float | None = None
    tier_cutoff: float | None = None
    if sr < 44100:
        tier, reason = "D", "sample_rate"
    elif cutoff_edge_hz is not None:
        edge_hz, reason = float(cutoff_edge_hz), "hard_edge"
    elif zero_from_hz is not None and zero_from_hz < thr_a + EDGE_GUARD_HZ:
        edge_hz, reason = max(float(zero_from_hz), float(cutoff_thr_hz)), "digital_zero"
    elif (
        zero_from_hz is None
        and floor_rel_db is not None
        and floor_rel_db < DIGITAL_ZERO_REL_DB
        and cutoff_thr_hz < thr_a
    ):
        edge_hz, reason = float(cutoff_thr_hz), "digital_zero"
    elif cutoff_thr_hz >= thr_a:
        tier, reason, tier_cutoff = "A", "full_band", float(cutoff_thr_hz)
        if abs(cutoff_thr_hz - thr_a) <= TIER_BOUNDARY_SLACK_HZ:
            flags += ["pruefen", "boundary"]
    else:
        reason = "rolloff"
        flags.append("pruefen")
    lame: int | None = None
    if edge_hz is not None:
        tier_cutoff = edge_hz
        if edge_hz >= TIER_B_HZ:
            tier = "B"
        elif edge_hz > TIER_C_HZ:
            tier = "C"
        else:
            tier = "D"
        if any(abs(edge_hz - b) <= TIER_BOUNDARY_SLACK_HZ for b in (TIER_C_HZ, TIER_B_HZ)):
            flags += ["pruefen", "boundary"]
        bitrate, lowpass = min(LAME_LOWPASS, key=lambda bl: abs(bl[1] - edge_hz))
        if abs(lowpass - edge_hz) <= LAME_MATCH_HZ:
            lame = bitrate
    return {
        "tier": tier,
        "tier_reason": reason,
        "tier_cutoff_hz": tier_cutoff,
        "flags": flags,
        "lame_estimate_kbps": lame,
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


def analyze_spectrum(
    y: np.ndarray,
    sr: int,
    *,
    band_hz: float = HARD_EDGE_BAND_HZ,
    sample_rate_meta: int | None = None,
) -> tuple[dict[str, Any], dict[str, float | None]]:
    """E1 + E6 from one STFT of the native-rate signal (stereo is downmixed here, not resampled:
    the 44.1 kHz analysis signal would hide everything above 22 kHz and fake an edge).
    Returns (spectrum, bass)."""
    freqs, median_db, mean_power = power_spectrum_stats(y, sr)
    spectrum = spectral_cutoff(freqs, median_db, band_hz=band_hz)
    sr_tier = int(sr)
    if sample_rate_meta and int(sample_rate_meta) > 0:
        sr_tier = min(sr_tier, int(sample_rate_meta))
    spectrum.update(
        cutoff_tier(
            spectrum["cutoff_edge_hz"],
            spectrum["cutoff_thr_hz"],
            spectrum["floor_rel_db"],
            sr_tier,
            zero_from_hz=spectrum["zero_from_hz"],
        )
    )
    spectrum["sample_rate_used"] = sr_tier
    return spectrum, bass_share(freqs, mean_power)


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
# E8: Chromaprint fingerprint via fpcalc
# --------------------------------------------------------------------------- #


def find_fpcalc() -> str | None:
    """fpcalc on PATH, else $FPCALC_DIR, else the winget AcoustID.Chromaprint package dir.
    A hit outside PATH is prepended to os.environ["PATH"] so subprocess + the cached
    ``is_fingerprinting_available`` see it from then on. None when nothing is found."""
    found = shutil.which("fpcalc")
    if found:
        return found
    candidates: list[str] = []
    env_dir = os.environ.get("FPCALC_DIR")
    if env_dir:
        candidates += [str(Path(env_dir) / "fpcalc.exe"), str(Path(env_dir) / "fpcalc")]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(str(Path(local) / "Microsoft" / "WinGet" / "Links" / "fpcalc.exe"))
        candidates += sorted(glob.glob(str(Path(local) / FPCALC_WINGET_GLOB), recursive=True))
    for cand in candidates:
        if Path(cand).is_file():
            os.environ["PATH"] = str(Path(cand).parent) + os.pathsep + os.environ.get("PATH", "")
            try:
                from app import external_track_match as etm

                etm.is_fingerprinting_available.cache_clear()
            except Exception as exc:  # import is optional here; the fallback is "unavailable"
                logger.debug("fpcalc cache clear skipped: %s", exc)
            logger.info("fpcalc found outside PATH, prepended dir=%s", Path(cand).parent)
            return cand
    return None


def fingerprint_file(
    path: str | Path | None,
    *,
    sample_seconds: int = FPCALC_SAMPLE_SECONDS,
    timeout: float = FPCALC_TIMEOUT_S,
) -> dict[str, Any] | None:
    """E8. None for no path. ``{"available": False}`` when fpcalc is missing. Otherwise
    ``fpcalc_hash`` (full string), ``duration_s``, ``elapsed_s`` or ``error``. Never raises."""
    if not path:
        return None
    try:
        if find_fpcalc() is None:
            return {"available": False, "reason": "fpcalc not found"}
        from app import external_track_match as etm

        resolved = Path(path).resolve()
        started = time.perf_counter()
        # allowed_roots = the file's own dir: the caller already validated the path, and the
        # default would import app.main (FastAPI app) inside every analysis worker.
        res = etm.fingerprint(
            resolved,
            sample_seconds=sample_seconds,
            timeout=timeout,
            allowed_roots=[resolved.parent],
        )
        elapsed = round(time.perf_counter() - started, 3)
        if isinstance(res, etm.Fingerprint):
            return {
                "available": True,
                "fpcalc_hash": res.fpcalc_hash,
                "duration_s": res.duration_s,
                "sample_seconds": sample_seconds,
                "elapsed_s": elapsed,
            }
        if isinstance(res, etm.BinaryMissing):
            return {"available": False, "reason": res.reason}
        return {"available": True, "error": res.reason, "elapsed_s": elapsed}
    except Exception as exc:
        logger.warning("fingerprint failed path=%s err=%s", path, exc)
        return {"available": True, "error": f"{type(exc).__name__}: {exc}"[:300]}


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def compute_extras(
    y_native: np.ndarray,
    sr_native: int,
    y_mono: np.ndarray,
    sr: int,
    *,
    lufs: float | None,
    first_signal_ms: float | None,
    file_path: str | None = None,
    sample_rate_meta: int | None = None,
) -> dict[str, Any]:
    """E1-E8 on the decoded track. Never raises for a normal track: every block is wrapped and a
    failing block becomes ``{"error": "..."}`` in its sub-dict.

    ``y_native`` (channels, n) or (n,) at ``sr_native`` carries every measurement; ``y_mono`` /
    ``sr`` (the engine's 44.1 kHz analysis signal) is only the fallback when ``y_native`` is empty.
    ``file_path`` None skips E8. ``sample_rate_meta`` (container sample rate) lowers the tier's
    sample-rate check when it is below the decoded rate. ``t_stage`` holds CPU seconds per block
    (``fingerprint``: wall seconds, the work happens in the fpcalc subprocess).
    """
    t_stage: dict[str, float] = {}
    out: dict[str, Any] = {"extras_version": EXTRAS_VERSION}

    def run(name: str, fn: Any) -> Any:
        t0 = time.process_time()
        try:
            return fn()
        except Exception as exc:
            logger.warning("extras block=%s err=%s", name, exc)
            return {"error": f"{type(exc).__name__}: {exc}"[:300]}
        finally:
            t_stage[name] = round(time.process_time() - t0, 3)

    y = np.asarray(y_native, dtype=np.float32)
    rate = int(sr_native)
    if y.size == 0:
        y, rate = np.asarray(y_mono, dtype=np.float32), int(sr)
    if y.ndim > 2 or y.size == 0:
        err = {"error": f"unsupported signal shape {tuple(np.shape(y_native))}"}
        for k in ("spectrum", "clipping", "dynamics", "silence", "dc", "bass", "lowband"):
            out[k] = dict(err)
        out["fingerprint"] = fingerprint_file(file_path) if file_path else None
        out["t_stage"] = t_stage
        return out

    spec = run("spectrum", lambda: analyze_spectrum(y, rate, sample_rate_meta=sample_rate_meta))
    if isinstance(spec, tuple):
        out["spectrum"], out["bass"] = spec
    else:
        out["spectrum"], out["bass"] = spec, dict(spec)

    def clipping() -> dict[str, Any]:
        c = clipping_stats(y)
        c["true_peak_dbtp"] = true_peak_dbtp(y)
        return c

    def dynamics() -> dict[str, Any]:
        d: dict[str, Any] = dict(dynamics_stats(y, lufs))
        d["lra"] = loudness_range(y, rate)
        return d

    def silence() -> dict[str, Any]:
        s = silence_stats(y, rate)
        s["first_signal_ms"] = first_signal_ms
        return s

    def dc() -> dict[str, Any]:
        per = dc_offset(y)
        return {"per_channel": per, "max_abs": max(abs(v) for v in per) if per else None}

    def lowband() -> dict[str, Any]:
        return {"corr": low_band_correlation(y, rate), "band_hz": LOW_BAND_HZ}

    out["clipping"] = run("clipping", clipping)
    out["dynamics"] = run("dynamics", dynamics)
    out["silence"] = run("silence", silence)
    out["dc"] = run("dc", dc)
    out["lowband"] = run("lowband", lowband)

    if file_path:
        t0 = time.perf_counter()
        out["fingerprint"] = fingerprint_file(file_path)
        t_stage["fingerprint"] = round(time.perf_counter() - t0, 3)
    else:
        out["fingerprint"] = None
    out["t_stage"] = t_stage
    return _py(out)
