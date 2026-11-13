"""
LibraryManagementSystem -- Audio Analyzer (Unified Wrapper)
===================================================
Thin wrapper around the production AnalysisEngine.
Maintains backward compatibility with the existing API endpoints
while delegating all heavy lifting to analysis_engine.py.

Endpoints that use this:
  POST /api/audio/analyze       -> AudioAnalyzer.analyze_track()
  GET  /api/audio/analyze/{id}  -> AudioAnalyzer.get_status()
"""

import hashlib
import importlib.util
import logging
import os
import threading
from concurrent.futures import Future, ProcessPoolExecutor
from types import ModuleType
from typing import Any, ClassVar

from .analysis_cache import DEFAULT_DEPTH

logger = logging.getLogger(__name__)


def _module_installed(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


# Presence check only. Importing librosa/numpy here put the whole numpy/scipy
# stack on every sidecar boot via app.main; the methods import them on use.
LIBROSA_AVAILABLE = _module_installed("librosa") and _module_installed("numpy")
if not LIBROSA_AVAILABLE:
    logger.warning("librosa not found. Audio analysis will use mock fallback.")

# analysis_engine imports numpy at module level -> loaded on first use, not boot.
_engine: ModuleType | None = None
_engine_checked = False
_engine_lock = threading.Lock()


def _load_engine() -> ModuleType | None:
    """Return the app.analysis_engine module, or None when it cannot import."""
    global _engine, _engine_checked
    if not _engine_checked:
        with _engine_lock:
            if not _engine_checked:
                try:
                    from . import analysis_engine

                    _engine = analysis_engine
                except ImportError:
                    _engine = None
                    logger.warning("analysis_engine not available. Using legacy analyzer.")
                _engine_checked = True
    return _engine


def fingerprint_pcm_md5(path: str) -> bytes | None:
    """MD5 digest of the first 30 s of decoded mono PCM (11025 Hz).

    Duplicate-finder fingerprint. Catches bit-identical files, re-encodes and
    format conversions of the same master; not remixes. Without librosa it
    hashes the raw leading file bytes (bit-identical duplicates only).

    Thread-safe (no shared state); the duplicate scan runs it on a thread pool.

    Returns None on any error.
    """
    try:
        try:
            import librosa

            y, _ = librosa.load(path, sr=11025, mono=True, duration=30.0)
            raw = (y * 32768).astype("int16").tobytes()
        except ImportError:
            with open(path, "rb") as fh:
                raw = fh.read(30 * 11025 * 2)
        digest = hashlib.md5(raw, usedforsecurity=False).digest()
        logger.debug("fingerprint_pcm_md5: %s -> %s", path, digest.hex())
        return digest
    except Exception as exc:
        logger.error("fingerprint_pcm_md5: failed for %s - %s", path, exc)
        return None


class AudioAnalyzer:
    """
    Background worker pool for audio analysis.

    Delegates to AnalysisEngine (v2.0) for high-accuracy results.
    ``depth`` = "rekordbox" | "high" selects how much the engine computes
    (see run_full_analysis); ``duration_cap`` limits the decoded seconds and
    bypasses the cache — explicit opt-in only.
    """

    _executor: ClassVar[ProcessPoolExecutor | None] = None
    _tasks: ClassVar[dict[str, Future]] = {}
    _executor_lock = threading.Lock()

    @classmethod
    def get_executor(cls):
        # Double-checked locking: FastAPI serves requests on a threadpool, so an
        # unguarded check-then-create could spawn two pools (one leaking its
        # worker processes). cpu_count() is read once — a second call could
        # return None and make `None - 1` raise.
        if cls._executor is None:
            with cls._executor_lock:
                if cls._executor is None:
                    n = os.cpu_count()
                    cores = max(1, n - 1) if n else 2
                    cls._executor = ProcessPoolExecutor(max_workers=cores)
        return cls._executor

    @classmethod
    def shutdown(cls):
        with cls._executor_lock:
            if cls._executor:
                cls._executor.shutdown(wait=False)
                cls._executor = None
            cls._tasks.clear()

    @classmethod
    def analyze_track(
        cls,
        task_id: str,
        file_path: str,
        depth: str = DEFAULT_DEPTH,
        duration_cap: float | None = None,
    ) -> dict[str, Any]:
        """Submit an analysis job to the worker pool."""
        executor = cls.get_executor()
        engine = _load_engine()

        if engine is not None:
            future = executor.submit(engine.run_full_analysis, file_path, duration_cap, depth=depth)
        else:
            future = executor.submit(cls._run_legacy_analysis, file_path)

        cls._tasks[task_id] = future
        return {"task_id": task_id, "status": "processing"}

    @classmethod
    def get_status(cls, task_id: str) -> dict[str, Any]:
        """Check the status of an ongoing analysis job."""
        future = cls._tasks.get(task_id)
        if not future:
            return {"status": "not_found"}

        if future.done():
            try:
                result = future.result()
                # Normalize output format for backward compatibility
                return {"status": "done", "result": cls._normalize_result(result)}
            except Exception as e:
                logger.error(f"Analysis task {task_id} failed: {e}")
                return {"status": "error", "error": str(e)}
        return {"status": "processing"}

    @classmethod
    def analyze_sync(
        cls,
        file_path: str,
        depth: str = DEFAULT_DEPTH,
        duration_cap: float | None = None,
    ) -> dict[str, Any]:
        """Synchronous analysis. Blocks until done."""
        engine = _load_engine()
        if engine is not None:
            result = engine.run_full_analysis(file_path, duration_cap, depth=depth)
            return cls._normalize_result(result)
        return cls._run_legacy_analysis(file_path)

    @classmethod
    def capabilities(cls) -> dict[str, Any]:
        """Report which analysis backends are available."""
        engine = _load_engine()
        if engine is not None:
            return engine.AnalysisEngine.capabilities()
        return {
            "core": LIBROSA_AVAILABLE,
            "madmom": False,
            "essentia": False,
            "beat_method": "librosa basic" if LIBROSA_AVAILABLE else "none",
            "key_method": "none",
        }

    @staticmethod
    def _normalize_result(result: dict[str, Any]) -> dict[str, Any]:
        """
        Ensure the result dict is compatible with existing API consumers.
        Maps the new AnalysisEngine output back to the legacy format expected
        by the frontend.
        """
        if not result:
            return result

        # The new engine already provides all fields. Add legacy aliases:
        normalized = dict(result)

        # Legacy field: "beatgrid" (list of times in seconds). Guard the entry
        # shape — the engine emits {"time_ms": ...} dicts, but a malformed/legacy
        # beat list must skip bad entries, not crash an otherwise-good analysis.
        if "beats" in result and "beatgrid" not in result:
            normalized["beatgrid"] = [
                b["time_ms"] / 1000.0
                for b in result["beats"]
                if isinstance(b, dict) and "time_ms" in b
            ]

        # Legacy field: "duration_analyzed"
        normalized.setdefault("duration_analyzed", result.get("duration", 0))

        return normalized

    @staticmethod
    def _run_legacy_analysis(file_path: str) -> dict[str, Any]:
        """
        Legacy fallback when analysis_engine is not available.
        Uses basic librosa for BPM detection.
        """
        if not LIBROSA_AVAILABLE:
            return {
                "bpm": 128.0,
                "key": "Unknown",
                "beatgrid": [],
                "error": "librosa not installed",
            }

        try:
            import warnings

            import librosa
            import numpy as np

            warnings.filterwarnings("ignore")

            file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
            duration = None
            if file_size_mb > 200:
                duration = 600.0

            y, sr = librosa.load(file_path, sr=44100, duration=duration, mono=True)

            # BPM
            onset_env = librosa.onset.onset_strength(y=y, sr=sr)
            tempo, beat_frames = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr)
            bpm = float(tempo[0] if isinstance(tempo, np.ndarray) else tempo)

            # Snap
            snapped = round(bpm)
            if abs(bpm - snapped) < 0.2:
                bpm = float(snapped)

            beat_times = librosa.frames_to_time(beat_frames, sr=sr)

            return {
                "bpm": round(bpm, 2),
                "key": "Unknown",
                "beatgrid": beat_times.tolist(),
                "duration_analyzed": librosa.get_duration(y=y, sr=sr),
                "status": "ok",
                "error": None,
            }

        except Exception as e:
            logger.error(f"Legacy analysis failed for '{file_path}': {e}")
            return {
                "bpm": 128.0,
                "key": "Unknown",
                "beatgrid": [],
                "error": str(e),
                "status": "error",
            }
