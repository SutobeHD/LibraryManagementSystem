"""Which further values can the audio component pass give away for free?

Re-uses the per-subset rows written by sections/extract.py for the 60 fresh tracks of rework A
(no audio is opened here). Three parts:
  1  scalar candidates: split Spearman (Thue-Morse interleaved / early-late / S1-S2), bootstrap
     interval, redundancy against the nine planned columns, distribution, saturation,
     hat-specificity (Spearman with the percussive fraction of the 5-12 kHz band)
  2  similarity kinds composed from the stored fingerprints: retrieval + pair-distance Spearman
     against the existing kinds
  3  grid offset: the two stored estimates (middle 120 s, longest M block)

Usage: derive_eval.py <tmp/sc-rework-a> <out dir>
The frozen distances come from similarity/eval_sim.py, executed unchanged on <data>/legacy (same
trick as sections/eval_sections.py); the builders in derived_defs.py are checked against it."""
import contextlib
import glob
import io
import json
import sys
from pathlib import Path

import numpy as np
from scipy import stats

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import derived_defs as D  # noqa: E402

SIM = D.BASE / "similarity"
DATA = Path(sys.argv[1]).resolve()
OUT = Path(sys.argv[2]).resolve()
OUT.mkdir(parents=True, exist_ok=True)
G = {"__file__": str(SIM / "eval_sim.py"), "__name__": "eval_sim"}
_argv = sys.argv
sys.argv = [sys.argv[0], str(DATA / "legacy")]
with contextlib.redirect_stdout(io.StringIO()):
    exec(compile((SIM / "eval_sim.py").read_text(encoding="utf-8"), str(SIM / "eval_sim.py"), "exec"), G)
sys.argv = _argv
d_eucz, d_cos, d_oti, norm_med, ranks_from_D = G["d_eucz"], G["d_cos"], G["d_oti"], G["norm_med"], G["ranks_from_D"]
arr, q16, st_of = D.arr, D.q16, D.st_of

sect = {}
for f in sorted(glob.glob(str(DATA / "run*" / "sect_shard*.jsonl"))):
    for line in open(f, encoding="utf-8"):
        r = json.loads(line)
        if r["status"] == "ok":
            sect[r["id"]] = r
IDS = sorted(sect)
R = [sect[i] for i in IDS]
N = len(R)
EXT = np.array([r["ext"] for r in R])
GEN = np.array([r["genre"] for r in R])
BPM = np.array([r["bpm"] for r in R], dtype=float)
LOSSY = np.isin(EXT, ["mp3", "m4a"])
SOFT, HARD = np.isin(GEN, ["House", "Trance"]), np.isin(GEN, ["Hard Techno", "Raw", "Uptempo"])
RNG = np.random.default_rng(20261122)
LINES: list = []


def out(s=""):
    print(s)
    LINES.append(s)


def sub(r, win, name):
    return (r.get(win) or {}).get(name) or {}


# the mirrored builders must equal the frozen ones on every stored subset
_chk = 0
for r in R:
    for w, k in (("mx", "all"), ("mx", "early"), ("mx", "late"), ("sx", "S1"), ("sx", "S2")):
        s = sub(r, w, k)
        if "line" in s and "bass" in s:
            assert np.array_equal(D.pit_c_abs(s), G["pit_C_abs"](s), equal_nan=True)
            assert np.array_equal(D.snd_hrel(s, "off"), G["snd_hrel"](s, "off"), equal_nan=True)
            assert np.array_equal(D.snd_hrel(s, "on", 4.0), G["snd_hrel"](s, "on", 4.0), equal_nan=True)
            _chk += 1
        if "post_pow" in (s.get("hat") or {}):
            assert np.array_equal(D.hat_bands(s, "post_pow", 5000, 12000), G["hat_bands"](s, "post_pow", 5000, 12000), equal_nan=True)


def spear(a, b):
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 8 or np.ptp(a[m]) == 0 or np.ptp(b[m]) == 0:
        return np.nan
    return float(stats.spearmanr(a[m], b[m])[0])


def boot(a, b, n=2000):
    m = np.isfinite(a) & np.isfinite(b)
    a, b = a[m], b[m]
    if len(a) < 8:
        return np.array([np.nan, np.nan])
    res = []
    for _ in range(n):
        ix = RNG.integers(0, len(a), len(a))
        if np.ptp(a[ix]) > 0 and np.ptp(b[ix]) > 0:
            res.append(stats.spearmanr(a[ix], b[ix])[0])
    return np.percentile(res, [2.5, 97.5])


def saturation(a):
    """Share of tracks inside the densest window of +- 5 % of the observed min-max range."""
    a = np.sort(a[np.isfinite(a)])
    if len(a) < 8 or np.ptp(a) == 0:
        return np.nan
    w = 0.10 * np.ptp(a)
    return float(max((np.searchsorted(a, x + w, side="right") - i) for i, x in enumerate(a)) / len(a))


# ----------------------------------------------------------------------------- scalar getters (subset dict -> value or None)
def w2(k, semis=False):
    def f(s):
        v = (s.get("w2") or {}).get(k)
        return st_of(v) if semis else v
    return f


def hat(k):
    return lambda s: (s.get("hat") or {}).get(k)


def bsnd(tag, k, semis=False):
    def f(s):
        v = ((s.get("bass") or {}).get(tag) or {}).get(k)
        return st_of(v) if semis else v
    return f


def line(k):
    return lambda s: (s.get("line") or {}).get(k)


def guard(fn):
    def f(s):
        try:
            v = fn(s)
        except (KeyError, TypeError, ValueError, IndexError, ZeroDivisionError):
            return None
        return None if v is None or not np.isfinite(v) else float(v)
    return f


