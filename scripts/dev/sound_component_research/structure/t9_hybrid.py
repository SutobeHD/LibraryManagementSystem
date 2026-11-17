"""Task 9: hybrid structure distance = 0.5 RLE-NW (t3_metrics) + 0.5 binned 8-bar edit distance
(t6_binned), scored on the same-audio copy pairs like t5 / t6. Reconstructed 2026-11-12 from the
t3 / t6 functions (the original t9 script was not preserved); reproduces out_t9_hybrid.txt.
Inputs: tmp/sc-struct/phrases.jsonl + root.npy (from t4_sanity). Run from anywhere."""
import collections as C
import math
import re
import sys
from pathlib import Path

import numpy as np
from numba import njit, prange

sys.path.insert(0, str(Path(__file__).parent))
import common  # noqa: E402

common.ROOT = next(p for p in Path(__file__).resolve().parents if (p / "app").is_dir())
common.SC = common.ROOT / "tmp" / "sc-struct"
from common import AIDX, abs_profile, load, sub_matrix  # noqa: E402

tracks, meta, anlz = load()
N = len(tracks)
root = np.load(common.SC / "root.npy")
bpm = np.array([t["bpm"] for t in tracks])
secs = np.array([t["secs"] for t in tracks])
genre = np.array([t["genre"] for t in tracks])
artist = np.array([t["artist"].lower().strip() for t in tracks])
hasg = genre != ""
S_loud = sub_matrix()


# ---------------------------------------------------------------- t3 (i): weighted NW on runs
@njit
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


@njit(parallel=True)
def nw_all(LAB, BAR, NR, TOT, S, g):
    n = LAB.shape[0]
    out = np.zeros((n, n), np.float32)
    for i in prange(n):
        for j in range(i + 1, n):
            c = nw_one(LAB[i], BAR[i], NR[i], LAB[j], BAR[j], NR[j], S, g)
            d = TOT[i] + TOT[j]
            v = c / (g * d) if d > 0 else 0.0
            out[i, j] = v
            out[j, i] = v
    return out


NR = np.array([len(t["runs"]) for t in tracks], np.int32)
LAB = np.zeros((N, NR.max()), np.int8)
BAR = np.zeros((N, NR.max()), np.float32)
for i, t in enumerate(tracks):
    for j, (lab, b) in enumerate(t["runs"]):
        LAB[i, j] = AIDX[lab]
        BAR[i, j] = b
D_nw = nw_all(LAB, BAR, NR, BAR.sum(1), S_loud, 0.5)


# ---------------------------------------------------------------- t6 (i-b): binned 8-bar edit distance
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


@njit
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


@njit(parallel=True)
def ed_all(SEQ, LN, S, g):
    n = SEQ.shape[0]
    out = np.zeros((n, n), np.float32)
    for i in prange(n):
        for j in range(i + 1, n):
            v = ed_one(SEQ[i], LN[i], SEQ[j], LN[j], S, g) / max(LN[i], LN[j])
            out[i, j] = v
            out[j, i] = v
    return out


seqs = [binned(t, 8, 512) for t in tracks]
LN8 = np.array([len(s) for s in seqs], np.int32)
SEQ8 = np.zeros((N, LN8.max()), np.int8)
for i, s in enumerate(seqs):
    SEQ8[i, : len(s)] = s
D_bed = ed_all(SEQ8, LN8, S_loud, 0.7)

# ---------------------------------------------------------------- t3 (ii-b): Hamming on absolute 8-bar bins
AB = [abs_profile(t) for t in tracks]
ABL = np.stack([a for a, _ in AB])
ABN = np.array([n for _, n in AB], np.float32)
OHAB = np.eye(8, dtype=np.float32)[ABL][:, :, :7].reshape(N, -1)
D_hamab = (1 - (OHAB @ OHAB.T) / np.maximum(ABN[:, None], ABN[None, :])).astype(np.float32)
np.fill_diagonal(D_hamab, 0)

# ---------------------------------------------------------------- scoring (t5 / t6)
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
    dbpm = np.abs(bpm[nn] - bpm[pool][:, None]).mean()
    print(f"{name:34s} | copy top1 {np.mean(ranks <= 1):.2f} top10 {np.mean(ranks <= 10):.2f} | artist {am:.4f} | genre {gm:.3f} | dBPM {dbpm:.2f}")


print(f"tracks {N}, copy queries {len(q)}, pool {len(pool)}")
H = 0.5 * D_nw + 0.5 * D_bed
score("NW alone (t3)", D_nw)
score("binned ED alone (t6)", D_bed)
score("hybrid 0.5 NW + 0.5 binned ED", H)
score("hybrid 0.5 NW + 0.5 hamab", 0.5 * D_nw + 0.5 * D_hamab)
score("hybrid NW + bED + hamab (mean)", (D_nw + D_bed + D_hamab) / 3)

idx = {t["id"]: i for i, t in enumerate(tracks)}
for sid in ("56342911", "157309106"):
    s = idx[sid]
    t = tracks[s]
    print(f"SEED {t['bpm']} {t['s_q8']} | {t['artist']} - {t['title']}")
    cand = pool[root[pool] != root[s]]
    for j in cand[np.argsort(H[s, cand])[:8]]:
        u = tracks[j]
        print(f"   {H[s, j]:.3f} | {u['bpm']:.0f} | {u['genre'] or '-'} | {u['s_q8']} | {u['artist'][:20]} - {u['title']}")
Hp = H[np.ix_(pool, pool)].copy()
np.fill_diagonal(Hp, np.inf)
srt = np.sort(Hp, axis=1)
iu = np.triu_indices(len(pool), 1)
print(f"hybrid distance to 1st / 10th / 50th neighbour, median: {np.median(srt[:, 0]):.3f} {np.median(srt[:, 9]):.3f} {np.median(srt[:, 49]):.3f} | random pair median: {np.median(Hp[iu]):.3f}")
close = (Hp < 0.15).sum(1)
print(f"tracks with >=10 neighbours within 0.15: {(close >= 10).sum()} of {len(pool)} | with none within 0.15: {(close == 0).sum()}")
