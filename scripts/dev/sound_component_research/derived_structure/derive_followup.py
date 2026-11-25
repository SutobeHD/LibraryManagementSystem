"""Follow-up to derive_features.py: grid / cue / status facts for the whole library, a no-audio
sanity check of the copy pairs, first-beat tolerance by file format, phrase-variant semantics,
"big drop" variants, bootstrap intervals. Read-only inputs, output tmp/sc-derived-struct/followup.txt."""
import collections as C
import json
import os
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
from common import load  # noqa: E402

OUT = ROOT / "tmp" / "sc-derived-struct"
rng = np.random.default_rng(20261122)
tracks, meta, anlz = load()
N = len(tracks)
LIB = len(meta)
raw = {}
for line in open(common.SC / "phrases.jsonl", encoding="utf-8"):
    r = json.loads(line)
    raw[r["id"]] = r
lines = []


def out(s=""):
    print(s)
    lines.append(s)


def sp(x, y):
    return float(np.corrcoef(rankdata(x), rankdata(y))[0, 1])


mood = np.array([t["mood"] for t in tracks])
secs = [t["secs"] for t in tracks]
bpm = [t["bpm"] for t in tracks]
tkey = C.defaultdict(list)
for i, t in enumerate(tracks):
    k = re.sub(r"[^a-z0-9]+", " ", t["title"].lower()).strip()
    if len(k) >= 8:
        tkey[k].append(i)
tp = [(v[a], v[b]) for v in tkey.values() for a in range(len(v)) for b in range(a + 1, len(v))
      if abs(secs[v[a]] - secs[v[b]]) <= 3 and abs(bpm[v[a]] - bpm[v[b]]) <= 1]


def kind(i):
    p = meta[tracks[i]["id"]].get("path") or ""
    return "stream" if p.startswith("soundcloud:") else (os.path.splitext(p)[1].lower().lstrip(".") or "?")


# ------------------------------------------------------------------ 1. how the copy pairs look (no audio)
out(f"== copy pairs: {len(tp)} pairs, rule = same normalised title (>= 8 chars), duration +-3 s, BPM +-1; no fingerprint ==")
out(f"file kinds per pair: {dict(C.Counter(' / '.join(sorted((kind(a), kind(b)))) for a, b in tp).most_common())}")
sizes = C.Counter(len(v) for v in tkey.values() if len(v) > 1)
grp = C.Counter()
for a, b in tp:
    grp[re.sub(r"[^a-z0-9]+", " ", tracks[a]["title"].lower()).strip()] += 1
out(f"pairs per title group: {dict(C.Counter(grp.values()))} (1 = a plain pair, 3 = a triple, ...)")
out(f"same path string within a pair: {sum(1 for a, b in tp if meta[tracks[a]['id']].get('path') == meta[tracks[b]['id']].get('path'))}")
out(f"|d duration| s p50/p90/max: {np.percentile([abs(secs[a] - secs[b]) for a, b in tp], [50, 90, 100]).round(2).tolist()} | |d total bars| p50/p90/max: "
    f"{np.percentile([abs(tracks[a]['bars'] - tracks[b]['bars']) for a, b in tp], [50, 90, 100]).round(2).tolist()}")


def curve(i, key="band_detail"):
    c = (anlz.get(tracks[i]["id"], {}).get(key) or {}).get("curve")
    return np.array(c, float) if c else None


def ccorr(pairs):
    o = []
    for a, b in pairs:
        x, y = curve(a), curve(b)
        if x is not None and y is not None and x.std() > 0 and y.std() > 0:
            o.append(float(np.corrcoef(x, y)[0, 1]))
    return np.array(o)


cc = ccorr(tp)
rp = [(int(a), int(b)) for a, b in rng.integers(0, N, (5000, 2)) if a != b]
cr = ccorr(rp)
out(f"waveform loudness curve (10 points, from ANLZ) correlation inside pairs: n {len(cc)} p10/p50/p90 {np.percentile(cc, [10, 50, 90]).round(3).tolist()} min {cc.min():.3f} "
    f"| share > 0.95: {np.mean(cc > 0.95):.2f}, > 0.90: {np.mean(cc > 0.90):.2f} | random pairs p50/p90/p99 {np.percentile(cr, [50, 90, 99]).round(3).tolist()}, share > 0.95: {np.mean(cr > 0.95):.3f}")
