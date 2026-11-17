"""Own-half retrieval of W1 / W5 fingerprint variants built from run_sim.py output.

Protocol: per track two non-overlapping 60 s halves (A1 / A2 of the middle 120 s; B1 / B2 of the
window at 5 %). All 2N half-fingerprints form the candidate set; the query is X1 of a track, its
own X2 must be found among the 2N - 1 others. Reports top-1 / top-10 / MRR (chance 1 / (2N - 1)),
split-half Spearman of scalars, genre split, quality-leak check, cost.
Usage: eval_sim.py [results dir] > eval_sim.txt"""
import glob
import json
import sys
from pathlib import Path

import numpy as np
from scipy import stats
from scipy.fft import dct
from scipy.spatial.distance import cdist
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / "app").is_dir())
DATA = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "tmp" / "sc-similarity"
sys.argv = sys.argv[:1]
from run_sim import FB, HB_EDGES  # noqa: E402

rows = [json.loads(l) for f in sorted(glob.glob(str(DATA / "sim_shard*.jsonl"))) for l in open(f, encoding="utf-8")]
rows = [r for r in rows if r["status"] == "ok"]
rows.sort(key=lambda r: (bool(r.get("extra")), r["id"]))
PRIM = [r for r in rows if not r.get("extra")]
ALL = rows
print(f"tracks ok: primary {len(PRIM)}, extra lossy {len(ALL) - len(PRIM)}")


def arr(x):
    return np.array([np.nan if v is None else v for v in x], dtype=float)


# ------------------------------------------------------------------ feature builders (one half -> vector)
LOG32 = np.geomspace(30, 250, 33)
LIN24 = np.linspace(30, 250, 25)


def bands(spec_db, edges):
    return np.array([np.nanmean(spec_db[(FB >= a) & (FB < b)]) for a, b in zip(edges[:-1], edges[1:])])


def snd_log32(h, tag):
    v = bands(arr(h["bass"][tag]["mean_log"]), LOG32)
    return v - v.mean()


def snd_lin24(h, tag):
    v = bands(arr(h["bass"][tag]["mean_log"]), LIN24)
    return v - v.mean()


def snd_pow32(h, tag):
    p = arr(h["bass"][tag]["mean_pow"])
    v = 10 * np.log10(np.array([p[(FB >= a) & (FB < b)].mean() for a, b in zip(LOG32[:-1], LOG32[1:])]) + 1e-30)
    return v - v.mean()


def snd_dct12(h, tag):
    return dct(snd_log32(h, tag), norm="ortho")[1:13]


def snd_scalar(h, tag):
    b = h["bass"][tag]
    hd = arr(b["harm_db"])
    return np.array([np.log(b["cent"]), np.log(b["cent_rel"]), np.log(b["flat"]), b["harm_share"],
                     np.nan_to_num(hd[1], nan=-40), np.nan_to_num(hd[2], nan=-40), np.nan_to_num(hd[3], nan=-40)])


def snd_dct_scalar(h, tag):
    return np.concatenate((snd_dct12(h, tag), snd_scalar(h, tag)))


def snd_hrel(h, tag, hmax=6.0, step=1):
    from run_sim import HGRID
    v = arr(h["bass"][tag]["hrel"])[(HGRID <= hmax + 1e-9)][::step]
    return v


def snd_hrel_sc(h, tag):
    return np.concatenate((snd_hrel(h, tag, 4.0), snd_scalar(h, tag)[[1, 2, 3]]))


def snd_both_dct(h, _tag):
    return np.concatenate((snd_dct12(h, "off"), snd_dct12(h, "on")))


def rhy_e16(h):
    v = arr(h["line"]["e16_db"])
    return v - v.mean()


def rhy_e12(h):
    v = rhy_e16(h)
    return np.delete(v, [0, 4, 8, 12])


def rhy_flux16(h):
    v = arr(h["line"]["flux16"])
    return v / (v.sum() + 1e-12)


def _rotate_pc(M, ref):
    return np.roll(M, -ref, axis=1)


def pit_H(h):
    H = arr(h["line"]["H16"]).reshape(16, 12)
    N = np.maximum(arr(h["line"]["N16"]), 1)[:, None]
    ref = int(H.sum(0).argmax()) if H.sum() > 0 else 0
    return (_rotate_pc(H, ref) / N).ravel()


def pit_C(h):
    C = arr(h["line"]["C16"]).reshape(16, 12)
    N = np.maximum(arr(h["line"]["N16"]), 1)[:, None]
    ref = int(C.sum(0).argmax())
    return (_rotate_pc(C, ref) / N).ravel()


