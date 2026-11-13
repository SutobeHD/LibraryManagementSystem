"""Metric (i'): edit distance on the 8-bar (or 4-bar) binned label string = shift-tolerant Hamming.
Fixes the run-split weakness of RLE-NW (C130 vs C66 V8 C56). Scored like t5, plus timing."""
import collections as C
import math
import re
import statistics
import sys
import time
from pathlib import Path

import numba
import numpy as np
from numba import njit, prange

sys.path.insert(0, str(Path(__file__).parent))
from common import AIDX, ALPHA, SC, load, sub_matrix

tracks, meta, anlz = load()
N = len(tracks)
root = np.load(SC / "root.npy")
bpm = np.array([t["bpm"] for t in tracks])
secs = np.array([t["secs"] for t in tracks])
genre = np.array([t["genre"] for t in tracks])
artist = np.array([t["artist"].lower().strip() for t in tracks])
hasg = genre != ""


def binned(t, bin_bars, cap):
    n = min(cap, max(1, int(math.floor(t["bars"] / bin_bars + 0.5))))
    m = np.zeros((n, 7), np.float32)
    pos = 0.0
    for lab, b in t["runs"]:
        a, e = pos / bin_bars, (pos + b) / bin_bars
        i = int(a)
        while i < n and i < e:
            m[i, AIDX[lab]] += min(e, i + 1) - max(a, i)
            i += 1
        pos += b
    return m.argmax(1).astype(np.int8)


def arrays(bin_bars, cap):
    seqs = [binned(t, bin_bars, cap) for t in tracks]
    ln = np.array([len(s) for s in seqs], np.int32)
    out = np.zeros((N, ln.max()), np.int8)
    for i, s in enumerate(seqs):
        out[i, : len(s)] = s
    return out, ln


@njit(cache=True)
def ed_one(a, n, b, m, S, g):
    prev = np.empty(m + 1)
    cur = np.empty(m + 1)
    for j in range(m + 1):
        prev[j] = g * j
    for i in range(1, n + 1):
        cur[0] = g * i
        ai = a[i - 1]
        for j in range(1, m + 1):
            best = prev[j - 1] + S[ai, b[j - 1]]
            v = prev[j] + g
            if v < best:
                best = v
            v = cur[j - 1] + g
            if v < best:
                best = v
            cur[j] = best
        prev, cur = cur, prev
    return prev[m]


@njit(cache=True)
def ed_seed(i, SEQ, LN, S, g):
    out = np.empty(SEQ.shape[0], np.float32)
    for j in range(SEQ.shape[0]):
        out[j] = ed_one(SEQ[i], LN[i], SEQ[j], LN[j], S, g) / max(LN[i], LN[j])
    return out


@njit(parallel=True, cache=True)
def ed_all(SEQ, LN, S, g):
    n = SEQ.shape[0]
    out = np.zeros((n, n), np.float32)
    for i in prange(n):
        for j in range(i + 1, n):
            v = ed_one(SEQ[i], LN[i], SEQ[j], LN[j], S, g) / max(LN[i], LN[j])
            out[i, j] = v
            out[j, i] = v
    return out


def ed_py(a, b, S, g):
    n, m = len(a), len(b)
    prev = [g * j for j in range(m + 1)]
    for i in range(1, n + 1):
        cur = [g * i] + [0.0] * m
        row = S[a[i - 1]]
        for j in range(1, m + 1):
            best = prev[j - 1] + row[b[j - 1]]
            v = prev[j] + g
            if v < best:
                best = v
            v = cur[j - 1] + g
            if v < best:
                best = v
            cur[j] = best
        prev = cur
    return prev[m] / max(n, m)


tkey = C.defaultdict(list)
for i, t in enumerate(tracks):
    k = re.sub(r"[^a-z0-9]+", " ", t["title"].lower()).strip()
    if len(k) >= 8:
        tkey[k].append(i)
q = []
for v in tkey.values():
    for a in range(len(v)):
        for b in range(a + 1, len(v)):
            if abs(secs[v[a]] - secs[v[b]]) <= 3 and abs(bpm[v[a]] - bpm[v[b]]) <= 1 and tracks[v[a]]["s_exact"] != tracks[v[b]]["s_exact"]:
                q += [(v[a], v[b]), (v[b], v[a])]
pool = np.where((root == np.arange(N)) & (bpm > 0))[0]


