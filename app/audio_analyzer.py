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

import os
import logging
from concurrent.futures import ProcessPoolExecutor, Future
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Check if analysis libraries are available
LIBROSA_AVAILABLE = False
try:
    import librosa
    import numpy as np
    LIBROSA_AVAILABLE = True
except ImportError:
    logger.warning("librosa not found. Audio analysis will use mock fallback.")

# Import the production engine (lazy -- won't load heavy libs until needed)
try:
    from .analysis_engine import AnalysisEngine, run_full_analysis, _ensure_libs
    _ENGINE_AVAILABLE = True
except ImportError:
    _ENGINE_AVAILABLE = False
    logger.warning("analysis_engine not available. Using legacy analyzer.")


class AudioAnalyzer:
    """
    Background worker pool for audio analysis.

    Delegates to AnalysisEngine (v2.0) for high-accuracy results.
    The `mode` parameter is kept for backward compatibility:
      - "accuracy" (default): Full analysis via AnalysisEngine
      - "speed": Lighter analysis (still uses AnalysisEngine but with duration cap)
    """

    _executor: Optional[ProcessPoolExecutor] = None
    _tasks: Dict[str, Future] = {}

    @classmethod
    def get_executor(cls):
        if cls._executor is None:
            cores = max(1, os.cpu_count() - 1) if os.cpu_count() else 2
            cls._executor = ProcessPoolExecutor(max_workers=cores)
        return cls._executor

    @classmethod
    def shutdown(cls):
        if cls._executor:
            cls._executor.shutdown(wait=False)
            cls._executor = None

    @classmethod
    def analyze_track(cls, task_id: str, file_path: str, mode: str = "accuracy") -> Dict[str, Any]:
        """Submit an analysis job to the worker pool."""
        executor = cls.get_executor()

        if _ENGINE_AVAILABLE:
            # Use the production engine
            duration_cap = 120.0 if mode == "speed" else None
            future = executor.submit(run_full_analysis, file_path, duration_cap)
        else:
            # Legacy fallback
            future = executor.submit(cls._run_legacy_analysis, file_path, mode)

        cls._tasks[task_id] = future
        return {"task_id": task_id, "status": "processing"}

    @classmethod
    def get_status(cls, task_id: str) -> Dict[str, Any]:
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
    def analyze_sync(cls, file_path: str, mode: str = "accuracy") -> Dict[str, Any]:
        """Synchronous analysis. Blocks until done."""
        if _ENGINE_AVAILABLE:
            duration_cap = 120.0 if mode == "speed" else None
            result = run_full_analysis(file_path, duration_cap)
            return cls._normalize_result(result)
        return cls._run_legacy_analysis(file_path, mode)

    @classmethod
    def capabilities(cls) -> Dict[str, Any]:
        """Report which analysis backends are available."""
        if _ENGINE_AVAILABLE:
            return AnalysisEngine.capabilities()
        return {
            "core": LIBROSA_AVAILABLE,
            "madmom": False,
            "essentia": False,
            "beat_method": "librosa basic" if LIBROSA_AVAILABLE else "none",
            "key_method": "none",
        }

    @staticmethod
    def _normalize_result(result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Ensure the result dict is compatible with existing API consumers.
        Maps the new AnalysisEngine output back to the legacy format expected
        by the frontend.
        """
        if not result:
            return result

        # The new engine already provides all fields. Add legacy aliases:
        normalized = dict(result)

        # Legacy field: "beatgrid" (list of times in seconds)
        if "beats" in result and "beatgrid" not in result:
            normalized["beatgrid"] = [
                b["time_ms"] / 1000.0 for b in result["beats"]
            ]

        # Legacy field: "mode"
        normalized.setdefault("mode", "accuracy")

        # Legacy field: "duration_analyzed"
        normalized.setdefault("duration_analyzed", result.get("duration", 0))

        return normalized

    @staticmethod
    def _run_legacy_analysis(file_path: str, mode: str) -> Dict[str, Any]:
        """
        Legacy fallback when analysis_engine is not available.
        Uses basic librosa for BPM detection.
        """
        if not LIBROSA_AVAILABLE:
            return {
                "bpm": 128.0, "key": "Unknown", "beatgrid": [],
                "mode": mode, "error": "librosa not installed"
            }

        try:
            import warnings
            warnings.filterwarnings('ignore')

            file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
            duration = None
            if file_size_mb > 200:
                duration = 600.0

            y, sr = librosa.load(file_path, sr=44100, duration=duration, mono=True)

            # BPM
            onset_env = librosa.onset.onset_strength(y=y, sr=sr)
            tempo, beat_frames = librosa.beat.beat_track(
                onset_envelope=onset_env, sr=sr
            )
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
                "mode": mode,
                "duration_analyzed": librosa.get_duration(y=y, sr=sr),
                "status": "ok",
                "error": None,
            }

        except Exception as e:
            logger.error(f"Legacy analysis failed for '{file_path}': {e}")
            return {
                "bpm": 128.0, "key": "Unknown", "beatgrid": [],
                "mode": mode, "error": str(e), "status": "error"
            }
