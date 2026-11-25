"""Which further per-track features fall out of what the planned structure scan already reads
(PSSI phrases + PQTZ grid + cue counts)? Measure-only, no audio, no ANLZ re-read.

Inputs (read-only): tmp/sc-struct/phrases.jsonl, tmp/library-analysis/measure/anlz.jsonl,
tmp/library-analysis/tracks.json. Output: tmp/sc-derived-struct/features.{txt,json}.

Same code path as structure/t2b_coarse.py + t8_rules.py: common.load() -> runs / summary(),
copy pairs = same normalised title (>= 8 chars), duration +-3 s, BPM +-1 (92 pairs; these are
NOT fingerprint-confirmed). Ids only in the output."""
import collections as C
import json
import re
import sys
from pathlib import Path

import numpy as np
from scipy.stats import rankdata

HERE = Path(__file__).resolve()
ROOT = next(p for p in HERE.parents if (p / "app").is_dir())
sys.path.insert(0, str(HERE.parents[1] / "structure"))
import common  # noqa: E402

common.ROOT = ROOT
common.SC = ROOT / "tmp" / "sc-struct"
from common import ZL, load  # noqa: E402

OUT = ROOT / "tmp" / "sc-derived-struct"
OUT.mkdir(parents=True, exist_ok=True)
LIB = 4765
rng = np.random.default_rng(20261122)

tracks, meta, anlz = load()
N = len(tracks)
raw = {}
for line in open(common.SC / "phrases.jsonl", encoding="utf-8"):
    r = json.loads(line)
    raw[r["id"]] = r


def post_break_drop(t):
    pos, seen_d = 0.0, False
    for lab, b in t["runs"]:
        if lab == "D" and b >= 4:
            seen_d = True
        elif lab == "C" and seen_d and b >= 8:
            return pos
        pos += b
    return None


def family(t):
    f = t["feat"]
    if t["mood"] != "high":
        return "V"
    if f["bars"] < 128:
        return "K"
    late = f["first_drop"] is None or f["first_drop"] >= 32
    nb = f["n_breaks"]
    return ("A" if nb == 0 else "B" if nb == 1 else "C") + ("2" if late else "1")


def mult(b, k):
    return b > 0 and abs(b / k - round(b / k)) < 1e-9


ZMIN, ZMAX = min(ZL.values()), max(ZL.values())