PLANNED = [  # the nine planned columns
    ("sub60_of_200", w2("sub60_of_200")), ("sub60_of_total", w2("sub60_of_total")), ("bass_between_db", w2("bass_between_db")),
    ("bass note (st)", w2("bass_f0_meanspec_hz", True)), ("top-end energy (dB)", w2("hi5_12k_share_db")),
    ("16th share", hat("sixteenth_share")), ("off-beat share", hat("offbeat_share")),
    ("long-decay off-beat share", hat("open_share_offbeat")), ("hats per beat", hat("hats_per_beat")),
]
# origin: H = definition in baseline/features.py or similarity/run_sim.py (committed before the 60 fresh tracks were drawn)
#         A = first defined in sections/extract.py or eval_sections.py of rework A (fixed in code, never run on another set)
#         X = designed in this script (exploratory)
CAND = [
    # --- kick / low end, already extracted
    ("kick f0 (st), mean spectrum", "H", "kick", w2("kick_f0_hz", True)),
    ("kick f0 (st), kick-in fingerprint f0", "H", "kick", bsnd("on", "f0", True)),
    ("tail_db (level 0.6-0.9 T re kick peak)", "A", "kick", w2("tail_db")),
    ("mono_share (kick tail only falls)", "A", "kick", w2("mono_share")),
    ("bass_rerise_share", "H", "bass", w2("bass_rerise_share")),
    ("bass_dip_db (dip after the kick)", "H", "bass", w2("bass_dip_db")),
    ("bass_sustain_ratio", "H", "bass", w2("bass_sustain_ratio")),
    ("sub120_of_total", "H", "bass", w2("sub120_of_total")),
    ("low onsets per beat", "H", "bass", w2("low_onsets_per_beat")),
    ("low between-kick onsets per beat", "H", "bass", w2("low_between_per_beat")),
    ("kick-bass interval (st, signed)", "A", "kick", D.kb_interval),
    ("kick-bass interval |st|", "A", "kick", lambda s: abs(D.kb_interval(s))),
    ("FLAG same note (|interval| <= 1 st)", "A", "kick", lambda s: float(abs(D.kb_interval(s)) <= 1.0)),
    ("FLAG same pitch class (+-0.5 st mod 12)", "X", "kick", lambda s: float(abs(((D.kb_interval(s) + 6) % 12) - 6) <= 0.5)),
    # --- bass movement
    ("bass f0 IQR over beats (st)", "H", "bass", w2("bass_f0_iqr_st")),
    ("bass f0 within 1 st share", "H", "bass", w2("bass_f0_within1st_share")),
    ("line f0 IQR over 16ths (st)", "H", "bass", line("f0_semis_iqr")),
    ("line voiced share", "H", "bass", line("voiced_share")),
    ("H16 pitch classes >= 15 % (ACF f0)", "A", "bass", D.h_n_pc),
    ("H16 pitch-class entropy (ACF f0)", "X", "bass", lambda s: D.entropy12(D.h12(s))),
    ("H16 top pitch-class share (ACF f0)", "X", "bass", lambda s: float(D.h12(s).max())),
    ("FP chroma entropy", "X", "bass", lambda s: D.entropy12(D.chroma(s)[1])),
    ("FP chroma classes >= 15 %", "X", "bass", lambda s: float((D.chroma(s)[1] >= 0.15).sum())),
    ("FP chroma top class share", "X", "bass", lambda s: float(D.chroma(s)[1].max())),
    ("FP chroma step movement", "X", "bass", D.chroma_step_move),
    # --- bass rhythm from the stored 16-step low-band flux
    ("FP low flux on-beat share", "X", "bass", D.lowflux_share(D.ON4)),
    ("FP low flux off-beat 8th share", "X", "bass", D.lowflux_share(D.OFF4)),
    ("FP low flux 16th share", "X", "bass", D.lowflux_share(D.SIX8)),
    ("FP low flux off-8th / between-kick", "X", "bass", D.lowflux_share(D.OFF4, True)),
    ("FP low flux 1-beat repetition", "A", "bass", lambda s: D.rep1(D.fp_line_flux(s))),
    # --- bass / kick sound scalars
    ("bass harmonic share (kick out)", "H", "bass", bsnd("off", "harm_share")),
    ("bass centroid / f0 (kick out)", "H", "bass", bsnd("off", "cent_rel")),
    ("bass flatness (kick out)", "H", "bass", bsnd("off", "flat")),
    ("FP overtones 2-6 re f0, kick out (dB)", "X", "bass", D.hrel_overtones("off", 6)),
    ("kick harmonic share (kick in)", "H", "kick", bsnd("on", "harm_share")),
    ("kick centroid / f0 (kick in)", "H", "kick", bsnd("on", "cent_rel")),
    ("kick flatness (kick in)", "H", "kick", bsnd("on", "flat")),
    ("FP overtones 2-4 re f0, kick in (dB)", "X", "kick", D.hrel_overtones("on", 4)),
    # --- hats, already extracted
    ("triplet share, counts", "H", "hat", hat("triplet_share")),
    ("other share, counts", "H", "hat", hat("other_share")),
    ("16th hits per beat", "H", "hat", hat("sixteenth_per_beat")),
    ("off-beat hits per beat", "H", "hat", hat("offbeat_per_beat")),
    ("hat decay T20 median (ms)", "H", "hat", hat("hat_decay_ms")),
    ("hat T10 median (ms)", "H", "hat", hat("hat_t10_ms")),
    ("long-decay share, all hits", "H", "hat", hat("hat_open_share")),
    ("decay T20 off-beat hits (ms)", "A", "hat", hat("decay_offbeat_ms")),
    ("fold drop @50 ms off-beat (dB)", "A", "hat", hat("fold_drop50_off")),
    ("fold drop @50 ms on-beat (dB)", "A", "hat", hat("fold_drop50_on")),
    ("fold drop @50 ms 16th (dB)", "A", "hat", hat("fold_drop50_16")),
    ("FP decay profile @15 ms (dB)", "H", "hat", lambda s: arr(s["hat"]["decay_prof_db"])[1]),
    ("FP decay profile @30 ms (dB)", "H", "hat", lambda s: arr(s["hat"]["decay_prof_db"])[2]),
    ("FP decay profile @60 ms (dB)", "H", "hat", lambda s: arr(s["hat"]["decay_prof_db"])[3]),
    ("flux triplet share", "H", "hat", hat("flux_tri")),
    ("flux other share", "H", "hat", hat("flux_other")),
    ("OFF share, energy 16-step", "A", "hat", hat("en_off")),
    ("16th share, energy 16-step", "A", "hat", hat("en_16")),
    ("ON share, energy 16-step", "A", "hat", hat("en_on")),
    # --- hats, from the stored fingerprints
    ("FP hat spectrum tilt (dB / octave)", "X", "hat", D.hat_tilt),
    ("hat spectral centroid (st re 5 kHz)", "X", "hat", D.hat_centroid),
    ("hat onset contrast post - pre (dB)", "X", "hat", D.hat_contrast),
    ("FP hat flux on-beat share", "A", "hat", lambda s: D.fp_hat_flux(s)[D.ON4].sum() / D.fp_hat_flux(s).sum()),
    ("FP hat flux off-beat share", "A", "hat", lambda s: D.fp_hat_flux(s)[D.OFF4].sum() / D.fp_hat_flux(s).sum()),
    ("FP hat flux 16th share", "A", "hat", lambda s: D.fp_hat_flux(s)[D.SIX8].sum() / D.fp_hat_flux(s).sum()),
    ("FP hat flux backbeat (2+4 of on-beat)", "X", "hat", lambda s: D.fp_hat_flux(s)[[4, 12]].sum() / D.fp_hat_flux(s)[D.ON4].sum()),
    ("hat energy backbeat (2+4 of on-beat)", "A", "hat", lambda s: arr(s["hat"]["e16"])[[4, 12]].sum() / arr(s["hat"]["e16"])[D.ON4].sum()),
    ("FP hat flux 1-beat repetition", "A", "hat", lambda s: D.rep1(D.fp_hat_flux(s))),
]


