"""Task 4: nearest neighbours for 6 seeds + BPM/genre signal test. Cross-mood checks for task 5."""
import collections as C
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from common import ALPHA, SC, load, profile

tracks, meta, anlz = load()
N = len(tracks)
idx = {t["id"]: i for i, t in enumerate(tracks)}
mats = {k: np.load(SC / f"D_{k}.npy") for k in ("nw", "bed", "cos32", "hamab", "en32", "eu")}
Z = np.load(SC / "Z.npy")
bpm = np.array([t["bpm"] for t in tracks])
secs = np.array([t["secs"] for t in tracks])
bars = np.array([t["bars"] for t in tracks])
nruns = np.array([len(t["runs"]) for t in tracks])
genre = np.array([t["genre"] for t in tracks])
mood = np.array([t["mood"] for t in tracks])
artist = np.array([t["artist"].lower().strip() for t in tracks])
names = {"nw": "(i) NW run-length", "bed": "(i-b) edit distance 8-bar bins", "cos32": "(ii) cosine profile-32", "hamab": "(ii-b) Hamming abs 8-bar bins", "en32": "(ii-c) L1 loudness profile-32", "eu": "(iii) Euclid summary"}

# ---------------------------------------------------------------- analysis stability: same title + same length
tkey = C.defaultdict(list)
for i, t in enumerate(tracks):
    k = re.sub(r"[^a-z0-9]+", " ", t["title"].lower()).strip()
    if len(k) >= 8:
        tkey[k].append(i)
tp = []
for v in tkey.values():
    for a in range(len(v)):
        for b in range(a + 1, len(v)):
            if abs(secs[v[a]] - secs[v[b]]) <= 3 and abs(bpm[v[a]] - bpm[v[b]]) <= 1:
                tp.append((v[a], v[b]))
tp = np.array(tp)
print(f"== same-title + same-length copies (ground truth for analysis stability): {len(tp)} pairs ==")
dnw = mats["nw"][tp[:, 0], tp[:, 1]]
print(f"identical exact structure: {np.mean([tracks[a]['s_exact'] == tracks[b]['s_exact'] for a, b in tp]):.2f}; identical q8: {np.mean([tracks[a]['s_q8'] == tracks[b]['s_q8'] for a, b in tp]):.2f}; "
      f"identical label sequence: {np.mean([tracks[a]['s_lab'] == tracks[b]['s_lab'] for a, b in tp]):.2f}; mood differs: {np.mean(mood[tp[:, 0]] != mood[tp[:, 1]]):.2f}; "
      f"NW dist median {np.median(dnw):.3f} p90 {np.percentile(dnw, 90):.3f}")
nonid = np.array([(a, b) for a, b in tp if tracks[a]["s_exact"] != tracks[b]["s_exact"]])
print(f"copies whose analysis differs: {len(nonid)} pairs -> retrieval test (rank of the copy among all {N} tracks, both directions)")
for k, D in mats.items():
    ranks = []
    for a, b in list(nonid) + [(b, a) for a, b in nonid]:
        d = D[a]
        ranks.append(int((d < d[b]).sum()) - (1 if d[a] < d[b] else 0) + 1)
    ranks = np.array(ranks)
    print(f"  {names[k]}: median rank {np.median(ranks):.0f}, top-1 {np.mean(ranks <= 1):.2f}, top-10 {np.mean(ranks <= 10):.2f}, top-50 {np.mean(ranks <= 50):.2f}")
sm = nonid[mood[nonid[:, 0]] != mood[nonid[:, 1]]]
for a, b in sm[:4]:
    print(f"  mood flip example: {tracks[a]['title'][:40]} | {tracks[a]['mood']}: {tracks[a]['s_q8']} || {tracks[b]['mood']}: {tracks[b]['s_q8']}")

# ---------------------------------------------------------------- same-audio duplicate clusters
parent = list(range(N))


def find(x):
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


ii, jj = np.where(np.triu(mats["nw"] < 0.05, 1))
for i, j in zip(ii, jj):
    same_len = abs(bpm[i] - bpm[j]) <= 0.05 and abs(secs[i] - secs[j]) <= 2
    identical = mats["nw"][i, j] == 0 and min(nruns[i], nruns[j]) >= 5
    if same_len or identical:
        parent[find(i)] = find(j)
