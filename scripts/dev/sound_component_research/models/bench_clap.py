"""LAION-CLAP via transformers: embedding throughput + zero-shot sanity (mix vs `other` stem)."""
import argparse
import time

import common
from common import PeakRSS, Timer, emit

import numpy as np
import soxr
import torch
from transformers import ClapModel, ClapProcessor

ap = argparse.ArgumentParser()
ap.add_argument("--model", default="laion/larger_clap_music")
ap.add_argument("--device", default="cuda")
ap.add_argument("--phase", default="timing")
ap.add_argument("--batch", type=int, default=16)
ap.add_argument("--threads", type=int, default=0)
ap.add_argument("--out", default="results_clap.jsonl")
a = ap.parse_args()
if a.threads:
    torch.set_num_threads(a.threads)
dev = a.device
PROMPTS = ["bell", "cowbell", "hi-hat", "acid bassline", "vocal", "pad"]
CSR, WIN = 48000, 480000


def windows(y44_mono):
    y = soxr.resample(y44_mono, common.SR, CSR).astype(np.float32)
    return [y[i:i + WIN] for i in range(0, len(y), WIN) if len(y[i:i + WIN]) >= CSR]  # drop tail < 1 s


def embed(model, proc, wins, batch):
    t_fe = t_fw = 0.0
    out = []
    for i in range(0, len(wins), batch):
        t0 = time.perf_counter()
        inp = proc(audio=wins[i:i + batch], sampling_rate=CSR, return_tensors="pt")
        t1 = time.perf_counter()
        inp = {k: v.to(dev) for k, v in inp.items()}
        with torch.inference_mode():
            o = model.get_audio_features(**inp)
        e = o if isinstance(o, torch.Tensor) else o.pooler_output
        if dev == "cuda":
            torch.cuda.synchronize()
        out.append(e.float().cpu())
        t_fe += t1 - t0
        t_fw += time.perf_counter() - t1
    return torch.cat(out), t_fe, t_fw


with Timer() as t, PeakRSS() as r:
    proc = ClapProcessor.from_pretrained(a.model)
    model = ClapModel.from_pretrained(a.model).eval().to(dev)
fe = proc.feature_extractor
emit(a.out, dict(kind="clap_load", model=a.model, device=dev, wall=round(t.wall, 2), rss_mb=r.mb,
                 params_m=round(sum(p.numel() for p in model.parameters()) / 1e6, 1),
                 fe_truncation=fe.truncation, fe_padding=fe.padding, fe_sr=fe.sampling_rate,
                 torch_threads=torch.get_num_threads()))

if a.phase == "timing":
    tr = common.load_tracks(["58442992"])[0]
    wav, _ = common.load_audio(tr["path"])
    with Timer() as trs:
        wins = windows(wav.mean(0))
    embed(model, proc, wins[:2], 2)  # warm-up
    if dev == "cuda":
        torch.cuda.reset_peak_memory_stats()
    load_before = common.sys_load(0.5)
    with Timer() as t, PeakRSS() as r:
        e, t_fe, t_fw = embed(model, proc, wins, a.batch)
    n = len(wins)
    emit(a.out, dict(kind="clap_timing", model=a.model, device=dev, batch=a.batch, id=tr["ID"],
                     dur=round(wav.shape[1] / common.SR, 1), n_windows=n, dim=int(e.shape[1]),
                     resample_s=round(trs.wall, 2), featex_s=round(t_fe, 2), forward_s=round(t_fw, 2),
                     wall=round(t.wall, 2), cpu=round(t.cpu, 2),
                     win_per_s_forward=round(n / t_fw, 1), win_per_s_total=round(n / (t.wall + trs.wall), 1),
                     vram_mb=round(torch.cuda.max_memory_allocated() / 2**20) if dev == "cuda" else None,
                     rss_mb=r.mb, torch_threads=torch.get_num_threads(), sysload_before=load_before))
else:
    tok = proc(text=PROMPTS, return_tensors="pt", padding=True)
    tok = {k: v.to(dev) for k, v in tok.items()}
    with torch.inference_mode():
        o = model.get_text_features(**tok)
    te = (o if isinstance(o, torch.Tensor) else o.pooler_output).float().cpu()
    te = te / te.norm(dim=-1, keepdim=True)
    scale = float(model.logit_scale_a.exp())
    dm = common.get_demucs("htdemucs").to("cuda")
    for tr in common.load_tracks():
        wav, _ = common.load_audio(tr["path"])
        stems = common.separate(dm, wav, "cuda", shifts=1, overlap=0.25)
        rec = dict(kind="clap_zeroshot", model=a.model, id=tr["ID"], track=common.label(tr), logit_scale=round(scale, 1))
        for name, sig in (("mix", wav.mean(0)), ("other", stems["other"].mean(0))):
            e, _, _ = embed(model, proc, windows(sig), a.batch)
            e = e / e.norm(dim=-1, keepdim=True)
            sim = e @ te.T                                  # (windows, prompts) cosine
            prob = torch.softmax(sim * scale, dim=-1)
            top1 = torch.bincount(sim.argmax(-1), minlength=len(PROMPTS)).float() / len(sim)
            rec[name] = {p: dict(cos=round(float(sim[:, j].mean()), 3), cos_max=round(float(sim[:, j].max()), 3),
                                 p=round(float(prob[:, j].mean()), 3), top1=round(float(top1[j]), 2))
                         for j, p in enumerate(PROMPTS)}
        emit(a.out, rec)
        del stems