def col(get, win, name):
    g = guard(get)
    return np.array([np.nan if (v := g(sub(r, win, name))) is None else v for r in R], dtype=float)


def verdict(tm, el):
    if not np.isfinite(tm) or not np.isfinite(el):
        return "n/a"
    base = "column" if el >= 0.85 else "coarse" if el >= 0.80 else "hidden"
    return base if tm >= 0.95 else f"{base}*tm<0.95"


out(f"tracks {N}; ext {dict(zip(*np.unique(EXT, return_counts=True)))}; builder equality checked on {_chk} subsets")
PL = {n: col(g, "mx", "all") for n, g in PLANNED}
PERC = np.array([np.nan if (v := (sub(r, "mx", "all").get("en") or {}).get("perc_frac_5_12k_band")) is None else v for r in R])
BNOTE = PL["bass note (st)"]

out("\n## 1a sanity: the nine planned columns re-derived (must match eval_sections.txt section 1)")
out(f"{'feature':42s} {'tm':>5s} {'el':>5s} {'S':>5s}  el 95 % CI")
for n, g in PLANNED:
    tm, el, s_ = spear(col(g, "mx", "tmA"), col(g, "mx", "tmB")), spear(col(g, "mx", "early"), col(g, "mx", "late")), spear(col(g, "sx", "S1"), col(g, "sx", "S2"))
    ci = boot(col(g, "mx", "early"), col(g, "mx", "late"))
    out(f"{n:42s} {tm:5.2f} {el:5.2f} {s_:5.2f}  [{ci[0]:.2f}, {ci[1]:.2f}]  sat {saturation(PL[n]):.2f}  perc {spear(PL[n], PERC):+.2f}")

out("\n## 1b scalar candidates (window M, n = 60)")
out("origin H = definition predates the fresh 60 (baseline / run_sim) -> held-out; A = first defined in rework A code; X = designed now (exploratory)")
out("redund = max |Spearman| with the nine planned columns on window M; sat = share of tracks in the densest +-5 % of the min-max range; "
    "perc = Spearman with the percussive fraction of the 5-12 kHz band (hat rows only); FP = derivable from a stored fingerprint")
out(f"{'candidate':42s} or |  tm     el     S    | el 95 % CI    | S 95 % CI     | verdict          | redund (with)                     |   p10    med    p90 |  sat |  perc | lossy p")
ROWS = []
ALLV = {}
SPLIT = {}
for name, origin, grp, get in CAND:
    a = col(get, "mx", "all")
    ALLV[name] = a
    tA, tB, e1, e2, s1, s2 = (col(get, w, k) for w, k in (("mx", "tmA"), ("mx", "tmB"), ("mx", "early"), ("mx", "late"), ("sx", "S1"), ("sx", "S2")))
    SPLIT[name] = (tA, tB, e1, e2, s1, s2)
    row = {"name": name, "origin": origin, "group": grp, "n": int(np.isfinite(a).sum())}
    if name.startswith("FLAG"):
        def agree(x, y):
            m = np.isfinite(x) & np.isfinite(y)
            po = float((x[m] == y[m]).mean())
            pe = float(x[m].mean() * y[m].mean() + (1 - x[m].mean()) * (1 - y[m].mean()))
            return po, (po - pe) / (1 - pe) if pe < 1 else np.nan
        row.update(kind="flag", share_true=float(np.nanmean(a)), agree_tm=agree(tA, tB), agree_el=agree(e1, e2), agree_S=agree(s1, s2))
        out(f"{name:42s} {origin}  | share true {row['share_true']:.2f}; agreement / kappa: tm {row['agree_tm'][0]:.2f} / {row['agree_tm'][1]:.2f}, "
            f"el {row['agree_el'][0]:.2f} / {row['agree_el'][1]:.2f}, S {row['agree_S'][0]:.2f} / {row['agree_S'][1]:.2f}")
        ROWS.append(row)
        continue
    tm, el, s_ = spear(tA, tB), spear(e1, e2), spear(s1, s2)
    ci, ci_s = boot(e1, e2), boot(s1, s2)
    red = {n: spear(a, v) for n, v in PL.items()}
    rn = max(red, key=lambda k: -1 if not np.isfinite(red[k]) else abs(red[k]))
    q = np.nanpercentile(a, [10, 50, 90])
    pc = spear(a, PERC) if grp == "hat" else np.nan
    m = np.isfinite(a)
    p_lossy = float(stats.mannwhitneyu(a[m & LOSSY], a[m & ~LOSSY])[1])
    row.update(kind="scalar", tm=tm, el=el, S=s_, el_ci=ci.tolist(), S_ci=ci_s.tolist(), verdict=verdict(tm, el), redund=red[rn], redund_with=rn,
               p10=q[0], med=q[1], p90=q[2], sat=saturation(a), perc=pc, rho_bass_note=spear(a, BNOTE), rho_bpm=spear(a, BPM), p_lossy=p_lossy)
    ROWS.append(row)
    out(f"{name:42s} {origin}  | {tm:5.2f} {el:6.3f} {s_:5.2f} | [{ci[0]:.2f}, {ci[1]:.2f}] | [{ci_s[0]:.2f}, {ci_s[1]:.2f}] | {row['verdict']:16s} | "
        f"{red[rn]:+.2f} {rn:27s} | {q[0]:6.2f} {q[1]:6.2f} {q[2]:6.2f} | {row['sat']:.2f} | {pc:+5.2f} | {p_lossy:.3f}")

