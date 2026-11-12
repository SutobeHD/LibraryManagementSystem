"""Plausibility evaluation of the baseline features (no ground truth). Prints tables, writes
eval_summary.json. Usage: evaluate.py > eval_tables.txt"""
import glob
import json
import sys
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
ok = [r for r in rows if r["status"] == "ok"]
print(f"tracks {len(rows)} ok {len(ok)}")
for r in rows:
    if r["status"] != "ok":
        print("ERROR", r["id"], r.get("error"))
SUMMARY: dict = {"n": len(ok)}


def flat(w):
    d = {}
    d.update(w["bass"])
    d.update(w["hpss"])
    for tag in ("h7", "h5"):
        for k, v in w["hats"][tag].items():
            d[f"{tag}_{k}"] = v
    d.update(w["mel"])
    d["lag_ms"] = w["lag_ms"]
    for est in ("bass_f0_hz", "bass_f0_meanspec_hz", "bass_f0_dom_hz", "bass_f0_acf_hz", "kick_f0_hz"):
        v = d.get(est)
        d[est.replace("_hz", "_st")] = 69 + 12 * np.log2(v / 440.0) if v and v > 0 else None
    o = d.get("h7_other_share")
    d["h7_spurious_est"] = min(1.0, 2 * o) if o is not None else None
    return d


W = {w: [flat(r[w]) for r in ok] for w in ("A", "B", "A1", "A2")}
meta = ok
bpm = np.array([float(r["bpm"]) for r in ok])
genre = np.array([r["genre"] for r in ok])


def col(name, w="A"):
    return np.array([np.nan if x.get(name) is None else float(x[name]) for x in W[w]], dtype=float)


def spear(a, b):
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 6 or np.ptp(a[m]) == 0 or np.ptp(b[m]) == 0:
        return np.nan, int(m.sum())
    return float(stats.spearmanr(a[m], b[m])[0]), int(m.sum())


KEY = [  # (feature, wish, unit)
    ("bass_f0_meanspec_hz", "W2a", "Hz"), ("bass_f0_hz", "W2a", "Hz"), ("kick_f0_hz", "W2a", "Hz"),
    ("sub60_of_200", "W2b", "ratio"), ("sub60_of_total", "W2b", "ratio"), ("sub120_of_total", "W2b", "ratio"),
    ("boom_t20_ms", "W2c", "ms"), ("boom_t20_rel", "W2c", "beat"), ("boom_t10_ms", "W2c", "ms"),
    ("boom_censored_share", "W2c", "share"), ("bass_dip_db", "W2c", "dB"), ("bass_sustain_ratio", "W2c", "share"),
    ("bass_between_db", "W2c", "dB"), ("bass_rerise_share", "W2c", "share"), ("low_between_per_beat", "W2c", "1/beat"),
    ("kick_t20_ms", "W2c", "ms"), ("bassnote_t20_ms", "W2c", "ms"),
    ("hi7k_share_db", "W4", "dB"), ("perc_share_7k_db", "W4", "dB"), ("perc_share_5_12k_db", "W4", "dB"),
    ("perc_frac_7k", "W4", "share"),
    ("h7_hats_per_beat", "W4", "1/beat"), ("h7_hats_per_beat_nonbeat", "W4", "1/beat"), ("h7_flux_per_beat", "W4", "log10/beat"),
    ("h5_hats_per_beat", "W4", "1/beat"),
    ("h7_offbeat_share", "W4", "share"), ("h7_sixteenth_share", "W4", "share"), ("h7_triplet_share", "W4", "share"),
    ("h7_other_share", "W4", "share"), ("h7_flux_off", "W4", "share"), ("h7_flux_16", "W4", "share"),
    ("h7_hat_decay_ms", "W4", "ms"), ("h7_hat_open_share", "W4", "share"), ("h7_open_share_offbeat", "W4", "share"),
    ("h5_hat_decay_ms", "W4", "ms"), ("h5_hat_open_share", "W4", "share"),
    ("hpr_mid_db", "W6", "dB"), ("chroma_entropy", "W6", "0-1"), ("pitch_salience", "W6", "ratio"),
    ("pitch_salience_p90", "W6", "ratio"),
    ("voiced_share_t45", "W6", "share"), ("note_changes_per_beat_t30", "W6", "1/beat"),
    ("note_changes_per_beat_t45", "W6", "1/beat"), ("note_changes_per_beat_t60", "W6", "1/beat"),
    ("n_pitch_classes", "W6", "count"), ("tonal_share_mid", "W6", "share"), ("tonality_db", "W6", "dB"),
    ("harm_flux", "W6", "ratio"),
]

