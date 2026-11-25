"""Task 7: k-medoids / agglomerative on metric (iii) and (ii)/(i-b); do nameable families emerge?"""
import collections as C
import sys
from pathlib import Path

import numpy as np
from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics import adjusted_rand_score, silhouette_score

sys.path.insert(0, str(Path(__file__).parent))
from common import SC, load

tracks, meta, anlz = load()
N = len(tracks)
Z = np.load(SC / "Z.npy")
D = {k: np.maximum(np.load(SC / f"D_{k}.npy"), 0) for k in ("eu", "cos32", "bed")}
keep = np.array([
    not (t["feat"]["n_phr"] > 60 or t["secs"] > 900 or t["bars"] < 48 or t["secs"] < 90 or (t["tempo_distinct"] or 1) > 1
         or abs(t["grid"].get("beats", 0) - t["end"]) > 64)
    for t in tracks
])
ids = np.where(keep)[0]
print(f"clustering population: {len(ids)} of {N} (hard-flagged excluded: {N - len(ids)})")


def kmedoids(Dm, k, seed, iters=60):
    rng = np.random.default_rng(seed)
    n = len(Dm)
    med = [int(rng.integers(n))]
    for _ in range(k - 1):  # k-means++ style seeding on the distance matrix
        d = Dm[:, med].min(1) ** 2
        med.append(int(rng.choice(n, p=d / d.sum())))
    med = np.array(med)
    for _ in range(iters):
        lab = Dm[:, med].argmin(1)
        new = med.copy()
        for c in range(k):
            m = np.where(lab == c)[0]
            if len(m):
                new[c] = m[Dm[np.ix_(m, m)].sum(0).argmin()]
        if np.array_equal(new, med):
            break
        med = new
    lab = Dm[:, med].argmin(1)
    return lab, med, float(Dm[np.arange(n), med[lab]].sum())


def best_kmedoids(Dm, k):
    return min((kmedoids(Dm, k, s) for s in range(6)), key=lambda r: r[2])


sub = {k: v[np.ix_(ids, ids)] for k, v in D.items()}
rng = np.random.default_rng(3)
samp = rng.choice(len(ids), 2500, replace=False)
res = {}
print("\nsilhouette (2500-track sample) and cluster sizes")
for name in ("eu", "cos32", "bed"):
    for k in (3, 4, 5, 6, 8, 10, 12):
        lab, med, cost = best_kmedoids(sub[name], k)
        sil = silhouette_score(sub[name][np.ix_(samp, samp)], lab[samp], metric="precomputed")
        res[(name, k)] = (lab, med)
        print(f"  k-medoids {name:5s} k={k:2d}: silhouette {sil:.3f} sizes {sorted(C.Counter(lab).values(), reverse=True)}")
for k in (4, 6, 8, 10):
    lab = AgglomerativeClustering(n_clusters=k, linkage="ward").fit_predict(Z[ids])
    sil = silhouette_score(sub["eu"][np.ix_(samp, samp)], lab[samp], metric="precomputed")
    res[("ward", k)] = (lab, None)
    print(f"  ward on summary features k={k:2d}: silhouette {sil:.3f} sizes {sorted(C.Counter(lab).values(), reverse=True)}")
print("stability: ARI between k-medoids runs with different seeds (eu):", [round(adjusted_rand_score(kmedoids(sub["eu"], k, 1)[0], kmedoids(sub["eu"], k, 2)[0]), 2) for k in (4, 6, 8)], "for k=4,6,8")
print("agreement eu-k6 vs ward-k6 ARI:", round(adjusted_rand_score(res[("eu", 6)][0], res[("ward", 6)][0]), 2), "| eu-k6 vs bed-k6:", round(adjusted_rand_score(res[("eu", 6)][0], res[("bed", 6)][0]), 2), "| eu-k6 vs cos32-k6:", round(adjusted_rand_score(res[("eu", 6)][0], res[("cos32", 6)][0]), 2))


def describe(name, k):
    lab, med = res[(name, k)]
    print(f"\n-- {name} k={k}: n | mood h/m/l | intro | 1st drop | drops>=8 | breaks | break% | up% | main% | verse% | outro | bars | pct8 | top genre (lift) | medoid --")
    gall = C.Counter(tracks[i]["genre"] for i in ids if tracks[i]["genre"])
    gtot = sum(gall.values())
    for c in sorted(range(k), key=lambda c: -(lab == c).sum()):
        m = ids[lab == c]
        tt = [tracks[i] for i in m]
        f = lambda key: np.median([t["feat"][key] if t["feat"][key] is not None else t["feat"]["bars"] for t in tt])  # noqa: E731
        md = C.Counter(t["mood"] for t in tt)
        g = C.Counter(t["genre"] for t in tt if t["genre"])
        gt = sum(g.values()) or 1
        lift = sorted(((v / gt) / (gall[x] / gtot), x) for x, v in g.items() if v >= 15)
        top = f"{lift[-1][1]} x{lift[-1][0]:.2f}" if lift else "-"
        mstr = tracks[ids[med[c]]]["s_q8"] if med is not None else tracks[m[np.linalg.norm(Z[m] - Z[m].mean(0), axis=1).argmin()]]["s_q8"]
        print(f"{len(m):5d} | {md['high']}/{md['mid']}/{md['low']} | {f('intro'):g} | {f('first_drop'):g} | {f('drops8'):g} | {f('n_breaks'):g} | {f('break_share') * 100:.0f} | {f('sh_U') * 100:.0f} | {f('main_share') * 100:.0f} | {f('sh_V') * 100:.0f} | {f('outro'):g} | {f('bars'):g} | {f('pct8') * 100:.0f} | {top} | {mstr}")


for nm, k in (("eu", 4), ("eu", 6), ("eu", 8), ("ward", 6), ("bed", 6), ("cos32", 6)):
    describe(nm, k)
np.save(SC / "cluster_eu6.npy", np.stack([ids, res[("eu", 6)][0]]))
