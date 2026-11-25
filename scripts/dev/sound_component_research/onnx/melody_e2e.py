"""End-to-end melody path on onnxruntime only: separation (`other`) -> basic-pitch on 4 x 30 s windows.
Decode is excluded (mixes are pre-decoded npy). CPU or DirectML."""
import argparse
import json

import numpy as np
import soxr
import oc_common as c
import bp_min
import sep_min

ap = argparse.ArgumentParser()
ap.add_argument("--sep", default="umx", choices=["umx", "htd"])
ap.add_argument("--scope", default="full", choices=["full", "windows"], help="htd only: separate just the segments the 4 windows touch")
ap.add_argument("--provider", default="cpu")
ap.add_argument("--threads", type=int, default=0)
ap.add_argument("--tracks", default="all")
ap.add_argument("--out", default="results_e2e.jsonl")
a = ap.parse_args()
FRACS = (0.2, 0.4, 0.6, 0.8)

M0 = c.gpu_state()[1]
with c.PeakRSS() as rtot:
    sep = c.session(c.MODELS / ("umxhq_other.onnx" if a.sep == "umx" else "htdemucs_core.onnx"), a.provider, a.threads)
    bp = c.session(c.MODELS / "nmp.onnx", a.provider, a.threads)
    warm = (np.random.RandomState(0).randn(2, sep_min.SEG) * 0.05).astype(np.float32)
    (sep_min.umx_other if a.sep == "umx" else sep_min.htd_segment)(sep, warm)
    bp_min.predict(bp, warm[0, :88200])
    c.emit(a.out, dict(kind="e2e_env", sep=a.sep, scope=a.scope, provider=a.provider, threads=a.threads,
                       used=sep.get_providers(), **c.env_info()))
    for tid in (c.TRACK_IDS if a.tracks == "all" else a.tracks.split(",")):
        wav = np.load(c.WORK / f"mix44_{tid}.npy")
        n = wav.shape[1]
        spans = [(max(0, int(f * n) - 15 * c.SR), max(0, int(f * n) - 15 * c.SR) + 30 * c.SR) for f in FRACS]
        gu = c.gpu_wait() if a.provider == "dml" else (None, None, 0)
        load = c.sys_load()
        with c.PeakRSS() as r, c.VramPeak() as v:
            with c.Timer() as ts:
                if a.sep == "umx":
                    other, n_seg = sep_min.umx_other(sep, wav), None
                else:
                    stems, n_seg = sep_min.htdemucs(sep, wav, ranges=spans if a.scope == "windows" else None)
                    other = stems[2]
            with c.Timer() as tb:
                notes = [bp_min.predict(bp, soxr.resample(other[:, s:e].mean(0), c.SR, 22050).astype(np.float32), 19)
                         for s, e in spans]
        (c.WORK / f"notes_{a.sep}_{a.scope}_{a.provider}_{tid}.json").write_text(json.dumps(notes))
        dur = n / c.SR
        c.emit(a.out, dict(kind="e2e", sep=a.sep, scope=a.scope, provider=a.provider, threads=a.threads, id=tid,
                           dur=round(dur, 1), n_seg=n_seg, sep_wall=round(ts.wall, 2), sep_cpu=round(ts.cpu, 1),
                           bp_wall=round(tb.wall, 2), bp_cpu=round(tb.cpu, 2), wall=round(ts.wall + tb.wall, 2),
                           cpu=round(ts.cpu + tb.cpu, 1), notes=sum(len(x) for x in notes), rss_mb=r.mb,
                           vram_vs_presession_mb=(v.peak - M0) if a.provider == "dml" else None, sysload_before=load,
                           gpu_util_before=gu[0], gpu_mem_before=gu[1], gpu_waited_s=gu[2]))
c.emit(a.out, dict(kind="e2e_peak", sep=a.sep, scope=a.scope, provider=a.provider, threads=a.threads, peak_rss_mb=rtot.mb))
