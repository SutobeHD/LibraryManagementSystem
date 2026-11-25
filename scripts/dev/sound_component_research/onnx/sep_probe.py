"""Separation on ONNX: parity vs torch references (SI-SDR) + speed. CPU or DirectML."""
import argparse

import numpy as np
import oc_common as c
import sep_min

ap = argparse.ArgumentParser()
ap.add_argument("--model", default="umx", choices=["umx", "htd"])
ap.add_argument("--provider", default="cpu")
ap.add_argument("--threads", type=int, default=0)
ap.add_argument("--tracks", default="all")
ap.add_argument("--no-parity", action="store_true")
ap.add_argument("--out", default="results_sep.jsonl")
a = ap.parse_args()

path = c.MODELS / ("umxhq_other.onnx" if a.model == "umx" else "htdemucs_core.onnx")
M0 = c.gpu_state()[1]
with c.Timer() as tl, c.PeakRSS() as rl:
    sess = c.session(path, a.provider, a.threads)
c.emit(a.out, dict(kind="sep_env", model=a.model, provider=a.provider, used=sess.get_providers(), threads=a.threads,
                   load_wall=round(tl.wall, 2), load_rss_mb=rl.mb, **c.env_info()))
warm = (np.random.RandomState(0).randn(2, sep_min.SEG) * 0.05).astype(np.float32)
if a.model == "umx":
    sep_min.umx_other(sess, warm)
else:
    sep_min.htd_segment(sess, warm)
ids = None if a.tracks == "all" else a.tracks.split(",")
for tid in (ids or c.TRACK_IDS):
    wav = np.load(c.WORK / f"mix44_{tid}.npy")
    dur = wav.shape[1] / c.SR
    gu = c.gpu_wait() if a.provider == "dml" else (None, None, 0)
    load = c.sys_load()
    with c.Timer() as t, c.PeakRSS() as r, c.VramPeak() as v:
        if a.model == "umx":
            other = sep_min.umx_other(sess, wav)
            stems = None
        else:
            stems, _ = sep_min.htdemucs(sess, wav)
            other = stems[2]
    rec = dict(kind="sep", model=a.model, provider=a.provider, threads=a.threads, id=tid, dur=round(dur, 1),
               wall=round(t.wall, 2), cpu=round(t.cpu, 1), xrt=round(dur / t.wall, 1),
               wall_per_5min=round(t.wall * 300 / dur, 2), cpu_per_5min=round(t.cpu * 300 / dur, 1), rss_mb=r.mb,
               vram_delta_mb=v.delta if a.provider == "dml" else None,
                       vram_vs_presession_mb=(v.peak - M0) if a.provider == "dml" else None, sysload_before=load,
               gpu_util_before=gu[0], gpu_mem_before=gu[1], gpu_waited_s=gu[2])
    if not a.no_parity:
        if a.model == "umx":
            rec["sisdr_vs_torch_other"] = round(c.si_sdr(np.load(c.WORK / f"ref_umx0_other_{tid}.npy"), other), 1)
        else:
            ref = np.load(c.WORK / f"ref_htd_{tid}.npy")
            for i, s in enumerate(sep_min.HTD_SOURCES):
                rec[f"sisdr_vs_torch_{s}"] = round(c.si_sdr(ref[i], stems[i]), 1)
            rec["maxabs_diff"] = float(np.abs(ref - stems).max())
    c.emit(a.out, rec)