def pit_C_abs(h):
    C = arr(h["line"]["C16"]).reshape(16, 12)
    return (C / np.maximum(arr(h["line"]["N16"]), 1)[:, None]).ravel()


def pit_hist12(h):
    H = arr(h["line"]["H16"]).reshape(16, 12).sum(0)
    if H.sum() == 0:
        return np.zeros(12)
    return np.roll(H, -int(H.argmax())) / H.sum()


def pit_mode16(h):
    H = arr(h["line"]["H16"]).reshape(16, 12)
    V = arr(h["line"]["V16"])
    N = np.maximum(arr(h["line"]["N16"]), 1)
    ref = int(H.sum(0).argmax()) if H.sum() > 0 else 0
    m = np.roll(H, -ref, axis=1).argmax(1).astype(float)
    m[V / N < 0.3] = -1
    return m


def hat_bands(h, key, lo, hi):
    v = arr(h["hat"][key])
    edges_lo = HB_EDGES[:-1]
    m = (edges_lo >= lo - 1) & (edges_lo < hi - 1)
    return v[m]


def hat_post24(h):
    v = hat_bands(h, "post_log", 5000, 12000)
    return v - v.mean()


def hat_post12(h):
    v = hat_post24(h)
    return v.reshape(12, 2).mean(1)


def hat_nb24(h):
    v = hat_bands(h, "post_log_nb" if "post_log_nb" in h["hat"] else "post_log", 5000, 12000)
    return v - v.mean()


def hat_pre24(h):
    v = 10 * np.log10(hat_bands(h, "pre_pow", 5000, 12000) + 1e-30)
    return v - v.mean()


def hat_diff24(h):
    return hat_bands(h, "diff_log", 5000, 12000)


def hat_decay(h):
    x = h["hat"]
    return np.concatenate((arr(x["decay_prof_db"]), [np.log(x["hat_decay_ms"] or 1), np.log(x["hat_t10_ms"] or 1), x["hat_open_share"] or 0]))


def hat_post24_decay(h):
    return np.concatenate((hat_post24(h), hat_decay(h)))


def hat_hi(h):  # leak contrast: 12-20 kHz bands, same onsets
    v = hat_bands(h, "post_log", 12000, 20000)
    return v - hat_bands(h, "post_log", 5000, 12000).mean()


def hat_7_20(h):
    v = hat_bands(h, "post_log", 7000, 20000)
    return v - v.mean()


def hat_flux16(h):
    v = arr(h["hat"]["flux16"])
    return v


# ------------------------------------------------------------------ distances
def d_eucz(X):
    X = np.where(np.isfinite(X), X, np.nanmean(X, axis=0, keepdims=True))
    X = np.nan_to_num(X)
    sd = X.std(0)
    sd[sd == 0] = 1
    return cdist((X - X.mean(0)) / sd, (X - X.mean(0)) / sd)


def d_cosc(X):
    X = np.nan_to_num(X)
    X = X - X.mean(1, keepdims=True)
    X = X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-12)
    return 1 - X @ X.T


def d_cos(X):
    X = np.nan_to_num(X)
    X = X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-12)
    return 1 - X @ X.T


def d_rot4(base):
    """min over the 4 beat rotations of the 16-step axis (downbeat-free)."""
    def f(X):
        k = X.shape[1] // 16
        out = np.full((len(X), len(X)), np.inf)
        for r in range(4):
            Y = np.roll(X.reshape(len(X), 16, k), 4 * r, axis=1).reshape(len(X), -1)
            Z = np.vstack((X, Y))
            out = np.minimum(out, base(Z)[: len(X), len(X):])
        return out
    return f


def d_oti(X):
    """transposition-invariant: min over 12 pitch rotations of the 16x12 matrix (cosine)."""
    n = len(X)
    out = np.full((n, n), np.inf)
    for r in range(12):
        Y = np.roll(X.reshape(n, -1, 12), r, axis=2).reshape(n, -1)
        out = np.minimum(out, d_cos(np.vstack((X, Y)))[:n, n:])
    return out


def d_mode(X):
    a, b = X[:, None, :], X[None, :, :]
    return ((a != b) & ~((a < 0) & (b < 0))).mean(2)


def norm_med(D):
    off = D[~np.eye(len(D), dtype=bool)]
    return D / (np.median(off) + 1e-12)


# ------------------------------------------------------------------ retrieval
def halves(rs, fn, w):
    return np.array([fn(r[w + "1"]) for r in rs]), np.array([fn(r[w + "2"]) for r in rs])


def ranks_from_D(D):
    n = len(D) // 2
    rk = np.empty(n, int)
    for i in range(n):
        d = D[i].copy()
        d[i] = np.inf
        rk[i] = int((d < d[n + i]).sum()) + 1
    return rk


