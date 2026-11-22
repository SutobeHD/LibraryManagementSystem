"""Evaluate grid_lag_blocks.jsonl: repeatability of the grid offset, distribution, contrast as a trust signal.
Usage: grid_lag_eval.py <out dir with grid_lag_blocks.jsonl>"""
import json
import sys
from pathlib import Path

import numpy as np
from scipy import stats

OUT = Path(sys.argv[1])
R = [json.loads(line) for line in open(OUT / "grid_lag_blocks.jsonl", encoding="utf-8")]
R = [r for r in R if r["status"] == "ok"]
N = len(R)
L: list = []


def out(s=""):
    print(s)
    L.append(s)


def auc_low(score, bad):
    """Probability that a 'bad' estimate has the lower contrast than a good one."""
    b, g = score[bad], score[~bad]
    if len(b) == 0 or len(g) == 0:
        return np.nan
    return float(np.mean([(x < g).mean() + 0.5 * (x == g).mean() for x in b]))


ext = np.array([r["ext"] for r in R])
lossless = np.isin(ext, ["aiff", "wav", "flac"])
mid = np.array([r["mid"]["lag_ms"] for r in R])
mid_c = np.array([r["mid"]["contrast"] for r in R])
st_mid = np.array([r["stored"]["lag_ms"] for r in R])
st_blk = np.array([r["stored"]["lag_M_ms"] for r in R])
pooled = np.array([r["pooled"][0] for r in R], dtype=float)
pooled_c = np.array([r["pooled"][1] for r in R], dtype=float)
pooled100 = np.array([r["pooled100"][0] for r in R], dtype=float)
longest = np.array([max(r["blocks"], key=lambda b: b["n_bars"])["lag_ms"] for r in R], dtype=float)
longest_c = np.array([max(r["blocks"], key=lambda b: b["n_bars"])["contrast"] for r in R], dtype=float)
out(f"tracks {N}; blocks {sum(len(r['blocks']) for r in R)} (median {np.median([len(r['blocks']) for r in R]):.0f} per track; bars per block median "
    f"{np.median([b['n_bars'] for r in R for b in r['blocks']]):.0f}, min {min(b['n_bars'] for r in R for b in r['blocks'])})")
out(f"sanity: middle-120 lag reproduces the stored value in {np.mean(np.abs(mid - st_mid) < 0.01):.2f}; longest-block lag (raw arg max) equals the stored block lag in "
    f"{np.mean(np.abs(longest - st_blk) < 0.01):.2f} (stored value is set to 0 below contrast 1.5: {int(((st_blk == 0) & (np.abs(longest) > 0.01)).sum())} such tracks)")

out("\n## estimates per track")
for nm, a, b in (("middle 120 s vs all M blocks pooled", mid, pooled), ("middle 120 s vs longest M block", mid, longest), ("longest M block vs all M blocks pooled", longest, pooled)):
    d = np.abs(a - b)
    out(f"   {nm:40s} |diff| <= 1 ms {np.mean(d <= 1):.2f}, <= 3 ms {np.mean(d <= 3):.2f}, > 5 ms {int((d > 5).sum())} tracks, > 10 ms {int((d > 10).sum())}; Spearman {stats.spearmanr(a, b)[0]:.2f}, "
        f"lossless only (n={lossless.sum()}) Spearman {stats.spearmanr(a[lossless], b[lossless])[0]:.2f}")
h = np.array([[x[0] for x in r["mid_halves"]] for r in R], dtype=float)
d = np.abs(h[:, 0] - h[:, 1])
out(f"   two 60 s halves of the middle 120 s: |diff| <= 1 ms {np.mean(d <= 1):.2f}, <= 3 ms {np.mean(d <= 3):.2f}, > 5 ms {int((d > 5).sum())} tracks; Spearman {stats.spearmanr(h[:, 0], h[:, 1])[0]:.2f}, "
    f"lossless only {stats.spearmanr(h[lossless, 0], h[lossless, 1])[0]:.2f}")

out("\n## blocks inside one track (reference = median of the track's block lags)")
dev, con, nbar, tid, is_ll = [], [], [], [], []
for i, r in enumerate(R):
    bl = np.array([b["lag_ms"] for b in r["blocks"]], dtype=float)
    ref = np.median(bl)
    for b in r["blocks"]:
        dev.append(abs(b["lag_ms"] - ref))
        con.append(b["contrast"])
        nbar.append(b["n_bars"])
        tid.append(i)
        is_ll.append(lossless[i])
