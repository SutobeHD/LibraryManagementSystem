"""Task 2 (exact-structure groups), task 6 (sortable-column distributions), extra task-5 counts."""
import collections as C
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from common import load, quant

tracks, meta, anlz = load()
N = len(tracks)
for t in tracks:
    t["s_q4"] = " ".join(f"{lab}{b}" for lab, b in quant(t["runs"], 4))
    t["s_q16"] = " ".join(f"{lab}{b}" for lab, b in quant(t["runs"], 16))
    t["s_moodlab"] = t["mood"][0] + ":" + t["s_lab"]


def dupkey(t):
    return (t["artist"].lower().strip(), t["title"].lower().strip())


print("== Task 2: exact-structure groups ==")
print("key | distinct | singletons | tracks sharing with >=1 | >=5 | >=20 others | largest")
keys = [("phrase-level exact (unmerged)", "s_phr"), ("runs exact bars", "s_exact"), ("runs q4", "s_q4"),
        ("runs q8", "s_q8"), ("runs q16", "s_q16"), ("labels only (merged)", "s_lab"), ("labels after q8-drop", "s_q8lab")]
groups = {}
for name, k in keys:
    g = C.defaultdict(list)
    for t in tracks:
        g[t[k]].append(t)
    groups[k] = g
    sizes = np.array([len(v) for v in g.values()])
    print(f"{name} | {len(g)} | {(sizes == 1).sum()} | {sizes[sizes >= 2].sum()} | {sizes[sizes >= 6].sum()} | {sizes[sizes >= 21].sum()} | {sizes.max()}")

# how many shared groups are only duplicates of the same track?
for k in ("s_exact", "s_q8"):
    g = groups[k]
    multi = [v for v in g.values() if len(v) >= 2]
    only_dupes = sum(1 for v in multi if len({dupkey(t) for t in v}) == 1)
    print(f"{k}: groups>=2: {len(multi)}, of which same artist+title only: {only_dupes}")

for k, label in (("s_exact", "exact bars"), ("s_q8", "q8"), ("s_lab", "labels only")):
    print(f"\n-- top 10 structures [{label}] --")
    for s, v in sorted(groups[k].items(), key=lambda kv: -len(kv[1]))[:10]:
        seen, ex = set(), []
        for t in v:
            if dupkey(t) not in seen:
                seen.add(dupkey(t))
                ex.append(f"{t['artist'][:28]} - {t['title'][:38]}")
            if len(ex) == 2:
                break
        bpm = np.median([t["bpm"] for t in v])
        print(f"{len(v):4d} | {s} | bpm~{bpm:.0f} | " + " ;; ".join(ex))

print("\n== Task 6: sortable columns (min / p10 / median / p90 / max), n ==")
cols = [("intro", "Intro-Laenge Bars", 1), ("outro", "Outro-Laenge Bars", 1), ("first_drop", "Erster Drop nach Bars", 1),
        ("drops", "Anzahl Drops (C-Runs)", 1), ("drops8", "Anzahl Drops >=8 Bars", 1), ("break_share", "Break-Anteil %", 100),
        ("main_share", "Main/Chorus-Anteil %", 100), ("longest_break", "Laengster Break Bars", 1), ("longest_main", "Laengster Main-Block Bars", 1),
        ("n_breaks", "Anzahl Breaks >=4 Bars", 1), ("bars", "Gesamt Bars", 1), ("n_phr", "Phrasen", 1), ("n_runs", "Abschnitte (Runs)", 1),
        ("pct8", "Phrasen = Vielfache von 8 Bars %", 100), ("pct4", "Phrasen = Vielfache von 4 Bars %", 100), ("first_drop_rel", "Erster Drop relativ %", 100),
        ("fills", "Fills", 1)]
for k, name, mul in cols:
    v = np.array([t["feat"][k] for t in tracks if t["feat"][k] is not None], float) * mul
    p = np.percentile(v, [0, 10, 50, 90, 100])
    top = C.Counter(np.round(v).astype(int)).most_common(4)
    print(f"{name} | " + " / ".join(f"{x:g}" for x in np.round(p, 1)) + f" | n={len(v)} | distinct={len(set(np.round(v, 2)))} | top {top}")