def summ(rk):
    return np.mean(rk == 1), np.mean(rk <= 10), np.mean(1.0 / rk)


def dist_of(rs, fn, metric, w, f16=False):
    X1, X2 = halves(rs, fn, w)
    X = np.vstack((X1, X2))
    if f16:
        X = X.astype(np.float16).astype(float)
    return metric(X)


GEN = np.array([r["genre"] for r in PRIM])
GROUPS = {"hard (HT+Raw+Upt)": np.isin(GEN, ["Hard Techno", "Raw", "Uptempo"]),
          "techno+groove": np.isin(GEN, ["Techno", "Groove"]),
          "soft (House+Trance)": np.isin(GEN, ["House", "Trance"])}
RES = {}


def report(name, fn, metric, rs=PRIM, label=None, f16=False):
    out = {}
    for w in ("A", "B"):
        D = dist_of(rs, fn, metric, w, f16)
        rk = ranks_from_D(D)
        out[w] = (rk, D)
    dim = len(fn(rs[0]["A1"]))
    a, b = summ(out["A"][0]), summ(out["B"][0])
    print(f"{name:44s} d={dim:3d} {dim * 2:4d}B | A top1 {a[0]:.2f} top10 {a[1]:.2f} MRR {a[2]:.2f} | B top1 {b[0]:.2f} top10 {b[1]:.2f} MRR {b[2]:.2f}")
    RES[label or name] = out
    return out


def report_D(name, DA, DB, dim):
    rka, rkb = ranks_from_D(DA), ranks_from_D(DB)
    a, b = summ(rka), summ(rkb)
    print(f"{name:44s} d={dim:3d} {dim * 2:4d}B | A top1 {a[0]:.2f} top10 {a[1]:.2f} MRR {a[2]:.2f} | B top1 {b[0]:.2f} top10 {b[1]:.2f} MRR {b[2]:.2f}")
    RES[name] = {"A": (rka, DA), "B": (rkb, DB)}


def genre_split(label):
    rk = RES[label]["A"][0]
    rkb = RES[label]["B"][0]
    s = " | ".join(f"{g} n={m.sum()}: A {np.mean(rk[m] == 1):.2f}/{np.mean(rk[m] <= 10):.2f} B {np.mean(rkb[m] == 1):.2f}/{np.mean(rkb[m] <= 10):.2f}" for g, m in GROUPS.items())
    print(f"  genre split {label} (top1/top10): {s}")


n = len(PRIM)
print(f"chance: top1 {1 / (2 * n - 1):.3f}, top10 {10 / (2 * n - 1):.3f}, MRR ~{np.mean([1 / k for k in range(1, 2 * n)]):.3f}\n")

print("## W1 bass SOUND (30-250 Hz, between-kick 'off' = kick excluded, on-beat 'on' = kick included)")
for tag in ("off", "on"):
    report(f"{tag}: log-band 32 (mean dB), eucz", lambda h, t=tag: snd_log32(h, t), d_eucz, label=f"snd_log32_{tag}")
    report(f"{tag}: log-band 32, centred cosine", lambda h, t=tag: snd_log32(h, t), d_cosc)
    report(f"{tag}: lin(mel-like)-band 24, eucz", lambda h, t=tag: snd_lin24(h, t), d_eucz, label=f"snd_lin24_{tag}")
    report(f"{tag}: log of mean power 32, eucz", lambda h, t=tag: snd_pow32(h, t), d_eucz, label=f"snd_pow32_{tag}")
    report(f"{tag}: DCT-12 of log-band 32 (envelope), eucz", lambda h, t=tag: snd_dct12(h, t), d_eucz, label=f"snd_dct12_{tag}")
    report(f"{tag}: scalars (cent, cent/f0, flat, harm, h2-h4)", lambda h, t=tag: snd_scalar(h, t), d_eucz, label=f"snd_scalar_{tag}")
    report(f"{tag}: DCT-12 + scalars, eucz", lambda h, t=tag: snd_dct_scalar(h, t), d_eucz, label=f"snd_dctsc_{tag}")
report("off+on: DCT-12 each, eucz", lambda h: snd_both_dct(h, None), d_eucz, label="snd_both")
print("-- transposition-invariant by construction (log spectrum on the f0-relative axis h * f0, h 0.5..):")
for tag in ("off", "on"):
    report(f"{tag}: f0-relative spectrum h 0.5-6 step 1/8, eucz", lambda h, t=tag: snd_hrel(h, t), d_eucz, label=f"snd_hrel6_{tag}")
    report(f"{tag}: f0-relative spectrum h 0.5-4 step 1/8, eucz", lambda h, t=tag: snd_hrel(h, t, 4.0), d_eucz, label=f"snd_hrel4_{tag}")
    report(f"{tag}: f0-relative spectrum h 0.5-4 step 1/2, eucz", lambda h, t=tag: snd_hrel(h, t, 4.0, 4), d_eucz, label=f"snd_hrel4c_{tag}")
    report(f"{tag}: f0-rel h 0.5-4 + cent/f0, flat, harm share", lambda h, t=tag: snd_hrel_sc(h, t), d_eucz, label=f"snd_hrelsc_{tag}")

