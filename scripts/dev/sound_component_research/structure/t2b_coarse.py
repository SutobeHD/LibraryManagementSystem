"""Coarser exact-group keys + stability of keys/columns across same-audio copies."""
import collections as C
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from common import load, quant

tracks, meta, anlz = load()
N = len(tracks)


def lenclass(b):
    return "s" if b <= 8 else ("m" if b <= 24 else "l")


for t in tracks:
    q8 = t["q8"]
    t["k_exact"] = t["s_exact"]
    t["k_q8"] = t["s_q8"]
    t["k_q16"] = " ".join(f"{lab}{b}" for lab, b in quant(t["runs"], 16))
    t["k_lab"] = t["s_lab"]
    t["k_q8lab"] = t["s_q8lab"]
    t["k_sml"] = " ".join(f"{lab}{lenclass(b)}" for lab, b in q8)
    core = [lab for lab, b in quant(t["runs"], 16) if lab not in "IO"]
    t["k_q16lab"] = " ".join(lab for lab, _ in quant(t["runs"], 16))
    sk = []
    for lab, b in q8:  # skeleton: only main blocks and breaks, Up/Intro/Outro dropped
        if lab in "CDB" and (not sk or sk[-1] != lab):
            sk.append(lab)
    t["k_skel"] = t["mood"][0] + ":" + "".join(sk)
    f = t["feat"]
    t["k_counts"] = f"{t['mood'][0]} drops{f['drops8']} breaks{f['n_breaks']}"
    t["k_i_fd"] = f"I{int(round(f['intro'] / 8) * 8)} FD{'-' if f['first_drop'] is None else int(round(f['first_drop'] / 8) * 8)} N{f['drops8']}"

keys = [("exact bars", "k_exact"), ("q8", "k_q8"), ("q16", "k_q16"), ("labels + s/m/l length class (q8)", "k_sml"), ("label seq (merged)", "k_lab"),
        ("label seq after q8-drop", "k_q8lab"), ("label seq after q16-drop", "k_q16lab"), ("skeleton C/D/B only", "k_skel"),
        ("mood + #drops>=8 + #breaks", "k_counts"), ("intro q8 + first-drop q8 + #drops", "k_i_fd")]
tkey = C.defaultdict(list)
secs = [t["secs"] for t in tracks]
bpm = [t["bpm"] for t in tracks]
for i, t in enumerate(tracks):
    k = re.sub(r"[^a-z0-9]+", " ", t["title"].lower()).strip()
    if len(k) >= 8:
        tkey[k].append(i)
tp = [(v[a], v[b]) for v in tkey.values() for a in range(len(v)) for b in range(a + 1, len(v))
      if abs(secs[v[a]] - secs[v[b]]) <= 3 and abs(bpm[v[a]] - bpm[v[b]]) <= 1]
print(f"same-audio copy pairs: {len(tp)}")
print("key | distinct | tracks sharing with >=1 | >=5 | >=20 others | largest | median group size seen by a track | copies agree")
for name, k in keys:
    g = C.Counter(t[k] for t in tracks)
    sizes = np.array(list(g.values()))
    per_track = np.array([g[t[k]] for t in tracks])
    agree = np.mean([tracks[a][k] == tracks[b][k] for a, b in tp])
    print(f"{name} | {len(g)} | {sizes[sizes >= 2].sum()} | {sizes[sizes >= 6].sum()} | {sizes[sizes >= 21].sum()} | {sizes.max()} | {int(np.median(per_track))} | {agree:.2f}")
for k in ("k_skel", "k_counts", "k_i_fd"):
    print(f"top {k}:", C.Counter(t[k] for t in tracks).most_common(8))

print("\ncolumn stability across same-audio copies (share of pairs equal / within tolerance):")
for col, tol in (("intro", 0), ("intro", 4), ("outro", 4), ("first_drop", 0), ("first_drop", 8), ("drops", 0), ("drops8", 0), ("n_breaks", 0), ("longest_break", 4), ("longest_main", 8), ("bars", 2)):
    ok = []
    for a, b in tp:
        x, y = tracks[a]["feat"][col], tracks[b]["feat"][col]
        ok.append((x is None and y is None) or (x is not None and y is not None and abs(x - y) <= tol))
    print(f"  {col} (+-{tol}): {np.mean(ok):.2f}")
for col, tol in (("break_share", 0.03), ("main_share", 0.05), ("first_drop_rel", 0.03), ("pct8", 0.1)):
    ok = []
    for a, b in tp:
        x, y = tracks[a]["feat"][col], tracks[b]["feat"][col]
        ok.append((x is None and y is None) or (x is not None and y is not None and abs(x - y) <= tol))
    print(f"  {col} (+-{tol * 100:g} pts): {np.mean(ok):.2f}")

print("\nbreak columns with break = Down only (high mood):")
hi = [t for t in tracks if t["mood"] == "high"]
for col, mul in (("break_share", 100), ("longest_break", 1), ("n_breaks", 1)):
    v = np.array([t["feat"][col] for t in hi]) * mul
    print(f"  {col} high-mood n={len(v)}: " + " / ".join(f"{x:g}" for x in np.round(np.percentile(v, [0, 10, 50, 90, 100]), 1)), "| zero:", int((v == 0).sum()))
v = np.array([t["feat"]["sh_B"] for t in tracks if t["mood"] != "high"]) * 100
print("  bridge share mid/low:", np.round(np.percentile(v, [0, 10, 50, 90, 100]), 1))
v = np.array([t["feat"]["sh_U"] for t in hi]) * 100
print("  up/build share high:", np.round(np.percentile(v, [0, 10, 50, 90, 100]), 1))
