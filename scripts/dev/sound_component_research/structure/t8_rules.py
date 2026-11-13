"""Rule-based families + alternative drop definition + final column table."""
import collections as C
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from common import load

tracks, meta, anlz = load()


def post_break_drop(t):
    """Start bar of the first Chorus run that comes after a Down run (Up in between allowed)."""
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
        return "V  Verse-Typ (mood mid/low, kein Break-Label)"
    if f["bars"] < 128:
        return "K  Kurz (<128 Bars)"
    late = f["first_drop"] is None or f["first_drop"] >= 32
    nb = f["n_breaks"]
    if nb == 0:
        return "A2 Ohne Break, spaeter Einstieg (Main ab Bar >=32)" if late else "A1 Ohne Break, frueher Einstieg (<32)"
    if nb == 1:
        return "B2 1 Break, spaeter Einstieg" if late else "B1 1 Break, frueher Einstieg"
    return "C2 2+ Breaks, spaeter Einstieg" if late else "C1 2+ Breaks, frueher Einstieg"


for t in tracks:
    t["pbd"] = post_break_drop(t)
    t["fam"] = family(t)
secs = [t["secs"] for t in tracks]
bpm = [t["bpm"] for t in tracks]
tkey = C.defaultdict(list)
for i, t in enumerate(tracks):
    k = re.sub(r"[^a-z0-9]+", " ", t["title"].lower()).strip()
    if len(k) >= 8:
        tkey[k].append(i)
tp = [(v[a], v[b]) for v in tkey.values() for a in range(len(v)) for b in range(a + 1, len(v))
      if abs(secs[v[a]] - secs[v[b]]) <= 3 and abs(bpm[v[a]] - bpm[v[b]]) <= 1]
print("rule-based families (deterministic): family | n | median: intro / main-start / drops>=8 / break% / bars | example structures")
fam = C.defaultdict(list)
for t in tracks:
    fam[t["fam"]].append(t)
for k in sorted(fam):
    tt = fam[k]
    f = lambda key: np.median([t["feat"][key] if t["feat"][key] is not None else t["feat"]["bars"] for t in tt])  # noqa: E731
    ex = C.Counter(t["s_q8"] for t in tt).most_common(1)[0][0]
    mid = sorted(tt, key=lambda t: abs(t["feat"]["bars"] - f("bars")))[0]["s_q8"]
    print(f"{k} | {len(tt)} | {f('intro'):g} / {f('first_drop'):g} / {f('drops8'):g} / {f('break_share') * 100:.0f} / {f('bars'):g} | {mid}")
print("family agreement across same-audio copies:", round(float(np.mean([tracks[a]["fam"] == tracks[b]["fam"] for a, b in tp])), 2), f"({len(tp)} pairs)")

pbd = np.array([t["pbd"] for t in tracks if t["pbd"] is not None])
hi = sum(1 for t in tracks if t["mood"] == "high")
print(f"\n'Drop nach Break' (first Chorus>=8 bars after a Down>=4 bars): available for {len(pbd)} tracks ({len(pbd) / hi:.0%} of high-mood): "
      + " / ".join(f"{x:g}" for x in np.round(np.percentile(pbd, [0, 10, 50, 90, 100]), 1)), "| top", C.Counter(np.round(pbd).astype(int)).most_common(5))
ok = []
for a, b in tp:
    x, y = tracks[a]["pbd"], tracks[b]["pbd"]
    ok.append((x is None and y is None) or (x is not None and y is not None and abs(x - y) <= 8))
print("  stability across copies (+-8 bars):", round(float(np.mean(ok)), 2))
# main-start in seconds for DJ use
ms = np.array([t["feat"]["first_drop"] * 240 / t["bpm"] for t in tracks if t["feat"]["first_drop"] is not None and t["bpm"] > 0])
print("first main start in seconds:", np.round(np.percentile(ms, [0, 10, 50, 90, 100]), 0))
# excluded / flagged summary
hard = [t for t in tracks if t["feat"]["n_phr"] > 60 or t["secs"] > 900 or t["bars"] < 48 or t["secs"] < 90 or (t["tempo_distinct"] or 1) > 1 or abs(t["grid"].get("beats", 0) - t["end"]) > 64]
print("\nhard-flagged:", len(hard), "| by mood", dict(C.Counter(t["mood"] for t in hard)))
print("tracks with >=1 phrase < 4 bars:", sum(1 for t in tracks if any(b < 4 for _, b in t["phr"][:-1])), "| share of all phrases < 4 bars: 4.4 %")
print("bars lost when runs < 4 bars are dropped (q8): mean share", round(float(np.mean([1 - sum(b for _, b in t["q8"]) / t["bars"] for t in tracks])), 4))