low = [(tracks[a]["id"], tracks[b]["id"], round(float(c), 2)) for (a, b), c in zip(tp, cc) if c < 0.9]
out(f"pairs with curve correlation < 0.90 (ids): {low}")

# ------------------------------------------------------------------ 2. grid over the whole library
rows = list(anlz.values())
g_ok = [r for r in rows if (r.get("grid") or {}).get("present")]
out(f"\n== grid (anlz.jsonl, {len(rows)} rows, library {LIB}) ==")
out(f"grid present: {len(g_ok)} ({len(g_ok) / LIB:.3%}) | missing: {[r['id'] for r in rows if not (r.get('grid') or {}).get('present')]}")
tc = C.Counter(r["grid"]["tempo_changes"] for r in g_ok)
ts = np.array([r["grid"]["tempo_switches"] for r in g_ok])
dr = np.array([r["grid"]["bpm_max"] - r["grid"]["bpm_min"] for r in g_ok])
out(f"tempo changes (distinct - 1): 0 for {tc[0]} ({tc[0] / len(g_ok):.3%}); > 0: {len(g_ok) - tc[0]} tracks; values {dict(sorted(tc.items()))}")
var = [r for r in g_ok if r["grid"]["tempo_changes"] > 0]
out(f"variable-tempo tracks: switches p50/max {np.percentile([r['grid']['tempo_switches'] for r in var], [50, 100]).tolist()} | drift BPM p50/max "
    f"{np.percentile([r['grid']['bpm_max'] - r['grid']['bpm_min'] for r in var], [50, 100]).round(2).tolist()} | drift > 2 BPM: {sum(1 for r in var if r['grid']['bpm_max'] - r['grid']['bpm_min'] > 2)} | ids {[r['id'] for r in var]}")
dur = {i: float(m.get("TotalTime") or 0) for i, m in meta.items()}
out(f"variable-tempo tracks longer than 15 min: {sum(1 for r in var if dur.get(r['id'], 0) > 900)} | switches > 0 overall: {int((ts > 0).sum())} | drift > 0.05 overall: {int((dr > 0.05).sum())}")
dbb = np.array([abs(r["grid"]["bpm_first"] - float(meta[r["id"]].get("BPM") or 0)) for r in g_ok if r["id"] in meta])
out(f"|grid bpm - library BPM| > 0.05: {int((dbb > 0.05).sum())} of {len(dbb)} -> BPM min / max carry no information beyond the BPM column for constant grids")
fb = np.array([r["grid"]["first_beat_ms"] for r in g_ok])
fd = np.array([r["grid"]["first_downbeat_ms"] or 0 for r in g_ok])
out(f"first beat ms p10/p50/p90/p99: {np.percentile(fb, [10, 50, 90, 99]).tolist()} | > 500 ms: {np.mean(fb > 500):.3f} | > 2000 ms: {np.mean(fb > 2000):.3f} | first downbeat ms p10/p50/p90: {np.percentile(fd, [10, 50, 90]).tolist()}")
by = C.defaultdict(list)
for i, t in enumerate(tracks):
    g = (anlz.get(t["id"], {}).get("grid") or {})
    if g.get("present"):
        by[kind(i)].append(g["first_beat_ms"])
out("first beat ms median by file kind: " + ", ".join(f"{k} {np.median(v):.0f} (n {len(v)})" for k, v in sorted(by.items(), key=lambda kv: -len(kv[1]))))


def fbm(i):
    return (anlz.get(tracks[i]["id"], {}).get("grid") or {}).get("first_beat_ms")


