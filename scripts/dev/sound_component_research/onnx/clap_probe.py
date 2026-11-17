"""CLAP audio tower ONNX: feature parity (numpy/librosa vs HF extractor), embedding parity vs torch, speed. CPU or DirectML."""
import argparse

import numpy as np
import oc_common as c
import clap_fe_min as fe

ap = argparse.ArgumentParser()
ap.add_argument("--provider", default="cpu")
ap.add_argument("--model", default="clap_audio_fp32.onnx")
ap.add_argument("--threads", type=int, default=0)
ap.add_argument("--batch", type=int, default=8)
ap.add_argument("--fixed", action="store_true", help="override the batch dim to --batch (pad the last batch)")
ap.add_argument("--out", default="results_clap.jsonl")
a = ap.parse_args()
WIN = fe.MAX_LEN


def cos(u, v):
    u = u / np.linalg.norm(u, axis=-1, keepdims=True)
    v = v / np.linalg.norm(v, axis=-1, keepdims=True)
    return (u * v).sum(-1)


def run(sess, x, batch):
    out = []
    for i in range(0, len(x), batch):
        xb = x[i:i + batch]
        n = len(xb)
        if a.fixed and n < batch:
            xb = np.concatenate([xb, np.repeat(xb[-1:], batch - n, 0)])
        out.append(sess.run(None, {"input_features": xb})[0][:n])
    return np.concatenate(out)


M0 = c.gpu_state()[1]
with c.Timer() as tl, c.PeakRSS() as rl:
    sess = c.session(c.MODELS / a.model, a.provider, a.threads, {"batch": a.batch} if a.fixed else None)
c.emit(a.out, dict(kind="clap_env", model=a.model, provider=a.provider, used=sess.get_providers(), threads=a.threads,
                   batch=a.batch, fixed=a.fixed, load_wall=round(tl.wall, 2), load_rss_mb=rl.mb, **c.env_info()))
run(sess, np.zeros((a.batch, 1, 1001, 64), np.float32), a.batch)  # warm-up
for f in sorted(c.WORK.glob("clap48_*.npy")):
    tid = f.stem.split("_")[1]
    y = np.load(f)
    ref = np.load(c.WORK / f"clapref_{tid}.npz")
    wins = [y[i:i + WIN] for i in range(0, len(y), WIN) if len(y[i:i + WIN]) >= fe.SR]
    with c.Timer() as tf:
        x = fe.features(wins)
    d = np.abs(x - ref["feats"])
    gu = c.gpu_wait() if a.provider == "dml" else (None, None, 0)
    load = c.sys_load()
    with c.Timer() as tm, c.PeakRSS() as r, c.VramPeak() as v:
        emb = run(sess, x, a.batch)
    emb_hf = run(sess, ref["feats"], a.batch)
    cm, ch = cos(emb, ref["emb"]), cos(emb_hf, ref["emb"])
    n = len(wins)
    c.emit(a.out, dict(kind="clap", model=a.model, provider=a.provider, threads=a.threads, batch=a.batch, fixed=a.fixed,
                       id=tid, n_windows=n, feat_maxdiff_db=round(float(d.max()), 5), feat_meandiff_db=round(float(d.mean()), 7),
                       cos_min=round(float(cm.min()), 6), cos_mean=round(float(cm.mean()), 6), one_minus_cos_max=float(f"{1 - cm.min():.2e}"),
                       cos_min_hf_feats=round(float(ch.min()), 6), norm_ratio=round(float(np.linalg.norm(emb, axis=-1).mean()), 3),
                       fe_wall=round(tf.wall, 3), fe_cpu=round(tf.cpu, 2), fe_win_per_s=round(n / tf.wall, 1),
                       fwd_wall=round(tm.wall, 3), fwd_cpu=round(tm.cpu, 2), fwd_win_per_s=round(n / tm.wall, 1),
                       total_win_per_s=round(n / (tm.wall + tf.wall), 1), sysload_before=load, rss_mb=r.mb,
                       vram_delta_mb=v.delta if a.provider == "dml" else None,
                       vram_vs_presession_mb=(v.peak - M0) if a.provider == "dml" else None, gpu_util_before=gu[0], gpu_mem_before=gu[1]))
