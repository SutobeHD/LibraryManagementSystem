"""Shared helpers for the melody probes (torch env `tmp/sc-bench/venv`). Read-only towards user
audio; stems and decoded audio live in memory only."""

import atexit
import json
import os
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3] if "scripts" in HERE.parts else HERE.parents[1]
OUT = ROOT / "tmp" / "sc-rework-m"
CACHE = ROOT / "tmp" / "sc-bench" / "cache"
os.environ.setdefault("TORCH_HOME", str(CACHE / "torch"))
os.environ.setdefault("HF_HOME", str(CACHE / "hf"))
os.environ.setdefault("XDG_CACHE_HOME", str(CACHE / "xdg"))
os.environ.setdefault("NUMBA_CACHE_DIR", str(CACHE / "numba"))
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402
import soxr  # noqa: E402

SR = 44100
WIN_S = 30.0
GPU_LOCK = ROOT / "tmp" / "gpu.lock"
SF_EXT = ("aiff", "aif", "wav", "flac")


def load_meta():
    """ids -> {path, ...} from the library snapshot (paths never leave this process)."""
    data = json.loads((ROOT / "tmp/library-analysis/tracks.json").read_text(encoding="utf-8"))
    return {t["ID"]: t for t in data}


def load_samples():
    return json.loads((OUT / "samples.json").read_text(encoding="utf-8"))


def load_notes():
    """All extraction records with notes (every notes*.jsonl part file)."""
    for f in sorted(OUT.glob("notes*.jsonl")):
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                if line.strip().endswith("}"):
                    r = json.loads(line)
                    if "notes" in r:
                        yield r


def read_window(path, start, length=WIN_S):
    """-> float32 (2, n) at 44.1 kHz, n = length * SR (zero-padded). File opened read-only."""
    n = int(round(length * SR))
    ext = path.rsplit(".", 1)[-1].lower()
    if ext in SF_EXT:
        with sf.SoundFile(path) as f:
            fsr = f.samplerate
            f.seek(min(int(round(start * fsr)), f.frames))
            y = f.read(int(round(length * fsr)), dtype="float32", always_2d=True).T
        if y.shape[0] == 1:
            y = np.repeat(y, 2, axis=0)
        y = y[:2]
        if fsr != SR:
            y = soxr.resample(y.T, fsr, SR).T.astype(np.float32)
    else:
        cmd = ["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{start:.4f}", "-t", f"{length:.4f}", "-i", path,
               "-f", "s16le", "-acodec", "pcm_s16le", "-ac", "2", "-ar", str(SR), "pipe:1"]
        res = subprocess.run(cmd, capture_output=True, timeout=60)
        if res.returncode != 0 or not res.stdout:
            raise RuntimeError("ffmpeg decode failed: " + res.stderr.decode("utf-8", "replace").strip().splitlines()[-1][:80])
        y = (np.frombuffer(res.stdout, dtype="<i2").reshape(-1, 2).T / 32768.0).astype(np.float32)
    out = np.zeros((2, n), dtype=np.float32)
    m = min(n, y.shape[1])
    out[:, :m] = y[:, :m]
    return out


def gpu_lock_acquire(tag, wait_s=900):
    """tmp/gpu.lock = 'a GPU batch is running'. Waits while another owner holds it."""
    t0 = time.time()
    while GPU_LOCK.exists() and time.time() - t0 < wait_s:
        time.sleep(5)
    GPU_LOCK.write_text(f"{tag} pid={os.getpid()} since={time.strftime('%H:%M:%S')}\n", encoding="utf-8")
    atexit.register(gpu_lock_release)


def gpu_lock_release():
    try:
        if GPU_LOCK.exists() and f"pid={os.getpid()}" in GPU_LOCK.read_text(encoding="utf-8"):
            GPU_LOCK.unlink()
    except OSError:
        pass


def get_demucs(name="htdemucs"):
    from demucs import pretrained

    models = pretrained._parse_remote_files(pretrained.REMOTE_ROOT / "files.txt")
    model_repo = pretrained.RemoteRepo(models)
    bag_repo = pretrained.BagOnlyRepo(pretrained.REMOTE_ROOT, model_repo)
    model = pretrained.AnyModelRepo(model_repo, bag_repo).get_model(name)
    model.eval()
    return model


def separate_batch(model, wav_np, device="cuda"):
    """wav_np float32 (B, 2, n) -> float32 (B, stems, 2, n); shifts 0, overlap 0.1. Memory only."""
    import torch
    from demucs.apply import apply_model

    wav = torch.from_numpy(wav_np)
    ref = wav.mean(1)
    mean = ref.mean(-1)[:, None, None]
    std = ref.std(-1)[:, None, None] + 1e-8
    with torch.no_grad():
        out = apply_model(model, (wav - mean) / std, shifts=0, split=True, overlap=0.1, device=device, progress=False)
    if str(device).startswith("cuda"):
        torch.cuda.synchronize()
    return (out * std[:, None] + mean[:, None]).numpy()