out("\n## 1c hat-specificity: Spearman with the percussive fraction of the 5-12 kHz band (4096 HPSS, window M)")
for n in ("long-decay off-beat share",):
    out(f"   planned  {n:40s} {spear(PL[n], PERC):+.2f}")
for n in ("long-decay share, all hits", "hat decay T20 median (ms)", "hat T10 median (ms)", "decay T20 off-beat hits (ms)", "fold drop @50 ms off-beat (dB)",
          "fold drop @50 ms on-beat (dB)", "fold drop @50 ms 16th (dB)", "FP decay profile @15 ms (dB)", "FP decay profile @30 ms (dB)", "FP decay profile @60 ms (dB)",
          "hat onset contrast post - pre (dB)", "FP hat spectrum tilt (dB / octave)"):
    out(f"   candidate {n:39s} {spear(ALLV[n], PERC):+.2f}   vs long-decay off-beat share {spear(ALLV[n], PL['long-decay off-beat share']):+.2f}   vs top-end energy {spear(ALLV[n], PL['top-end energy (dB)']):+.2f}")
ci = boot(PL["long-decay off-beat share"], PERC)
ci2 = boot(ALLV["fold drop @50 ms off-beat (dB)"], PERC)
out(f"   bootstrap 95 %: long-decay off-beat share vs perc [{ci[0]:+.2f}, {ci[1]:+.2f}]; fold drop off-beat vs perc [{ci2[0]:+.2f}, {ci2[1]:+.2f}]")
dd = []
mm = np.isfinite(PL["long-decay off-beat share"]) & np.isfinite(ALLV["fold drop @50 ms off-beat (dB)"]) & np.isfinite(PERC)
for _ in range(2000):
    ix = RNG.integers(0, mm.sum(), mm.sum())
    dd.append(abs(stats.spearmanr(ALLV["fold drop @50 ms off-beat (dB)"][mm][ix], PERC[mm][ix])[0]) - abs(stats.spearmanr(PL["long-decay off-beat share"][mm][ix], PERC[mm][ix])[0]))
out(f"   paired bootstrap of |rho(fold drop, perc)| - |rho(long-decay share, perc)|: median {np.median(dd):+.2f}, 95 % [{np.percentile(dd, 2.5):+.2f}, {np.percentile(dd, 97.5):+.2f}]")


def partial(x, y, z):
    m = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
    rx, ry, rz = (stats.rankdata(v[m]) for v in (x, y, z))
    ex = rx - np.polyval(np.polyfit(rz, rx, 1), rz)
    ey = ry - np.polyval(np.polyfit(rz, ry, 1), rz)
    return float(np.corrcoef(ex, ey)[0, 1])


out(f"   partial Spearman given the onset contrast: long-decay off-beat share vs perc {partial(PL['long-decay off-beat share'], PERC, ALLV['hat onset contrast post - pre (dB)']):+.2f}; "
    f"fold drop off-beat vs perc {partial(ALLV['fold drop @50 ms off-beat (dB)'], PERC, ALLV['hat onset contrast post - pre (dB)']):+.2f}")
tilt_pre = col(lambda s: D.hat_tilt(s, "pre_pow"), "mx", "all")
cen_pre = col(lambda s: D.hat_centroid(s, "pre_pow"), "mx", "all")
out(f"   control for the hat spectrum tilt (same value from the frames BEFORE each onset): Spearman post vs pre {spear(ALLV['FP hat spectrum tilt (dB / octave)'], tilt_pre):+.2f} (centroid {spear(ALLV['hat spectral centroid (st re 5 kHz)'], cen_pre):+.2f}); "
    f"pre-frame tilt split Spearman el {spear(col(lambda s: D.hat_tilt(s, 'pre_pow'), 'mx', 'early'), col(lambda s: D.hat_tilt(s, 'pre_pow'), 'mx', 'late')):.2f}, "
    f"S {spear(col(lambda s: D.hat_tilt(s, 'pre_pow'), 'sx', 'S1'), col(lambda s: D.hat_tilt(s, 'pre_pow'), 'sx', 'S2')):.2f}; median post - pre tilt {np.nanmedian(ALLV['FP hat spectrum tilt (dB / octave)'] - tilt_pre):+.2f} dB / oct")

out("\n## 1d confounds of the chroma / pitch-class measures: Spearman with the bass note (st) and with the tempo")
for n in ("FP chroma entropy", "FP chroma classes >= 15 %", "FP chroma top class share", "FP chroma step movement", "H16 pitch classes >= 15 % (ACF f0)",
          "H16 pitch-class entropy (ACF f0)", "H16 top pitch-class share (ACF f0)", "bass f0 IQR over beats (st)", "bass f0 within 1 st share", "line f0 IQR over 16ths (st)",
          "bass harmonic share (kick out)", "FP low flux 1-beat repetition"):
    out(f"   {n:40s} bass note {spear(ALLV[n], BNOTE):+.2f}   bpm {spear(ALLV[n], BPM):+.2f}   harmonic share {spear(ALLV[n], ALLV['bass harmonic share (kick out)']):+.2f}   "
        f"H16 entropy {spear(ALLV[n], ALLV['H16 pitch-class entropy (ACF f0)']):+.2f}   beat-f0 within 1 st {spear(ALLV[n], ALLV['bass f0 within 1 st share']):+.2f}")