for label, sel in (("all pairs", lambda a, b: True), ("same file kind", lambda a, b: kind(a) == kind(b)), ("different file kind", lambda a, b: kind(a) != kind(b))):
    d = np.array([abs(fbm(a) - fbm(b)) for a, b in tp if sel(a, b) and fbm(a) is not None and fbm(b) is not None])
    if len(d):
        out(f"  first beat copies ({label}, n {len(d)}): = {np.mean(d == 0):.2f} | +-1 ms {np.mean(d <= 1):.2f} | +-10 {np.mean(d <= 10):.2f} | +-30 {np.mean(d <= 30):.2f} | +-50 {np.mean(d <= 50):.2f} | +-100 {np.mean(d <= 100):.2f} | median {np.median(d):.0f} ms")
d = np.array([abs(fbm(a) - fbm(b)) for a, b in rp if fbm(a) is not None and fbm(b) is not None])
out(f"  first beat random pairs: +-10 ms {np.mean(d <= 10):.2f} | +-50 {np.mean(d <= 50):.2f}")
fb_class = lambda v: 0 if v < 100 else (1 if v < 1000 else 2)  # noqa: E731
ag = np.mean([fb_class(fbm(a)) == fb_class(fbm(b)) for a, b in tp])
cl = C.Counter(fb_class(v) for v in fb)
out(f"  3 classes (< 0.1 s / 0.1-1 s / > 1 s before the first beat): library {dict(sorted((k, round(v / len(fb), 3)) for k, v in cl.items()))} | copies agree {ag:.2f}")

# ------------------------------------------------------------------ 3. cues over the whole library
out("\n== cues in ANLZ (PCOB / PCO2) ==")
cu = [r.get("cues") or {} for r in rows]
for k in ("hot", "memory", "loops", "comments"):
    v = np.array([c.get(k, 0) for c in cu])
    out(f"{k}: tracks with > 0: {int((v > 0).sum())} of {len(v)} ({np.mean(v > 0):.3%}) | max {int(v.max())} | ids {[r['id'] for r, c in zip(rows, cu) if c.get(k, 0) > 0][:12]}")
out(f"PCO2 tag present: {sum(1 for c in cu if c.get('pco2_present'))} | any colour: {sum(1 for c in cu if c.get('colours'))}")
tags = C.Counter()
for r in rows:
    for f_, tl in (r.get("tags") or {}).items():
        for t_ in set(tl):
            tags[(f_, t_)] += 1
out(f"tag presence per file: {dict(sorted(tags.items()))}")

# ------------------------------------------------------------------ 4. status category
out("\n== 'analysed in Rekordbox?' status over the library ==")


def status(tid):
    a = anlz.get(tid) or {}
    r = raw.get(tid) or {}
    fl = a.get("files") or {}
    if a.get("status") in (None, "no_anlz_path", "missing") or not any(fl.values()):
        return "1 no ANLZ files"
    g = a.get("grid") or {}
    if not g.get("present"):
        return "2 no beat grid"
    p = r.get("pssi")
    if not p:
        return "3 grid, no phrases"
    e = sorted(p["e"], key=lambda x: x[0])
    st = [x[0] for x in e]
    bad = p["mood"] not in (1, 2, 3) or len(e) > 1024 or any(b <= a_ for a_, b in zip(st, st[1:])) or p["end_beat"] > g["beats"] + 64
    if bad:
        return "4 phrases flagged by the reader (mood / order / end beyond grid)"
    bars = (p["end_beat"] - st[0]) / 4
    secs_ = dur.get(tid, 0)
    if len(e) > 60 or secs_ > 900 or bars < 48 or secs_ < 90 or abs(g["beats"] - p["end_beat"]) > 64:
        return "5 phrases present, excluded from similarity (mix / very short / end vs grid)"
    if g["tempo_changes"] > 0:
        return "6 complete, variable tempo"
    return "7 complete"


stc = C.Counter(status(i) for i in meta)
for k, v in sorted(stc.items()):
    out(f"  {k}: {v} ({v / LIB:.2%})")
out(f"  writer guess: {dict(C.Counter((r.get('writer') or {}).get('guess') for r in rows))} | PSSI masked: {dict(C.Counter((r.get('pssi') or {}).get('masked') for r in rows))} "
    f"| files: {dict(C.Counter(''.join(k[0] if v else '-' for k, v in sorted((r.get('files') or {}).items())) for r in rows))} | row status: {dict(C.Counter(r.get('status') for r in rows))}")