# pitch confound: share of top-10 other-track neighbours with the same bass pitch class
pc = np.array([int(round(69 + 12 * np.log2(r["A1"]["bass"]["off"]["f0"] / 440))) % 12 for r in PRIM])
base = np.mean(pc[:, None] == pc[None, :])
print(f"\npitch confound (bass f0 pitch class from A1): random pair same-pc rate {base:.2f}")
for lab in ("snd_log32_off", "snd_lin24_off", "snd_pow32_off", "snd_dct12_off", "snd_scalar_off", "snd_dctsc_off", "snd_log32_on", "snd_pow32_on", "snd_dct12_on"):
    D = RES[lab]["A"][1][:n, :n].copy()
    np.fill_diagonal(D, np.inf)
    nn = np.argsort(D, axis=1)[:, :10]
    print(f"  {lab:16s} top-10 neighbours same pc {np.mean(pc[nn] == pc[:, None]):.2f}")

# transposition test: second halves' bass spectra moved up by s semitones (f -> f * 2^(s/12));
# a timbre fingerprint should still find its own half, a note fingerprint should not
import copy  # noqa: E402


def shifted(h, st):
    g = copy.deepcopy(h)
    r = 2 ** (st / 12)
    for tag in ("off", "on"):
        for key in ("mean_log", "mean_pow"):
            v = arr(g["bass"][tag][key])
            g["bass"][tag][key] = list(np.interp(FB / r, FB, v, left=np.nan, right=np.nan))
        g["bass"][tag]["cent"] = g["bass"][tag]["cent"] * r
    return g


print("transposition test (A2 spectra shifted; query A1; top1 / top10):")
for lab, fn in (("log32 off", lambda h: snd_log32(h, "off")), ("lin24 off", lambda h: snd_lin24(h, "off")),
                ("pow32 off", lambda h: snd_pow32(h, "off")), ("dct12 off", lambda h: snd_dct12(h, "off")),
                ("scalars off", lambda h: snd_scalar(h, "off")), ("dct12 on", lambda h: snd_dct12(h, "on")),
                ("pow32 on", lambda h: snd_pow32(h, "on"))):
    out = []
    for st in (0, 1, 2, 5):
        X1 = np.array([fn(r["A1"]) for r in PRIM])
        X2 = np.array([fn(shifted(r["A2"], st)) for r in PRIM])
        rk = ranks_from_D(d_eucz(np.vstack((X1, X2))))
        out.append(f"{st:+d} st {np.mean(rk == 1):.2f}/{np.mean(rk <= 10):.2f}")
    print(f"  {lab:12s} " + " | ".join(out))

print("\n## W1 bass LINE (16 steps / bar, downbeat-anchored)")
report("rhythm: 40-120 Hz energy 16 steps (dB), eucz", rhy_e16, d_eucz, label="rhy_e16")
report("rhythm: energy 16 steps, centred cosine", rhy_e16, d_cosc, label="rhy_e16_cos")
report("rhythm: energy 12 between-kick steps, eucz", rhy_e12, d_eucz, label="rhy_e12")
report("rhythm: low-band flux 16 steps, cosine", rhy_flux16, d_cos, label="rhy_flux16")
report("rhythm: energy 16, rotation-free (min of 4)", rhy_e16, d_rot4(d_cosc), label="rhy_e16_rot")
report("notes: ACF-f0 pc x step (16x12), key-rotated, cos", pit_H, d_cos, label="pit_H")
report("notes: chroma x step (16x12), key-rotated, cos", pit_C, d_cos, label="pit_C")
report("notes: chroma x step, OTI min over 12 shifts", pit_C_abs, d_oti, label="pit_C_oti")
report("notes: relative pc histogram 12 (no rhythm)", pit_hist12, d_cos, label="pit_hist12")
report("notes: modal relative pc per step (16 B)", pit_mode16, d_mode, label="pit_mode16")
report("notes: chroma x 8th-step (8x12), key-rotated, cos", lambda h: pit_C(h).reshape(8, 2, 12).sum(1).ravel(), d_cos, label="pit_C8")
report("notes: chroma x step, uint8-quantised, cos", lambda h: np.round(pit_C(h) / (pit_C(h).max() + 1e-12) * 255), d_cos, label="pit_C_u8")
report("notes: chroma x 12 between-kick steps, uint8, OTI (144 B)", lambda h: (lambda c: np.round(c / (c.max() + 1e-12) * 255))(np.delete(pit_C_abs(h).reshape(16, 12), [0, 4, 8, 12], axis=0).ravel()), d_oti, label="pit_C12_oti_u8")
report("notes: chroma x step, uint8, OTI (192 B)", lambda h: np.round(pit_C_abs(h) / (pit_C_abs(h).max() + 1e-12) * 255), d_oti, label="pit_C_oti_u8")