v = ALLV["H16 pitch classes >= 15 % (ACF f0)"]
out("   H16 classes >= 15 %: distribution " + ", ".join(f"{int(k)}: {int((v == k).sum())}" for k in np.unique(v[np.isfinite(v)])))
for w_, a_, b_ in (("tm", ("mx", "tmA"), ("mx", "tmB")), ("el", ("mx", "early"), ("mx", "late")), ("S", ("sx", "S1"), ("sx", "S2"))):
    x, y = col(D.h_n_pc, *a_), col(D.h_n_pc, *b_)
    m = np.isfinite(x) & np.isfinite(y)
    out(f"   H16 classes: same count in both halves ({w_}) {np.mean(x[m] == y[m]):.2f}; 'one note' (<= 1 class) agreement {np.mean((x[m] <= 1) == (y[m] <= 1)):.2f} (share one-note {np.mean(x[m] <= 1):.2f})")
w1 = ALLV["bass f0 within 1 st share"]
one_a, one_b = v <= 1, w1 >= 0.9
out(f"   'one note' by two routes on window M: H16 <= 1 class {int(one_a.sum())} tracks, beat-f0 within 1 st >= 0.9 {int(one_b.sum())} tracks, both {int((one_a & one_b).sum())}, neither {int((~one_a & ~one_b).sum())} "
    f"(agreement {np.mean(one_a == one_b):.2f}; the 0.9 cut is set here, not tuned)")

out("\n## 1e candidates among each other: |Spearman| >= 0.85 on window M (duplicates)")
names = [r["name"] for r in ROWS if r["kind"] == "scalar"]
for i, a in enumerate(names):
    for b in names[i + 1:]:
        rho = spear(ALLV[a], ALLV[b])
        if np.isfinite(rho) and abs(rho) >= 0.85:
            out(f"   {rho:+.2f}  {a}  ~  {b}")

out("\n## 1f category 'bass character' (thresholds of eval_sections.py section 5, chosen in rework A): agreement between halves")
ca = [D.bass_class(sub(r, "mx", "all")) for r in R]
out("   window M: " + ", ".join(f"{k} {ca.count(k)}" for k in sorted({c for c in ca if c})))
for w_, a_, b_ in (("tm", ("mx", "tmA"), ("mx", "tmB")), ("el", ("mx", "early"), ("mx", "late")), ("S", ("sx", "S1"), ("sx", "S2"))):
    x, y = [D.bass_class(sub(r, *a_)) for r in R], [D.bass_class(sub(r, *b_)) for r in R]
    ok = [(p, q_) for p, q_ in zip(x, y) if p and q_]
    out(f"   {w_}: same class in both halves {np.mean([p == q_ for p, q_ in ok]):.2f} (n={len(ok)}); chance agreement from the marginals "
        f"{sum((np.mean([p == c for p, _ in ok]) * np.mean([q_ == c for _, q_ in ok])) for c in set(ca)):.2f}")
sn = ALLV["FLAG same note (|interval| <= 1 st)"] == 1
out(f"   same-note flag ({int(sn.sum())} tracks) by bass character: " + ", ".join(f"{k} {sum(1 for c, f_ in zip(ca, sn) if c == k and f_)} / {ca.count(k)}" for k in sorted(set(ca))))
out("   same-note flag by genre: " + ", ".join(f"{g_} {int(sn[GEN == g_].sum())} / {int((GEN == g_).sum())}" for g_ in sorted(set(GEN))))

out("\n## 1g note agreement between halves (same within 0.5 st / 1 st)")
for n in ("kick f0 (st), mean spectrum", "kick f0 (st), kick-in fingerprint f0"):
    tA, tB, e1, e2, s1, s2 = SPLIT[n]
    out(f"   {n:40s} tm {np.nanmean(np.abs(tA - tB) <= 0.5):.2f} / {np.nanmean(np.abs(tA - tB) <= 1):.2f}; early-late {np.nanmean(np.abs(e1 - e2) <= 0.5):.2f} / {np.nanmean(np.abs(e1 - e2) <= 1):.2f}; "
        f"S1-S2 {np.nanmean(np.abs(s1 - s2) <= 0.5):.2f} / {np.nanmean(np.abs(s1 - s2) <= 1):.2f}")
kf, kf2 = ALLV["kick f0 (st), mean spectrum"], ALLV["kick f0 (st), kick-in fingerprint f0"]
out(f"   the two kick-f0 routes on window M: within 0.5 st {np.nanmean(np.abs(kf - kf2) <= 0.5):.2f}, within 1 st {np.nanmean(np.abs(kf - kf2) <= 1):.2f}; kick f0 vs bass note Spearman {spear(kf, BNOTE):+.2f}, "
    f"kick above bass by > 1 st in {np.nanmean(kf - BNOTE > 1):.2f}")

out("\n## 1h genre contrast soft (House + Trance, n=%d) vs hard (Hard Techno + Raw + Uptempo, n=%d): medians, Mann-Whitney p (uncorrected, %d tests)" % (SOFT.sum(), HARD.sum(), len(names)))
for n in names:
    a = ALLV[n]
    s_, h_ = a[SOFT & np.isfinite(a)], a[HARD & np.isfinite(a)]
    u, p = stats.mannwhitneyu(s_, h_)
    if p < 0.01:
        out(f"   {n:42s} soft {np.median(s_):8.2f}  hard {np.median(h_):8.2f}  p {p:.4f}  r_rb {2 * u / (len(s_) * len(h_)) - 1:+.2f}")

out("\n## 1i low-end rhythm candidates among each other and against the planned bass columns (Spearman, window M)")
grp = ["low onsets per beat", "low between-kick onsets per beat", "FP low flux on-beat share", "FP low flux off-beat 8th share", "FP low flux 16th share",
       "FP low flux off-8th / between-kick", "FP low flux 1-beat repetition", "bass_sustain_ratio", "bass_dip_db (dip after the kick)", "tail_db (level 0.6-0.9 T re kick peak)",
       "bass f0 within 1 st share", "bass harmonic share (kick out)", "bass centroid / f0 (kick out)", "sub120_of_total", "kick f0 (st), mean spectrum"]
vals = {**{n: ALLV[n] for n in grp}, "bass_between_db": PL["bass_between_db"], "sub60_of_200": PL["sub60_of_200"], "16th share": PL["16th share"], "off-beat share": PL["off-beat share"]}
keys = list(vals)
out(" " * 42 + " ".join(f"{i:>5d}" for i in range(len(keys))))
for i, a in enumerate(keys):
    out(f"{i:2d} {a[:38]:38s} " + " ".join(f"{spear(vals[a], vals[b]):+5.2f}" for b in keys))