def derive(t):
    f, runs, phr, total = t["feat"], t["runs"], t["phr"], t["feat"]["bars"]
    hi = t["mood"] == "high"
    a = anlz.get(t["id"], {})
    g = a.get("grid") or {}
    cu = a.get("cues") or {}
    bar_s = 240.0 / t["bpm"] if t["bpm"] > 0 else None
    pos = 0.0
    cs, ds, us = [], [], []
    for lab, b in runs:
        if lab == "C":
            cs.append((pos, b))
        elif lab == "D":
            ds.append((pos, b))
        elif lab == "U":
            us.append((pos, b))
        pos += b
    body = [b for _, b in phr[:-1]] or [b for _, b in phr]
    d = {}
    # ---- the 7 planned columns
    d["P intro bars"] = f["intro"]
    d["P main entry bar"] = f["first_drop"]
    d["P drop-after-break bar"] = post_break_drop(t)
    d["P drop count"] = f["drops"]
    d["P break share % (high)"] = f["sh_D"] * 100 if hi else None
    d["P outro bars"] = f["outro"]
    d["P total bars"] = total
    # ---- phrase candidates
    d["longest break bars"] = max((b for _, b in ds), default=0.0) if hi else None
    d["break count (>=4 bars)"] = sum(1 for _, b in ds if b >= 4) if hi else None
    d["longest main run bars"] = max((b for _, b in cs), default=0.0)
    d["main share %"] = f["sh_C"] * 100
    d["build-up share % (high)"] = f["sh_U"] * 100 if hi else None
    d["longest build-up bars (high)"] = max((b for _, b in us), default=0.0) if hi else None
    d["build-up count (high)"] = len(us) if hi else None
    d["first drop pos %"] = cs[0][0] / total * 100 if cs and total else None
    d["last drop pos %"] = cs[-1][0] / total * 100 if cs and total else None
    d["last drop start -> end bars"] = total - cs[-1][0] if cs else None
    d["tail after last main bars"] = total - (cs[-1][0] + cs[-1][1]) if cs else None
    d["first main run bars"] = cs[0][1] if cs else None
    d["last main run bars"] = cs[-1][1] if cs else None
    d["longest gap between mains bars"] = (
        max(cs[i + 1][0] - (cs[i][0] + cs[i][1]) for i in range(len(cs) - 1)) if len(cs) > 1 else 0.0
    )
    msum = sum(b for _, b in cs)
    d["main centre of mass %"] = (
        sum(b * (p + b / 2) for p, b in cs) / msum / total * 100 if msum and total else None
    )
    d["energy index 0-100"] = (
        (sum(ZL.get(lab, 0.0) * b for lab, b in runs) / total - ZMIN) / (ZMAX - ZMIN) * 100
        if total
        else None
    )
    d["drops >= 8 bars"] = f["drops8"]
    d["phrases multiple of 8 bars %"] = sum(1 for b in body if mult(b, 8)) / len(body) * 100
    d["phrases multiple of 4 bars %"] = sum(1 for b in body if mult(b, 4)) / len(body) * 100
    d["odd phrases (not x4 bars)"] = sum(1 for b in body if not mult(b, 4))
    d["phrases not x8 bars"] = sum(1 for b in body if not mult(b, 8))
    d["short phrases (<4 bars)"] = sum(1 for b in body if b < 4)
    d["phrase count"] = len(phr)
    d["run count"] = len(runs)
    d["median phrase bars"] = float(np.median(body))
    d["intro seconds"] = f["intro"] * bar_s if bar_s else None
    d["outro seconds"] = f["outro"] * bar_s if bar_s else None
    d["main entry seconds"] = f["first_drop"] * bar_s if bar_s and f["first_drop"] is not None else None
    d["outro - intro bars"] = f["outro"] - f["intro"]
    d["fill-in count"] = t["fills"]
    d["fill-in share %"] = t["fills"] / len(phr) * 100
    d["verse share % (mid/low)"] = f["sh_V"] * 100 if not hi else None
    d["bridge share % (mid/low)"] = f["sh_B"] * 100 if not hi else None
    # flags
    d["F intro >= 16 bars"] = int(f["intro"] >= 16)
    d["F outro >= 16 bars"] = int(f["outro"] >= 16)
    d["F DJ-friendly (both >= 16)"] = int(f["intro"] >= 16 and f["outro"] >= 16)
    d["F intro >= 8 and outro >= 8"] = int(f["intro"] >= 8 and f["outro"] >= 8)
    d["F main entry >= 16 bars"] = int(f["first_drop"] is not None and f["first_drop"] >= 16)
    d["F tail after main >= 16 bars"] = int(bool(cs) and total - (cs[-1][0] + cs[-1][1]) >= 16)
    d["F has intro"] = int(runs[0][0] == "I")
    d["F has outro"] = int(runs[-1][0] == "O")
    d["F all phrases x4 bars"] = int(all(mult(b, 4) for b in body))
    # raw variant flags (high mood): Intro 1/2, Outro 1/2 = k1 of first / last phrase
    ents = sorted(raw[t["id"]]["pssi"]["e"], key=lambda e: e[0])
    d["C intro variant (high)"] = (f"I{ents[0][2] + 1}" if ents[0][1] == 1 else "none") if hi else None
    d["C outro variant (high)"] = (f"O{ents[-1][2] + 1}" if ents[-1][1] == 6 else "none") if hi else None
    d["C bank"] = str(raw[t["id"]]["pssi"]["bank"])
    # ---- grid
    if g.get("present"):
        d["G tempo changes (distinct-1)"] = g["tempo_changes"]
        d["G tempo switches along grid"] = g["tempo_switches"]
        d["G bpm min"] = g["bpm_min"]
        d["G bpm max"] = g["bpm_max"]
        d["G bpm drift (max-min)"] = g["bpm_max"] - g["bpm_min"]
        d["F constant tempo"] = int(g["tempo_distinct"] == 1)
        d["G first beat ms"] = g["first_beat_ms"]
        d["G first downbeat ms"] = g["first_downbeat_ms"]
        d["G grid beats - phrase end beat"] = g["beats"] - t["end"]
        d["F pickup (first beat not a 1)"] = int((t["grid"] or {}).get("bib0", 1) != 1)
        if t["secs"] > 0:
            d["G grid cover % of duration"] = (g["last_beat_ms"] - g["first_beat_ms"]) / 10 / t["secs"]
    # ---- cues
    if cu:
        d["Q hot cues"] = cu.get("hot", 0)
        d["Q memory cues"] = cu.get("memory", 0)
        d["Q loops"] = cu.get("loops", 0)
        d["Q cue comments"] = cu.get("comments", 0)
        d["F prepared (any cue)"] = int(cu.get("hot", 0) + cu.get("memory", 0) > 0)
    return d


