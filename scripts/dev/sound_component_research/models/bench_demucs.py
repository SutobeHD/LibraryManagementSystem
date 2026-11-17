"""Demucs separation timing. Stems stay in memory and are discarded."""
import argparse
import gc
import time

import common
from common import PeakRSS, Timer, emit

import numpy as np
import torch

CONFIGS = {
    "A": dict(shifts=1, overlap=0.25, segment=None),   # demucs CLI default (segment 7.8 s)
    "B": dict(shifts=0, overlap=0.10, segment=None),
    "C": dict(shifts=0, overlap=0.10, segment=4.0),    # reduced segment
}

ap = argparse.ArgumentParser()
ap.add_argument("--device", default="cuda")
ap.add_argument("--model", default="htdemucs")
ap.add_argument("--configs", default="A,B,C")
ap.add_argument("--tracks", default="all")
ap.add_argument("--threads", type=int, default=0)
ap.add_argument("--out", default="results_demucs.jsonl")
ap.add_argument("--tag", default="")
a = ap.parse_args()

if a.threads:
    torch.set_num_threads(a.threads)
ids = None if a.tracks == "all" else a.tracks.split(",")
tracks = common.load_tracks(ids)
dev = a.device

with Timer() as t, PeakRSS() as r:
    model = common.get_demucs(a.model)
    if dev == "cuda":
        model.to("cuda")
emit(a.out, dict(kind="model_load", model=a.model, device=dev, wall=round(t.wall, 2), cpu=round(t.cpu, 2),
                 rss_mb=r.mb, sources=list(model.sources), torch_threads=torch.get_num_threads(),
                 segment=float(model.models[0].segment), tag=a.tag))

if dev == "cuda":
    torch.cuda.reset_peak_memory_stats()
    with Timer() as t:
        common.separate(model, (np.random.randn(2, 44100 * 10) * 0.1).astype(np.float32), dev)
    emit(a.out, dict(kind="warmup_10s", device=dev, wall=round(t.wall, 2), cpu=round(t.cpu, 2),
                     vram_mb=round(torch.cuda.max_memory_allocated() / 2**20), tag=a.tag))

for tr in tracks:
    with Timer() as tl:
        wav, fsr = common.load_audio(tr["path"])
    dur = wav.shape[1] / common.SR
    for c in a.configs.split(","):
        cfg = CONFIGS[c]
        gc.collect()
        load_before = common.sys_load(0.5)
        if dev == "cuda":
            torch.cuda.empty_cache()
            torch.cuda.reset_peak_memory_stats()
        with Timer() as t, PeakRSS() as r:
            stems = common.separate(model, wav, dev, **cfg)
        rec = dict(kind="separate", model=a.model, device=dev, cfg=c, **{k: v for k, v in cfg.items()},
                   id=tr["ID"], track=common.label(tr), ext=tr["path"].rsplit(".", 1)[-1], file_sr=fsr,
                   dur=round(dur, 1), decode_s=round(tl.wall, 2), wall=round(t.wall, 2), cpu=round(t.cpu, 2),
                   xrt=round(dur / t.wall, 1), rss_mb=r.mb,
                   vram_mb=round(torch.cuda.max_memory_allocated() / 2**20) if dev == "cuda" else None,
                   vram_reserved_mb=round(torch.cuda.max_memory_reserved() / 2**20) if dev == "cuda" else None,
                   torch_threads=torch.get_num_threads(), sysload_before=load_before, tag=a.tag)
        emit(a.out, rec)
        del stems
