"""W9 structure-similarity prototype: load phrases, build the three representations."""
import json
import math
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SC = ROOT / "tmp" / "sc-struct"
ALPHA = "IUDCVBO"  # Intro, Up/Build, Down/Break, Chorus/Main, Verse, Bridge, Outro
AIDX = {c: i for i, c in enumerate(ALPHA)}
NORM = {
    1: {1: "I", 2: "U", 3: "D", 5: "C", 6: "O"},
    2: {1: "I", 2: "V", 3: "V", 4: "V", 5: "V", 6: "V", 7: "V", 8: "B", 9: "C", 10: "O"},
    3: {1: "I", 2: "V", 3: "V", 4: "V", 5: "V", 6: "V", 7: "V", 8: "B", 9: "C", 10: "O"},
}
MOOD = {1: "high", 2: "mid", 3: "low"}
# mean z-scored PWV7 loudness per label, measured in t4_sanity.py (mid-mood Bridge is LOUD, not a break)
ZL = {"D": -0.98, "I": -0.59, "O": -0.60, "U": -0.40, "V": 0.04, "B": 0.40, "C": 0.70}
ZRANGE = 1.68
ENERGY = ZL
BREAK = ("D",)  # only the high-mood "Down" is a real breakdown


def sub_matrix():
    """Substitution cost per bar: 0 same label, else 0.3 + 0.7 * loudness gap (0..1)."""
    S = np.zeros((7, 7))
    for a in ALPHA:
        for b in ALPHA:
            if a != b:
                S[AIDX[a], AIDX[b]] = min(1.0, 0.3 + 0.7 * abs(ZL[a] - ZL[b]) / ZRANGE)
    return S


def fmt(b):
    return f"{b:g}"


def load():
    meta = {
        str(t["ID"]): t
        for t in json.load(open(ROOT / "tmp/library-analysis/tracks.json", encoding="utf-8"))
    }
    anlz = {}
    for line in open(ROOT / "tmp/library-analysis/measure/anlz.jsonl", encoding="utf-8"):
        r = json.loads(line)
        anlz[r["id"]] = r
    tracks = []
    for line in open(SC / "phrases.jsonl", encoding="utf-8"):
        r = json.loads(line)
        if not r.get("pssi"):
            continue
        tracks.append(build(r, meta.get(r["id"], {}), anlz.get(r["id"], {})))
    return tracks, meta, anlz


def build(r, m, a):
    p = r["pssi"]
    mood = p["mood"]
    ents = sorted(p["e"], key=lambda e: e[0])
    starts = [e[0] for e in ents]
    end = p["end_beat"]
    lens = [
        max(0, (starts[i + 1] if i + 1 < len(starts) else end) - s) for i, s in enumerate(starts)
    ]
    labs = [NORM.get(mood, {}).get(e[1], "X") for e in ents]
    phr = [(lab, n / 4) for lab, n in zip(labs, lens)]  # (label, bars) per phrase
    runs = []
    for lab, b in phr:
        if runs and runs[-1][0] == lab:
            runs[-1][1] += b
        else:
            runs.append([lab, b])
    runs = [(lab, b) for lab, b in runs]
    q8 = quant(runs, 8)
    t = {
        "id": r["id"],
        "mood": MOOD.get(mood, "?"),
        "phr": phr,
        "runs": runs,
        "q8": q8,
        "starts": starts,
        "lens": lens,
        "end": end,
        "fills": sum(1 for e in ents if e[5]),
        "s_exact": " ".join(f"{lab}{fmt(round(b * 4) / 4)}" for lab, b in runs),
        "s_q8": " ".join(f"{lab}{b}" for lab, b in q8),
        "s_lab": " ".join(lab for lab, _ in runs),
        "s_q8lab": " ".join(lab for lab, _ in q8),
        "s_phr": " ".join(f"{lab}{fmt(round(b * 4) / 4)}" for lab, b in phr),
        "artist": m.get("Artist") or "",
        "title": m.get("Title") or "",
        "genre": (m.get("Genre") or "").strip().lower().replace("hardtechno", "hard techno"),
        "bpm": float(m.get("BPM") or 0),
        "secs": float(m.get("TotalTime") or 0),
        "grid": r.get("grid") or {},
        "tempo_distinct": (a.get("grid") or {}).get("tempo_distinct", 1),
        "masked": p["masked"],
        "writer": ((a.get("writer") or {}).get("votes") or {}).get("pssi"),
    }
    t["bars"] = sum(b for _, b in runs)
    t["feat"] = summary(t)
    return t