F = [derive(t) for t in tracks]
names = []
for d in F:
    for k in d:
        if k not in names:
            names.append(k)
mood = np.array([t["mood"] for t in tracks])
fam = np.array([family(t) for t in tracks])

# ------------------------------------------------------------------ copy pairs (t2b / t8 path)
tkey = C.defaultdict(list)
secs = [t["secs"] for t in tracks]
bpm = [t["bpm"] for t in tracks]
for i, t in enumerate(tracks):
    k = re.sub(r"[^a-z0-9]+", " ", t["title"].lower()).strip()
    if len(k) >= 8:
        tkey[k].append(i)
tp = [
    (v[a], v[b])
    for v in tkey.values()
    for a in range(len(v))
    for b in range(a + 1, len(v))
    if abs(secs[v[a]] - secs[v[b]]) <= 3 and abs(bpm[v[a]] - bpm[v[b]]) <= 1
]
rp = [(int(a), int(b)) for a, b in rng.integers(0, N, (200000, 2)) if a != b]


def val(i, name):
    return F[i].get(name)


def agree(pairs, name, tol, need_one=False):
    ok = []
    for a, b in pairs:
        x, y = val(a, name), val(b, name)
        if x is None and y is None:
            if not need_one:
                ok.append(True)
            continue
        if x is None or y is None:
            ok.append(False)
        elif isinstance(x, str) or isinstance(y, str):
            ok.append(x == y)
        else:
            ok.append(abs(x - y) <= tol + 1e-9)
    return (float(np.mean(ok)) if ok else float("nan")), len(ok)


def spearman(x, y):
    if len(x) < 30 or np.all(x == x[0]) or np.all(y == y[0]):
        return float("nan")
    return float(np.corrcoef(rankdata(x), rankdata(y))[0, 1])


def col(name, idx=None):
    idx = range(N) if idx is None else idx
    return [val(i, name) for i in idx]


def cramers_v(x, y):
    xs, ys = sorted(set(x)), sorted(set(y))
    if len(xs) < 2 or len(ys) < 2:
        return float("nan")
    tab = np.zeros((len(xs), len(ys)))
    xi = {v: i for i, v in enumerate(xs)}
    yi = {v: i for i, v in enumerate(ys)}
    for a, b in zip(x, y):
        tab[xi[a], yi[b]] += 1
    n = tab.sum()
    exp = tab.sum(1, keepdims=True) * tab.sum(0, keepdims=True) / n
    chi = ((tab - exp) ** 2 / np.where(exp > 0, exp, 1)).sum()
    return float(np.sqrt(chi / n / (min(tab.shape) - 1)))