for a, b in tp:
    parent[find(a)] = find(b)
root = np.array([find(i) for i in range(N)])
cl = C.Counter(root)
dup_tracks = sum(v for v in cl.values() if v > 1)
print(f"\nsame-audio duplicate clusters: {sum(1 for v in cl.values() if v > 1)} clusters, {dup_tracks} tracks, {dup_tracks - sum(1 for v in cl.values() if v > 1)} redundant copies")
print(f"pairs with NW==0 (identical run sequence): {int((np.triu(mats['nw'] == 0, 1)).sum())}; NW<0.05: {len(ii)}; NW<0.10: {int(np.triu(mats['nw'] < 0.10, 1).sum())}")
rep = root == np.arange(N)  # one representative per duplicate cluster

# ---------------------------------------------------------------- seeds
ht = [i for i in range(N) if genre[i] == "hard techno" and mood[i] == "high" and 48 <= bars[i] <= 400]
cen = Z[ht].mean(0)
print("hard-techno pool", len(ht), "seeds = 3 closest to the genre centroid (summary features), distinct artists/songs")
seeds = [idx["157309106"], idx["235643068"], idx["80581211"], idx["56342911"], idx["87532748"], idx["78705571"]]
print("  centroid ranks of chosen seeds:", [sorted(ht, key=lambda i: np.linalg.norm(Z[i] - cen)).index(s) + 1 for s in seeds[3:]])


def line(i, d=None):
    t = tracks[i]
    head = f"{d:.3f} " if d is not None else ""
    return f"{head}| {t['mood'][0]} | {t['bpm']:.0f} | {t['genre'] or '-'} | {t['s_q8']} | {t['artist'][:22]} - {t['title'][:34]}"


out = []
for s in seeds:
    out.append(f"\n### SEED {tracks[s]['id']}  {line(s)}")
    out.append(f"    exact: {tracks[s]['s_exact']}")
    for k in ("nw", "bed", "cos32", "hamab", "eu"):
        d = mats[k][s].copy()
        d[~rep] = np.inf  # one representative per same-audio cluster
        d[root == root[s]] = np.inf  # drop self + own copies
        nn = np.argsort(d)[:8]
        out.append(f"  -- {names[k]} --")
        out.extend(f"    {line(j, d[j])}" for j in nn)
(SC / "neighbours.txt").write_text("\n".join(out), encoding="utf-8")
print("\n".join(out))

# ---------------------------------------------------------------- signal test
print("\n== signal: do top-10 structure neighbours share BPM / genre / artist more than random? ==")
pool = np.where(rep & (bpm > 0))[0]
rng = np.random.default_rng(11)
hasg = genre != ""
gc = C.Counter(genre[pool][hasg[pool]])
ng = sum(gc.values())
print(f"pool after dedupe: {len(pool)}; with genre {ng}; genre random match = {sum((v / ng) ** 2 for v in gc.values()):.3f}")
ra, rb = rng.choice(pool, 400000), rng.choice(pool, 400000)
m = ra != rb
gg = m & hasg[ra] & hasg[rb]
print(f"random pairs: mean |dBPM| {np.abs(bpm[ra] - bpm[rb])[m].mean():.2f}, median {np.median(np.abs(bpm[ra] - bpm[rb])[m]):.2f}; "
      f"genre match {np.mean(genre[ra][gg] == genre[rb][gg]):.3f}; same artist {np.mean((artist[ra] == artist[rb])[m & (artist[ra] != '')]):.4f}; same mood {np.mean(mood[ra][m] == mood[rb][m]):.3f}")
ordb = np.argsort(bars[pool])
posb = np.empty(len(pool), int)
posb[ordb] = np.arange(len(pool))
ctrl_b, ctrl_g = [], []
for a, i in enumerate(pool):
    lo = max(0, min(len(pool) - 201, posb[a] - 100))
    cand = pool[ordb[lo : lo + 201]]
    cand = cand[cand != i]
    pick = rng.choice(cand, 10, replace=False)
    ctrl_b.append(np.abs(bpm[pick] - bpm[i]).mean())
    if hasg[i]:
        g = pick[hasg[pick]]
        if len(g):
            ctrl_g.append(np.mean(genre[g] == genre[i]))