out("\n## 1j redundancy near the 0.85 line: bootstrap 95 % of |Spearman| with the closest planned column")
for row in ROWS:
    if row["kind"] == "scalar" and abs(row["redund"]) >= 0.70:
        ci = boot(ALLV[row["name"]], PL[row["redund_with"]])
        out(f"   {row['name']:42s} {row['redund']:+.2f} with {row['redund_with']:27s} [{ci[0]:+.2f}, {ci[1]:+.2f}]")

out("\n## 1k candidates that differ between lossy and lossless files (Mann-Whitney p < 0.05, uncorrected): " + "; ".join(
    f"{r_['name']} p {r_['p_lossy']:.3f}" for r_ in ROWS if r_["kind"] == "scalar" and r_["p_lossy"] < 0.05))
out("   lossy share by genre (format is not independent of genre in this sample): " + ", ".join(f"{g_} {int(LOSSY[GEN == g_].sum())} / {int((GEN == g_).sum())}" for g_ in sorted(set(GEN))))

out("\n## 1l short-listed candidates: soft vs hard genre medians (Mann-Whitney p, uncorrected) and lossy vs lossless inside the hard group")
for n in ("kick f0 (st), mean spectrum", "kick harmonic share (kick in)", "kick flatness (kick in)", "kick centroid / f0 (kick in)", "tail_db (level 0.6-0.9 T re kick peak)",
          "low onsets per beat", "sub120_of_total", "bass f0 within 1 st share", "H16 pitch-class entropy (ACF f0)", "bass harmonic share (kick out)", "bass centroid / f0 (kick out)",
          "FP low flux off-beat 8th share", "FP low flux 16th share", "FP low flux off-8th / between-kick", "FP low flux 1-beat repetition", "bass_sustain_ratio",
          "bass_dip_db (dip after the kick)", "triplet share, counts", "FP hat spectrum tilt (dB / octave)", "fold drop @50 ms off-beat (dB)", "hat onset contrast post - pre (dB)"):
    a = ALLV[n]
    s_, h_ = a[SOFT & np.isfinite(a)], a[HARD & np.isfinite(a)]
    hl, hn = a[HARD & LOSSY & np.isfinite(a)], a[HARD & ~LOSSY & np.isfinite(a)]
    out(f"   {n:42s} soft {np.median(s_):8.2f}  hard {np.median(h_):8.2f}  p {stats.mannwhitneyu(s_, h_)[1]:.3f} | hard lossy (n={len(hl)}) {np.median(hl):8.2f} vs hard lossless (n={len(hn)}) {np.median(hn):8.2f}  p {stats.mannwhitneyu(hl, hn)[1]:.3f}")

out("\n## 1m is the lossy difference the codec, the grid offset or the sample? medians by file type without Uptempo (all 3 Uptempo tracks are lossy); mp3 split by grid offset")
LAG = np.array([r["lag_ms"] for r in R], dtype=float)
NU = GEN != "Uptempo"
grp_ = {"lossless": NU & ~LOSSY, "m4a": NU & (EXT == "m4a"), "mp3": NU & (EXT == "mp3"), "mp3 lag < -30": NU & (EXT == "mp3") & (LAG < -30), "mp3 lag >= -30": NU & (EXT == "mp3") & (LAG >= -30)}
out(f"   {'':42s} " + " ".join(f"{k + ' n=' + str(int(m.sum())):>18s}" for k, m in grp_.items()) + "   p(m4a vs lossless)  p(mp3 vs lossless)  Spearman with lag (mp3 only)")
for n in ("tail_db (level 0.6-0.9 T re kick peak)", "bass_dip_db (dip after the kick)", "bass harmonic share (kick out)", "FP low flux off-beat 8th share", "FP low flux 16th share",
          "FP low flux off-8th / between-kick", "low onsets per beat", "fold drop @50 ms off-beat (dB)", "hat onset contrast post - pre (dB)", "hat T10 median (ms)",
          "kick f0 (st), mean spectrum", "sub120_of_total", "bass f0 within 1 st share"):
    a = ALLV[n]
    f_ = np.isfinite(a)
    out(f"   {n:42s} " + " ".join(f"{np.median(a[m & f_]) if (m & f_).any() else np.nan:18.2f}" for m in grp_.values())
        + f"   {stats.mannwhitneyu(a[grp_['m4a'] & f_], a[grp_['lossless'] & f_])[1]:18.3f}  {stats.mannwhitneyu(a[grp_['mp3'] & f_], a[grp_['lossless'] & f_])[1]:18.3f}  {spear(a[EXT == 'mp3'], LAG[EXT == 'mp3']):+.2f}")
out("   genres of the non-Uptempo lossy files: " + ", ".join(f"{g_} mp3 {int(((GEN == g_) & (EXT == 'mp3')).sum())} m4a {int(((GEN == g_) & (EXT == 'm4a')).sum())}" for g_ in sorted(set(GEN[NU]))))


# ============================================================================ 2 similarity kinds
def have(s, kind):
    try:
        if kind == "bass":
            return s["bass"]["off"]["hrel"] is not None and s["line"]["flux16"] is not None and s["bass"]["on"]["hrel"] is not None
        return all(k in s["hat"] for k in ("post_pow", "pre_pow", "decay_prof_db", "flux16"))
    except (KeyError, TypeError):
        return False


kick_sc = lambda s: np.array([np.nan if (v := guard(w2("kick_f0_hz", True))(s)) is None else v, np.nan if (v := guard(w2("tail_db"))(s)) is None else v])  # noqa: E731
EXIST = ("bass (kick out)", "bass (kick in)", "hat sound", "hat pattern")


def rb(Dm):
    """Rank-balanced: off-diagonal distances replaced by their percentile, so every part has the same spread."""
    off = ~np.eye(len(Dm), dtype=bool)
    o = np.zeros_like(Dm, dtype=float)
    o[off] = stats.rankdata(Dm[off]) / off.sum()
    return o