# ------------------------------------------------------------------ 1 distributions + retest
ov = np.array([r["overlap_ab_s"] for r in ok])
low_ov = ov <= 60.0
print(f"\n## overlap A/B: median {np.median(ov):.0f} s, tracks with overlap <= 60 s: {low_ov.sum()}")
print("\n## distributions (window A) + retest Spearman (A vs B all / A vs B overlap<=60s / split-half A1 vs A2)")
print(f"{'feature':30s} {'wish':4s} {'unit':10s} {'min':>8s} {'p10':>8s} {'med':>8s} {'p90':>8s} {'max':>8s} | {'rAB':>5s} {'rABlo':>5s} {'rA1A2':>5s} n")
SUMMARY["features"] = {}
for name, wish, unit in KEY:
    a = col(name)
    f = a[np.isfinite(a)]
    if len(f) == 0:
        continue
    q = [f.min(), *np.percentile(f, [10, 50, 90]), f.max()]
    r_ab, n_ab = spear(a, col(name, "B"))
    r_lo, _ = spear(a[low_ov], col(name, "B")[low_ov])
    r_sh, _ = spear(col(name, "A1"), col(name, "A2"))
    print(f"{name:30s} {wish:4s} {unit:10s} " + " ".join(f"{v:8.3f}" for v in q) + f" | {r_ab:5.2f} {r_lo:5.2f} {r_sh:5.2f} {len(f)}")
    SUMMARY["features"][name] = {"wish": wish, "unit": unit, "min": q[0], "p10": q[1], "median": q[2], "p90": q[3],
                                 "max": q[4], "retest_ab": r_ab, "retest_ab_lowoverlap": r_lo, "splithalf": r_sh, "n": len(f)}

# ------------------------------------------------------------------ 2 bass f0 details
print("\n## W2a bass f0: estimator agreement / retest in semitones")
for est in ("bass_f0_meanspec_st", "bass_f0_st", "bass_f0_dom_st", "bass_f0_acf_st", "kick_f0_st"):
    a, b, a1, a2 = col(est), col(est, "B"), col(est, "A1"), col(est, "A2")
    dab, dsh = np.abs(a - b), np.abs(a1 - a2)
    pcab = np.abs(((a - b + 6) % 12) - 6)
    print(f"{est:22s} |A-B|<=0.5st {np.nanmean(dab <= 0.5):.2f}  pitch-class match(A,B) {np.nanmean(pcab <= 0.5):.2f}  |A1-A2|<=0.5st {np.nanmean(dsh <= 0.5):.2f}  median |A-B| {np.nanmedian(dab):.2f} st")
ms, sg_, ks = col("bass_f0_meanspec_st"), col("bass_f0_st"), col("kick_f0_st")
print(f"meanspec vs seg-median within 0.5 st: {np.mean(np.abs(ms - sg_) <= 0.5):.2f};  octave apart (11.5-12.5 st): {np.mean(np.abs(np.abs(ms - sg_) - 12) <= 0.5):.2f}")
d_kb = np.abs(ms - ks)
print(f"bass(between kicks) vs kick(on beat): same note (<=0.5 st) {np.mean(d_kb <= 0.5):.2f}; same pitch class {np.mean(np.abs(((ms - ks + 6) % 12) - 6) <= 0.5):.2f}; median |diff| {np.median(d_kb):.1f} st")
SUMMARY["bass_kick_same_note"] = float(np.mean(d_kb <= 0.5))
SUMMARY["bass_kick_same_pc"] = float(np.mean(np.abs(((ms - ks + 6) % 12) - 6) <= 0.5))


def camelot(k):
    try:
        n, m = int(k[:-1]), k[-1].upper()
    except Exception:
        return None
    return ((8 if m == "A" else 11) + 7 * (n - 1)) % 12, m == "A"


