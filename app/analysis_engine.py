"""
RB Editor Pro — High-Accuracy Analysis Engine
================================================
Replaces the basic AudioAnalyzer with a production-grade DSP pipeline
that produces Rekordbox-compatible analysis data.

Output format matches Rekordbox ANLZ structures so data can be injected
directly into master.db + ANLZ files without re-analysis.

Dependencies: librosa, scipy, numpy (all Python 3.13 compatible)
"""

import os
import json
import logging
import numpy as np
import warnings
from typing import Dict, Any, List, Optional, Tuple
from concurrent.futures import ProcessPoolExecutor, Future

warnings.filterwarnings('ignore', category=UserWarning)
warnings.filterwarnings('ignore', category=FutureWarning)

logger = logging.getLogger(__name__)

# ─── Lazy imports (heavy libs) ───────────────────────────────────────────────
_LIBS_LOADED = False
librosa = None
signal = None


def _ensure_libs():
    """Lazy-load heavy libraries only when analysis is actually requested."""
    global _LIBS_LOADED, librosa, signal
    if _LIBS_LOADED:
        return True
    try:
        import librosa as _lr
        import scipy.signal as _sig
        librosa = _lr
        signal = _sig
        _LIBS_LOADED = True
        return True
    except ImportError as e:
        logger.error(f"Missing analysis dependency: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# 1. KEY DETECTION — Krumhansl-Schmuckler Algorithm
# ═══════════════════════════════════════════════════════════════════════════════

# Key profiles from Krumhansl & Kessler (1982) — the gold standard
# These are correlation weights for each pitch class in a major/minor key.
_MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09,
                           2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_MINOR_PROFILE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53,
                           2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

_PITCH_CLASSES = ['C', 'C#', 'D', 'D#', 'E', 'F',
                  'F#', 'G', 'G#', 'A', 'A#', 'B']

# Camelot wheel mapping for DJ-friendly key display
_CAMELOT_MAP = {
    'C major': '8B',  'G major': '9B',  'D major': '10B',
    'A major': '11B', 'E major': '12B', 'B major': '1B',
    'F# major': '2B', 'C# major': '3B', 'G# major': '4B',
    'D# major': '5B', 'A# major': '6B', 'F major': '7B',
    'A minor': '8A',  'E minor': '9A',  'B minor': '10A',
    'F# minor': '11A','C# minor': '12A','G# minor': '1A',
    'D# minor': '2A', 'A# minor': '3A', 'F minor': '4A',
    'C minor': '5A',  'G minor': '6A',  'D minor': '7A',
}

# Open Key notation (alternative to Camelot)
_OPENKEY_MAP = {
    'C major': '1d',  'G major': '2d',  'D major': '3d',
    'A major': '4d',  'E major': '5d',  'B major': '6d',
    'F# major': '7d', 'C# major': '8d', 'G# major': '9d',
    'D# major': '10d','A# major': '11d','F major': '12d',
    'A minor': '1m',  'E minor': '2m',  'B minor': '3m',
    'F# minor': '4m', 'C# minor': '5m', 'G# minor': '6m',
    'D# minor': '7m', 'A# minor': '8m', 'F minor': '9m',
    'C minor': '10m', 'G minor': '11m', 'D minor': '12m',
}


def detect_key(y: np.ndarray, sr: int) -> Dict[str, str]:
    """
    Detect musical key using Krumhansl-Schmuckler key-finding algorithm.

    Significantly more accurate than simple chroma argmax because it
    correlates against proper major/minor key profiles and detects MODE
    (major vs minor) — the #1 weakness of our old implementation.

    Returns: {"key": "Am", "camelot": "8A", "openkey": "1m", "confidence": 0.85}
    """
    # Use HPSS to isolate harmonic content (removes drums/percussion)
    y_harmonic = librosa.effects.harmonic(y, margin=4.0)

    # Compute chromagram using CQT (more accurate than STFT for key detection)
    chroma = librosa.feature.chroma_cqt(
        y=y_harmonic, sr=sr, n_chroma=12, bins_per_octave=36
    )

    # Average chroma vector across time
    mean_chroma = np.mean(chroma, axis=1)

    # Normalize to unit vector
    norm = np.linalg.norm(mean_chroma)
    if norm < 1e-8:
        return {"key": "Unknown", "camelot": "", "openkey": "", "confidence": 0.0}
    mean_chroma = mean_chroma / norm

    best_corr = -2.0
    best_key = ""
    best_mode = ""

    # Test all 24 keys (12 major + 12 minor)
    for shift in range(12):
        # Rotate chroma to test this root note
        rotated = np.roll(mean_chroma, -shift)

        # Correlate with major profile
        major_corr = np.corrcoef(rotated, _MAJOR_PROFILE)[0, 1]
        if major_corr > best_corr:
            best_corr = major_corr
            best_key = _PITCH_CLASSES[shift]
            best_mode = "major"

        # Correlate with minor profile
        minor_corr = np.corrcoef(rotated, _MINOR_PROFILE)[0, 1]
        if minor_corr > best_corr:
            best_corr = minor_corr
            best_key = _PITCH_CLASSES[shift]
            best_mode = "minor"

    # Format outputs
    full_key = f"{best_key} {best_mode}"
    short_key = f"{best_key}m" if best_mode == "minor" else best_key
    camelot = _CAMELOT_MAP.get(full_key, "")
    openkey = _OPENKEY_MAP.get(full_key, "")

    return {
        "key": short_key,
        "camelot": camelot,
        "openkey": openkey,
        "confidence": round(float(best_corr), 4)
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 2. BPM & BEAT GRID — Enhanced Beat Tracking
# ═══════════════════════════════════════════════════════════════════════════════

def detect_beats(y: np.ndarray, sr: int) -> Dict[str, Any]:
    """
    High-accuracy BPM and beat grid detection.

    Improvements over basic librosa.beat.beat_track:
    1. Uses HPSS to isolate percussive component → cleaner onset detection.
    2. Uses dynamic programming beat tracker with prior tempo estimate.
    3. Snaps BPM to nearest integer when close (Pioneer convention).
    4. Detects downbeat (beat 1) position using spectral flux changes.

    Returns: {
        "bpm": 174.0,
        "bpm_raw": 173.87,
        "beats": [{"beat_number": 1, "tempo": 17400, "time_ms": 450}, ...],
        "downbeat_index": 0
    }
    """
    # 1. Harmonic/Percussive Source Separation
    y_harmonic, y_percussive = librosa.effects.hpss(y, margin=2.0)

    # 2. Compute onset strength from percussive component
    onset_env = librosa.onset.onset_strength(
        y=y_percussive, sr=sr,
        hop_length=512,
        aggregate=np.median  # Median is more robust to outliers than mean
    )

    # 3. Estimate tempo with prior (electronic music typically 60-200 BPM)
    tempo_estimate = librosa.feature.tempo(
        onset_envelope=onset_env, sr=sr,
        hop_length=512,
        start_bpm=130.0,  # Good prior for electronic music
        ac_size=8.0       # Larger window for more stable estimate
    )
    prior_tempo = float(tempo_estimate[0]) if len(tempo_estimate) > 0 else 130.0

    # 4. Beat tracking with the tempo prior
    tempo, beat_frames = librosa.beat.beat_track(
        onset_envelope=onset_env,
        sr=sr,
        hop_length=512,
        start_bpm=prior_tempo,
        tightness=120  # Higher = stricter grid (good for electronic)
    )
    bpm_raw = float(tempo[0] if isinstance(tempo, np.ndarray) else tempo)

    # 5. Pioneer-style BPM snapping
    bpm_snapped = round(bpm_raw)
    if abs(bpm_raw - bpm_snapped) < 0.25:
        bpm = float(bpm_snapped)
    else:
        bpm = round(bpm_raw, 2)

    # 6. Convert frames to times
    beat_times = librosa.frames_to_time(beat_frames, sr=sr, hop_length=512)

    # 7. Build Rekordbox-format beat grid (PQTZ compatible)
    beats = []
    tempo_int = int(round(bpm * 100))  # Rekordbox stores as BPM × 100

    for i, t in enumerate(beat_times):
        beat_number = (i % 4) + 1  # Cycles 1,2,3,4
        beats.append({
            "beat_number": beat_number,
            "tempo": tempo_int,
            "time_ms": int(round(t * 1000))
        })

    # 8. Downbeat detection (find beat 1)
    # Uses spectral flux: the beat with the largest low-frequency energy change
    # is likely the downbeat (kick drum on beat 1).
    downbeat_idx = _detect_downbeat(y, sr, beat_times)

    # Re-align beat_number based on detected downbeat
    if downbeat_idx > 0:
        for i in range(len(beats)):
            beats[i]["beat_number"] = ((i - downbeat_idx) % 4) + 1

    return {
        "bpm": bpm,
        "bpm_raw": round(bpm_raw, 4),
        "beats": beats,
        "downbeat_index": downbeat_idx,
        "beat_count": len(beats)
    }


def _detect_downbeat(y: np.ndarray, sr: int, beat_times: np.ndarray) -> int:
    """
    Heuristic downbeat (beat 1) detection.
    Looks for the beat with the strongest low-frequency energy onset
    among the first 16 beats — the kick is loudest on beat 1.
    """
    if len(beat_times) < 8:
        return 0

    # Low-pass filter to isolate kick drum region (< 150 Hz)
    sos = signal.butter(4, 150.0, btype='low', fs=sr, output='sos')
    y_low = signal.sosfilt(sos, y)

    # Compute energy at each beat position
    hop = int(sr * 0.02)  # 20ms window
    energies = []
    for t in beat_times[:16]:
        sample = int(t * sr)
        start = max(0, sample - hop)
        end = min(len(y_low), sample + hop)
        if end > start:
            rms = np.sqrt(np.mean(y_low[start:end] ** 2))
            energies.append(rms)
        else:
            energies.append(0.0)

    if not energies:
        return 0

    # Group by beat position (0,1,2,3) and find which position has highest avg energy
    group_energy = [0.0] * 4
    group_count = [0] * 4
    for i, e in enumerate(energies):
        pos = i % 4
        group_energy[pos] += e
        group_count[pos] += 1

    for i in range(4):
        if group_count[i] > 0:
            group_energy[i] /= group_count[i]

    return int(np.argmax(group_energy))


# ═══════════════════════════════════════════════════════════════════════════════
# 3. THREE-BAND WAVEFORM — Rekordbox RGB Waveform Data
# ═══════════════════════════════════════════════════════════════════════════════

# Rekordbox crossover frequencies (empirically derived)
LOW_CUTOFF = 200.0     # Hz — below this is "Low" (kick, bass)
HIGH_CUTOFF = 2500.0   # Hz — above this is "High" (hi-hat, cymbals)


def generate_waveform_data(
    y: np.ndarray,
    sr: int,
    detail_fps: int = 150  # Rekordbox: 150 entries per second
) -> Dict[str, Any]:
    """
    Generate all waveform data required for Rekordbox ANLZ files:
    - Monochrome preview (400 columns, PWAV format)
    - Monochrome detail (150/sec, PWV3 format)
    - Color detail (150/sec, PWV5 format with RGB + height)
    - 3-Band arrays for our own UI rendering

    Each "column" packs height (0-31) and whiteness/color into bytes
    matching the exact Rekordbox binary specification.
    """
    duration = len(y) / sr
    total_detail_entries = int(duration * detail_fps)

    if total_detail_entries < 1:
        return _empty_waveform()

    # ── 3-Band Filtering ──────────────────────────────────────────────────
    # 4th-order Butterworth filters (matches Pioneer crossover characteristics)
    sos_low = signal.butter(4, LOW_CUTOFF, btype='low', fs=sr, output='sos')
    sos_mid = signal.butter(4, [LOW_CUTOFF, HIGH_CUTOFF], btype='band', fs=sr, output='sos')
    sos_high = signal.butter(4, HIGH_CUTOFF, btype='high', fs=sr, output='sos')

    y_low = signal.sosfilt(sos_low, y)
    y_mid = signal.sosfilt(sos_mid, y)
    y_high = signal.sosfilt(sos_high, y)

    # ── RMS per window ────────────────────────────────────────────────────
    hop = int(sr / detail_fps)  # Samples per waveform entry

    def rms_array(sig: np.ndarray) -> np.ndarray:
        """Compute RMS energy for each window."""
        n_frames = len(sig) // hop
        if n_frames < 1:
            return np.array([0.0])
        # Reshape into frames and compute RMS per frame
        trimmed = sig[:n_frames * hop].reshape(n_frames, hop)
        return np.sqrt(np.mean(trimmed ** 2, axis=1))

    rms_low = rms_array(y_low)
    rms_mid = rms_array(y_mid)
    rms_high = rms_array(y_high)
    rms_full = rms_array(y)

    # Ensure all same length
    min_len = min(len(rms_low), len(rms_mid), len(rms_high), len(rms_full))
    rms_low = rms_low[:min_len]
    rms_mid = rms_mid[:min_len]
    rms_high = rms_high[:min_len]
    rms_full = rms_full[:min_len]

    # ── Quantization ──────────────────────────────────────────────────────
    # Use logarithmic scaling (dB-like) for more natural visual representation
    def quantize_log(arr: np.ndarray, max_val: int) -> np.ndarray:
        """Log-scale quantization: maps amplitude to 0..max_val."""
        eps = 1e-10
        db = 20 * np.log10(arr + eps)
        # Normalize: -60dB → 0, 0dB → max_val
        db_norm = np.clip((db + 60.0) / 60.0, 0.0, 1.0)
        return np.round(db_norm * max_val).astype(np.uint8)

    # ── PWAV: Monochrome Preview (400 columns) ────────────────────────────
    preview_entries = 400
    preview_rms = _resample_array(rms_full, preview_entries)
    preview_heights = quantize_log(preview_rms, 31)  # 5 bits: 0-31

    # Compute "whiteness" from spectral brightness (high-freq ratio)
    preview_high = _resample_array(rms_high, preview_entries)
    preview_total = _resample_array(rms_full, preview_entries)
    brightness = np.zeros(preview_entries, dtype=np.uint8)
    mask = preview_total > 1e-10
    brightness[mask] = np.clip(
        (preview_high[mask] / preview_total[mask]) * 7.0, 0, 7
    ).astype(np.uint8)

    # Pack: (whiteness << 5) | height
    pwav = ((brightness & 0x07) << 5) | (preview_heights & 0x1F)

    # ── PWV2: Tiny Preview (100 columns) ──────────────────────────────────
    tiny_rms = _resample_array(rms_full, 100)
    tiny_heights = quantize_log(tiny_rms, 31)
    tiny_bright = _resample_array(rms_high, 100)
    tiny_total = _resample_array(rms_full, 100)
    tiny_whiteness = np.zeros(100, dtype=np.uint8)
    mask2 = tiny_total > 1e-10
    tiny_whiteness[mask2] = np.clip(
        (tiny_bright[mask2] / tiny_total[mask2]) * 7.0, 0, 7
    ).astype(np.uint8)
    pwv2 = ((tiny_whiteness & 0x07) << 5) | (tiny_heights & 0x1F)

    # ── PWV3: Monochrome Detail (150 entries/sec) ─────────────────────────
    detail_heights = quantize_log(rms_full, 31)
    detail_bright = np.zeros(min_len, dtype=np.uint8)
    mask3 = rms_full > 1e-10
    detail_bright[mask3] = np.clip(
        (rms_high[mask3] / rms_full[mask3]) * 7.0, 0, 7
    ).astype(np.uint8)
    pwv3 = ((detail_bright & 0x07) << 5) | (detail_heights & 0x1F)

    # ── PWV5: Color Detail (2 bytes/entry, 150/sec) ───────────────────────
    # Bit layout: [R:3][G:3][B:3][Height:5][pad:2]
    r_vals = quantize_log(rms_high, 7)   # 3 bits: 0-7
    g_vals = quantize_log(rms_mid, 7)    # 3 bits: 0-7
    b_vals = quantize_log(rms_low, 7)    # 3 bits: 0-7
    h_vals = quantize_log(rms_full, 31)  # 5 bits: 0-31

    # Pack into 16-bit values
    pwv5 = np.zeros(min_len, dtype=np.uint16)
    pwv5 = (r_vals.astype(np.uint16) << 13) | \
           (g_vals.astype(np.uint16) << 10) | \
           (b_vals.astype(np.uint16) << 7)  | \
           (h_vals.astype(np.uint16) << 2)

    # ── 3-Band float arrays (for our frontend rendering) ──────────────────
    # Normalize to 0.0–1.0 for Canvas/WebGL
    max_low = np.max(rms_low) if np.max(rms_low) > 0 else 1.0
    max_mid = np.max(rms_mid) if np.max(rms_mid) > 0 else 1.0
    max_high = np.max(rms_high) if np.max(rms_high) > 0 else 1.0

    return {
        # Rekordbox binary-compatible data
        "pwav": pwav.tolist(),          # 400 bytes — monochrome preview
        "pwv2": pwv2.tolist(),          # 100 bytes — tiny preview
        "pwv3": pwv3.tolist(),          # N bytes — monochrome detail
        "pwv5": pwv5.tolist(),          # N × uint16 — color detail
        # Our own float arrays for frontend
        "rgb_low": (rms_low / max_low).tolist(),
        "rgb_mid": (rms_mid / max_mid).tolist(),
        "rgb_high": (rms_high / max_high).tolist(),
        # Metadata
        "detail_fps": detail_fps,
        "detail_entries": min_len,
        "duration": round(duration, 3),
    }


def _resample_array(arr: np.ndarray, target_len: int) -> np.ndarray:
    """Resample an array to target length using linear interpolation."""
    if len(arr) == target_len:
        return arr
    x_old = np.linspace(0, 1, len(arr))
    x_new = np.linspace(0, 1, target_len)
    return np.interp(x_new, x_old, arr)


def _empty_waveform() -> Dict[str, Any]:
    return {
        "pwav": [0] * 400, "pwv2": [0] * 100, "pwv3": [],
        "pwv5": [], "rgb_low": [], "rgb_mid": [], "rgb_high": [],
        "detail_fps": 150, "detail_entries": 0, "duration": 0,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 4. MAIN ANALYSIS PIPELINE
# ═══════════════════════════════════════════════════════════════════════════════

class AnalysisEngine:
    """
    High-accuracy audio analysis engine producing Rekordbox-compatible output.

    Usage:
        result = AnalysisEngine.analyze("/path/to/track.mp3")
        # result contains: bpm, key, beats[], waveform data, etc.
    """

    _executor: Optional[ProcessPoolExecutor] = None
    _tasks: Dict[str, Future] = {}

    @classmethod
    def get_executor(cls):
        if cls._executor is None:
            cores = max(1, (os.cpu_count() or 2) - 1)
            cls._executor = ProcessPoolExecutor(max_workers=cores)
        return cls._executor

    @classmethod
    def shutdown(cls):
        if cls._executor:
            cls._executor.shutdown(wait=False)
            cls._executor = None

    @classmethod
    def submit(cls, task_id: str, file_path: str) -> Dict[str, Any]:
        """Submit an analysis job to the background worker pool."""
        executor = cls.get_executor()
        future = executor.submit(run_full_analysis, file_path)
        cls._tasks[task_id] = future
        return {"task_id": task_id, "status": "processing"}

    @classmethod
    def get_status(cls, task_id: str) -> Dict[str, Any]:
        """Check the status of an analysis job."""
        future = cls._tasks.get(task_id)
        if not future:
            return {"status": "not_found"}
        if future.done():
            try:
                return {"status": "done", "result": future.result()}
            except Exception as e:
                logger.error(f"Analysis {task_id} failed: {e}")
                return {"status": "error", "error": str(e)}
        return {"status": "processing"}

    @classmethod
    def analyze_sync(cls, file_path: str) -> Dict[str, Any]:
        """Synchronous analysis (blocks until done). For scripts/CLI."""
        return run_full_analysis(file_path)


def run_full_analysis(file_path: str) -> Dict[str, Any]:
    """
    Full analysis pipeline. Runs in a worker process.

    Returns a dict with all Rekordbox-compatible analysis data:
    - bpm, key, camelot, beats (PQTZ-format)
    - waveform data (PWAV, PWV2, PWV3, PWV5 formats)
    - 3-band RGB arrays for our frontend
    """
    if not _ensure_libs():
        return _fallback_result(file_path, "Analysis libraries not available")

    try:
        # ── OOM Protection ────────────────────────────────────────────────
        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
        duration_cap = None
        if file_size_mb > 200:
            logger.warning(f"Large file ({file_size_mb:.0f}MB), capping at 10min")
            duration_cap = 600.0

        # ── Load Audio ────────────────────────────────────────────────────
        y, sr = librosa.load(
            file_path, sr=44100, mono=True, duration=duration_cap
        )
        duration = len(y) / sr

        logger.info(f"Analyzing: {os.path.basename(file_path)} "
                     f"({duration:.1f}s, {sr}Hz)")

        # ── Run Analysis Components ───────────────────────────────────────
        key_result = detect_key(y, sr)
        beat_result = detect_beats(y, sr)
        waveform_result = generate_waveform_data(y, sr)

        return {
            # Metadata
            "file": file_path,
            "duration": round(duration, 3),
            "sample_rate": sr,
            # BPM & Beats
            "bpm": beat_result["bpm"],
            "bpm_raw": beat_result["bpm_raw"],
            "beats": beat_result["beats"],
            "beat_count": beat_result["beat_count"],
            "downbeat_index": beat_result["downbeat_index"],
            # Key
            "key": key_result["key"],
            "camelot": key_result["camelot"],
            "openkey": key_result["openkey"],
            "key_confidence": key_result["confidence"],
            # Waveform (Rekordbox binary-compatible)
            "waveform": waveform_result,
            # Status
            "status": "ok",
            "error": None,
        }

    except Exception as e:
        logger.error(f"Analysis failed for '{file_path}': {e}", exc_info=True)
        return _fallback_result(file_path, str(e))


def _fallback_result(file_path: str, error: str) -> Dict[str, Any]:
    """Safe fallback — never crash the batch pipeline."""
    return {
        "file": file_path, "duration": 0, "sample_rate": 44100,
        "bpm": 128.0, "bpm_raw": 128.0,
        "beats": [], "beat_count": 0, "downbeat_index": 0,
        "key": "Unknown", "camelot": "", "openkey": "", "key_confidence": 0.0,
        "waveform": _empty_waveform(),
        "status": "error", "error": error,
    }
