"""Task 3: the three metric families, compute cost seed-vs-all and all-pairs. Saves matrices."""
import statistics
import sys
import time
import tracemalloc
from pathlib import Path

import numba
import numpy as np
from numba import njit, prange
from scipy.spatial.distance import cdist

sys.path.insert(0, str(Path(__file__).parent))
from common import AIDX, ALPHA, ENERGY, SC, ZRANGE, abs_profile, feat_matrix, load, profile, sub_matrix

tracks, meta, anlz = load()
N = len(tracks)
G = 0.5  # gap cost per bar
S = sub_matrix()
print('substitution matrix rows', ALPHA); print(np.round(S, 2))

# ---------------------------------------------------------------- (a) run-length arrays
NR = np.array([len(t["runs"]) for t in tracks], np.int32)
M = int(NR.max())
LAB = np.zeros((N, M), np.int8)
BAR = np.zeros((N, M), np.float32)
for i, t in enumerate(tracks):
    for j, (lab, b) in enumerate(t["runs"]):
        LAB[i, j] = AIDX[lab]
        BAR[i, j] = b
TOT = BAR.sum(1)
print(f"N={N} max runs={M} mean runs={NR.mean():.1f} run arrays bytes={LAB.nbytes + BAR.nbytes}")
print("stored bytes/track if packed (1 byte label + 2 byte quarter-bars per run): median", int(np.median(NR) * 3), "p90", int(np.percentile(NR, 90) * 3), "max", int(M * 3))


def nw_py(ra, rb):
    """Reference pure-Python weighted NW on (label, bars) runs. Returns normalised distance 0..1."""
    n, m = len(ra), len(rb)
    prev = [0.0] * (m + 1)
    for j in range(1, m + 1):
        prev[j] = prev[j - 1] + G * rb[j - 1][1]
    for i in range(1, n + 1):
        la, x = ra[i - 1]
        cur = [prev[0] + G * x] + [0.0] * m
        srow = S[AIDX[la]]
        for j in range(1, m + 1):
            lb, y = rb[j - 1]
            best = prev[j - 1] + srow[AIDX[lb]] * min(x, y) + G * abs(x - y)
            v = prev[j] + G * x
            if v < best:
                best = v
            v = cur[j - 1] + G * y
            if v < best:
                best = v
            cur[j] = best
        prev = cur
    ta, tb = sum(b for _, b in ra), sum(b for _, b in rb)
    return prev[m] / (G * (ta + tb)) if ta + tb else 0.0


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


@njit(cache=True)
def nw_seed(i, LAB, BAR, NR, TOT, S, g):
    out = np.empty(LAB.shape[0], np.float32)
    for j in range(LAB.shape[0]):
        c = nw_one(LAB[i], BAR[i], NR[i], LAB[j], BAR[j], NR[j], S, g)
        d = TOT[i] + TOT[j]
        out[j] = c / (g * d) if d > 0 else 0.0
    return out


@njit(parallel=True, cache=True)
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


def ms(fn, reps):
    xs = []
    for _ in range(reps):
        t0 = time.perf_counter()
        fn()
        xs.append((time.perf_counter() - t0) * 1000)
    return statistics.median(xs)


idx = {t["id"]: i for i, t in enumerate(tracks)}
seeds = [idx[s] for s in ("157309106", "235643068", "80581211")]
rng = np.random.default_rng(7)
rand_seeds = rng.choice(N, 20, replace=False)

print("\n== (i) weighted NW on run-length sequences ==")
t0 = time.perf_counter()
ref = [nw_py(tracks[seeds[0]]["runs"], t["runs"]) for t in tracks]
t_py = (time.perf_counter() - t0) * 1000
py_ms = [t_py]
for s in rand_seeds[:4]:
    t0 = time.perf_counter()
    [nw_py(tracks[s]["runs"], t["runs"]) for t in tracks]
    py_ms.append((time.perf_counter() - t0) * 1000)
print(f"pure Python seed-vs-all: median {statistics.median(py_ms):.0f} ms (range {min(py_ms):.0f}-{max(py_ms):.0f}) -> all-pairs est {statistics.median(py_ms) * N / 2 / 1000 / 60:.1f} min single core")
t0 = time.perf_counter()
d0 = nw_seed(seeds[0], LAB, BAR, NR, TOT, S, G)
print(f"numba first call incl. JIT: {(time.perf_counter() - t0) * 1000:.0f} ms; max |py - numba| = {np.abs(np.array(ref) - d0).max():.2e}")
nb_ms = [ms(lambda s=s: nw_seed(s, LAB, BAR, NR, TOT, S, G), 5) for s in list(seeds) + list(rand_seeds)]
print(f"numba seed-vs-all: median {statistics.median(nb_ms):.2f} ms (range {min(nb_ms):.2f}-{max(nb_ms):.2f})")
nw_all(LAB[:50], BAR[:50], NR[:50], TOT[:50], S, G)  # JIT warm-up
t0 = time.perf_counter()
D_nw = nw_all(LAB, BAR, NR, TOT, S, G)
t_all = time.perf_counter() - t0
print(f"numba all-pairs ({numba.get_num_threads()} threads): {t_all:.1f} s wall; matrix float32 {D_nw.nbytes / 1e6:.0f} MB (condensed upper triangle {N * (N - 1) / 2 * 4 / 1e6:.0f} MB)")
numba.set_num_threads(1)
sub = 600
t0 = time.perf_counter()
nw_all(LAB[:sub], BAR[:sub], NR[:sub], TOT[:sub], S, G)
t1 = time.perf_counter() - t0
print(f"numba single-thread all-pairs estimate: {t1 * (N / sub) ** 2:.1f} s (from {sub}-track subset {t1:.2f} s)")
numba.set_num_threads(numba.config.NUMBA_NUM_THREADS)
np.save(SC / "D_nw.npy", D_nw)