def key_stats(est):
    hits = {"tonic": 0, "fifth": 0, "scale": 0, "n": 0}
    for r, x in zip(ok, W["A"]):
        k = camelot(str(r["key"]))
        v = x.get(est)
        if not k or v is None or not np.isfinite(v):
            continue
        pc = int(round(v)) % 12
        rel = (pc - k[0]) % 12
        scale = {0, 2, 3, 5, 7, 8, 10} if k[1] else {0, 2, 4, 5, 7, 9, 11}
        hits["n"] += 1
        hits["tonic"] += rel == 0
        hits["fifth"] += rel == 7
        hits["scale"] += rel in scale
    return hits


print("\n## W2a external check: bass pitch class vs Rekordbox key (chance: tonic 8 %, tonic|fifth 17 %, in scale 58 %)")
for est in ("bass_f0_meanspec_st", "bass_f0_st", "kick_f0_st"):
    h = key_stats(est)
    n = h["n"]
    p_t = stats.binomtest(h["tonic"], n, 1 / 12, alternative="greater").pvalue
    print(f"{est:22s} n={n} tonic {h['tonic']/n:.2f} (p={p_t:.1e})  tonic|fifth {(h['tonic']+h['fifth'])/n:.2f}  in-scale {h['scale']/n:.2f}")
    SUMMARY[f"key_{est}"] = {k: int(v) for k, v in h.items()}
notes = [x.get("bass_note") for x in W["A"]]
uniq, cnt = np.unique([n for n in notes if n], return_counts=True)
print("bass notes (seg-median):", dict(zip(uniq.tolist(), cnt.tolist())))
f0 = col("bass_f0_meanspec_hz")
print("corr sub60_of_200 vs bass f0 (meanspec):", spear(col("sub60_of_200"), f0))
print("corr sub60_of_total vs bass f0:", spear(col("sub60_of_total"), f0))
SUMMARY["sub60_vs_f0"] = spear(col("sub60_of_200"), f0)[0]

# ------------------------------------------------------------------ 3 kick vs bass separability
rr = col("bass_rerise_share")
print("\n## kick vs bass by timing")
print(f"rerise_share >= 0.5: {np.mean(rr >= 0.5):.2f} of tracks; <= 0.1: {np.mean(rr <= 0.1):.2f}; median {np.median(rr):.2f}")
print(f"boom censored share >= 0.5 (T20 never reached within the beat): {np.mean(col('boom_censored_share') >= 0.5):.2f} of tracks")
print(f"low-band onset on the beat per beat: median {np.nanmedian(col('low_onbeat_per_beat')):.2f}; between beats per beat: median {np.nanmedian(col('low_between_per_beat')):.2f}")
print(f"bassnote_t20 available (>=8 between-beat low events): {np.mean(np.isfinite(col('bassnote_t20_ms'))):.2f}; kick_t20 available: {np.mean(np.isfinite(col('kick_t20_ms'))):.2f}")
SUMMARY["rerise_ge_05"] = float(np.mean(rr >= 0.5))
SUMMARY["boom_censored_ge_05"] = float(np.mean(col("boom_censored_share") >= 0.5))

# ------------------------------------------------------------------ 4 hats diagnostics
print("\n## W4 picker diagnostics")
ext = np.array([r["path"].rsplit(".", 1)[-1].lower() for r in ok])
lag = col("lag_ms")
for grp, m in (("lossless aiff/wav/flac", np.isin(ext, ["aiff", "wav", "flac"])), ("mp3", ext == "mp3"), ("m4a", ext == "m4a")):
    if m.any():
        print(f"grid lag {grp:24s} n={m.sum():2d} median {np.median(lag[m]):6.1f} ms  min {lag[m].min():6.1f} max {lag[m].max():6.1f}")