def kinds(S):
    """All distance matrices for a list of subset dicts (fingerprints quantised as stored)."""
    X = lambda fn: np.array([fn(s) for s in S])  # noqa: E731
    so, son = d_eucz(X(D.fp_snd_off)), d_eucz(X(D.fp_snd_on))
    rhy, pit = d_cos(X(D.fp_line_flux)), d_oti(X(D.fp_pit12))
    ln = 0.5 * norm_med(rhy) + 0.5 * norm_med(pit)
    ht = 0.75 * norm_med(d_eucz(X(D.fp_hat_timbre))) + 0.25 * norm_med(d_eucz(X(D.fp_hat_decay)))
    pat = d_cos(X(D.fp_hat_flux))
    ksc = d_eucz(X(kick_sc))
    nm = norm_med
    return {
        "bass (kick out)": 0.5 * nm(so) + 0.5 * nm(ln), "bass (kick in)": 0.5 * nm(son) + 0.5 * nm(ln), "hat sound": ht, "hat pattern": pat,
        "part: bass sound kick out": so, "part: bass sound kick in": son, "part: bass line": ln, "part: line rhythm (flux16)": rhy, "part: line notes (chroma OTI)": pit,
        "NEW groove = bass line + hat pattern": 0.5 * nm(ln) + 0.5 * nm(pat),
        "NEW groove, rank-balanced": 0.5 * rb(ln) + 0.5 * rb(pat),
        "NEW groove, rhythm only = low flux16 + hat flux16": 0.5 * nm(rhy) + 0.5 * nm(pat),
        "NEW groove, rhythm only, rank-balanced": 0.5 * rb(rhy) + 0.5 * rb(pat),
        "NEW kick = kick-in sound alone": son,
        "NEW kick+ = 0.75 kick-in sound + 0.25 (kick f0, tail)": 0.75 * nm(son) + 0.25 * nm(ksc),
        "NEW kick+ = 0.5 kick-in sound + 0.5 (kick f0, tail)": 0.5 * nm(son) + 0.5 * nm(ksc),
        "NEW kick scalars alone (kick f0, tail)": ksc,
        "NEW overall sound = bass sound out + hat sound": 0.5 * nm(so) + 0.5 * nm(ht),
        "NEW overall sound, rank-balanced": 0.5 * rb(so) + 0.5 * rb(ht),
        "NEW overall sound 3 = bass out + kick in + hat sound": (nm(so) + nm(son) + nm(ht)) / 3,
        "NEW everything = bass out + line + hat sound + hat pattern": (nm(so) + nm(ln) + nm(ht) + nm(pat)) / 4,
        "NEW everything, rank-balanced": (rb(so) + rb(ln) + rb(ht) + rb(pat)) / 4,
    }


def stats_D(Dm):
    n = len(Dm) // 2
    rk = ranks_from_D(Dm)
    C = Dm[:n, n:]
    own, other = np.diag(C), C[~np.eye(n, dtype=bool)]
    return {"n": n, "top1": float(np.mean(rk == 1)), "top10": float(np.mean(rk <= 10)), "mrr": float(np.mean(1.0 / rk)),
            "dprime": float((other.mean() - own.mean()) / np.sqrt(0.5 * (own.var() + other.var())))}


out("\n## 2 similarity kinds from the stored fingerprints (float16 / uint8 as stored); own second half among 2n-1 candidates")
SIMRES = {}
for prot, (w, a, b) in {"tm (interleaved)": ("mx", "tmA", "tmB"), "early / late": ("mx", "early", "late"), "S1 / S2": ("sx", "S1", "S2")}.items():
    keep = [i for i, r in enumerate(R) if all(have(sub(r, w, k), kd) for k in (a, b) for kd in ("bass", "hat"))]
    Ks = kinds([sub(R[i], w, a) for i in keep] + [sub(R[i], w, b) for i in keep])
    out(f"-- {prot} (n={len(keep)}, chance top1 {1 / (2 * len(keep) - 1):.3f}, top10 {10 / (2 * len(keep) - 1):.3f})")
    for nm_, Dm in Ks.items():
        s = stats_D(Dm)
        SIMRES.setdefault(nm_, {})[prot] = s
        out(f"   {nm_:58s} top1 {s['top1']:.2f} top10 {s['top10']:.2f} MRR {s['mrr']:.2f} d' {s['dprime']:.2f}")

keep = [i for i, r in enumerate(R) if all(have(sub(r, "mx", "all"), kd) for kd in ("bass", "hat"))]
Kall = kinds([sub(R[i], "mx", "all") for i in keep])
iu = np.triu_indices(len(keep), 1)
out(f"\npair-distance Spearman on the full window M (n={len(keep)}, {len(iu[0])} pairs): rows = kind, columns = the four existing kinds")
out(f"{'':58s} " + " ".join(f"{e[:15]:>15s}" for e in EXIST) + "   max")
CORR = {}
for nm_, Dm in Kall.items():
    rr = [float(stats.spearmanr(Dm[iu], Kall[e][iu])[0]) for e in EXIST]
    others = [v for e, v in zip(EXIST, rr) if e != nm_]
    CORR[nm_] = dict(zip(EXIST, rr))
    out(f"{nm_:58s} " + " ".join(f"{v:15.2f}" for v in rr) + f"   {max(others):.2f}")
out("pair-distance Spearman, parts among each other: " + "; ".join(
    f"{a_} ~ {b_} {stats.spearmanr(Kall[a_][iu], Kall[b_][iu])[0]:+.2f}" for a_, b_ in (
        ("part: bass sound kick out", "part: bass sound kick in"), ("part: bass sound kick out", "part: bass line"), ("part: bass sound kick in", "part: bass line"),
        ("part: bass line", "hat pattern"), ("part: line rhythm (flux16)", "hat pattern"), ("part: bass sound kick out", "hat sound"),
        ("part: bass sound kick in", "hat sound"), ("part: line rhythm (flux16)", "part: line notes (chroma OTI)"),
        ("NEW kick scalars alone (kick f0, tail)", "part: bass sound kick in"))))
# how many of a seed's 10 nearest tracks does a new kind share with the existing kinds (full window, n tracks)?
out("top-10 neighbour overlap on the full window M (mean share of a seed's 10 nearest tracks that are also among its 10 nearest in the other kind; chance %.2f):" % (10 / (len(keep) - 1)))


