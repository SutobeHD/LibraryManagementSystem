"""Sensitivity runs on top of derive_features.py: (1) copy agreement on the pairs whose ANLZ
waveform curves match (stand-in for a fingerprint, no audio read), (2) what Intro 1 / 2 and
Outro 1 / 2 mean in loudness when the first / last tenth lies fully inside the phrase,
(3) zero shares per mood. Output tmp/sc-derived-struct/confirm.txt."""
import collections as C
import contextlib
import io
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
with contextlib.redirect_stdout(io.StringIO()):
    import derive_features as D

tracks, anlz, F, tp, N, mood = D.tracks, D.anlz, D.F, D.tp, D.N, D.mood
rng = np.random.default_rng(7)
lines = []


def out(s=""):
    print(s)
    lines.append(s)


def curve(i):
    c = (anlz.get(tracks[i]["id"], {}).get("band_detail") or {}).get("curve")
    return np.array(c, float) if c else None


def corr(a, b):
    x, y = curve(a), curve(b)
    return float(np.corrcoef(x, y)[0, 1]) if x is not None and y is not None and x.std() > 0 and y.std() > 0 else float("nan")


tp_ok = [(a, b) for a, b in tp if corr(a, b) > 0.95]
tp_diff = [(a, b) for a, b in tp_ok if tracks[a]["s_exact"] != tracks[b]["s_exact"]]
out(f"pairs {len(tp)} -> waveform-confirmed (curve corr > 0.95) {len(tp_ok)}; of those with a different phrase analysis {len(tp_diff)}")
out("name | all 92: = / +-1 | confirmed: = / +-1 / +-4 / +-8 | confirmed, pairs with a value: = / +-1 (n)")
for name in D.names:
    cat = name.startswith("C ")
    a0 = [D.agree(tp, name, t)[0] for t in ((0,) if cat else (0, 1))]
    a1 = [D.agree(tp_ok, name, t)[0] for t in ((0,) if cat else (0, 1, 4, 8))]
    a2 = [D.agree(tp_ok, name, t, True) for t in ((0,) if cat else (0, 1))]
    out(f"{name} | " + " / ".join(f"{x:.2f}" for x in a0) + " | " + " / ".join(f"{x:.2f}" for x in a1) + " | " + " / ".join(f"{x[0]:.2f}" for x in a2) + f" ({a2[0][1]})")

out("\nkappa for the two variant categories (high-high confirmed pairs):")
for name in ("C intro variant (high)", "C outro variant (high)"):
    pr = [(F[a][name], F[b][name]) for a, b in tp_ok if F[a][name] is not None and F[b][name] is not None]
    po = np.mean([x == y for x, y in pr])
    cnt = C.Counter(F[i][name] for i in range(N) if F[i][name] is not None)
    tot = sum(cnt.values())
    pe = sum((v / tot) ** 2 for v in cnt.values())
    out(f"  {name}: n {len(pr)} agree {po:.2f} | library {({k: round(v / tot, 3) for k, v in cnt.items()})} | kappa {(po - pe) / (1 - pe):.2f}")

out("\nvariant loudness when the tenth lies fully inside the phrase (first tenth inside the intro / last tenth inside the outro):")
for name, key, pos in (("intro", "P intro bars", 0), ("outro", "P outro bars", 9)):
    v = {"1": [], "2": []}
    for i in range(N):
        var = F[i][f"C {name} variant (high)"]
        c = curve(i)
        if var in (None, "none") or c is None or c.max() <= 0:
            continue
        if F[i][key] >= F[i]["P total bars"] / 10:
            v[var[1]].append(c[pos] / c.max())
    a, b = np.array(v["1"]), np.array(v["2"])
    s = rng.integers(0, len(a), 100000), rng.integers(0, len(b), 100000)
    out(f"  {name}: variant 1 n {len(a)} median {np.median(a):.2f} (p10 {np.percentile(a, 10):.2f}, p90 {np.percentile(a, 90):.2f}) | variant 2 n {len(b)} median {np.median(b):.2f} "
        f"(p10 {np.percentile(b, 10):.2f}, p90 {np.percentile(b, 90):.2f}) | P(variant 2 louder) {np.mean(b[s[1]] > a[s[0]]):.2f}")
both = C.Counter((F[i]["C intro variant (high)"], F[i]["C outro variant (high)"]) for i in range(N) if mood[i] == "high")
out(f"  intro x outro variant (high mood): {dict(both)}")
x = [F[i]["C intro variant (high)"] for i in range(N) if mood[i] == "high"]
y = [F[i]["C outro variant (high)"] for i in range(N) if mood[i] == "high"]
out(f"  Cramer's V intro variant vs outro variant: {D.cramers_v(x, y):.2f}")
for name, key in (("intro", "P intro bars"), ("outro", "P outro bars")):
    idx = [i for i in range(N) if F[i][f"C {name} variant (high)"] in ("I1", "I2", "O1", "O2")]
    out(f"  {name} variant vs {key} (5 bins) V: {D.cramers_v([F[i][f'C {name} variant (high)'] for i in idx], D.binned([F[i][key] for i in idx])):.2f} | vs family V: "
        f"{D.cramers_v([F[i][f'C {name} variant (high)'] for i in idx], [D.fam[i] for i in idx]):.2f} | vs intro >= 16 flag V: {D.cramers_v([F[i][f'C {name} variant (high)'] for i in idx], [str(F[i]['F intro >= 16 bars']) for i in idx]):.2f}")

out("\nzero shares per mood:")
for name in ("longest gap between mains bars", "longest break bars", "P break share % (high)", "tail after last main bars", "fill-in count", "odd phrases (not x4 bars)", "P drop count"):
    out(f"  {name}: " + " | ".join(f"{m} {np.mean([F[i][name] == 0 for i in range(N) if mood[i] == m and F[i][name] is not None]):.2f}" for m in ("high", "mid") if any(F[i][name] is not None for i in range(N) if mood[i] == m)))
one = [sum(1 for lab, _ in t["runs"] if lab == "C") for t in tracks]
out(f"  tracks with 0 / 1 / 2+ main runs: {np.mean(np.array(one) == 0):.3f} / {np.mean(np.array(one) == 1):.3f} / {np.mean(np.array(one) >= 2):.3f}")

(D.OUT / "confirm.txt").write_text("\n".join(lines), encoding="utf-8")