def binned(v):
    v = np.asarray(v, float)
    if len(set(v.tolist())) <= 6:
        return [str(x) for x in v]
    q = np.unique(np.quantile(v, [0.2, 0.4, 0.6, 0.8]))
    return [str(int(np.searchsorted(q, x, side="right"))) for x in v]


def eta(cat, v):
    v = np.asarray(v, float)
    cats = sorted(set(cat))
    cat = np.asarray(cat)
    ss_t = ((v - v.mean()) ** 2).sum()
    if ss_t == 0:
        return float("nan")
    ss_b = sum((cat == c).sum() * (v[cat == c].mean() - v.mean()) ** 2 for c in cats)
    return float(np.sqrt(ss_b / ss_t))


PLANNED = [n for n in names if n.startswith("P ")]
lines = []


def out(s=""):
    print(s)
    lines.append(s)


out(f"tracks with PSSI {N} of {LIB} | mood {dict(C.Counter(mood))} | copy pairs {len(tp)}")
pm = C.Counter(tuple(sorted((mood[a], mood[b]))) for a, b in tp)
out(f"copy pairs by mood: {dict(pm)} | distinct tracks in pairs: {len({i for p in tp for i in p})}")
out(f"family agreement across copies: {np.mean([fam[a] == fam[b] for a, b in tp]):.3f} | mood agreement: {np.mean([mood[a] == mood[b] for a, b in tp]):.3f}")
out()
hdr = ("name | moods | n defined | cover % lib | copy = / +-1 / +-4 / +-8 (None==None ok) | copy = / +-1 on pairs with a value (n) | "
       "chance = / +-1 | p10 / p50 / p90 | top value : share | distinct | max|rho| planned all (which) | max|rho| planned high | eta family")
out(hdr)
res = {}
for name in names:
    is_cat = name.startswith("C ")
    v_all = col(name)
    di = [i for i, v in enumerate(v_all) if v is not None]
    moods_def = "+".join(m for m in ("high", "mid", "low") if any(mood[i] == m for i in di))
    r = {"n": len(di), "cover": len(di) / LIB * 100, "moods": moods_def}
    tols = (0,) if is_cat else (0, 1, 4, 8)
    r["copy_all"] = [agree(tp, name, tol)[0] for tol in tols]
    r["copy_def"] = [agree(tp, name, tol, True)[0] for tol in tols[:2]]
    r["copy_def_n"] = agree(tp, name, 0, True)[1]
    r["chance"] = [agree(rp, name, tol)[0] for tol in tols[:2]]
    vals = [v_all[i] for i in di]
    if is_cat:
        cnt = C.Counter(vals)
        top, share = cnt.most_common(1)[0]
        r.update(top=top, sat=share / len(vals), distinct=len(cnt), pct=None)
        vs = {}
        for p in PLANNED:
            idx = [i for i in di if val(i, p) is not None]
            vs[p] = cramers_v([v_all[i] for i in idx], binned([val(i, p) for i in idx]))
        vs["family"] = cramers_v(vals, [fam[i] for i in di])
        best = max(vs, key=lambda k: (vs[k] if vs[k] == vs[k] else -1))
        r.update(red=vs[best], red_with=best + " (V)", red_hi=float("nan"), eta=vs["family"])
    else:
        arr = np.array(vals, float)
        cnt = C.Counter(np.round(arr).astype(int).tolist())
        top, share = cnt.most_common(1)[0]
        r.update(top=top, sat=share / len(arr), distinct=len(cnt), pct=np.percentile(arr, [10, 50, 90]).round(2).tolist())
        best, best_hi, which = 0.0, 0.0, "-"
        for p in PLANNED:
            if p == name:
                continue
            idx = [i for i in di if val(i, p) is not None]
            if len(idx) >= 100:
                rho = abs(spearman(np.array([v_all[i] for i in idx], float), np.array([val(i, p) for i in idx], float)))
                if rho == rho and rho > best:
                    best, which = rho, p
            idx = [i for i in idx if mood[i] == "high"]
            if len(idx) >= 100:
                rho = abs(spearman(np.array([v_all[i] for i in idx], float), np.array([val(i, p) for i in idx], float)))
                if rho == rho and rho > best_hi:
                    best_hi = rho
        r.update(red=best, red_with=which, red_hi=best_hi, eta=eta([fam[i] for i in di], arr))
        if name.startswith("F "):
            a_ = np.array([(val(a, name), val(b, name)) for a, b in tp if val(a, name) is not None and val(b, name) is not None])
            if len(a_):
                po = np.mean(a_[:, 0] == a_[:, 1])
                p1 = arr.mean()
                pe = p1 * p1 + (1 - p1) * (1 - p1)
                r["kappa"] = float((po - pe) / (1 - pe)) if pe < 1 else float("nan")
                r["rate"] = float(p1)
    res[name] = r
    pct = "-" if r["pct"] is None else " / ".join(f"{x:g}" for x in r["pct"])
    extra = f" | rate {r['rate']:.3f} kappa {r['kappa']:.2f}" if "kappa" in r else ""
    out(f"{name} | {r['moods']} | {r['n']} | {r['cover']:.1f} | " + " / ".join(f"{x:.2f}" for x in r["copy_all"]) + " | "
        + " / ".join(f"{x:.2f}" for x in r["copy_def"]) + f" ({r['copy_def_n']}) | " + " / ".join(f"{x:.2f}" for x in r["chance"])
        + f" | {pct} | {r['top']} : {r['sat']:.2f} | {r['distinct']} | {r['red']:.2f} ({r['red_with']}) | {r['red_hi']:.2f} | {r['eta']:.2f}{extra}")