print("\n## W1 line combined (rhythm + notes, distances / median, equal weight)")
for r_lab, p_lab in (("rhy_e16", "pit_C"), ("rhy_e16", "pit_C_oti"), ("rhy_e16", "pit_H"), ("rhy_e12", "pit_C"), ("rhy_flux16", "pit_C"),
                     ("rhy_flux16", "pit_C_oti"), ("rhy_flux16", "pit_C8"), ("rhy_flux16", "pit_C_u8"), ("rhy_flux16", "pit_C12_oti_u8")):
    DA = 0.5 * norm_med(RES[r_lab]["A"][1]) + 0.5 * norm_med(RES[p_lab]["A"][1])
    DB = 0.5 * norm_med(RES[r_lab]["B"][1]) + 0.5 * norm_med(RES[p_lab]["B"][1])
    report_D(f"line = {r_lab} + {p_lab}", DA, DB, 16 + 192)

print("\n## W1 combined (sound + line)")
SND_BEST = {}
INV = ("snd_hrel6_", "snd_hrel4_", "snd_hrel4c_", "snd_hrelsc_", "snd_scalar_")
for tag in ("off", "on"):
    cands = [k for k in RES if k.startswith("snd_") and k.endswith(tag)]
    best_any = max(cands, key=lambda k: summ(RES[k]["A"][0])[2])
    SND_BEST[tag] = max([p + tag for p in INV], key=lambda k: summ(RES[k]["A"][0])[2])
    print(f"'{tag}': best own-half sound variant {best_any} (note-driven, fails transposition); best transposition-invariant {SND_BEST[tag]}")
LINE_BEST = max([k for k in RES if k.startswith("line = ")], key=lambda k: summ(RES[k]["A"][0])[2])
print(f"best line variant by MRR (A): {LINE_BEST}")
for tag in ("off", "on"):
    for ws in (0.25, 0.5, 0.75):
        DA = ws * norm_med(RES[SND_BEST[tag]]["A"][1]) + (1 - ws) * norm_med(RES[LINE_BEST]["A"][1])
        DB = ws * norm_med(RES[SND_BEST[tag]]["B"][1]) + (1 - ws) * norm_med(RES[LINE_BEST]["B"][1])
        report_D(f"W1 {tag}: {ws:.2f} sound + {1 - ws:.2f} line", DA, DB, 0)
print("\n## genre split (A1->A2 and B1->B2; candidate set always all halves)")
for tag in ("off", "on"):
    for ws in (0.5,):
        DA = ws * norm_med(RES["snd_dct12_" + tag]["A"][1]) + (1 - ws) * norm_med(RES[LINE_BEST]["A"][1])
        DB = ws * norm_med(RES["snd_dct12_" + tag]["B"][1]) + (1 - ws) * norm_med(RES[LINE_BEST]["B"][1])
        report_D(f"[note-driven] W1 {tag}: 0.5 dct12 + 0.5 line", DA, DB, 0)
for lab in (SND_BEST["off"], SND_BEST["on"], LINE_BEST, "W1 off: 0.50 sound + 0.50 line", "W1 on: 0.50 sound + 0.50 line"):
    genre_split(lab)