idx = {t["id"]: i for i, t in enumerate(tracks)}
st_pair = np.mean([status(tracks[a]["id"]) == status(tracks[b]["id"]) for a, b in tp])
out(f"  status equal across copies: {st_pair:.2f}")

# ------------------------------------------------------------------ 5. phrase variants (high mood): Intro 1/2, Outro 1/2
out("\n== high-mood phrase variants (k1 / k2 / k3 flags) ==")
hi = [i for i in range(N) if mood[i] == "high"]


def ents(i):
    return sorted(raw[tracks[i]["id"]]["pssi"]["e"], key=lambda e: e[0])


def rel(i, pos):
    c = curve(i)
    return None if c is None or c.max() <= 0 else float(c[pos] / c.max())


for name, first, kindid, pos in (("intro", True, 1, 0), ("outro", False, 6, 9)):
    v = {0: [], 1: []}
    bars = {0: [], 1: []}
    for i in hi:
        e = ents(i)[0 if first else -1]
        if e[1] != kindid:
            continue
        x = rel(i, pos)
        if x is not None:
            v[e[2]].append(x)
        bars[e[2]].append(tracks[i]["feat"]["intro" if first else "outro"])
    out(f"{name} variant 1 (k1 = 0): n {len(bars[0])}, loudness of the {'first' if first else 'last'} tenth relative to the loudest tenth median {np.median(v[0]):.2f} (p10 {np.percentile(v[0], 10):.2f}, p90 {np.percentile(v[0], 90):.2f}), {name} bars median {np.median(bars[0]):g}")
    out(f"{name} variant 2 (k1 = 1): n {len(bars[1])}, same median {np.median(v[1]):.2f} (p10 {np.percentile(v[1], 10):.2f}, p90 {np.percentile(v[1], 90):.2f}), {name} bars median {np.median(bars[1]):g}")
    a_, b_ = np.array(v[0]), np.array(v[1])
    s = rng.integers(0, len(a_), 100000), rng.integers(0, len(b_), 100000)
    out(f"  P(variant 2 louder than variant 1) = {np.mean(b_[s[1]] > a_[s[0]]):.2f} (0.5 = no difference)")
upv = C.Counter()
for i in hi:
    for e in ents(i):
        if e[1] == 2:
            upv["Up1" if (e[3], e[4]) == (0, 0) else "Up2" if (e[3], e[4]) == (0, 1) else "Up3"] += 1
        if e[1] == 5:
            upv["Chorus1" if e[2] == 0 else "Chorus2"] += 1
out(f"phrase variant counts: {dict(upv)}")
ch1 = np.array([sum(1 for e in ents(i) if e[1] == 5 and e[2] == 0) / max(1, sum(1 for e in ents(i) if e[1] == 5)) for i in hi])
up3 = np.array([sum(1 for e in ents(i) if e[1] == 2 and e[3] == 1) / max(1, sum(1 for e in ents(i) if e[1] == 2)) for i in hi])
out(f"tracks with any Chorus 1: {np.mean(ch1 > 0):.3f} | all Chorus 1: {np.mean(ch1 == 1):.3f} | Up 3 share of Up phrases p10/p50/p90: {np.percentile(up3, [10, 50, 90]).round(2).tolist()} | no Up 3: {np.mean(up3 == 0):.2f}")
hix = {i: k for k, i in enumerate(hi)}
pp = [(a, b) for a, b in tp if a in hix and b in hix]
out(f"copies ({len(pp)} high-high pairs): any Chorus 1 equal {np.mean([(ch1[hix[a]] > 0) == (ch1[hix[b]] > 0) for a, b in pp]):.2f} | Up-3 share within 10 pts {np.mean([abs(up3[hix[a]] - up3[hix[b]]) <= 0.1 for a, b in pp]):.2f}")

# ------------------------------------------------------------------ 6. "big drop" = main that follows the longest gap; other variants
out("\n== extra variants ==")


def cruns(t):
    pos, cs = 0.0, []
    for lab, b in t["runs"]:
        if lab == "C":
            cs.append((pos, b))
        pos += b
    return cs