# ------------------------------------------------------------------ redundancy among candidates
out("\ncandidate pairs with |Spearman| > 0.85 (all tracks where both defined, n >= 100):")
num = [n for n in names if not n.startswith("C ")]
for i, a in enumerate(num):
    for b in num[i + 1:]:
        idx = [k for k in range(N) if val(k, a) is not None and val(k, b) is not None]
        if len(idx) < 100:
            continue
        rho = spearman(np.array([val(k, a) for k in idx], float), np.array([val(k, b) for k in idx], float))
        if rho == rho and abs(rho) > 0.85:
            out(f"  {rho:+.2f} | {a} <-> {b} (n {len(idx)})")

# ------------------------------------------------------------------ seconds vs bars: more than a unit change?
out("\nseconds vs bars (order):")
for s, b in (("intro seconds", "P intro bars"), ("outro seconds", "P outro bars"), ("main entry seconds", "P main entry bar")):
    idx = [k for k in range(N) if val(k, s) is not None and val(k, b) is not None]
    x, y = np.array([val(k, s) for k in idx], float), np.array([val(k, b) for k in idx], float)
    pr = rng.integers(0, len(idx), (200000, 2))
    dx, dy = x[pr[:, 0]] - x[pr[:, 1]], y[pr[:, 0]] - y[pr[:, 1]]
    flip = np.mean((dx * dy < 0))
    tie_b = np.mean(dy == 0)
    split = np.mean((dy == 0) & (np.abs(dx) > 1))
    out(f"  {s}: Spearman vs bars {spearman(x, y):.3f} | random pairs: order flipped {flip:.3f}, tied in bars {tie_b:.3f}, tied in bars but > 1 s apart {split:.3f} | seconds p10/p50/p90 "
        + " / ".join(f"{v:.0f}" for v in np.percentile(x, [10, 50, 90])))
bp = np.array([t["bpm"] for t in tracks if t["bpm"] > 0])
out(f"  BPM p10/p50/p90: {np.percentile(bp, [10, 50, 90]).round(1).tolist()} -> bar duration {(240 / np.percentile(bp, [90, 50, 10])).round(2).tolist()} s")