print("\n## W5 hat SOUND (onsets picked in 5-12 kHz, 46 ms post-onset frames)")
report("post-onset log spectrum 24 bands 5-12k, eucz", hat_post24, d_eucz, label="hat_post24")
report("post-onset log spectrum 24 bands, centred cos", hat_post24, d_cosc, label="hat_post24_cos")
report("post-onset log spectrum 12 bands 5-12k, eucz", hat_post12, d_eucz, label="hat_post12")
report("non-beat onsets only, 24 bands, eucz", hat_nb24, d_eucz, label="hat_nb24")
report("post minus pre (transient gain) 24 bands, eucz", hat_diff24, d_eucz, label="hat_diff24")
report("decay stats (profile 5/15/30/60 ms, T20, T10, open)", hat_decay, d_eucz, label="hat_decay")
report("24 bands + decay, eucz", hat_post24_decay, d_eucz, label="hat_post24_decay")
report("post-onset log of mean power 24 (same form as pre)", lambda h: (lambda v: v - v.mean())(10 * np.log10(hat_bands(h, "post_pow", 5000, 12000) + 1e-30)), d_eucz, label="hat_postpow24")
report("[control] PRE-onset frames only (mix background), 24 bands", hat_pre24, d_eucz, label="hat_pre24")
report("[control] PRE-onset frames only, centred cos", hat_pre24, d_cosc, label="hat_pre24_cos")
report("[leak contrast] 7-20 kHz bands, eucz", hat_7_20, d_eucz, label="hat_7_20")
report("[leak contrast] 12-20 kHz bands, eucz", hat_hi, d_eucz, label="hat_hi")
HAT_BEST = max(["hat_post24", "hat_post24_cos", "hat_post12", "hat_nb24", "hat_diff24", "hat_decay", "hat_post24_decay", "hat_postpow24"],
               key=lambda k: summ(RES[k]["A"][0])[2])
print(f"best hat sound by MRR (A): {HAT_BEST}")
print("\n## W5 combined (hat sound + flux16 pattern 5-12k)")
report("flux16 pattern alone, cosine", hat_flux16, d_cos, label="hat_flux16")
report("flux16 pattern alone, centred cosine", hat_flux16, d_cosc, label="hat_flux16c")
FLUX_BEST = max(["hat_flux16", "hat_flux16c"], key=lambda k: summ(RES[k]["A"][0])[2])
for ws in (0.5, 0.75):
    DA = ws * norm_med(RES[HAT_BEST]["A"][1]) + (1 - ws) * norm_med(RES["hat_decay"]["A"][1])
    DB = ws * norm_med(RES[HAT_BEST]["B"][1]) + (1 - ws) * norm_med(RES["hat_decay"]["B"][1])
    report_D(f"hat sound: {ws:.2f} {HAT_BEST} + {1 - ws:.2f} decay", DA, DB, 31)
    DA3 = 0.5 * norm_med(DA) + 0.5 * norm_med(RES[FLUX_BEST]["A"][1])
    DB3 = 0.5 * norm_med(DB) + 0.5 * norm_med(RES[FLUX_BEST]["B"][1])
    report_D(f"W5: 0.5 (that hat sound) + 0.5 {FLUX_BEST}", DA3, DB3, 47)
for ws in (0.25, 0.5, 0.75):
    DA = ws * norm_med(RES[HAT_BEST]["A"][1]) + (1 - ws) * norm_med(RES[FLUX_BEST]["A"][1])
    DB = ws * norm_med(RES[HAT_BEST]["B"][1]) + (1 - ws) * norm_med(RES[FLUX_BEST]["B"][1])
    report_D(f"W5: {ws:.2f} {HAT_BEST} + {1 - ws:.2f} {FLUX_BEST}", DA, DB, 0)
for lab in (HAT_BEST, FLUX_BEST, f"W5: 0.50 {HAT_BEST} + 0.50 {FLUX_BEST}"):
    genre_split(lab)

print("\n## float16 check (best variants, A)")
POSTPOW = lambda h: (lambda v: v - v.mean())(10 * np.log10(hat_bands(h, "post_pow", 5000, 12000) + 1e-30))  # noqa: E731
for nm, fn, met in (("snd hrel6 off", lambda h: snd_hrel(h, "off"), d_eucz), ("hat postpow24", POSTPOW, d_eucz),
                    ("pit_C_abs OTI", pit_C_abs, d_oti), ("rhy_flux16", rhy_flux16, d_cos)):
    if fn is None:
        continue
    D16 = dist_of(PRIM, fn, met, "A", f16=True)
    print(f"  {nm:12s} float16 top1/top10/MRR {summ(ranks_from_D(D16))}")

print("\n## robustness: retrieval on all 50 tracks (40 + 10 extra lossy), chance top1 1/99")
for nm, fn, met in (("sound off f0-rel h0.5-6", lambda h: snd_hrel(h, "off"), d_eucz), ("line flux16", rhy_flux16, d_cos),
                    ("line chroma OTI", pit_C_abs, d_oti), ("hat postpow24", POSTPOW, d_eucz), ("hat post24 cos", hat_post24, d_cosc),
                    ("hat flux16", hat_flux16, d_cos)):
    report(f"[50] {nm}", fn, met, rs=ALL, label=f"all50_{nm}")