def nn10(Dm):
    Dm = Dm.copy()
    np.fill_diagonal(Dm, np.inf)
    return np.argsort(Dm, axis=1)[:, :10]


NN = {k: nn10(v) for k, v in Kall.items()}
for nm_ in [k for k in Kall if k.startswith("NEW")] + list(EXIST):
    out(f"   {nm_:58s} " + " ".join(f"{e[:15]}: {np.mean([len(set(NN[nm_][i]) & set(NN[e][i])) / 10 for i in range(len(keep))]):.2f}" for e in EXIST))

# ============================================================================ 3 grid offset
out("\n## 3 grid offset from the two stored estimates (search range +-50 ms, estimate set to 0 when the contrast is < 1.5)")
lag, lagm, con = (np.array([r[k] for r in R], dtype=float) for k in ("lag_ms", "lag_M_ms", "lag_contrast"))
d = lag - lagm
out(f"middle-120 estimate: median {np.median(lag):+.1f} ms, p10 {np.percentile(lag, 10):+.1f}, p90 {np.percentile(lag, 90):+.1f}, min {lag.min():+.1f}, max {lag.max():+.1f}; "
    f"|lag| > 10 ms in {np.mean(np.abs(lag) > 10):.2f}, > 20 ms in {np.mean(np.abs(lag) > 20):.2f}; exactly 0 in {np.mean(lag == 0):.2f}; at the +-50 ms edge {int((np.abs(lag) >= 49.5).sum())}")
out(f"longest-M-block estimate: median {np.median(lagm):+.1f} ms, p10 {np.percentile(lagm, 10):+.1f}, p90 {np.percentile(lagm, 90):+.1f}; |lag| > 10 ms in {np.mean(np.abs(lagm) > 10):.2f}, "
    f"> 20 ms in {np.mean(np.abs(lagm) > 20):.2f}; exactly 0 in {np.mean(lagm == 0):.2f}; at the edge {int((np.abs(lagm) >= 49.5).sum())}")
ci = boot(lag, lagm)
out(f"repeatability: Spearman {spear(lag, lagm):.2f} [{ci[0]:.2f}, {ci[1]:.2f}], Pearson {np.corrcoef(lag, lagm)[0, 1]:.2f}; |diff| median {np.median(np.abs(d)):.2f} ms, p90 {np.percentile(np.abs(d), 90):.2f}, "
    f"<= 1 ms in {np.mean(np.abs(d) <= 1):.2f}, <= 3 ms in {np.mean(np.abs(d) <= 3):.2f}, > 5 ms in {int((np.abs(d) > 5).sum())} tracks")
out(f"same side of the +-10 ms line in both estimates: {np.mean((np.abs(lag) > 10) == (np.abs(lagm) > 10)):.2f}; +-20 ms line: {np.mean((np.abs(lag) > 20) == (np.abs(lagm) > 20)):.2f}")
out(f"contrast (middle-120 estimate only; none stored for the block estimate): p10 {np.percentile(con, 10):.1f}, median {np.median(con):.1f}, p90 {np.percentile(con, 90):.1f}, min {con.min():.2f}; < 1.5 in {int((con < 1.5).sum())}, < 3 in {int((con < 3).sum())}, < 5 in {int((con < 5).sum())}")
bad = np.abs(d) > 5
if bad.any():
    auc = np.mean([c_b < c_g for c_b in con[bad] for c_g in con[~bad]]) + 0.5 * np.mean([c_b == c_g for c_b in con[bad] for c_g in con[~bad]])
    out(f"disagreeing tracks (|diff| > 5 ms, n={int(bad.sum())}): ids {[IDS[i] for i in np.nonzero(bad)[0]]}, lag mid {lag[bad]}, lag block {lagm[bad]}, contrast {con[bad]}; "
        f"contrast rank among the 60 (1 = lowest): {[int((con < c).sum()) + 1 for c in con[bad]]}; AUC of low contrast for 'disagrees' {auc:.2f}; Spearman contrast vs |diff| {spear(con, np.abs(d)):+.2f}")
out("by file type (middle-120 estimate):")
for e in sorted(set(EXT)):
    m = EXT == e
    out(f"   {e:5s} n={m.sum():2d}: median {np.median(lag[m]):+6.1f} ms, min {lag[m].min():+6.1f}, max {lag[m].max():+6.1f}, |lag| > 10 ms {np.mean(np.abs(lag[m]) > 10):.2f}, > 20 ms {np.mean(np.abs(lag[m]) > 20):.2f}")
ll = np.isin(EXT, ["aiff", "wav", "flac"])
out(f"   lossless n={ll.sum()}: median {np.median(lag[ll]):+.1f} ms, IQR [{np.percentile(lag[ll], 25):+.1f}, {np.percentile(lag[ll], 75):+.1f}], |lag| > 10 ms {np.mean(np.abs(lag[ll]) > 10):.2f}, > 20 ms {np.mean(np.abs(lag[ll]) > 20):.2f}; "
    f"lossy n={(~ll).sum()}: median {np.median(lag[~ll]):+.1f} ms, IQR [{np.percentile(lag[~ll], 25):+.1f}, {np.percentile(lag[~ll], 75):+.1f}], |lag| > 10 ms {np.mean(np.abs(lag[~ll]) > 10):.2f}, > 20 ms {np.mean(np.abs(lag[~ll]) > 20):.2f}; "
    f"Mann-Whitney p {stats.mannwhitneyu(lag[ll], lag[~ll])[1]:.4f}")
out(f"lag vs tempo: Spearman {spear(lag, BPM):+.2f}; lag in beats (lag * bpm / 60000): median {np.median(lag * BPM / 60000):+.4f}")

(OUT / "derived_eval.txt").write_text("\n".join(LINES) + "\n", encoding="utf-8")


def js(o):
    if isinstance(o, dict):
        return {k: js(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [js(v) for v in o]
    if isinstance(o, (float, np.floating)):
        return None if not np.isfinite(o) else round(float(o), 4)
    if isinstance(o, np.integer):
        return int(o)
    return o


json.dump(js({"ids": IDS, "scalars": ROWS, "similarity": SIMRES, "pair_corr": CORR}), open(OUT / "derived_eval.json", "w", encoding="utf-8"), indent=1)