# by mood for the break share (D exists only in high, B only in mid/low)
for md in ("high", "mid"):
    v = np.array([t["feat"]["break_share"] for t in tracks if t["mood"] == md]) * 100
    print(f"  break_share {md}:", np.round(np.percentile(v, [0, 10, 50, 90, 100]), 1), "zero:", int((v == 0).sum()))
    v = np.array([t["feat"]["drops"] for t in tracks if t["mood"] == md])
    print(f"  drops {md}:", np.percentile(v, [0, 10, 50, 90, 100]))
v = np.array([t["feat"]["intro"] for t in tracks])
print("intro multiples of 8:", float(np.mean(v % 8 == 0).round(3)), "of 16:", float(np.mean(v % 16 == 0).round(3)), "intro==0:", int((v == 0).sum()))
fd = np.array([t["feat"]["first_drop"] for t in tracks if t["feat"]["first_drop"] is not None])
print("first_drop multiples of 8:", float(np.mean(fd % 8 == 0).round(3)), "of 16:", float(np.mean(fd % 16 == 0).round(3)), "==intro:", sum(1 for t in tracks if t["feat"]["first_drop"] == t["feat"]["intro"]))

print("\n== Task 5 extras ==")
gd = np.array([t["grid"].get("beats", 0) - t["end"] for t in tracks])
print("|grid beats - end_beat| > 64:", int((np.abs(gd) > 64).sum()), "end_beat > grid beats:", int((gd < 0).sum()))
off_nonfirst = 0
for t in tracks:
    b0 = t["grid"].get("bib0") or 1
    if any(((s - 1) + (b0 - 1)) % 4 for s in t["starts"][1:]):
        off_nonfirst += 1
print("tracks with a non-first phrase off the downbeat:", off_nonfirst, "| first grid beat not a downbeat:", sum(1 for t in tracks if (t["grid"].get("bib0") or 1) != 1))
flags = C.Counter()
flagged = set()
for t in tracks:
    f = t["feat"]
    fl = []
    if f["n_phr"] > 60 or t["secs"] > 900:
        fl.append("mix/long (>60 phrases or >15 min)")
    if t["bars"] < 48 or t["secs"] < 90:
        fl.append("short (<48 bars or <90 s)")
    if (t["tempo_distinct"] or 1) > 1:
        fl.append("variable tempo")
    if f["drops"] == 0:
        fl.append("no chorus")
    if t["runs"][0][0] != "I":
        fl.append("no intro label")
    if t["runs"][-1][0] != "O":
        fl.append("no outro label")
    if f["pct4"] < 0.5:
        fl.append("irregular (<50% phrases x4 bars)")
    if abs(t["grid"].get("beats", 0) - t["end"]) > 64:
        fl.append("pssi/grid length mismatch")
    for x in fl:
        flags[x] += 1
    if fl:
        flagged.add(t["id"])
    t["flags"] = fl
print("flags:", dict(flags))
hard = {t["id"] for t in tracks if any(x.startswith(("mix", "short", "variable", "pssi")) for x in t["flags"])}
print("any flag:", len(flagged), "| hard-exclude (mix/short/variable tempo/length mismatch):", len(hard), "| soft only:", len(flagged) - len(hard))
print("masked by writer:", C.Counter((t["masked"], t["writer"]) for t in tracks))
for name, sel in (("masked", lambda t: t["masked"]), ("plain", lambda t: not t["masked"])):
    tt = [t for t in tracks if sel(t)]
    print(f"  {name}: n={len(tt)} mood={dict(C.Counter(t['mood'] for t in tt))} med phrases={np.median([t['feat']['n_phr'] for t in tt])} pct8={np.mean([t['feat']['pct8'] for t in tt]):.3f} med bars={np.median([t['bars'] for t in tt])}")