# ------------------------------------------------------------------ split-half stability of scalars
print("\n## split-half Spearman (A1 vs A2 | B1 vs B2), primary 40")
SCAL = {
    "bass off centroid Hz": lambda h: h["bass"]["off"]["cent"], "bass off centroid/f0": lambda h: h["bass"]["off"]["cent_rel"],
    "bass off flatness": lambda h: h["bass"]["off"]["flat"], "bass off harmonic share": lambda h: h["bass"]["off"]["harm_share"],
    "bass off f0 Hz": lambda h: h["bass"]["off"]["f0"], "bass on centroid Hz": lambda h: h["bass"]["on"]["cent"],
    "bass on flatness": lambda h: h["bass"]["on"]["flat"], "bass on harmonic share": lambda h: h["bass"]["on"]["harm_share"],
    "bass off h2 dB": lambda h: arr(h["bass"]["off"]["harm_db"])[1],
    "line voiced share": lambda h: h["line"]["voiced_share"], "line f0 IQR st": lambda h: h["line"]["f0_semis_iqr"],
    "line between-kick energy (e12 mean - e4 mean)": lambda h: np.mean(rhy_e12(h)) - np.mean(rhy_e16(h)[[0, 4, 8, 12]]),
    "hat decay T20 ms": lambda h: h["hat"]["hat_decay_ms"], "hat T10 ms": lambda h: h["hat"]["hat_t10_ms"],
    "hat open share": lambda h: h["hat"]["hat_open_share"], "hat decay @30 ms dB": lambda h: arr(h["hat"]["decay_prof_db"])[2],
    "hat 5-12k spectral slope": lambda h: np.polyfit(np.log(HB_EDGES[:24]), hat_post24(h), 1)[0],
    "hats per beat (5-12k)": lambda h: h["hat"]["hats_per_beat"],
}
for nm, f in SCAL.items():
    v = []
    for w in ("A", "B"):
        a = np.array([np.nan if f(r[w + "1"]) is None else f(r[w + "1"]) for r in PRIM], float)
        b = np.array([np.nan if f(r[w + "2"]) is None else f(r[w + "2"]) for r in PRIM], float)
        m = np.isfinite(a) & np.isfinite(b)
        v.append(stats.spearmanr(a[m], b[m])[0])
    print(f"  {nm:46s} {v[0]:5.2f} | {v[1]:5.2f}")

# ------------------------------------------------------------------ quality leak (A5)
print("\n## quality leak: W5 hat fingerprint vs file quality, all 50 tracks (mean of A1 + A2)")
lossy = np.array([r["ext"] in ("mp3", "m4a") for r in ALL])


def cutoff_hz(r):
    c = r["cutoff"]
    p = arr(c["psd_db"])
    f = c["f_hz0"] + np.arange(len(p)) * c["df"]
    ref = np.nanmedian(p[(f >= 9000) & (f < 12000)])
    w = int(500 / c["df"])
    for k in np.nonzero(f >= 12000)[0]:
        if np.nanmedian(p[k : k + w]) < ref - 40:
            return f[k]
    return f[-1]


cut = np.array([cutoff_hz(r) for r in ALL])
LOWQ_LIST = ", ".join(r["ext"] + " " + format(c / 1000, ".1f") for r, c in zip(ALL, cut) if c < 20500)
genre_all = np.array([r["genre"] for r in ALL])
print(f"lossy (mp3 + AAC m4a) {lossy.sum()} / lossless {(~lossy).sum()}; measured cutoff (-40 dB re 9-12 kHz): lossless median {np.median(cut[~lossy]) / 1000:.1f} kHz, "
      f"mp3 {np.median(cut[[r['ext'] == 'mp3' for r in ALL]]) / 1000:.1f}, m4a {np.median(cut[[r['ext'] == 'm4a' for r in ALL]]) / 1000:.1f}; cutoff < 20.5 kHz: {(cut < 20500).sum()} tracks "
      f"({LOWQ_LIST})")
G = np.array([[g == u for u in sorted(set(genre_all))] for g in genre_all], float)


def loo_auc(X, y):
    p = np.zeros(len(y))
    for i in range(len(y)):
        m = np.arange(len(y)) != i
        sc = StandardScaler().fit(X[m])
        clf = LogisticRegression(C=0.1, max_iter=2000).fit(sc.transform(X[m]), y[m])
        p[i] = clf.predict_proba(sc.transform(X[i : i + 1]))[0, 1]
    return roc_auc_score(y, p)


