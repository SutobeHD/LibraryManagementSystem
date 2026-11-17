"""Shared helpers for the ONNX probe (B0-1). Read-only towards user audio.

Run every script with cwd = the probe root (tmp/sc-onnx). Track paths come from
../library-analysis/tracks.json (gitignored); nothing here names a library path.
"""
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(os.environ.get("SC_ONNX_ROOT", Path.cwd()))
MODELS = ROOT / "models"
WORK = ROOT / "work"
WORK.mkdir(exist_ok=True)
os.environ.setdefault("NUMBA_CACHE_DIR", str(ROOT / "cache" / "numba"))

import numpy as np
import psutil
import soundfile as sf

TRACKS_JSON = ROOT.parent / "library-analysis" / "tracks.json"
TRACK_IDS = ["58442992", "53115918", "253093800", "58562002", "1353025", "177985252"]
SR = 44100


def load_tracks(ids=None):
    data = json.loads(TRACKS_JSON.read_text(encoding="utf-8"))
    by_id = {str(x["ID"]): x for x in data}
    return [by_id[i] for i in (ids or TRACK_IDS)]


def load_audio(path, sr=SR):
    """-> float32 (2, n) at sr."""
    y, file_sr = sf.read(path, dtype="float32", always_2d=True)
    y = y.T
    if y.shape[0] == 1:
        y = np.repeat(y, 2, axis=0)
    elif y.shape[0] > 2:
        y = y[:2]
    if file_sr != sr:
        import soxr
        y = soxr.resample(y.T, file_sr, sr).T.astype(np.float32)
    return np.ascontiguousarray(y)


class PeakRSS:
    def __init__(self, interval=0.05):
        self.p = psutil.Process()
        self.interval = interval
        self.peak = 0
        self._stop = threading.Event()

    def __enter__(self):
        self.peak = self.p.memory_info().rss
        self._stop.clear()
        self.t = threading.Thread(target=self._run, daemon=True)
        self.t.start()
        return self

    def _run(self):
        while not self._stop.is_set():
            self.peak = max(self.peak, self.p.memory_info().rss)
            time.sleep(self.interval)

    def __exit__(self, *a):
        self._stop.set()
        self.t.join()
        self.peak = max(self.peak, self.p.memory_info().rss)

    @property
    def mb(self):
        return round(self.peak / 2**20)


class Timer:
    def __enter__(self):
        self.w0 = time.perf_counter()
        self.c0 = time.process_time()
        return self

    def __exit__(self, *a):
        self.wall = time.perf_counter() - self.w0
        self.cpu = time.process_time() - self.c0


def sys_load(interval=0.5):
    """System-wide CPU % (other agents run benchmarks concurrently) - recorded next to every timing."""
    return psutil.cpu_percent(interval=interval)


def gpu_state():
    """-> (util %, MiB used) from nvidia-smi, or (None, None)."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10).stdout.strip().splitlines()[0]
        u, m = (int(x) for x in out.split(","))
        return u, m
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return None, None


def gpu_wait(limit=15, max_wait=300):
    """Poll until GPU utilisation < limit (another agent shares the GPU). -> (util, MiB, waited_s)."""
    t0 = time.time()
    while True:
        u, m = gpu_state()
        if u is None or u < limit or time.time() - t0 > max_wait:
            return u, m, round(time.time() - t0)
        time.sleep(5)


class VramPeak:
    """Samples nvidia-smi used memory (whole GPU, MiB) in a thread; .delta = peak - baseline."""

    def __init__(self, interval=0.25):
        self.interval = interval
        self._stop = threading.Event()

    def __enter__(self):
        self.base = gpu_state()[1] or 0
        self.peak = self.base
        self.t = threading.Thread(target=self._run, daemon=True)
        self.t.start()
        return self

    def _run(self):
        while not self._stop.is_set():
            self.peak = max(self.peak, gpu_state()[1] or 0)
            time.sleep(self.interval)

    def __exit__(self, *a):
        self._stop.set()
        self.t.join()

    @property
    def delta(self):
        return self.peak - self.base


def session(path, provider="cpu", threads=0, free_dims=None):
    """onnxruntime session. provider: cpu | dml."""
    import onnxruntime as ort
    so = ort.SessionOptions()
    if threads:
        so.intra_op_num_threads = threads
    for k, v in (free_dims or {}).items():
        so.add_free_dimension_override_by_name(k, v)
    if provider == "dml":
        so.enable_mem_pattern = False
        so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        prov = ["DmlExecutionProvider", "CPUExecutionProvider"]
    else:
        prov = ["CPUExecutionProvider"]
    return ort.InferenceSession(str(path), so, providers=prov)


def env_info():
    import onnxruntime as ort
    return dict(numpy=np.__version__, onnxruntime=ort.__version__, providers=ort.get_available_providers(),
                python=sys.version.split()[0])


def emit(path, rec):
    with open(ROOT / path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(json.dumps(rec, ensure_ascii=False), flush=True)


def si_sdr(ref, est):
    """Scale-invariant SDR in dB over flattened arrays."""
    ref = ref.astype(np.float64).ravel()
    est = est.astype(np.float64).ravel()
    a = np.dot(est, ref) / (np.dot(ref, ref) + 1e-12)
    t = a * ref
    return float(10 * np.log10((np.dot(t, t) + 1e-12) / (np.dot(est - t, est - t) + 1e-12)))
