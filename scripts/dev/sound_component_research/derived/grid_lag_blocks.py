"""Grid offset per block of window M (lag + contrast), for the 60 fresh tracks of rework A.

The rework-A rows keep only two lag estimates per track (middle 120 s with its contrast, longest
M block without one). This re-decodes the tracks (read-only) and estimates the lag with the
unchanged baseline `estimate_lag` rule on: the middle 120 s, its two 60 s halves, every block of
window M, and all M blocks pooled (scores summed). A +-100 ms search is stored next to the
+-50 ms one to see clipped optima.

Usage: grid_lag_blocks.py <fresh_sample.json> <rework-a data dir> <out dir>"""
import glob
import json
import os
import sys
import time
import warnings
from pathlib import Path

for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMBA_NUM_THREADS"):
    os.environ[_k] = "1"
warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402
import scipy.signal as sg  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / "app").is_dir())
BASE = ROOT / "scripts" / "dev" / "sound_component_research"
sys.path.insert(0, str(BASE / "sections"))
import extract as EX  # noqa: E402  (window M selection, unchanged)

F, BR, SR = EX.F, EX.BR, EX.SR


def lag_scores(y, bt, max_ms):
    """Score per candidate lag exactly as F.estimate_lag builds it."""
    e = F.env_power(sg.sosfiltfilt(F.SOS_HP2K, y))
    nov, _ = F.novelty(e, F.FS_ENV)
    m = int(max_ms * F.FS_ENV / 1000)
    lags = np.arange(-m, m + 1)
    b = bt[(bt > 0.2) & (bt < len(e) / F.FS_ENV - 0.2)]
    if len(b) < 8:
        return lags, None, 0
    idx = np.round(b * F.FS_ENV).astype(int)
    return lags, np.array([nov[idx + l_].sum() for l_ in lags]), len(b)


def pick(lags, score):
    if score is None:
        return None, None
    best = int(np.argmax(score))
    return round(float(lags[best] / F.FS_ENV * 1000), 2), round(float(score[best] / (np.median(score) + 1e-9)), 2)


def m_blocks(tr, y_full, lag):
    """Blocks of window M exactly as sections/extract.py analyse_track picks them."""
    grid, pssi = tr["grid"], tr["pssi"]
    d = len(y_full) / SR
    t, bn, bar_i0 = EX.grid_bars(grid, lag)
    bar_ok = (t[bar_i0] - EX.PRE - EX.PAD > 0.2) & (t[bar_i0 + 4] + EX.PAD < d - 0.2)
    mood = pssi["mood"] if pssi["mood"] in EX.MAIN_KIND else 1
    ph_meta = []
    for pi, (s, en, kind) in enumerate(EX.phrase_list(pssi, len(t))):
        bars = [b for b in np.nonzero((bar_i0 >= s) & (bar_i0 + 4 <= en) & bar_ok)[0]]
        seg = y_full[int(max(t[s], 0) * SR): int(max(t[en], 0) * SR)]
        ph_meta.append({"i": pi, "kind": kind, "bars": bars, "rms_db": float(F.db(np.mean(seg ** 2))) if len(seg) > SR else -120.0})
    main = [p for p in ph_meta if p["kind"] in EX.MAIN_KIND[mood] and p["bars"]]
    if sum(len(p["bars"]) for p in main) < 32:
        cand = sorted((p for p in ph_meta if p["kind"] not in EX.EDGE_KIND[mood] and p["bars"]), key=lambda p: -p["rms_db"])
        pick_, tot = [], 0
        for p in cand:
            if tot >= EX.M_BARS:
                break
            pick_.append(p)
            tot += len(p["bars"])
        main = sorted(pick_, key=lambda p: p["i"])
    m_bars = EX.select_m([p["bars"] for p in main])
    blocks: list = []
    for b in sorted(m_bars):
        if blocks and bar_i0[b] == bar_i0[blocks[-1][-1]] + 4:
            blocks[-1].append(b)
        else:
            blocks.append([b])
    return t, bar_i0, blocks