print(f"length-matched random (10 of the 200 nearest in total bars): mean |dBPM| {np.mean(ctrl_b):.2f} (SE {np.std(ctrl_b) / np.sqrt(len(ctrl_b)):.2f}); genre match {np.mean(ctrl_g):.3f} (SE {np.std(ctrl_g) / np.sqrt(len(ctrl_g)):.3f})")
print("metric | mean |dBPM| top10 (SE) | median | genre match top10 (SE) | same artist top10 | same mood top10 (high / mid seeds)")
for k, D in mats.items():
    sub = D[np.ix_(pool, pool)].copy()
    np.fill_diagonal(sub, np.inf)
    nn = pool[np.argpartition(sub, 10, axis=1)[:, :10]]
    db = np.abs(bpm[nn] - bpm[pool][:, None])
    gm = [np.mean(genre[r[hasg[r]]] == genre[i]) for i, r in zip(pool, nn) if hasg[i] and hasg[r].any()]
    am = np.mean((artist[nn] == artist[pool][:, None])[artist[pool] != ""])
    mh = np.mean(mood[nn][mood[pool] == "high"] == "high")
    mm = np.mean(mood[nn][mood[pool] == "mid"] == "mid")
    print(f"{names[k]} | {db.mean():.2f} ({db.mean(1).std() / np.sqrt(len(pool)):.2f}) | {np.median(db):.2f} | {np.mean(gm):.3f} ({np.std(gm) / np.sqrt(len(gm)):.3f}) | {am:.4f} | {mh:.3f} / {mm:.3f}")
band = pool[(bpm[pool] >= 145) & (bpm[pool] <= 155) & hasg[pool] & (mood[pool] == "high")]
gcb = C.Counter(genre[band])
print(f"control: BPM 145-155 + high mood + genre subset n={len(band)}; random genre match {sum((v / len(band)) ** 2 for v in gcb.values()):.3f}")
for k, D in mats.items():
    sub = D[np.ix_(band, band)].copy()
    np.fill_diagonal(sub, np.inf)
    nn = band[np.argpartition(sub, 10, axis=1)[:, :10]]
    print(f"  {names[k]}: genre match top10 {np.mean(genre[nn] == genre[band][:, None]):.3f}")
print("genre-level structure differences (median): genre | n | intro | first drop | drops | break% | bars")
for g, _ in gc.most_common(7):
    tt = [tracks[i] for i in pool if genre[i] == g and mood[i] == "high"]
    f = lambda k: np.median([t["feat"][k] for t in tt if t["feat"][k] is not None])  # noqa: E731
    print(f"  {g} | {len(tt)} | {f('intro'):g} | {f('first_drop'):g} | {f('drops'):g} | {f('break_share') * 100:.1f} | {f('bars'):g}")

# ---------------------------------------------------------------- label vs waveform loudness
print("\n== waveform loudness (PWV7 10-segment curve, z-scored per track) by normalised label ==")
acc = C.defaultdict(list)
for t in tracks:
    cur = ((anlz.get(t["id"]) or {}).get("band_detail") or {}).get("curve")
    if not cur or len(cur) != 10 or t["bars"] < 48:
        continue
    c = np.array(cur, float)
    if c.std() == 0:
        continue
    z = (c - c.mean()) / c.std()
    p = profile(t, 10)
    for b in range(10):
        j = int(p[b].argmax())
        if p[b, j] >= 0.8:  # segment dominated by one label
            acc[(t["mood"], ALPHA[j])].append(z[b])
for (md, lab), v in sorted(acc.items()):
    print(f"  {md:4s} {lab}: mean z {np.mean(v):+.2f} (n={len(v)})")
np.save(SC / "root.npy", root)
mats["hyb"] = 0.5 * mats["bed"] + 0.5 * mats["hamab"]
for a, b in [("bed", "hamab"), ("bed", "nw"), ("bed", "cos32"), ("bed", "eu")]:
    ov = []
    for i in pool[::9]:
        da, dbb = mats[a][i].copy(), mats[b][i].copy()
        da[i] = dbb[i] = np.inf
        ov.append(len(set(np.argsort(da)[:10]) & set(np.argsort(dbb)[:10])) / 10)
    print(f"top-10 overlap {a} vs {b}: {np.mean(ov):.2f}")