print(f"{'fingerprint':34s} | PC1 AUC lossy | PC1 rho cutoff | LOO-logit AUC lossy | +genre | genre only")
auc_g = loo_auc(G, lossy)
for nm, fn in (("hat 5-12k post 24", hat_post24), ("hat 5-12k postpow 24", POSTPOW), ("hat 5-12k post 24 + decay", hat_post24_decay), ("hat 5-12k diff 24", hat_diff24),
               ("hat decay only", hat_decay), ("[contrast] hat 7-20k", hat_7_20), ("[contrast] hat 12-20k", hat_hi)):
    X = np.array([(fn(r["A1"]) + fn(r["A2"])) / 2 for r in ALL])
    X = np.nan_to_num(X, nan=np.nanmean(X))
    Z = StandardScaler().fit_transform(X)
    pc1 = np.linalg.svd(Z - Z.mean(0), full_matrices=False)[2][0]
    s = Z @ pc1
    auc = roc_auc_score(lossy, s)
    rho = stats.spearmanr(s, cut)[0]
    print(f"{nm:34s} | {max(auc, 1 - auc):.2f} | {rho:+.2f} | {loo_auc(X, lossy):.2f} | {loo_auc(np.hstack((X, G)), lossy):.2f} | {auc_g:.2f}")
lowq = cut < 20500


def brickwall(r):
    c = r["cutoff"]
    p = arr(c["psd_db"])
    f = c["f_hz0"] + np.arange(len(p)) * c["df"]
    w = int(150 / c["df"])
    m = np.nonzero((f >= 15000) & (f <= 21000))[0]
    drop = np.array([p[k - w] - p[k + w] for k in m])
    return float(drop.max()), float(f[m[int(drop.argmax())]])


bw = np.array([brickwall(r) for r in ALL])
brick = bw[:, 0] >= 25
print(f"brickwall low-pass (>= 25 dB drop within 300 Hz, 15-21 kHz): {brick.sum()} tracks: " + ", ".join(f"{r['ext']} {f / 1000:.1f}k" for r, (d, f), b in zip(ALL, bw, brick) if b))
for nm, fn in (("hat 5-12k post 24", hat_post24), ("hat 5-12k postpow 24", POSTPOW), ("hat 5-12k post 24 + decay", hat_post24_decay), ("[contrast] hat 7-20k", hat_7_20), ("[contrast] hat 12-20k", hat_hi)):
    X = np.nan_to_num(np.array([(fn(r["A1"]) + fn(r["A2"])) / 2 for r in ALL]))
    Z = StandardScaler().fit_transform(X)
    s1 = Z @ np.linalg.svd(Z - Z.mean(0), full_matrices=False)[2][0]
    a1 = roc_auc_score(brick, s1)
    print(f"  target brickwall: {nm:30s} PC1 AUC {max(a1, 1 - a1):.2f} | LOO-logit AUC {loo_auc(X, brick):.2f}")
print(f"same with target = measured cutoff < 20.5 kHz (n={lowq.sum()}):")
for nm, fn in (("hat 5-12k post 24", hat_post24), ("hat 5-12k post 24 + decay", hat_post24_decay), ("[contrast] hat 12-20k", hat_hi)):
    X = np.nan_to_num(np.array([(fn(r["A1"]) + fn(r["A2"])) / 2 for r in ALL]))
    print(f"  {nm:32s} LOO-logit AUC {loo_auc(X, lowq):.2f}")

# ------------------------------------------------------------------ cost
print("\n## cost per 120 s window (process_time, sum of the two 60 s halves), primary + extra, n=%d" % len(ALL))
keys = ["load", "lag", "bass_sound", "bass_line", "hat_sound"]
tot = np.zeros(len(ALL))
for k in keys:
    c = np.array([r["cpu_A"][k] for r in ALL])
    wl = np.array([r["cpu_A"][k + "_wall"] for r in ALL])
    if k != "load":
        tot += c
    print(f"  {k:11s} cpu median {np.median(c):.3f} p90 {np.percentile(c, 90):.3f} | wall median {np.median(wl):.3f}")
for e in ("aiff", "mp3", "m4a"):
    m = np.array([r["ext"] == e for r in ALL])
    print(f"  load {e}: cpu median {np.median([r['cpu_A']['load'] for r, k in zip(ALL, m) if k]):.2f} wall median {np.median([r['cpu_A']['load_wall'] for r, k in zip(ALL, m) if k]):.2f} (decoder subprocess not in process_time)")
FILES, MEAN_S = 4633, 305.0
v = float(np.median(tot))
print(f"features (lag + W1 sound + W1 line + W5) per 120 s: {v:.2f} CPU-s -> full track x{MEAN_S / 120:.2f} = {v * MEAN_S / 120:.2f} CPU-s (Schaetzung) -> library {v * MEAN_S / 120 * FILES / 3600:.2f} CPU-h (Schaetzung, decode excluded)")
for k in keys[2:]:
    c = float(np.median([r["cpu_A"][k] for r in ALL]))
    print(f"  {k}: {c:.3f} s / 120 s -> {c * MEAN_S / 120 * FILES / 3600:.2f} CPU-h library (Schaetzung)")