dev, con, nbar, tid = np.array(dev), np.array(con), np.array(nbar), np.array(tid)
out(f"   block lag vs track median: <= 1 ms in {np.mean(dev <= 1):.2f} of blocks, <= 3 ms {np.mean(dev <= 3):.2f}, > 5 ms {np.mean(dev > 5):.3f} ({int((dev > 5).sum())} blocks in {len(set(tid[dev > 5]))} tracks), > 10 ms {int((dev > 10).sum())}")
per_track_max = np.array([dev[tid == i].max() for i in range(N)])
out(f"   tracks whose blocks all agree within 1 ms: {np.mean(per_track_max <= 1):.2f}; within 3 ms: {np.mean(per_track_max <= 3):.2f}; a block > 5 ms off in {int((per_track_max > 5).sum())} tracks")
bad = dev > 5
out(f"   block contrast: p10 {np.percentile(con, 10):.1f}, median {np.median(con):.1f}, p90 {np.percentile(con, 90):.1f}, min {con.min():.2f}; below 1.5 (the rule's own cut): {int((con < 1.5).sum())} blocks")
out(f"   contrast as a trust signal for a block (bad = > 5 ms off the track median, n={int(bad.sum())}): AUC {auc_low(con, bad):.2f}; Spearman contrast vs deviation {stats.spearmanr(con, dev)[0]:+.2f}")
for lo, hi in ((0, 2), (2, 3), (3, 5), (5, 10), (10, 1e9)):
    m = (con >= lo) & (con < hi)
    if m.any():
        out(f"      contrast {lo:>4.0f} - {hi if hi < 1e8 else float('inf'):<5.0f}: {m.sum():4d} blocks, bad {int(bad[m].sum()):3d} ({np.mean(bad[m]):.2f}), median deviation {np.median(dev[m]):.2f} ms")
out(f"   bad blocks by length: <= 8 bars {np.mean(bad[nbar <= 8]):.3f} (n={int((nbar <= 8).sum())}), > 8 bars {np.mean(bad[nbar > 8]):.3f} (n={int((nbar > 8).sum())})")
out("   tracks with a bad block: " + "; ".join(
    f"{R[i]['id']} ({R[i]['ext']}) blocks " + " ".join(f"{b['lag_ms']:+.1f}/{b['contrast']:.1f}" for b in R[i]["blocks"]) + f" | mid {R[i]['mid']['lag_ms']:+.1f}/{R[i]['mid']['contrast']:.1f} pooled {R[i]['pooled'][0]:+.1f}/{R[i]['pooled'][1]:.1f}"
    for i in np.nonzero(per_track_max > 5)[0]))

out("\n## track-level trust: does the contrast flag the tracks whose two track-level estimates disagree?")
dis = np.abs(mid - pooled) > 5
out(f"   middle-120 vs pooled-M disagree by > 5 ms in {int(dis.sum())} tracks: " + "; ".join(
    f"{R[i]['id']} mid {mid[i]:+.1f} (contrast {mid_c[i]:.1f}) pooled {pooled[i]:+.1f} (contrast {pooled_c[i]:.1f})" for i in np.nonzero(dis)[0]))
out(f"   middle-120 contrast: AUC for 'disagrees' {auc_low(mid_c, dis):.2f}; pooled-M contrast: AUC {auc_low(pooled_c, dis):.2f}; min of both: AUC {auc_low(np.minimum(mid_c, pooled_c), dis):.2f}")
for thr in (3.0, 5.0):
    fl = np.minimum(mid_c, pooled_c) < thr
    out(f"   rule 'min contrast < {thr:.0f}': flags {int(fl.sum())} tracks, of them disagreeing {int((fl & dis).sum())}; disagreeing but not flagged {int((~fl & dis).sum())}")
out(f"   pooled-M contrast: p10 {np.percentile(pooled_c, 10):.1f}, median {np.median(pooled_c):.1f}, min {pooled_c.min():.2f}; middle-120 contrast: p10 {np.percentile(mid_c, 10):.1f}, median {np.median(mid_c):.1f}, min {mid_c.min():.2f}; "
    f"Spearman of the two contrasts {stats.spearmanr(mid_c, pooled_c)[0]:.2f}")

out("\n## distribution of the pooled-M offset")
for nm, m in (("all", np.ones(N, bool)), ("lossless", lossless), ("mp3", ext == "mp3"), ("m4a", ext == "m4a")):
    a = pooled[m]
    out(f"   {nm:9s} n={m.sum():2d}: median {np.median(a):+6.1f} ms, p10 {np.percentile(a, 10):+6.1f}, p90 {np.percentile(a, 90):+6.1f}, min {a.min():+6.1f}, max {a.max():+6.1f}; |x| > 10 ms {np.mean(np.abs(a) > 10):.2f}, > 20 ms {np.mean(np.abs(a) > 20):.2f}; "
        f"within +-1 ms of the group median {np.mean(np.abs(a - np.median(a)) <= 1.0):.2f}, within +-3 ms {np.mean(np.abs(a - np.median(a)) <= 3.0):.2f}")
out("   mp3 values (ms): " + " ".join(f"{v:+.1f}" for v in np.sort(pooled[ext == "mp3"])))
out("   lossless values beyond +-3 ms of the lossless median: " + " ".join(f"{R[i]['id']}:{pooled[i]:+.1f}(c {pooled_c[i]:.1f})" for i in np.nonzero(lossless & (np.abs(pooled - np.median(pooled[lossless])) > 3))[0]))
out(f"   +-100 ms search: pooled optimum outside +-50 ms in {int((np.abs(pooled100) > 50).sum())} tracks: " + " ".join(
    f"{R[i]['id']}({R[i]['ext']}):{pooled100[i]:+.1f} vs {pooled[i]:+.1f}" for i in np.nonzero(np.abs(pooled100) > 50)[0]))
(OUT / "grid_lag_eval.txt").write_text("\n".join(L) + "\n", encoding="utf-8")