lagb = col("lag_ms", "B")
print(f"lag A vs B: |diff| median {np.median(np.abs(lag - lagb)):.1f} ms, <=3 ms in {np.mean(np.abs(lag - lagb) <= 3):.2f}")
print(f"lattice16 abs dev median {np.nanmedian(col('h7_lattice16_absdev_ms')):.1f} ms; est. spurious share (2*other) median {np.nanmedian(col('h7_spurious_est')):.2f}, p90 {np.nanpercentile(col('h7_spurious_est'), 90):.2f}")
d15, d25, d40 = col("h7_hats_per_beat_d15"), col("h7_hats_per_beat"), col("h7_hats_per_beat_d40")
print(f"delta sensitivity: median hats/beat d0.15 {np.median(d15):.2f}  d0.25 {np.median(d25):.2f}  d0.40 {np.median(d40):.2f};  Spearman d15~d40 {spear(d15, d40)[0]:.2f}, d25~d40 {spear(d25, d40)[0]:.2f}, d15~d25 {spear(d15, d25)[0]:.2f}; median ratio d15/d40 {np.median(d15 / d40):.2f}")
print(f"count vs threshold-free flux: Spearman hats_per_beat ~ flux_per_beat {spear(d25, col('h7_flux_per_beat'))[0]:.2f}")
print(f"band >7k vs 5-12k: Spearman hats_per_beat {spear(d25, col('h5_hats_per_beat'))[0]:.2f}; decay {spear(col('h7_hat_decay_ms'), col('h5_hat_decay_ms'))[0]:.2f}; open share {spear(col('h7_hat_open_share'), col('h5_hat_open_share'))[0]:.2f}")
print(f"hpss needed? Spearman perc_share_7k_db ~ plain hi7k_share_db {spear(col('perc_share_7k_db'), col('hi7k_share_db'))[0]:.3f}")
SUMMARY["hat_delta_spearman_d15_d40"] = spear(d15, d40)[0]
SUMMARY["hat_spurious_median"] = float(np.nanmedian(col("h7_spurious_est")))
SUMMARY["perc_vs_plain_hi7k"] = spear(col("perc_share_7k_db"), col("hi7k_share_db"))[0]

# ------------------------------------------------------------------ 5 W5 pattern
print("\n## W5 16-step pattern: stability and discriminability")


def cosmat(X, Y, center=False):
    X, Y = np.array(X, float), np.array(Y, float)
    if center:
        X, Y = X - X.mean(1, keepdims=True), Y - Y.mean(1, keepdims=True)
    X = X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-12)
    Y = Y / (np.linalg.norm(Y, axis=1, keepdims=True) + 1e-12)
    return X @ Y.T


def pattern_stats(tag, key, w1, w2, center):
    idx = [i for i, r in enumerate(ok) if r[w1]["hats"][tag].get(key) and r[w2]["hats"][tag].get(key)
           and sum(r[w1]["hats"][tag][key]) > 0 and sum(r[w2]["hats"][tag][key]) > 0]
    X = [ok[i][w1]["hats"][tag][key] for i in idx]
    Y = [ok[i][w2]["hats"][tag][key] for i in idx]
    C = cosmat(X, Y, center)
    own = np.diag(C)
    off = C[~np.eye(len(idx), dtype=bool)]
    rank = np.array([(C[i] > C[i, i]).sum() + 1 for i in range(len(idx))])
    return {"n": len(idx), "own_median": float(np.median(own)), "own_p10": float(np.percentile(own, 10)),
            "cross_median": float(np.median(off)), "top1": float(np.mean(rank == 1)), "mrr": float(np.mean(1 / rank)),
            "top3": float(np.mean(rank <= 3))}


SUMMARY["w5"] = {}
for tag in ("h7", "h5"):
    for key in ("hist16", "flux16"):
        for w1, w2 in (("A1", "A2"), ("A", "B")):
            for center in (False, True):
                st = pattern_stats(tag, key, w1, w2, center)
                nm = f"{tag}_{key}_{w1}{w2}_{'centered' if center else 'cos'}"
                SUMMARY["w5"][nm] = st
                print(f"{nm:32s} n={st['n']} own median {st['own_median']:.3f} p10 {st['own_p10']:.3f} | cross-track median {st['cross_median']:.3f} | top1 {st['top1']:.2f} top3 {st['top3']:.2f} MRR {st['mrr']:.2f}  (chance top1 {1/st['n']:.3f})")
