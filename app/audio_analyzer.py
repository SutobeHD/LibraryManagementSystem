import os
import json
import logging
from concurrent.futures import ProcessPoolExecutor, Future
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Try to import librosa, but allow the app to run (without analysis) if missing
try:
    import librosa
    import numpy as np
    import warnings
    warnings.filterwarnings('ignore', category=UserWarning) # Suppress librosa warnings
    LIBROSA_AVAILABLE = True
except ImportError:
    LIBROSA_AVAILABLE = False
    logger.warning("Librosa not found. Audio analysis will be mocked.")


class AudioAnalyzer:
    """Background worker pool for high-accuracy audio analysis (BPM, Key, Beatgrid)."""
    
    _executor: Optional[ProcessPoolExecutor] = None
    _tasks: Dict[str, Future] = {}

    @classmethod
    def get_executor(cls):
        if cls._executor is None:
            # Reserve 1 core for the OS to prevent freezing
            cores = max(1, os.cpu_count() - 1) if os.cpu_count() else 2
            cls._executor = ProcessPoolExecutor(max_workers=cores)
        return cls._executor

    @classmethod
    def shutdown(cls):
        if cls._executor:
            cls._executor.shutdown(wait=False)
            cls._executor = None

    @classmethod
    def analyze_track(cls, task_id: str, file_path: str, mode: str = "speed") -> Dict[str, Any]:
        """Submit an analysis job to the worker pool."""
        executor = cls.get_executor()
        future = executor.submit(cls._run_analysis, file_path, mode)
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
                return {"status": "done", "result": result}
            except Exception as e:
                logger.error(f"Analysis task {task_id} failed: {e}")
                return {"status": "error", "error": str(e)}
        else:
            return {"status": "processing"}

    @staticmethod
    def _run_analysis(file_path: str, mode: str) -> Dict[str, Any]:
        """The actual heavy lifting. Runs in a separate process."""
        if not LIBROSA_AVAILABLE:
            # Fallback mock for testing if librosa is missing
            return {
                "bpm": 128.0,
                "key": "Am",
                "beatgrid": [0.5, 1.0, 1.5, 2.0], # Mock grid in seconds
                "mode": mode,
                "error": "Librosa not installed"
            }

        try:
            # 1. Load Audio
            # Accuracy: Load full track, native sample rate
            # Speed: Load first 60 seconds, resample to 22050Hz for speed
            sr = 22050 if mode == "speed" else 44100
            duration = 60.0 if mode == "speed" else None
            
            y, sr = librosa.load(file_path, sr=sr, duration=duration, mono=True)

            # 2. Extract BPM and Beats
            if mode == "accuracy":
                # Use Harmonic/Percussive separation for highly accurate beats
                y_harmonic, y_percussive = librosa.effects.hpss(y)
                onset_env = librosa.onset.onset_strength(y=y_percussive, sr=sr)
            else:
                onset_env = librosa.onset.onset_strength(y=y, sr=sr)
            
            # Use dynamic programming beat tracker
            tempo, beat_frames = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr)
            bpm = float(tempo[0] if isinstance(tempo, np.ndarray) else tempo)
            
            # Snap BPM to nearest integer if it's very close (common in electronic music)
            snapped_bpm = round(bpm)
            if abs(bpm - snapped_bpm) < 0.2:
                bpm = float(snapped_bpm)

            # Convert beat frames to times (seconds)
            beat_times = librosa.frames_to_time(beat_frames, sr=sr)

            # 3. Extract Key (Accuracy only, as it's computationally expensive)
            key_str = ""
            if mode == "accuracy":
                chromagram = librosa.feature.chroma_stft(y=y_harmonic, sr=sr)
                mean_chroma = np.mean(chromagram, axis=1)
                
                # Simple major/minor profile correlation
                # Note: This is an estimation. A production app might use specialized models (like madmom)
                chroma_to_key = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
                estimated_pitch_idx = np.argmax(mean_chroma)
                key_str = chroma_to_key[estimated_pitch_idx]
                
                # Very rough major/minor guess based on 3rd/4th intervals would go here.
                # For brevity, defaulting to Major string.
                key_str += "M" 

            return {
                "bpm": round(bpm, 2),
                "key": key_str,
                "beatgrid": beat_times.tolist(),
                "mode": mode,
                "duration_analyzed": duration or librosa.get_duration(y=y, sr=sr)
            }
        except Exception as e:
            logger.error(f"Error in _run_analysis for {file_path}: {e}")
            raise e