def big_drop(t):
    cs = cruns(t)
    if len(cs) < 2:
        return None
    k = max(range(len(cs) - 1), key=lambda i: cs[i + 1][0] - (cs[i][0] + cs[i][1]))
    return cs[k + 1][0]


def pbd(t):
    pos, seen = 0.0, False
    for lab, b in t["runs"]:
        if lab == "D" and b >= 4:
            seen = True
        elif lab == "C" and seen and b >= 8:
            return pos
        pos += b
    return None


def agree(vals, tol):
    ok = []
    for a, b in tp:
        x, y = vals[a], vals[b]
        ok.append((x is None and y is None) or (x is not None and y is not None and abs(x - y) <= tol + 1e-9))
    return float(np.mean(ok))


def show(name, vals, planned):
    di = [i for i in range(N) if vals[i] is not None]
    arr = np.array([vals[i] for i in di], float)
    top = C.Counter(np.round(arr).astype(int).tolist()).most_common(1)[0]
    red = []
    for pn, pv in planned.items():
        ix = [i for i in di if pv[i] is not None]
        if len(ix) > 100:
            red.append((abs(sp(np.array([vals[i] for i in ix], float), np.array([pv[i] for i in ix], float))), pn))
    out(f"{name}: defined {len(di)} ({len(di) / LIB:.1%}; moods {dict(C.Counter(mood[di]))}) | copies = {agree(vals, 0):.2f} +-1 {agree(vals, 1):.2f} +-4 {agree(vals, 4):.2f} +-8 {agree(vals, 8):.2f} "
        f"| p10/p50/p90 {np.percentile(arr, [10, 50, 90]).round(1).tolist()} | top {top[0]}:{top[1] / len(arr):.2f} | max rho planned {max(red)[0]:.2f} ({max(red)[1]})")


F = [t["feat"] for t in tracks]
planned = {
    "intro": [f["intro"] for f in F],
    "main entry": [f["first_drop"] for f in F],
    "drop after break": [pbd(t) for t in tracks],
    "drop count": [f["drops"] for f in F],
    "break share": [f["sh_D"] * 100 if mood[i] == "high" else None for i, f in enumerate(F)],
    "outro": [f["outro"] for f in F],
    "total bars": [f["bars"] for f in F],
}
bd = [big_drop(t) for t in tracks]
show("big drop bar (main after the longest gap, any mood)", bd, planned)
gap = [max((cs[i + 1][0] - (cs[i][0] + cs[i][1]) for i in range(len(cs) - 1)), default=0.0) for cs in map(cruns, tracks)]
show("longest gap between mains bars", gap, planned)
lde = [(t["bars"] - cruns(t)[-1][0]) if cruns(t) else None for t in tracks]
show("last drop start -> end bars", lde, planned)
lml = [cruns(t)[-1][1] if cruns(t) else None for t in tracks]
lmr = [max((b for _, b in cruns(t)), default=0.0) for t in tracks]
ldp = [(cruns(t)[-1][0] / t["bars"] * 100) if cruns(t) and t["bars"] else None for t in tracks]
lb = [max((b for lab, b in t["runs"] if lab == "D"), default=0.0) if mood[i] == "high" else None for i, t in enumerate(tracks)]


def rho(a, b):
    ix = [i for i in range(N) if a[i] is not None and b[i] is not None]
    return sp(np.array([a[i] for i in ix], float), np.array([b[i] for i in ix], float)), len(ix)


for n1, v1, n2, v2 in (("big drop bar", bd, "drop after break", planned["drop after break"]), ("longest gap", gap, "longest break", lb), ("longest gap", gap, "break share", planned["break share"]),
                       ("last drop -> end", lde, "last drop pos %", ldp), ("last drop -> end", lde, "last main run", lml), ("last drop -> end", lde, "outro", planned["outro"]),
                       ("longest main", lmr, "last main run", lml), ("longest main", lmr, "last drop -> end", lde), ("last drop pos %", ldp, "drop count", planned["drop count"])):
    r_, n_ = rho(v1, v2)
    out(f"  rho {n1} vs {n2}: {r_:+.2f} (n {n_})")