H = np.array([r["A"]["hats"]["h7"]["hist16"] for r in ok], float)
per_beat = H.reshape(len(H), 4, 4).mean(1)
recon = np.tile(per_beat, (1, 4))
c4 = np.array([np.corrcoef(H[i], recon[i])[0, 1] if np.ptp(H[i]) > 0 and np.ptp(recon[i]) > 0 else np.nan for i in range(len(H))])
print(f"16-step vs its 4-step (one beat) repetition: median Pearson r {np.nanmedian(c4):.2f} -> share of variance carried by the 1-beat pattern {np.nanmedian(c4)**2:.2f}")
flat_cv = H.std(1) / (H.mean(1) + 1e-9)
print(f"flatness of the 16-step histogram (CV over steps): median {np.median(flat_cv):.2f}, p10 {np.percentile(flat_cv, 10):.2f} (0 = every step equally filled)")
SUMMARY["w5"]["one_beat_r2"] = float(np.nanmedian(c4) ** 2)

# ------------------------------------------------------------------ 6 genre contrast
GROUPS = [("Hard Techno", ["Hard Techno"]), ("Raw", ["Raw"]), ("Techno", ["Techno"]), ("Groove", ["Groove"]),
          ("Trance", ["Trance"]), ("House", ["House"]), ("Uptempo", ["Uptempo"]), ("Hip-Hop*", ["Hip-Hop*"])]
CONTRAST = ["bass_f0_meanspec_hz", "sub60_of_200", "sub60_of_total", "boom_t20_ms", "boom_t20_rel", "bass_sustain_ratio",
            "bass_dip_db", "bass_between_db", "bass_rerise_share", "hi7k_share_db", "perc_share_7k_db", "h7_hats_per_beat",
            "h7_hats_per_beat_nonbeat", "h7_flux_per_beat", "h7_offbeat_share", "h7_sixteenth_share", "h7_other_share",
            "h7_hat_decay_ms", "h7_hat_open_share", "h7_open_share_offbeat", "hpr_mid_db", "chroma_entropy", "pitch_salience",
            "pitch_salience_p90", "voiced_share_t45", "note_changes_per_beat_t30", "note_changes_per_beat_t45",
            "note_changes_per_beat_t60", "n_pitch_classes", "tonal_share_mid", "tonality_db", "harm_flux"]
print("\n## genre medians (window A) + contrast hard (Hard Techno+Raw+Uptempo) vs soft (House+Trance): Mann-Whitney p, rank-biserial r (+ = hard higher)")
print(f"{'feature':28s} " + " ".join(f"{g[:8]:>8s}" for g, _ in GROUPS) + "   p_MW   r_rb   KW_p")
print(f"{'n':28s} " + " ".join(f"{int(np.isin(genre, m).sum()):8d}" for _, m in GROUPS))
hard, soft = np.isin(genre, ["Hard Techno", "Raw", "Uptempo"]), np.isin(genre, ["House", "Trance"])
SUMMARY["genre"] = {}
for name in ["bpm"] + CONTRAST:
    a = bpm if name == "bpm" else col(name)
    meds = [np.nanmedian(a[np.isin(genre, m)]) if np.isfinite(a[np.isin(genre, m)]).any() else np.nan for _, m in GROUPS]
    x, y = a[hard & np.isfinite(a)], a[soft & np.isfinite(a)]
    u, p = stats.mannwhitneyu(x, y, alternative="two-sided")
    rb = 2 * u / (len(x) * len(y)) - 1
    kw = stats.kruskal(*[a[np.isin(genre, m) & np.isfinite(a)] for g, m in GROUPS if g not in ("Hip-Hop*", "Uptempo")])[1]
    print(f"{name:28s} " + " ".join(f"{v:8.2f}" for v in meds) + f"  {p:6.3f} {rb:6.2f} {kw:6.3f}")
    SUMMARY["genre"][name] = {"medians": dict(zip([g for g, _ in GROUPS], [float(v) for v in meds])), "p_mw": float(p), "r_rb": float(rb), "kw_p": float(kw)}

# ------------------------------------------------------------------ 7 correlation matrix
CM = ["sub60_of_200", "bass_f0_meanspec_hz", "boom_t20_rel", "bass_sustain_ratio", "bass_dip_db", "perc_share_7k_db",
      "h7_hats_per_beat", "h7_flux_per_beat", "h7_sixteenth_share", "h7_hat_decay_ms", "h7_hat_open_share", "hpr_mid_db",
      "chroma_entropy", "pitch_salience", "note_changes_per_beat_t45", "tonal_share_mid", "harm_flux"]