def quant(runs, q):
    """Bars -> nearest multiple of q; runs rounding to 0 (< q/2) are dropped, neighbours merged."""
    out = []
    for lab, b in runs:
        n = int(math.floor(b / q + 0.5)) * q
        if n == 0:
            continue
        if out and out[-1][0] == lab:
            out[-1][1] += n
        else:
            out.append([lab, n])
    return [(lab, n) for lab, n in out]


def summary(t):
    runs, phr, total = t["runs"], t["phr"], t["bars"] or 1e-9
    share = {c: sum(b for lab, b in runs if lab == c) / total for c in ALPHA}
    pos = 0.0
    first_drop = None
    drops = drops8 = n_breaks = 0
    longest_break = longest_main = 0.0
    for lab, b in runs:
        if lab == "C":
            drops += 1
            drops8 += b >= 8
            longest_main = max(longest_main, b)
            if first_drop is None:
                first_drop = pos
        if lab in BREAK:
            n_breaks += b >= 4
            longest_break = max(longest_break, b)
        pos += b
    body = [b for _, b in phr[:-1]] or [b for _, b in phr]  # last phrase is cut by end_beat

    def pct(k):
        return sum(1 for b in body if b > 0 and abs(b / k - round(b / k)) < 1e-9) / len(body)

    return {
        "bars": total,
        "n_phr": len(phr),
        "n_runs": len(runs),
        "intro": runs[0][1] if runs[0][0] == "I" else 0.0,
        "outro": runs[-1][1] if runs[-1][0] == "O" else 0.0,
        "drops": drops,
        "drops8": drops8,
        "first_drop": first_drop,
        "first_drop_rel": None if first_drop is None else first_drop / total,
        "longest_break": longest_break,
        "n_breaks": n_breaks,
        "longest_main": longest_main,
        "break_share": share["D"] + share["B"],
        "main_share": share["C"],
        **{f"sh_{c}": share[c] for c in ALPHA},
        "pct4": pct(4),
        "pct8": pct(8),
        "pct16": pct(16),
        "min_phr": min(b for _, b in phr),
        "med_phr": float(np.median([b for _, b in phr])),
        "fills": t["fills"],
    }


def _fill(m, runs, scale, nbins):
    pos = 0.0
    for lab, b in runs:
        if lab in AIDX and b > 0:
            a, e = pos * scale, (pos + b) * scale
            i = int(a)
            while i < nbins and i < e:
                m[i, AIDX[lab]] += min(e, i + 1) - max(a, i)
                i += 1
        pos += b


def profile(t, nbins):
    """nbins equal slices of the track (in beats); returns (nbins, 7) label-share matrix."""
    out = np.zeros((nbins, len(ALPHA)), np.float32)
    if t["bars"] > 0:
        _fill(out, t["runs"], nbins / t["bars"], nbins)
    return out


def abs_profile(t, bin_bars=8, nbins=64):
    """Majority label per absolute 8-bar bin; 7 = past the end. Returns (labels[nbins], used)."""
    m = np.zeros((nbins, len(ALPHA)), np.float32)
    _fill(m, t["runs"], 1 / bin_bars, nbins)
    used = min(nbins, int(math.floor(t["bars"] / bin_bars + 0.5)))  # last bin counts if >= half
    lab = m.argmax(1).astype(np.int8)
    lab[m.sum(1) < 0.5] = 7
    lab[used:] = 7
    return lab, max(used, 1)


FEATS = [
    "intro", "outro", "drops", "first_drop", "longest_break", "n_breaks", "longest_main", "bars",
    "n_runs", "sh_I", "sh_U", "sh_D", "sh_C", "sh_V", "sh_B", "sh_O", "pct8",
]  # fmt: skip
LOGF = {"intro", "outro", "drops", "first_drop", "longest_break", "n_breaks", "longest_main",
        "bars", "n_runs"}  # fmt: skip


def feat_matrix(tracks):
    X = np.zeros((len(tracks), len(FEATS)))
    for i, t in enumerate(tracks):
        f = t["feat"]
        for j, k in enumerate(FEATS):
            v = f[k]
            if v is None:  # no chorus: first drop = end of track
                v = f["bars"]
            X[i, j] = math.log1p(v) if k in LOGF else v
    mu, sd = X.mean(0), X.std(0)
    sd[sd == 0] = 1
    return np.clip((X - mu) / sd, -4, 4)
