"""Probe 6 timing: htdemucs on the whole track vs on 4 x 30 s windows (GPU, shifts 0, overlap 0.1).
Stems stay in memory. Output: timing.json."""

import json
import time

import mcommon as M
import numpy as np
import soundfile as sf
import torch

N_TRACKS = 8
S = M.load_samples()
META = M.load_meta()
ids = [i for i in S["sets"]["distract"] if S["tracks"][i]["ext"] in M.SF_EXT and 240 <= S["tracks"][i]["dur"] <= 420][:N_TRACKS]

M.gpu_lock_acquire("melody-timing")
dm = M.get_demucs("htdemucs").to("cuda")
M.separate_batch(dm, (np.random.randn(1, 2, M.SR * 10) * 0.1).astype(np.float32))
rows = []
try:
    for tid in ids:
        tr = S["tracks"][tid]
        path = META[tid]["path"]
        t0 = time.perf_counter()
        y, fsr = sf.read(path, dtype="float32", always_2d=True)
        y = np.ascontiguousarray(y.T[:2])
        if y.shape[0] == 1:
            y = np.repeat(y, 2, axis=0)
        if fsr != M.SR:
            import soxr

            y = soxr.resample(y.T, fsr, M.SR).T.astype(np.float32)
        t1 = time.perf_counter()
        torch.cuda.reset_peak_memory_stats()
        full = M.separate_batch(dm, y[None])
        t2 = time.perf_counter()
        vram_full = torch.cuda.max_memory_allocated() / 2**20
        del full
        t3 = time.perf_counter()
        wav = np.stack([M.read_window(path, s) for s in tr["wins"]])
        t4 = time.perf_counter()
        torch.cuda.reset_peak_memory_stats()
        win = M.separate_batch(dm, wav)
        t5 = time.perf_counter()
        vram_win = torch.cuda.max_memory_allocated() / 2**20
        del win
        rows.append({"id": tid, "dur": round(y.shape[1] / M.SR, 1), "decode_full": round(t1 - t0, 3), "sep_full": round(t2 - t1, 3),
                     "decode_win": round(t4 - t3, 3), "sep_win": round(t5 - t4, 3), "vram_full_mb": round(vram_full),
                     "vram_win_mb": round(vram_win)})
        print(rows[-1], flush=True)
finally:
    M.gpu_lock_release()
med = {k: float(np.median([r[k] for r in rows])) for k in rows[0] if k != "id"}
med["saving_sep"] = round(med["sep_full"] / med["sep_win"], 2)
med["saving_total"] = round((med["sep_full"] + med["decode_full"]) / (med["sep_win"] + med["decode_win"]), 2)
print("median", med)
(M.OUT / "timing.json").write_text(json.dumps({"rows": rows, "median": med}, indent=1), encoding="utf-8")