def score(name, D):
    ranks = np.array([int((D[a] < D[a][b]).sum()) + 1 - (1 if D[a][a] < D[a][b] else 0) for a, b in q])
    sub = D[np.ix_(pool, pool)].copy()
    np.fill_diagonal(sub, np.inf)
    nn = pool[np.argpartition(sub, 10, axis=1)[:, :10]]
    am = np.mean((artist[nn] == artist[pool][:, None])[artist[pool] != ""])
    gm = np.mean([np.mean(genre[r[hasg[r]]] == genre[i]) for i, r in zip(pool, nn) if hasg[i] and hasg[r].any()])
    db = np.abs(bpm[nn] - bpm[pool][:, None]).mean()
    print(f"{name:46s} | top1 {np.mean(ranks <= 1):.2f} top10 {np.mean(ranks <= 10):.2f} top50 {np.mean(ranks <= 50):.2f} | artist {am:.4f} | genre {gm:.3f} | dBPM {db:.2f}")


S_loud, S_bin = sub_matrix(), 1.0 - np.eye(7)
SEQ8, LN8 = arrays(8, 512)
SEQ4, LN4 = arrays(4, 1024)
print(f"8-bar bins: median {int(np.median(LN8))} p90 {int(np.percentile(LN8, 90))} max {LN8.max()} bins; 4-bar: median {int(np.median(LN4))} max {LN4.max()}")
ed_all(SEQ8[:20], LN8[:20], S_loud, 0.5)
best = None
for nm, SEQ, LN, S, g in (
    ("binned ED 8-bar, S=binary, g=0.5", SEQ8, LN8, S_bin, 0.5),
    ("binned ED 8-bar, S=binary, g=0.7", SEQ8, LN8, S_bin, 0.7),
    ("binned ED 8-bar, S=binary, g=1.0 (Levenshtein)", SEQ8, LN8, S_bin, 1.0),
    ("binned ED 8-bar, S=loudness, g=0.5", SEQ8, LN8, S_loud, 0.5),
    ("binned ED 8-bar, S=loudness, g=0.7", SEQ8, LN8, S_loud, 0.7),
    ("binned ED 4-bar, S=binary, g=0.7", SEQ4, LN4, S_bin, 0.7),
    ("binned ED 4-bar, S=loudness, g=0.7", SEQ4, LN4, S_loud, 0.7),
):
    t0 = time.perf_counter()
    D = ed_all(SEQ, LN, S, g)
    dt = time.perf_counter() - t0
    score(nm + f" [{dt:.1f}s]", D)
    if nm == "binned ED 8-bar, S=loudness, g=0.7":
        best = D
np.save(SC / "D_bed.npy", best)
score("hamab (no shift)", np.load(SC / "D_hamab.npy"))
score("RLE-NW baseline", np.load(SC / "D_nw.npy"))

print("\n== cost of binned ED 8-bar ==")
idx = {t["id"]: i for i, t in enumerate(tracks)}
rng = np.random.default_rng(7)
ss = [idx["157309106"], idx["235643068"], idx["80581211"], *rng.choice(N, 20, replace=False)]
v = []
for s in ss:
    xs = []
    for _ in range(5):
        t0 = time.perf_counter()
        ed_seed(s, SEQ8, LN8, S_loud, 0.7)
        xs.append((time.perf_counter() - t0) * 1000)
    v.append(statistics.median(xs))
print(f"numba seed-vs-all: median {statistics.median(v):.2f} ms (range {min(v):.2f}-{max(v):.2f})")
pv = []
seqs = [SEQ8[i, : LN8[i]].tolist() for i in range(N)]
Sl = S_loud.tolist()
for s in ss[:5]:
    t0 = time.perf_counter()
    [ed_py(seqs[s], x, Sl, 0.7) for x in seqs]
    pv.append((time.perf_counter() - t0) * 1000)
print(f"pure Python seed-vs-all: median {statistics.median(pv):.0f} ms (range {min(pv):.0f}-{max(pv):.0f}) -> all-pairs est {statistics.median(pv) * N / 2 / 60000:.0f} min single core")
t0 = time.perf_counter()
ed_all(SEQ8, LN8, S_loud, 0.7)
print(f"numba all-pairs {numba.get_num_threads()} threads: {time.perf_counter() - t0:.2f} s")
numba.set_num_threads(1)
t0 = time.perf_counter()
ed_all(SEQ8[:800], LN8[:800], S_loud, 0.7)
t1 = time.perf_counter() - t0
print(f"numba all-pairs single thread estimate: {t1 * (N / 800) ** 2:.0f} s")
print(f"stored bytes/track 8-bar label string: median {int(np.median(LN8))} B (3 bit/bin packed: {int(np.median(LN8) * 3 / 8) + 1} B), p90 {int(np.percentile(LN8, 90))}, max {LN8.max()}")
