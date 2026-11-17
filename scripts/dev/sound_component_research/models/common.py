"""Shared helpers for the sc-bench measurement spike. Read-only towards user audio."""
import json
import os
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"
os.environ.setdefault("TORCH_HOME", str(CACHE / "torch"))
os.environ.setdefault("HF_HOME", str(CACHE / "hf"))
os.environ.setdefault("XDG_CACHE_HOME", str(CACHE / "xdg"))
os.environ.setdefault("NUMBA_CACHE_DIR", str(CACHE / "numba"))
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

import numpy as np
import psutil
import soundfile as sf

TRACKS_JSON = HERE.parent / "library-analysis" / "tracks.json"
TRACK_IDS = ["58442992", "53115918", "253093800", "58562002", "1353025", "177985252"]
SR = 44100


def load_tracks(ids=None):
    ids = ids or TRACK_IDS
    data = json.loads(TRACKS_JSON.read_text(encoding="utf-8"))
    by_id = {str(x["ID"]): x for x in data}
    return [by_id[i] for i in ids]


def label(t):
    return f"{t['Artist']} - {t['Title']}"[:60]


def load_audio(path, sr=SR):
    """-> float32 (2, n) at sr. soundfile only (AIFF/WAV/FLAC/MP3 via libsndfile)."""
    y, file_sr = sf.read(path, dtype="float32", always_2d=True)
    y = y.T
    if y.shape[0] == 1:
        y = np.repeat(y, 2, axis=0)
    elif y.shape[0] > 2:
        y = y[:2]
    if file_sr != sr:
        import soxr
        y = soxr.resample(y.T, file_sr, sr).T.astype(np.float32)
    return np.ascontiguousarray(y), file_sr


class PeakRSS:
    """Samples process RSS in a thread; .peak in MB."""

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
            r = self.p.memory_info().rss
            if r > self.peak:
                self.peak = r
            time.sleep(self.interval)

    def __exit__(self, *a):
        self._stop.set()
        self.t.join()
        r = self.p.memory_info().rss
        self.peak = max(self.peak, r)

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


def sys_load(interval=1.0):
    """System-wide CPU % (other benchmarks may run concurrently)."""
    return psutil.cpu_percent(interval=interval)


def get_demucs(name="htdemucs"):
    """Load via the demucs package's legacy remote repo = dl.fbaipublicfiles.com (sha256-checked)."""
    from demucs import pretrained
    models = pretrained._parse_remote_files(pretrained.REMOTE_ROOT / "files.txt")
    model_repo = pretrained.RemoteRepo(models)
    bag_repo = pretrained.BagOnlyRepo(pretrained.REMOTE_ROOT, model_repo)
    model = pretrained.AnyModelRepo(model_repo, bag_repo).get_model(name)
    model.eval()
    return model


def separate(model, wav_np, device, shifts=1, overlap=0.25, segment=None):
    """wav_np float32 (2,n) @44.1k -> dict stem -> np float32 (2,n). In memory only."""
    import torch
    from demucs.apply import apply_model
    wav = torch.from_numpy(wav_np)
    ref = wav.mean(0)
    mean, std = ref.mean(), ref.std() + 1e-8
    wav = (wav - mean) / std
    with torch.no_grad():
        out = apply_model(model, wav[None], shifts=shifts, split=True, overlap=overlap,
                          segment=segment, device=device, progress=False)[0]
    if str(device).startswith("cuda"):
        torch.cuda.synchronize()
    out = out * std + mean
    return {s: out[i].numpy() for i, s in enumerate(model.sources)}


def emit(path, rec):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(json.dumps(rec, ensure_ascii=False), flush=True)
