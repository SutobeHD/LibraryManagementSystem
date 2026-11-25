"""torchcrepe (tiny/full) on the `other` stem, 30 s window, GPU vs CPU. Stems in memory only."""
import argparse
import time

import common
from common import emit

import numpy as np
import soxr
import torch
import torchcrepe

ap = argparse.ArgumentParser()
ap.add_argument("--out", default="results_pitch.jsonl")
ap.add_argument("--tracks", default="all")
a = ap.parse_args()
SR, PSR, HOP = common.SR, 16000, 160


def run(audio16, model, device, decoder):
    x = torch.from_numpy(audio16)[None]
    if device == "cuda":
        torch.cuda.reset_peak_memory_stats()
    w0, c0 = time.perf_counter(), time.process_time()
    f0, per = torchcrepe.predict(x, PSR, HOP, 50.0, 2006.0, model, decoder=decoder,
                                 return_periodicity=True, batch_size=1024, device=device)
    if device == "cuda":
        torch.cuda.synchronize()
    wall, cpu = time.perf_counter() - w0, time.process_time() - c0
    per = torchcrepe.filter.median(per, 3)
    per = torchcrepe.threshold.Silence(-60.0)(per, x, PSR, HOP)
    per, f0 = per[0].cpu().numpy(), f0[0].cpu().numpy()
    v = per > 0.21
    return dict(wall=round(wall, 2), cpu=round(cpu, 2), frames=int(len(f0)),
                voiced_021=round(float(v.mean()), 3), voiced_05=round(float((per > 0.5).mean()), 3),
                f0_med=round(float(np.median(f0[v])), 1) if v.any() else None,
                vram_mb=round(torch.cuda.max_memory_allocated() / 2**20) if device == "cuda" else None)


dm = common.get_demucs("htdemucs").to("cuda")
noise = (np.random.randn(PSR * 2) * 0.1).astype(np.float32)
for m in ("tiny", "full"):          # warm-up: weights load + cudnn + numba (viterbi)
    for d in ("cuda", "cpu"):
        t0 = time.perf_counter()
        run(noise, m, d, torchcrepe.decode.viterbi)
        emit(a.out, dict(kind="crepe_warmup", model=m, device=d, wall=round(time.perf_counter() - t0, 2)))

ids = None if a.tracks == "all" else a.tracks.split(",")
for tr in common.load_tracks(ids):
    wav, _ = common.load_audio(tr["path"])
    stems = common.separate(dm, wav, "cuda", shifts=1, overlap=0.25)
    other = stems["other"].mean(0)
    del stems
    e = np.add.reduceat(other ** 2, np.arange(0, len(other), SR))
    t0 = int(np.argmax(np.convolve(e, np.ones(30), "valid")))
    y16 = soxr.resample(other[t0 * SR:(t0 + 30) * SR], SR, PSR).astype(np.float32)
    rec = dict(kind="crepe", id=tr["ID"], track=common.label(tr), win_start_s=t0, sysload_before=common.sys_load(0.5),
               torch_threads=torch.get_num_threads())
    for m in ("tiny", "full"):
        for d in ("cuda", "cpu"):
            rec[f"{m}_{d}_viterbi"] = run(y16, m, d, torchcrepe.decode.viterbi)
        rec[f"{m}_cuda_wargmax"] = run(y16, m, "cuda", torchcrepe.decode.weighted_argmax)
    emit(a.out, rec)