same = np.mean([bd[i] == planned["drop after break"][i] for i in range(N) if bd[i] is not None and planned["drop after break"][i] is not None])
out(f"  big drop bar == drop-after-break bar where both exist: {same:.2f}")
for thr in (16, 32, 64):
    v = [int(f["first_drop"] is not None and f["first_drop"] >= thr) for f in F]
    po = np.mean([v[a] == v[b] for a, b in tp])
    p1 = np.mean(v)
    pe = p1 * p1 + (1 - p1) ** 2
    out(f"  flag main entry >= {thr} bars: rate {p1:.3f} | copies agree {po:.2f} | kappa {(po - pe) / (1 - pe):.2f}")
for thr in (1, 4):
    v = [int(sum(1 for _, b in (t["phr"][:-1] or t["phr"]) if not (b > 0 and abs(b / 4 - round(b / 4)) < 1e-9)) >= thr) for t in tracks]
    po = np.mean([v[a] == v[b] for a, b in tp])
    p1 = np.mean(v)
    pe = p1 * p1 + (1 - p1) ** 2
    out(f"  flag odd phrases >= {thr}: rate {p1:.3f} | copies agree {po:.2f} | kappa {(po - pe) / (1 - pe):.2f} | by mood {({m: round(float(np.mean([v[i] for i in range(N) if mood[i] == m])), 2) for m in ('high', 'mid', 'low')})}")
odd = [sum(1 for _, b in (t["phr"][:-1] or t["phr"]) if not (b > 0 and abs(b / 4 - round(b / 4)) < 1e-9)) for t in tracks]
oc = lambda n: 0 if n == 0 else (1 if n <= 3 else 2)  # noqa: E731
out(f"  odd-phrase classes 0 / 1-3 / 4+: library {dict(sorted(C.Counter(oc(n) for n in odd).items()))} | copies agree {np.mean([oc(odd[a]) == oc(odd[b]) for a, b in tp]):.2f}")
fills = [t["fills"] for t in tracks]
fh = np.array([fills[i] for i in hi])
out(f"  fill-in count, high mood only: p10/p50/p90 {np.percentile(fh, [10, 50, 90]).tolist()} | top {C.Counter(fh.tolist()).most_common(1)[0]} of {len(fh)} | zero share {np.mean(fh == 0):.3f} | rho vs phrase count {sp(fh, np.array([F[i]['n_phr'] for i in hi])):.2f} "
    f"| high-high copies = {np.mean([fills[a] == fills[b] for a, b in pp]):.2f} +-1 {np.mean([abs(fills[a] - fills[b]) <= 1 for a, b in pp]):.2f}")

# ------------------------------------------------------------------ 7. bootstrap interval for a copy-agreement figure
out("\n== uncertainty of copy figures (n = 92 pairs, 166 tracks; cluster bootstrap over title groups) ==")
groups = C.defaultdict(list)
for a, b in tp:
    groups[re.sub(r"[^a-z0-9]+", " ", tracks[a]["title"].lower()).strip()].append((a, b))
gl = list(groups.values())
for name, vals, tol in (("intro bars +-0", planned["intro"], 0), ("outro bars +-0", planned["outro"], 0), ("longest gap +-0", gap, 0), ("last drop -> end +-0", lde, 0), ("break share +-1", planned["break share"], 1)):
    ok = [[(vals[a] is None and vals[b] is None) or (vals[a] is not None and vals[b] is not None and abs(vals[a] - vals[b]) <= tol + 1e-9) for a, b in g] for g in gl]
    bs = []
    for _ in range(4000):
        pick = rng.integers(0, len(gl), len(gl))
        flat = [x for k in pick for x in ok[k]]
        bs.append(np.mean(flat))
    out(f"  {name}: {np.mean([x for g in ok for x in g]):.2f} [95 % {np.percentile(bs, 2.5):.2f}, {np.percentile(bs, 97.5):.2f}] ({len(gl)} title groups)")

(OUT / "followup.txt").write_text("\n".join(lines), encoding="utf-8")
