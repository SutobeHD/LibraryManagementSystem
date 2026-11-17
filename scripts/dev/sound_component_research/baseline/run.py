"""Run the baseline features on the sample. Usage: run.py <shard> <n_shards> [sample.json] [out prefix]

Windows per track: A = middle 120 s (timed), B = 120 s starting at 5 % of the duration (retest),
A1 / A2 = first / second 60 s of A (split-half). Audio opened read-only."""
import json
import os
import sys
import time
import warnings
from pathlib import Path

for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMBA_NUM_THREADS"):
    os.environ[_k] = "1"
warnings.filterwarnings("ignore")

import numpy as np
import psutil
import soundfile as sf
import librosa

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import features as F

WIN = 120.0
PROC = psutil.Process()


def rss_mb():
    mi = PROC.memory_info()
    return round(getattr(mi, "peak_wset", mi.rss) / 2 ** 20, 1)


class Clock:
    def __init__(self):
        self.t = {}

    def run(self, name, fn, *a, **k):
        c0, w0 = time.process_time(), time.perf_counter()
        r = fn(*a, **k)
        self.t[name] = [round(time.process_time() - c0, 3), round(time.perf_counter() - w0, 3)]
        self.t[name + "_rss"] = rss_mb()
        return r


def file_duration(path, fallback):
    try:
        return float(sf.info(path).duration)
    except Exception:
        try:
            import audioread
            with audioread.audio_open(path) as fh:
                return float(fh.duration)
        except Exception:
            return float(fallback)


def load(path, start, dur):
    y, _sr = librosa.load(path, sr=F.SR, mono=True, offset=start, duration=dur)
    return np.ascontiguousarray(y, dtype=np.float64)


def hats_all(y, bt, bn, dur, deltas=False):
    out = {}
    for tag, sos in (("h7", F.SOS_HP7K), ("h5", F.SOS_BP5_12K)):
        e, e_pick, on, pk = F.hat_onsets(y, sos)
        feats, hist = F.hat_features(e, on, pk, bt, bn, dur)
        fl, fhist = F.flux_profile(e_pick, bt, bn, dur)
        feats.update(fl)
        out[tag] = feats
        out[tag]["hist16"] = None if hist is None else [round(float(v), 4) for v in hist]
        out[tag]["flux16"] = None if fhist is None else [round(float(v), 4) for v in fhist]
        if deltas and tag == "h7":
            nb = max(1, feats.get("n_beats", 1))
            for d in (0.15, 0.40):
                on2, _p, _s = F.pick_onsets(e_pick, F.FS_ENV, delta=d)
                t = on2 / F.FS_ENV
                out[tag][f"hats_per_beat_d{int(d * 100)}"] = float(((t >= 0.05) & (t <= dur - 0.05)).sum() / nb)
    return out


def analyse(y, grid, t0, lag=None, clock=None):
    dur = len(y) / F.SR
    clock = clock or Clock()
    bt0, bn = F.window_grid(grid, t0, dur)
    est_lag, contrast = clock.run("lag", F.estimate_lag, y, bt0)
    use = est_lag if lag is None else lag
    bt = bt0 + use
    res = {"t0": round(t0, 2), "dur": round(dur, 2), "lag_ms": round(est_lag * 1000, 2), "lag_used_ms": round(use * 1000, 2),
           "lag_contrast": round(contrast, 2)}
    res["bass"] = clock.run("bass", F.bass_block, y, bt)
    S, H, P = clock.run("hpss", F.hpss_block, y)
    res["hpss"] = F.hpss_shares(H, P)
    res["hats"] = clock.run("hats", hats_all, y, bt, bn, dur, True)
    nb = int(((bt >= 0) & (bt <= dur)).sum())
    res["mel"] = clock.run("mel", F.melody_block, S, H, nb)
    return res, use, clock


def main():
    shard, n_shards = int(sys.argv[1]), int(sys.argv[2])
    sample = json.load(open(sys.argv[3] if len(sys.argv) > 3 else HERE / "sample.json", encoding="utf-8"))["tracks"]
    prefix = sys.argv[4] if len(sys.argv) > 4 else "results"
    out_path = HERE / f"{prefix}_shard{shard}.jsonl"
    # warm-up (numba JIT, FFT plans) so the first track's timing is not inflated
    rng = np.random.default_rng(0)
    yw = rng.standard_normal(int(20 * F.SR)) * 0.1
    gw = [[(i % 4) + 1, 150.0, 400.0 * i] for i in range(60)]
    analyse(yw, gw, 0.0)
    librosa.resample(yw[: F.SR].astype(np.float32), orig_sr=48000, target_sr=F.SR)
    base_rss = rss_mb()
    with open(out_path, "w", encoding="utf-8") as fh:
        for i, tr in enumerate(sample):
            if i % n_shards != shard:
                continue
            row = {k: tr[k] for k in ("id", "title", "artist", "genre", "bpm", "key", "path", "total_time", "in_w8")}
            row["rss_after_warmup_mb"] = base_rss
            try:
                d = file_duration(tr["path"], tr["total_time"])
                row["file_dur"] = round(d, 2)
                a0 = max(0.0, (d - WIN) / 2)
                b0 = min(0.05 * d, max(0.0, d - WIN))
                row["overlap_ab_s"] = round(max(0.0, min(a0, b0) + WIN - max(a0, b0)), 1)
                clock = Clock()
                ya = clock.run("load", load, tr["path"], a0, WIN)
                ra, lag, clock = analyse(ya, tr["grid"], a0, clock=clock)
                row["A"] = ra
                row["timing"] = clock.t
                row["rss_peak_mb_after_A"] = rss_mb()
                half = len(ya) // 2
                row["A1"], _l, _c = analyse(ya[:half], tr["grid"], a0, lag=lag)
                row["A2"], _l, _c = analyse(ya[half:], tr["grid"], a0 + half / F.SR, lag=lag)
                del ya
                yb = load(tr["path"], b0, WIN)
                row["B"], _l, _c = analyse(yb, tr["grid"], b0, lag=lag)
                row["status"] = "ok"
            except Exception as exc:  # keep the row, never drop silently
                import traceback
                row["status"] = "error"
                row["error"] = f"{type(exc).__name__}: {exc}"[:300]
                row["trace"] = traceback.format_exc()[-1500:]
            row["rss_peak_mb"] = rss_mb()
            fh.write(json.dumps(row, ensure_ascii=False, default=float) + "\n")
            fh.flush()
            print(shard, i, row["status"], row.get("timing", {}).get("hpss"), tr["artist"], "-", tr["title"], flush=True)


if __name__ == "__main__":
    main()