short = ["sub60", "f0", "boomRel", "sustain", "dip", "perc7k", "hats/b", "flux/b", "16th", "decay", "open", "HPR", "chrEnt", "salience", "noteChg", "tonal", "hFlux"]
print("\n## Spearman matrix (window A, n=%d)" % len(ok))
print(f"{'':9s}" + " ".join(f"{s[:7]:>7s}" for s in short) + "     BPM")
M = np.zeros((len(CM), len(CM)))
for i, a in enumerate(CM):
    line = f"{short[i]:9s}"
    for j, b in enumerate(CM):
        M[i, j] = spear(col(a), col(b))[0]
        line += f" {M[i, j]:7.2f}"
    line += f" {spear(col(a), bpm)[0]:7.2f}"
    print(line)
SUMMARY["corr"] = {"features": CM, "matrix": M.tolist(), "bpm": [spear(col(a), bpm)[0] for a in CM]}

# ------------------------------------------------------------------ 8 top / bottom
NOTE = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
TOP = ["bass_f0_meanspec_hz", "sub60_of_200", "sub60_of_total", "boom_t20_ms", "boom_t20_rel", "bass_sustain_ratio", "bass_dip_db", "bass_between_db", "bassnote_t20_ms", "h7_hats_per_beat_nonbeat", "h7_open_share_offbeat",
       "perc_share_7k_db", "h7_hats_per_beat", "h7_flux_per_beat", "h7_sixteenth_share", "h7_offbeat_share",
       "h7_hat_decay_ms", "h7_hat_open_share", "hpr_mid_db", "chroma_entropy", "pitch_salience", "pitch_salience_p90",
       "note_changes_per_beat_t45", "note_changes_per_beat_t60", "tonal_share_mid", "harm_flux"]
print("\n## top 5 / bottom 5 per feature (window A)")
SUMMARY["topbottom"] = {}
for name in TOP:
    a = col(name)
    idx = [i for i in np.argsort(a) if np.isfinite(a[i])]
    lab = lambda i: f"{(meta[i]['artist'] or '?')[:28]} - {(meta[i]['title'] or '?')[:44]} [{meta[i]['genre']}, {a[i]:.3g}]" + (f" {NOTE[int(round(69 + 12 * np.log2(a[i] / 440))) % 12]}{int(round(69 + 12 * np.log2(a[i] / 440))) // 12 - 1}" if "f0" in name else "")
    print(f"\n{name}\n  TOP:    " + "\n          ".join(lab(i) for i in idx[::-1][:5]) + "\n  BOTTOM: " + "\n          ".join(lab(i) for i in idx[:5]))
    SUMMARY["topbottom"][name] = {"top": [[meta[i]["id"], meta[i]["artist"], meta[i]["title"], meta[i]["genre"], float(a[i])] for i in idx[::-1][:5]],
                                  "bottom": [[meta[i]["id"], meta[i]["artist"], meta[i]["title"], meta[i]["genre"], float(a[i])] for i in idx[:5]]}

# ------------------------------------------------------------------ 9 cost
print("\n## cost per 120 s excerpt (CPU s = process_time, wall s), n=%d" % len(ok))
blocks = ["load", "lag", "bass", "hpss", "hats", "mel"]
tot_cpu = np.zeros(len(ok))
SUMMARY["cost"] = {}
for b in blocks:
    c = np.array([r["timing"][b][0] for r in ok])
    w = np.array([r["timing"][b][1] for r in ok])
    tot_cpu += c
    print(f"{b:6s} cpu median {np.median(c):6.2f}  p90 {np.percentile(c, 90):6.2f}  max {c.max():6.2f} | wall median {np.median(w):6.2f}")
    SUMMARY["cost"][b] = {"cpu_median": float(np.median(c)), "cpu_p90": float(np.percentile(c, 90)), "wall_median": float(np.median(w))}
print(f"total  cpu median {np.median(tot_cpu):6.2f}  p90 {np.percentile(tot_cpu, 90):6.2f}")
for e_ in ("aiff", "wav", "flac", "mp3", "m4a"):
    m = ext == e_
    if m.any():
        print(f"  load by ext {e_:5s} n={m.sum():2d} cpu median {np.median([r['timing']['load'][0] for r, k in zip(ok, m) if k]):.2f} wall {np.median([r['timing']['load'][1] for r, k in zip(ok, m) if k]):.2f}")
