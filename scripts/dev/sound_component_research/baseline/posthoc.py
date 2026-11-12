"""Post-hoc checks on the stored results (no audio access)."""
import glob, json
from pathlib import Path
import numpy as np
from scipy import stats
HERE = Path(__file__).parent
sample = json.load(open(HERE / "sample.json", encoding="utf-8"))["tracks"]
order = {t["id"]: i for i, t in enumerate(sample)}
rows = []
for f in sorted(glob.glob(str(HERE / "results_shard*.jsonl"))):
    rows += [json.loads(l) for l in open(f, encoding="utf-8")]
rows.sort(key=lambda r: order[r["id"]])
bpm = np.array([float(r["bpm"]) for r in rows]); genre = np.array([r["genre"] for r in rows])
NN = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
def g(w, sec, k, tag=None):
    out = []
    for r in rows:
        d = r[w][sec] if tag is None else r[w][sec][tag]
        v = d.get(k); out.append(np.nan if v is None else float(v))
    return np.array(out)
def sp(a, b):
    m = np.isfinite(a) & np.isfinite(b); return round(float(stats.spearmanr(a[m], b[m])[0]), 2)
hard, soft = np.isin(genre, ["Hard Techno", "Raw", "Uptempo"]), np.isin(genre, ["House", "Trance"])
def contrast(a):
    u, p = stats.mannwhitneyu(a[hard & np.isfinite(a)], a[soft & np.isfinite(a)]); n1, n2 = (hard & np.isfinite(a)).sum(), (soft & np.isfinite(a)).sum()
    return round(float(p), 3), round(float(2 * u / (n1 * n2) - 1), 2)
print("== W6: note-change rate normalised by voiced time (changes per voiced second)")
for w in ("A",):
    pass
def rate_voiced(w):
    return g(w, "mel", "note_changes_per_s") / np.maximum(g(w, "mel", "voiced_share_t45"), 0.02)
rv = rate_voiced("A")
print("dist", np.round(np.nanpercentile(rv, [0, 10, 50, 90, 100]), 2), "retest AB", sp(rv, rate_voiced("B")), "split", sp(rate_voiced("A1"), rate_voiced("A2")))
print("corr with pitch_salience", sp(rv, g("A", "mel", "pitch_salience")), "with voiced_share", sp(rv, g("A", "mel", "voiced_share_t45")), "hard-vs-soft (p, r)", contrast(rv))
for gname in ("Hard Techno", "Raw", "Techno", "Groove", "Trance", "House"):
    print("  ", gname, round(float(np.nanmedian(rv[genre == gname])), 2))
idx = np.argsort(rv)
print("  top:", [(rows[i]["artist"][:18], rows[i]["title"][:26], rows[i]["genre"], round(float(rv[i]), 2)) for i in idx[::-1][:5]])
print("  bottom:", [(rows[i]["artist"][:18], rows[i]["title"][:26], rows[i]["genre"], round(float(rv[i]), 2)) for i in idx[:5]])
print("== W6 inter-correlations: noteChg_t45~voiced_share", sp(g("A", "mel", "note_changes_per_beat_t45"), g("A", "mel", "voiced_share_t45")),
      " salience_p90~noteChg", sp(g("A", "mel", "pitch_salience_p90"), g("A", "mel", "note_changes_per_beat_t45")))
print("== W4 contamination: decay ~ other_share", sp(g("A", "hats", "hat_decay_ms", "h7"), g("A", "hats", "other_share", "h7")),
      " decay ~ perc_frac_7k", sp(g("A", "hats", "hat_decay_ms", "h7"), g("A", "hpss", "perc_frac_7k")),
      " open_share ~ perc_frac_7k", sp(g("A", "hats", "hat_open_share", "h7"), g("A", "hpss", "perc_frac_7k")),
      " hats/beat ~ perc_share_7k_db", sp(g("A", "hats", "hats_per_beat", "h7"), g("A", "hpss", "perc_share_7k_db")),
      " hats/beat ~ hi7k_share_db", sp(g("A", "hats", "hats_per_beat", "h7"), g("A", "bass", "hi7k_share_db")),
      " flux/beat ~ perc_share", sp(g("A", "hats", "flux_per_beat", "h7"), g("A", "hpss", "perc_share_7k_db")))
