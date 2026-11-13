"""NW parameter sensitivity, scored on (a) retrieval of same-audio copies with differing analysis,
(b) same-artist rate and genre match of the top-10 neighbours."""
import collections as C
import re
import sys
from pathlib import Path

import numpy as np
from numba import njit, prange

sys.path.insert(0, str(Path(__file__).parent))
from common import AIDX, SC, load, sub_matrix

tracks, meta, anlz = load()
N = len(tracks)
root = np.load(SC / "root.npy")
bpm = np.array([t["bpm"] for t in tracks])
secs = np.array([t["secs"] for t in tracks])
genre = np.array([t["genre"] for t in tracks])
artist = np.array([t["artist"].lower().strip() for t in tracks])
hasg = genre != ""


def arrays(key):
    nr = np.array([len(t[key]) for t in tracks], np.int32)
    lab = np.zeros((N, nr.max()), np.int8)
    bar = np.zeros((N, nr.max()), np.float32)
    for i, t in enumerate(tracks):
        for j, (la, b) in enumerate(t[key]):
            lab[i, j] = AIDX[la]
            bar[i, j] = b
    return lab, bar, nr


@njit(cache=True)
def nw_one(la, ba, n, lb, bb, m, S, g):
    prev = np.empty(m + 1)
    cur = np.empty(m + 1)
    prev[0] = 0.0
    for j in range(1, m + 1):
        prev[j] = prev[j - 1] + g * bb[j - 1]
    for i in range(1, n + 1):
        x = ba[i - 1]
        cur[0] = prev[0] + g * x
        for j in range(1, m + 1):
            y = bb[j - 1]
            best = prev[j - 1] + S[la[i - 1], lb[j - 1]] * min(x, y) + g * abs(x - y)
            v = prev[j] + g * x
            if v < best:
                best = v
            v = cur[j - 1] + g * y
            if v < best:
                best = v
            cur[j] = best
        prev, cur = cur, prev
    return prev[m]


@njit(parallel=True, cache=True)
def nw_all(LAB, BAR, NR, S, g, use_max):
    n = LAB.shape[0]
    out = np.zeros((n, n), np.float32)
    tot = BAR.sum(1)
    for i in prange(n):
        for j in range(i + 1, n):
            c = nw_one(LAB[i], BAR[i], NR[i], LAB[j], BAR[j], NR[j], S, g)
            d = max(tot[i], tot[j]) if use_max else g * (tot[i] + tot[j])
            v = c / d if d > 0 else 0.0
            out[i, j] = v
            out[j, i] = v
    return out


# ground-truth copies (same rule as t4_sanity.py)
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
    print(f"{name:52s} | top1 {np.mean(ranks <= 1):.2f} top10 {np.mean(ranks <= 10):.2f} top50 {np.mean(ranks <= 50):.2f} | artist {am:.4f} | genre {gm:.3f} | dBPM {db:.2f}")


S_loud = sub_matrix()
S_bin = 1.0 - np.eye(7)
S_flat = 0.6 * (1.0 - np.eye(7))
raw = arrays("runs")
q8 = arrays("q8")
lograw = (raw[0], np.log2(1 + raw[1] / 4).astype(np.float32), raw[2])  # compress long runs
print(f"queries {len(q)}, pool {len(pool)}")
for nm, arr, S, g, mx in (
    ("NW raw bars, S=loudness, g=0.5, norm=sum (baseline)", raw, S_loud, 0.5, False),
    ("NW raw bars, S=binary, g=0.5", raw, S_bin, 0.5, False),
    ("NW raw bars, S=flat 0.6, g=0.5", raw, S_flat, 0.5, False),
    ("NW raw bars, S=loudness, g=1.0, norm=max", raw, S_loud, 1.0, True),
    ("NW raw bars, S=binary, g=1.0, norm=max", raw, S_bin, 1.0, True),
    ("NW raw bars, S=loudness, g=0.35", raw, S_loud, 0.35, False),
    ("NW q8 runs, S=loudness, g=0.5", q8, S_loud, 0.5, False),
    ("NW q8 runs, S=binary, g=0.5", q8, S_bin, 0.5, False),
    ("NW log2 lengths, S=loudness, g=0.5", lograw, S_loud, 0.5, False),
):
    score(nm, nw_all(arr[0], arr[1], arr[2], S, g, mx))
for k in ("cos32", "hamab", "eu"):
    score(k, np.load(SC / f"D_{k}.npy"))
Dn, Dh, Dc = np.load(SC / "D_nw.npy"), np.load(SC / "D_hamab.npy"), np.load(SC / "D_cos32.npy")
score("hybrid 0.5 NW + 0.5 hamab", 0.5 * Dn + 0.5 * Dh)
score("hybrid 0.5 NW + 0.5 cos32", 0.5 * Dn + 0.5 * Dc)
score("hybrid NW + hamab + cos32 (mean)", (Dn + Dh + Dc) / 3)