# ------------------------------------------------------------------ mix partner (outro A vs intro B)
out("\nmix partner = |outro bars(A) - intro bars(B)|:")
for name in ("P intro bars", "P outro bars", "P main entry bar", "tail after last main bars"):
    v = [val(k, name) for k in range(N)]
    c = C.Counter(None if x is None else round(x) for x in v)
    q8 = float(np.mean([(val(a, name) is None and val(b, name) is None) or (val(a, name) is not None and val(b, name) is not None and round(val(a, name) / 8) == round(val(b, name) / 8)) for a, b in tp]))
    out(f"  {name}: copies = {agree(tp, name, 0)[0]:.2f}, +-1 {agree(tp, name, 1)[0]:.2f}, +-2 {agree(tp, name, 2)[0]:.2f}, +-4 {agree(tp, name, 4)[0]:.2f}, same 8-bar bin {q8:.2f} | top values "
        + ", ".join(f"{k}:{n / N:.2f}" for k, n in c.most_common(6)))
intro = np.array([val(k, "P intro bars") for k in range(N)])
outro = np.array([val(k, "P outro bars") for k in range(N)])
samp = rng.integers(0, N, 400)
tied0 = [np.mean(np.abs(intro - outro[s]) <= 0.5) for s in samp]
tied4 = [np.mean(np.abs(intro - outro[s]) <= 4) for s in samp]
out(f"  for a random seed A: share of library with intro within 0.5 bar of A's outro: median {np.median(tied0):.2f} (p10 {np.percentile(tied0, 10):.2f}, p90 {np.percentile(tied0, 90):.2f}); within 4 bars: median {np.median(tied4):.2f}")
out(f"  intro == 0: {np.mean(intro == 0):.3f} | outro == 0: {np.mean(outro == 0):.3f} | intro not a whole bar: {np.mean(np.abs(intro - np.round(intro)) > 1e-9):.3f} | outro not a whole bar: {np.mean(np.abs(outro - np.round(outro)) > 1e-9):.3f}")
out(f"  intro multiple of 8: {np.mean([mult(x, 8) for x in intro]):.3f} | outro multiple of 8: {np.mean([mult(x, 8) for x in outro]):.3f} (outro = last phrase, cut by end_beat)")
d_io = [abs(val(a, "P outro bars") - val(b, "P outro bars")) for a, b in tp]
d_in = [abs(val(a, "P intro bars") - val(b, "P intro bars")) for a, b in tp]
out(f"  copy |d intro| p50/p90/max: {np.percentile(d_in, [50, 90, 100]).round(2).tolist()} | copy |d outro| p50/p90/max: {np.percentile(d_io, [50, 90, 100]).round(2).tolist()}")

# ------------------------------------------------------------------ per-mood detail for the mood-agnostic candidates
out("\nper mood (median | saturation) for selected candidates:")
for name in ("longest main run bars", "main share %", "first drop pos %", "last drop pos %", "tail after last main bars", "phrase count", "median phrase bars",
             "phrases multiple of 8 bars %", "odd phrases (not x4 bars)", "fill-in count", "P drop count", "P intro bars", "P outro bars"):
    parts = []
    for m in ("high", "mid", "low"):
        v = np.array([val(k, name) for k in range(N) if mood[k] == m and val(k, name) is not None], float)
        if len(v):
            c = C.Counter(np.round(v).astype(int).tolist()).most_common(1)[0]
            parts.append(f"{m} n={len(v)} med {np.median(v):g} top {c[0]}:{c[1] / len(v):.2f}")
    out(f"  {name}: " + " | ".join(parts))

(OUT / "features.txt").write_text("\n".join(lines), encoding="utf-8")
json.dump(res, open(OUT / "features.json", "w", encoding="utf-8"), indent=1, default=float)
json.dump({"pairs": [[tracks[a]["id"], tracks[b]["id"]] for a, b in tp]}, open(OUT / "copy_pairs_ids.json", "w", encoding="utf-8"))
