"""Decode cost through an ffmpeg subprocess (what the app would use for m4a): whole track vs one
span vs one call per M block. Wall time only (the decoder runs in the child process).

Usage: bench_decode.py <data dir>   (needs <data dir>/fresh_sample.json and run*/sect_shard*.jsonl)
Audio is opened read-only; output goes to a pipe, nothing is written."""
import glob
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

DATA = Path(sys.argv[1])
SAMPLE = {t["id"]: t for t in json.load(open(DATA / "fresh_sample.json", encoding="utf-8"))["tracks"]}
ROWS = {}
for f in sorted(glob.glob(str(DATA / "run*" / "sect_shard*.jsonl"))):
    for line in open(f, encoding="utf-8"):
        r = json.loads(line)
        if r["status"] == "ok":
            ROWS[r["id"]] = r


def decode(path, start=None, length=None):
    """Returns (wall seconds, decoded seconds). s16le: some ffmpeg builds ship without pcm_f32le."""
    seek = ["-ss", f"{start:.3f}", "-t", f"{length:.3f}"] if start is not None else []
    cmd = ["ffmpeg", "-v", "error", "-nostdin", *seek, "-i", path, "-f", "s16le", "-ac", "1", "-ar", "44100", "pipe:1"]
    w0 = time.perf_counter()
    p = subprocess.run(cmd, capture_output=True, timeout=60)
    return time.perf_counter() - w0, len(p.stdout) / 2 / 44100


w0 = time.perf_counter()
subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=30)
print(f"ffmpeg process start {time.perf_counter() - w0:.2f} s")
for ext in ("m4a", "mp3", "aiff"):
    out = []
    for tid in [i for i, r in sorted(ROWS.items()) if r["ext"] == ext][:6]:
        r, path = ROWS[tid], SAMPLE[tid]["path"]
        w_full, d_full = decode(path)
        span, n_bl, aud = r["M"]["span_s"], r["M"]["n_blocks"], r["M"]["audio_s"]
        w_bl = d_bl = 0.0
        for k in range(n_bl):  # same count and total length as the M blocks, spread over the span
            w, d = decode(path, 30.0 + k * (span - aud / n_bl) / max(1, n_bl - 1), aud / n_bl)
            w_bl += w
            d_bl += d
        w_span, d_span = decode(path, 30.0, span)
        out.append((w_full, w_span, w_bl, n_bl, d_full, d_span, d_bl))
    a = np.array(out)
    print(f"ffmpeg {ext}: n={len(a)} whole wall {np.median(a[:, 0]):.2f} s ({np.median(a[:, 4]):.0f} s audio) | one span {np.median(a[:, 1]):.2f} "
          f"({np.median(a[:, 5]):.0f} s) | {np.median(a[:, 3]):.0f} calls with -ss {np.median(a[:, 2]):.2f} ({np.median(a[:, 6]):.0f} s)")