print("\n== (ii) profile vectors ==")
t0 = time.perf_counter()
P32 = np.stack([profile(t, 32) for t in tracks])  # (N, 32, 7) label shares
P64 = np.stack([profile(t, 64) for t in tracks])
AB = [abs_profile(t) for t in tracks]
print(f"profile build (32 + 64 + abs8x64) for all tracks: {(time.perf_counter() - t0):.2f} s")
ABL = np.stack([a for a, _ in AB])
ABN = np.array([n for _, n in AB], np.float32)
H32 = P32.argmax(2).astype(np.int8)
H64 = P64.argmax(2).astype(np.int8)
EN = np.array([ENERGY[c] for c in ALPHA], np.float32)
E32 = (P32 * EN).sum(2) / np.maximum(P32.sum(2), 1e-9)  # mean energy class per bin, mood-agnostic


def unit(x):
    x = x.reshape(len(x), -1).astype(np.float32)
    return x / np.maximum(np.linalg.norm(x, axis=1, keepdims=True), 1e-9)


U32, U64 = unit(P32), unit(P64)
OH32 = np.eye(7, dtype=np.float32)[H32].reshape(N, -1)
OHAB = np.eye(8, dtype=np.float32)[ABL][:, :, :7].reshape(N, -1)  # pad column removed
for name, fn in (
    ("cosine soft one-hot 32 bins (224 f32)", lambda s: 1 - U32 @ U32[s]),
    ("cosine soft one-hot 64 bins (448 f32)", lambda s: 1 - U64 @ U64[s]),
    ("Hamming majority label 32 bins (32 u8)", lambda s: (H32 != H32[s]).mean(1)),
    ("Hamming abs 8-bar bins x64 (64 u8)", lambda s: 1 - (ABL[:, :] == ABL[s]).__and__(ABL != 7).sum(1) / np.maximum(ABN, ABN[s])),
    ("L1 energy profile 32 bins (32 f32)", lambda s: np.abs(E32 - E32[s]).mean(1) / ZRANGE),
):
    v = [ms(lambda s=s: fn(s), 20) for s in list(seeds) + list(rand_seeds)]
    print(f"seed-vs-all {name}: median {statistics.median(v):.3f} ms")


def timed(name, fn):
    tracemalloc.start()
    t0 = time.perf_counter()
    out = fn()
    dt = time.perf_counter() - t0
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(f"all-pairs {name}: {dt:.2f} s, result {out.nbytes / 1e6:.0f} MB ({out.dtype}), peak alloc {peak / 1e6:.0f} MB")
    return out


D_cos32 = timed("cosine 32", lambda: (1 - U32 @ U32.T).astype(np.float32))
D_cos64 = timed("cosine 64", lambda: (1 - U64 @ U64.T).astype(np.float32))
D_ham32 = timed("Hamming 32 (one-hot matmul)", lambda: (1 - (OH32 @ OH32.T) / 32).astype(np.float32))
D_hamab = timed("Hamming abs 8-bar", lambda: (1 - (OHAB @ OHAB.T) / np.maximum(ABN[:, None], ABN[None, :])).astype(np.float32))
D_en32 = timed("L1 energy 32 (cdist cityblock)", lambda: (cdist(E32, E32, "cityblock") / 32 / ZRANGE).astype(np.float32))

print("\n== (iii) Euclid on standardised summary features ==")
Z = feat_matrix(tracks).astype(np.float32)
v = [ms(lambda s=s: np.linalg.norm(Z - Z[s], axis=1), 20) for s in list(seeds) + list(rand_seeds)]
print(f"seed-vs-all Euclid ({Z.shape[1]} features f32): median {statistics.median(v):.3f} ms")
D_eu = timed("Euclid (cdist)", lambda: cdist(Z, Z).astype(np.float32))

for name, arr in (("D_cos32", D_cos32), ("D_cos64", D_cos64), ("D_ham32", D_ham32), ("D_hamab", D_hamab), ("D_en32", D_en32), ("D_eu", D_eu)):
    np.fill_diagonal(arr, 0)
    np.save(SC / f"{name}.npy", arr)
np.save(SC / "Z.npy", Z)
print("\nrank agreement between metrics (mean overlap of top-10 neighbour sets, 500 random seeds):")
ss = rng.choice(N, 500, replace=False)
mats = {"nw": D_nw, "cos32": D_cos32, "cos64": D_cos64, "ham32": D_ham32, "hamab": D_hamab, "en32": D_en32, "eu": D_eu}
tops = {}
for k, D in mats.items():
    sub = D[ss].copy()
    sub[np.arange(len(ss)), ss] = np.inf
    tops[k] = np.argpartition(sub, 10, axis=1)[:, :10]
names = list(mats)
for a in names:
    print(f"  {a:6s}", " ".join(f"{np.mean([len(set(tops[a][i]) & set(tops[b][i])) for i in range(len(ss))]) / 10:.2f}" for b in names))
print("   cols:", names)
print("\nstore size per track: runs packed", "3 B/run -> median", int(np.median(NR) * 3), "B; profile32 majority 32 B (4 bit/bin: 16 B); abs 8-bar 64 B; soft P32 224 f32 = 896 B (u8: 224 B); summary", Z.shape[1], "f32 =", Z.shape[1] * 4, "B")
