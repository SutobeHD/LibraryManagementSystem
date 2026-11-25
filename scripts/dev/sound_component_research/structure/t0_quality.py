import collections as C
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from common import ALPHA, SC, load

tracks, meta, anlz = load()
print("tracks with PSSI", len(tracks), "| library rows", len(meta))
print("mood", C.Counter(t["mood"] for t in tracks))
print("masked", C.Counter(t["masked"] for t in tracks), "writer", C.Counter(t["writer"] for t in tracks))
print(
    "unknown labels X:",
    sum(1 for t in tracks if any(lab == "X" for lab, _ in t["phr"])),
    C.Counter((t["mood"], lab) for t in tracks for lab, _ in t["phr"] if lab == "X"),
)
print("label use by mood (share of bars):")
for md in ("high", "mid", "low"):
    tt = [t for t in tracks if t["mood"] == md]
    tot = sum(t["bars"] for t in tt)
    print(" ", md, len(tt), {c: round(sum(b for t in tt for lab, b in t["runs"] if lab == c) / tot, 3) for c in ALPHA})
kc = C.Counter()
for line in open(SC / "phrases.jsonl", encoding="utf-8"):
    r = json.loads(line)
    if r.get("pssi"):
        for e in r["pssi"]["e"]:
            kc[(r["pssi"]["mood"], e[1])] += 1
print("raw (mood,kind) counts", sorted(kc.items()))
n = np.array([t["feat"]["n_phr"] for t in tracks])
nr = np.array([t["feat"]["n_runs"] for t in tracks])
print("phrases pct", np.percentile(n, [0, 10, 50, 90, 99, 100]), "runs pct", np.percentile(nr, [0, 10, 50, 90, 99, 100]))
bars = np.array([t["bars"] for t in tracks])
print("bars pct", np.percentile(bars, [0, 1, 10, 50, 90, 99, 100]))
for thr in (40, 60, 100):
    print(f"phrases>{thr}:", int((n > thr).sum()), end="  ")
print()
print("bars>400:", int((bars > 400).sum()), "bars>512:", int((bars > 512).sum()), "bars<32:", int((bars < 32).sum()), "bars<48:", int((bars < 48).sum()))
secs = np.array([t["secs"] for t in tracks])
print("secs>600:", int((secs > 600).sum()), "secs>900:", int((secs > 900).sum()), "secs<90:", int((secs < 90).sum()))
print("variable tempo (tempo_distinct>1):", sum(1 for t in tracks if (t["tempo_distinct"] or 1) > 1))
gb = [(t["grid"].get("bpm_max", 0) - t["grid"].get("bpm_min", 0)) for t in tracks if t["grid"]]
print("grid bpm range >0.05:", sum(1 for x in gb if x > 0.05), ">2:", sum(1 for x in gb if x > 2), "no grid:", sum(1 for t in tracks if not t["grid"]))
allp = [b for t in tracks for _, b in t["phr"][:-1]]
ap = np.array(allp)


def mult(k):
    return float(np.mean(np.abs(ap / k - np.round(ap / k)) < 1e-9).round(4))


print("phrases (excl last)", len(ap), "share <1 bar", (ap < 1).mean().round(4), "<4 bars", (ap < 4).mean().round(4),
      "mult4", mult(4), "mult8", mult(8), "mult16", mult(16), "non-integer bars", float(np.mean(np.abs(ap - np.round(ap)) > 1e-9).round(4)))
print("phrase length top", C.Counter(allp).most_common(12))
print("tracks with any phrase <4 bars (excl last):", sum(1 for t in tracks if any(b < 4 for _, b in t["phr"][:-1])),
      "| <1 bar:", sum(1 for t in tracks if any(b < 1 for _, b in t["phr"][:-1])),
      "| zero-length:", sum(1 for t in tracks if any(b == 0 for _, b in t["phr"])))
print("tracks with any RUN <4 bars (excl last):", sum(1 for t in tracks if any(b < 4 for _, b in t["runs"][:-1])))
print("tracks pct8<0.5:", sum(1 for t in tracks if t["feat"]["pct8"] < 0.5), "pct4<0.5:", sum(1 for t in tracks if t["feat"]["pct4"] < 0.5))
off = C.Counter()
bad = 0
for t in tracks:
    b0 = t["grid"].get("bib0")
    if not b0:
        continue
    o = [((s - 1) + (b0 - 1)) % 4 for s in t["starts"]]
    off.update(o)
    bad += any(x != 0 for x in o)
print("phrase start beat-in-bar offsets", off, "tracks with any off-downbeat phrase:", bad)
print("first phrase beat != 1:", sum(1 for t in tracks if t["starts"][0] != 1), C.Counter(t["starts"][0] for t in tracks).most_common(5))
print("no Intro at start:", sum(1 for t in tracks if t["runs"][0][0] != "I"), "| no Outro at end:", sum(1 for t in tracks if t["runs"][-1][0] != "O"),
      "| no Chorus:", sum(1 for t in tracks if t["feat"]["drops"] == 0), "| Intro mid-track:", sum(1 for t in tracks if any(lab == "I" for lab, _ in t["runs"][1:])),
      "| Outro mid-track:", sum(1 for t in tracks if any(lab == "O" for lab, _ in t["runs"][:-1])))
gbt = [(t["grid"].get("beats", 0) - t["end"]) for t in tracks if t["grid"]]
print("grid beats - end_beat pct", np.percentile(gbt, [0, 5, 50, 95, 100]))
print("fills per track pct", np.percentile([t["fills"] for t in tracks], [0, 10, 50, 90, 100]))
print("genre by mood:")
for md in ("high", "mid", "low"):
    print(" ", md, C.Counter(t["genre"] or "-" for t in tracks if t["mood"] == md).most_common(8))
print("bpm by mood", {md: np.round(np.percentile([t["bpm"] for t in tracks if t["mood"] == md], [10, 50, 90]), 1).tolist() for md in ("high", "mid", "low")})
big = sorted(tracks, key=lambda t: -t["feat"]["n_phr"])[:8]
for t in big:
    print("  big:", t["id"], t["feat"]["n_phr"], round(t["bars"]), round(t["secs"]), t["artist"][:25], "-", t["title"][:40])
have = {t["id"] for t in tracks}
nopssi = [i for i in meta if i not in have]
print("no PSSI:", len(nopssi))
for i in nopssi[:25]:
    m = meta[i]
    a = anlz.get(i, {})
    print("  ", i, a.get("status"), a.get("files"), round(float(m.get("TotalTime") or 0)), m.get("BPM"), (m.get("Artist") or "")[:20], "-", (m.get("Title") or "")[:40], "|", (m.get("path") or "")[-30:])