no_hpss = tot_cpu - np.array([r["timing"]["hpss"][0] for r in ok]) - np.array([r["timing"]["mel"][0] for r in ok])
FILES, MEAN_S = 4633, 305.0
scale = MEAN_S / 120.0
for label, v in (("all blocks", np.median(tot_cpu)), ("without hpss+melody (W2+W4+W5 only)", np.median(no_hpss))):
    print(f"{label}: 120 s excerpt {v:.1f} CPU s/track -> library {v * FILES / 3600:.1f} CPU-h; full track (x{scale:.2f}, Schaetzung) {v * scale:.1f} s -> {v * scale * FILES / 3600:.1f} CPU-h")
    SUMMARY["cost"][label] = {"excerpt_s": float(v), "library_cpu_h": float(v * FILES / 3600), "full_track_s": float(v * scale), "full_library_cpu_h": float(v * scale * FILES / 3600)}
rss = [r["rss_peak_mb"] for r in ok]
print(f"peak RSS per worker process: max {max(rss):.0f} MB; after warm-up {ok[0]['rss_after_warmup_mb']:.0f} MB")
first = [r for r in ok if order[r["id"]] < 4]
for r in first:
    t = r["timing"]
    print("  first track of shard: RSS after load/lag/bass/hpss/hats/mel:", [t[b + "_rss"] for b in blocks])
SUMMARY["cost"]["rss_peak_mb"] = float(max(rss))

# ------------------------------------------------------------------ 10 app comparison
p8 = HERE / "w8_compare.jsonl"
if p8.exists():
    c8 = [json.loads(l) for l in open(p8, encoding="utf-8")]
    g = lambda f: np.array([f(r) for r in c8], float)
    a60, a120 = g(lambda r: r["app_share_60"]), g(lambda r: r["app_share_120"])
    w60, w120 = g(lambda r: r["whole"]["sub60_of_total"]), g(lambda r: r["whole"]["sub120_of_total"])
    e60, e120 = g(lambda r: r["excerpt"]["sub60_of_total"]), g(lambda r: r["excerpt"]["sub120_of_total"])
    m60, m120 = g(lambda r: r["appmethod_excerpt"]["share_60"]), g(lambda r: r["appmethod_excerpt"]["share_120"])
    print(f"\n## W2b vs app whole-track numbers (audio_w8.jsonl), n={len(c8)}")
    for lab, x, y in (("app whole <60/total vs mine whole (method)", a60, w60), ("mine whole vs mine middle-120s (excerpt)", w60, e60),
                      ("app whole vs mine middle-120s (both)", a60, e60), ("app whole vs app-method on middle-120s", a60, m60),
                      ("app whole <120/total vs mine whole", a120, w120), ("mine whole vs mine excerpt <120", w120, e120),
                      ("app whole <120 vs mine excerpt <120", a120, e120)):
        print(f"{lab:46s} Spearman {spear(x, y)[0]:.3f}  Pearson {np.corrcoef(x, y)[0, 1]:.3f}  median |diff| {np.median(np.abs(x - y)):.3f}  mean diff (y-x) {np.mean(y - x):+.3f}")
    print(f"app share_60: median {np.median(a60):.3f} range {a60.min():.3f}-{a60.max():.3f}; mine whole: median {np.median(w60):.3f}")
    SUMMARY["w8"] = {"n": len(c8), "app_vs_mine_whole_60": spear(a60, w60)[0], "whole_vs_excerpt_60": spear(w60, e60)[0],
                     "app_vs_excerpt_60": spear(a60, e60)[0], "app_vs_mine_whole_120": spear(a120, w120)[0],
                     "app_vs_excerpt_120": spear(a120, e120)[0], "median_abs_diff_60_method": float(np.median(np.abs(a60 - w60))),
                     "median_abs_diff_60_excerpt": float(np.median(np.abs(w60 - e60)))}

print("\n## track ids")
print(",".join(r["id"] for r in rows))
SUMMARY["ids"] = [r["id"] for r in rows]
json.dump(SUMMARY, open(HERE / "eval_summary.json", "w", encoding="utf-8"), indent=1, default=float)