sp_est = np.minimum(1, 2 * g("A", "hats", "other_share", "h7"))
print("   spurious est: share of tracks > 0.3:", round(float(np.mean(sp_est > 0.3)), 2), " > 0.5:", round(float(np.mean(sp_est > 0.5)), 2))
print("   hats/beat d40 retest AB:", sp(g("A", "hats", "hats_per_beat_d40", "h7"), g("B", "hats", "hats_per_beat_d40", "h7")))
print("== W2c BPM confound (Spearman with BPM):", {k: sp(g("A", "bass", k), bpm) for k in ("boom_t20_ms", "boom_t20_rel", "boom_t10_ms", "boom_censored_share", "bass_dip_db", "bass_sustain_ratio", "bass_between_db", "bassnote_t20_ms", "kick_t20_ms", "sub60_of_200")})
print("   hard-vs-soft:", {k: contrast(g("A", "bass", k)) for k in ("bass_between_db", "bass_sustain_ratio", "bass_dip_db", "bassnote_t20_ms", "kick_t20_ms", "boom_t10_ms", "sub60_of_200")})
# residual of between_db after BPM (rank regression)
from scipy.stats import rankdata
x, y = rankdata(bpm), rankdata(g("A", "bass", "bass_between_db")); res = y - np.polyval(np.polyfit(x, y, 1), x)
print("   bass_between_db hard-vs-soft after removing BPM rank trend:", contrast(res))
y = rankdata(g("A", "bass", "bass_sustain_ratio")); res = y - np.polyval(np.polyfit(x, y, 1), x)
print("   bass_sustain_ratio hard-vs-soft after removing BPM rank trend:", contrast(res))
print("== W2a top/bottom with note names from the mean-spectrum estimate")
f0 = g("A", "bass", "bass_f0_meanspec_hz"); idx = np.argsort(f0)
def nm(f):
    m = int(round(69 + 12 * np.log2(f / 440))); return f"{NN[m % 12]}{m // 12 - 1}"
for lab, ii in (("top", idx[::-1][:5]), ("bottom", idx[:5])):
    print(" ", lab, [(rows[i]["artist"][:20] or "?", rows[i]["title"][:30], rows[i]["genre"], round(float(f0[i]), 1), nm(f0[i])) for i in ii])
import collections
print("  notes:", collections.Counter(nm(f) for f in f0).most_common())
fb = g("B", "bass", "bass_f0_meanspec_hz")
print("  A vs B same note:", round(float(np.mean(np.abs(12 * np.log2(f0 / fb)) <= 0.5)), 2), "| disagreeing tracks:", [(rows[i]["title"][:25], round(float(f0[i]), 1), round(float(fb[i]), 1)) for i in range(len(rows)) if abs(12 * np.log2(f0[i] / fb[i])) > 0.5])
print("  f0 seg-share within 1 st of the median (stability of bass note inside window): median", round(float(np.nanmedian(g("A", "bass", "bass_f0_within1st_share"))), 2), "p10", round(float(np.nanpercentile(g("A", "bass", "bass_f0_within1st_share"), 10)), 2))
print("== W5 low-overlap A/B subset retrieval (flux16, h7, centered)")
ov = np.array([r["overlap_ab_s"] for r in rows]); keep = np.nonzero(ov <= 30)[0]
def cm(X, Y):
    X = X - X.mean(1, keepdims=True); Y = Y - Y.mean(1, keepdims=True)
    X /= np.linalg.norm(X, axis=1, keepdims=True) + 1e-12; Y /= np.linalg.norm(Y, axis=1, keepdims=True) + 1e-12
    return X @ Y.T
for key in ("hist16", "flux16"):
    X = np.array([rows[i]["A"]["hats"]["h7"][key] for i in keep], float); Y = np.array([rows[i]["B"]["hats"]["h7"][key] for i in keep], float)
    C = cm(X, Y); rank = np.array([(C[i] > C[i, i]).sum() + 1 for i in range(len(keep))])
    print(f"  {key}: n={len(keep)} (overlap<=30s) top1 {np.mean(rank == 1):.2f} MRR {np.mean(1 / rank):.2f} own median {np.median(np.diag(C)):.2f} cross median {np.median(C[~np.eye(len(keep), dtype=bool)]):.2f}")
print("== sample: durations", np.round(np.percentile([r["file_dur"] for r in rows], [0, 50, 100])), "ext", collections.Counter(r["path"].rsplit(".", 1)[-1].lower() for r in rows))
print("   bass_active_share median", round(float(np.nanmedian(g("A", "bass", "bass_active_share"))), 2), "min", round(float(np.nanmin(g("A", "bass", "bass_active_share"))), 2))