def one(tr, stored):
    y_full = BR.load(tr["path"], 0.0, None)
    d = len(y_full) / SR
    grid_t = np.asarray(tr["grid"], dtype=float)[:, 2] / 1000.0
    row = {"id": tr["id"], "ext": tr["path"].rsplit(".", 1)[-1].lower(), "bpm": tr["bpm"], "dur": round(d, 1)}
    a0 = max(0.0, (d - EX.WIN) / 2)
    ya = y_full[int(round(a0 * SR)): int(round(a0 * SR)) + int(EX.WIN * SR)]
    bt0, _bn = F.window_grid(tr["grid"], a0, len(ya) / SR)
    lag, contrast = F.estimate_lag(ya, bt0)
    row["mid"] = {"lag_ms": round(lag * 1000, 2), "contrast": round(contrast, 2)}
    for mx in (50.0, 100.0):
        lg, sc, nb = lag_scores(ya, bt0, mx)
        row["mid"][f"raw{int(mx)}"] = pick(lg, sc)
    hs = len(ya) // 2
    row["mid_halves"] = []
    for k, seg in enumerate((ya[:hs], ya[hs:])):
        bth, _ = F.window_grid(tr["grid"], a0 + k * hs / SR, len(seg) / SR)
        lg, sc, nb = lag_scores(seg, bth, 50.0)
        row["mid_halves"].append(pick(lg, sc))
    # blocks are cut with the stored middle-120 lag, as in rework A (the lag only moves the cut by a few ms)
    t, bar_i0, blocks = m_blocks(tr, y_full, stored["lag_ms"] / 1000.0)
    row["blocks"], pooled, pooled100 = [], None, None
    for bl in blocks:
        t0 = t[bar_i0[bl[0]]] - 0.5
        yb = y_full[int(t0 * SR): int((t[bar_i0[bl[-1]] + 4] + 0.5) * SR)]
        btb = grid_t - t0
        btb = btb[(btb > -1.5) & (btb < len(yb) / SR + 1.5)]
        lg, sc, nb = lag_scores(yb, btb, 50.0)
        lg2, sc2, _ = lag_scores(yb, btb, 100.0)
        l_, c_ = pick(lg, sc)
        l2, c2 = pick(lg2, sc2)
        row["blocks"].append({"n_bars": len(bl), "t0": round(float(t0), 1), "n_beats": nb, "lag_ms": l_, "contrast": c_, "lag100_ms": l2, "contrast100": c2})
        if sc is not None:
            pooled = sc if pooled is None else pooled + sc
            pooled100 = sc2 if pooled100 is None else pooled100 + sc2
    row["pooled"] = pick(lg, pooled)
    row["pooled100"] = pick(lg2, pooled100)
    row["stored"] = {"lag_ms": stored["lag_ms"], "lag_contrast": stored["lag_contrast"], "lag_M_ms": stored["lag_M_ms"]}
    return row


def main():
    sample = json.load(open(sys.argv[1], encoding="utf-8"))["tracks"]
    data, out_dir = Path(sys.argv[2]), Path(sys.argv[3])
    out_dir.mkdir(parents=True, exist_ok=True)
    stored = {}
    for f in sorted(glob.glob(str(data / "run*" / "sect_shard*.jsonl"))):
        for line in open(f, encoding="utf-8"):
            r = json.loads(line)
            if r["status"] == "ok":
                stored[r["id"]] = r
    with open(out_dir / "grid_lag_blocks.jsonl", "w", encoding="utf-8") as fh:
        for i, tr in enumerate(sample):
            if tr["id"] not in stored:
                continue
            w0 = time.perf_counter()
            try:
                row = one(tr, stored[tr["id"]])
                row["status"] = "ok"
            except Exception as exc:  # keep the row, never drop silently
                row = {"id": tr["id"], "status": "error", "error": f"{type(exc).__name__}: {exc}"[:200]}
            fh.write(json.dumps(row) + "\n")
            fh.flush()
            print(i, row["id"], row["status"], round(time.perf_counter() - w0, 1), "s", row.get("error", ""), flush=True)


if __name__ == "__main__":
    main()
