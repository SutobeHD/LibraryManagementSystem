"""Evaluation of extract.py output: three stabilities per scalar, hat grid shares, hat pattern
retrieval, held-out W1 / W5 retrieval on the section window, W2 on main sections, kick tail vs
bassline, cost.

Usage: eval_sections.py <data dir>   (expects <data dir>/run*/sect_shard*.jsonl and
       <data dir>/legacy/sim_shard*.jsonl written by the unchanged similarity/run_sim.py)

Splits (Spearman over tracks between the two halves):
  (i)   interleaved inside window M: tmA / tmB = bars by Thue-Morse parity of the phrase-relative
        bar index (balances 2- and 4-bar patterns); odd / even bars as the literal variant
  (ii)  cross-section: early / late half of the M bars; S1 / S2 = first / last 16 main bars
  (iii) consecutive 60 s halves of the middle 120 s: baseline functions unchanged ("legacy") and
        the masked pipeline on the same window (h1 / h2)
The frozen fingerprint builders, distances and rank statistics are taken from the namespace of
similarity/eval_sim.py, executed unchanged on the legacy directory."""
import contextlib
import glob
import io
import json
import sys
from pathlib import Path

import numpy as np
from scipy import stats

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / "app").is_dir())
SIM = ROOT / "scripts" / "dev" / "sound_component_research" / "similarity"
DATA = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(SIM))
sys.path.insert(0, str(SIM.parent / "baseline"))
G = {"__file__": str(SIM / "eval_sim.py"), "__name__": "eval_sim"}
sys.argv = [sys.argv[0], str(DATA / "legacy")]
with contextlib.redirect_stdout(io.StringIO()):
    exec(compile((SIM / "eval_sim.py").read_text(encoding="utf-8"), str(SIM / "eval_sim.py"), "exec"), G)
d_eucz, d_cos, d_cosc, d_oti, norm_med = G["d_eucz"], G["d_cos"], G["d_cosc"], G["d_oti"], G["norm_med"]
ranks_from_D, summ, arr = G["ranks_from_D"], G["summ"], G["arr"]

sect = {}
for f in sorted(glob.glob(str(DATA / "run*" / "sect_shard*.jsonl"))):
    for line in open(f, encoding="utf-8"):
        r = json.loads(line)
        if r["status"] == "ok":
            sect[r["id"]] = r
LEG = {r["id"]: r for r in G["PRIM"]}
IDS = sorted(i for i in sect if i in LEG)
R = [sect[i] for i in IDS]
N = len(R)
GEN = np.array([r["genre"] for r in R])
EXT = np.array([r["ext"] for r in R])
GRP = {"hard (HT+Raw+Upt)": np.isin(GEN, ["Hard Techno", "Raw", "Uptempo"]), "techno+groove": np.isin(GEN, ["Techno", "Groove"]),
       "soft (House+Trance)": np.isin(GEN, ["House", "Trance"])}
HARD, SOFT = GRP["hard (HT+Raw+Upt)"], GRP["soft (House+Trance)"]
RNG = np.random.default_rng(20261113)
print(f"tracks: {N}; genres {dict(zip(*np.unique(GEN, return_counts=True)))}; ext {dict(zip(*np.unique(EXT, return_counts=True)))}; "
      f"lossy {int(np.isin(EXT, ['mp3', 'm4a']).sum())}")


def sub(r, win, name):
    return (r.get(win) or {}).get(name) or {}


def spear(a, b):
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 8 or np.ptp(a[m]) == 0 or np.ptp(b[m]) == 0:
        return np.nan
    return float(stats.spearmanr(a[m], b[m])[0])


def boot(a, b, n=2000):
    m = np.isfinite(a) & np.isfinite(b)
    a, b = a[m], b[m]
    out = []
    for _ in range(n):
        ix = RNG.integers(0, len(a), len(a))
        if np.ptp(a[ix]) > 0 and np.ptp(b[ix]) > 0:
            out.append(stats.spearmanr(a[ix], b[ix])[0])
    return np.percentile(out, [2.5, 97.5])


# ============================================================================ 0 windows
print("\n## 0 windows")
mb = np.array([r["M"]["n_bars"] for r in R])
print(f"M bars: 64 in {np.mean(mb == 64):.2f} of tracks, median {np.median(mb):.0f}, min {mb.min()}; audio median {np.median([r['M']['audio_s'] for r in R]):.0f} s "
      f"(p10 {np.percentile([r['M']['audio_s'] for r in R], 10):.0f}, p90 {np.percentile([r['M']['audio_s'] for r in R], 90):.0f}); "
      f"blocks median {np.median([r['M']['n_blocks'] for r in R]):.0f}; main phrases used median {np.median([r['M']['n_phrases'] for r in R]):.0f}; "
      f">= 2 phrases {np.mean([r['M']['n_phrases'] >= 2 for r in R]):.2f}; >= 2 separate main runs {np.mean([r['M']['n_runs'] >= 2 for r in R]):.2f}; "
      f"span of M inside the track median {np.median([r['M']['span_s'] for r in R]):.0f} s")
print(f"fallback (< 32 main bars): {[r['id'] for r in R if r['fallback']]}; PSSI main bars median {np.median([r['main_bars_pssi'] for r in R]):.0f}, min {min(r['main_bars_pssi'] for r in R)}")
print(f"S1 / S2: 16 bars each in {np.mean([r['S']['n_bars'] == 16 for r in R]):.2f}; in different main runs {np.mean([r['S']['other_run'] for r in R]):.2f}; gap median {np.median([r['S']['gap_s'] for r in R]):.0f} s")
print(f"M bars that also lie in the middle 120 s: median {np.median([r['M']['bars_in_mid120'] for r in R]):.2f}")
lag_d = np.abs(np.array([r["lag_ms"] - r["lag_M_ms"] for r in R]))
print(f"grid lag (middle 120 s) vs lag from the longest M block: |diff| <= 3 ms in {np.mean(lag_d <= 3):.2f}; outliers {np.round(np.sort(lag_d)[-3:], 1)} ms")
lab = {k: np.array([r["mid"]["label_share"].get(k, 0.0) for r in R]) for k in "IUDCVBO"}
nonmain = 1 - lab["C"]
print("middle 120 s by PSSI label (share of the window): " + ", ".join(f"{k} median {np.median(v):.2f}" for k, v in lab.items()))
print(f"  Down (high mood kind 3) > 25 %: {int((lab['D'] > 0.25).sum())} / {N}; >= 20 %: {int((lab['D'] >= 0.20).sum())}; any Down: {int((lab['D'] > 0.01).sum())}")
print(f"  not Chorus > 25 %: {int((nonmain > 0.25).sum())} / {N}; > 50 %: {int((nonmain > 0.5).sum())}; Down + Up + Intro + Outro > 25 %: {int(((lab['D'] + lab['U'] + lab['I'] + lab['O']) > 0.25).sum())}")

# the same for the whole library from the stored PSSI (constant-tempo grid interpolated linearly)
try:
    meta = {str(t["ID"]): t for t in json.load(open(ROOT / "tmp/library-analysis/tracks.json", encoding="utf-8"))}
    n_lib = n_d25 = n_nm25 = n_nm50 = 0
    for line in open(ROOT / "tmp/sc-struct/phrases.jsonl", encoding="utf-8"):
        p = json.loads(line)
        ps, gr, m = p.get("pssi"), p.get("grid"), meta.get(p["id"], {})
        tt = float(m.get("TotalTime") or 0)
        if not ps or not gr or not ps["e"] or tt < 150 or gr["beats"] < 100 or gr["bpm_min"] != gr["bpm_max"]:
            continue
        spb = (gr["last_ms"] - gr["first_ms"]) / 1000.0 / (gr["beats"] - 1)
        a0 = max(0.0, (tt - 120) / 2)
        e = sorted(ps["e"])
        st = [gr["first_ms"] / 1000.0 + (x[0] - 1) * spb for x in e] + [gr["first_ms"] / 1000.0 + (ps["end_beat"] - 1) * spb]
        main = (5,) if ps["mood"] == 1 else (9,)
        d_sh = c_sh = 0.0
        for j, x in enumerate(e):
            ov = max(0.0, min(st[j + 1], a0 + 120) - max(st[j], a0)) / 120.0
            if ps["mood"] == 1 and x[1] == 3:
                d_sh += ov
            if x[1] in main:
                c_sh += ov
        n_lib += 1
        n_d25 += d_sh > 0.25
        n_nm25 += (1 - c_sh) > 0.25
        n_nm50 += (1 - c_sh) > 0.5
    print(f"  library (PSSI + constant grid, n={n_lib}): Down > 25 % of the middle 120 s in {n_d25} ({n_d25 / n_lib:.3f}); not Chorus > 25 % in {n_nm25} ({n_nm25 / n_lib:.2f}); > 50 % in {n_nm50} ({n_nm50 / n_lib:.2f})")
except FileNotFoundError as exc:
    print("  library pass skipped:", exc)


# ============================================================================ 1 scalars: three stabilities
def st_of(hz):
    return 69 + 12 * np.log2(hz / 440.0) if hz and hz > 0 else None


def g_w2(k, semis=False):
    def f(s):
        v = (s.get("w2") or {}).get(k)
        return st_of(v) if semis else v
    return f


def g_hat(k, ch="hat"):
    return lambda s: (s.get(ch) or {}).get(k)


def g_en(k):
    return lambda s: (s.get("en") or {}).get(k)


def l_bass(k, semis=False):
    def f(L):
        v = L["bass"].get(k)
        return st_of(v) if semis else v
    return f


def l_hat(k, band="h5"):
    return lambda L: L["hats"][band].get(k)


FEATS = [  # name, wish, masked getter, legacy getter (baseline functions, 60 s halves) or None
    ("sub60_of_200", "W2", g_w2("sub60_of_200"), l_bass("sub60_of_200")),
    ("sub60_of_total", "W2", g_w2("sub60_of_total"), l_bass("sub60_of_total")),
    ("bass_between_db", "W2", g_w2("bass_between_db"), l_bass("bass_between_db")),
    ("bass note: f0 mean-spectrum (st)", "W2", g_w2("bass_f0_meanspec_hz", True), l_bass("bass_f0_meanspec_hz", True)),
    ("bass f0 seg-median (st)", "W2", g_w2("bass_f0_hz", True), l_bass("bass_f0_hz", True)),
    ("kick f0 (st)", "W2", g_w2("kick_f0_hz", True), l_bass("kick_f0_hz", True)),
    ("bass_rerise_share", "W2", g_w2("bass_rerise_share"), l_bass("bass_rerise_share")),
    ("mono_share (kick-tail)", "A3", g_w2("mono_share"), None),
    ("tail_db", "A3", g_w2("tail_db"), None),
    ("hats energy perc 5-12k / total (dB)", "W4", g_en("perc_share_5_12k_db"), lambda L: L["hpss"].get("perc_share_5_12k_db")),
    ("5-12k share plain (dB)", "W4", g_w2("hi5_12k_share_db"), l_bass("hi5_12k_share_db")),
    ("perc fraction of 5-12k (4096 hpss)", "W4", g_en("perc_frac_5_12k_band"), lambda L: L["hpss"].get("perc_frac_5_12k")),
    ("perc fraction of 5-12k (fine hpss)", "W4", g_en("perc_frac_5_12k_fine"), None),
    ("hats per beat (count)", "W4", g_hat("hats_per_beat"), l_hat("hats_per_beat")),
    ("flux per beat", "W4", g_hat("flux_per_beat"), l_hat("flux_per_beat")),
    ("ON-beat share, counts", "W4", g_hat("onbeat_share"), l_hat("onbeat_share")),
    ("OFF-beat (8th) share, counts", "W4", g_hat("offbeat_share"), l_hat("offbeat_share")),
    ("16th share, counts", "W4", g_hat("sixteenth_share"), l_hat("sixteenth_share")),
    ("triplet share, counts", "W4", g_hat("triplet_share"), l_hat("triplet_share")),
    ("other share, counts", "W4", g_hat("other_share"), l_hat("other_share")),
    ("on-beat hits per beat", "W4", g_hat("onbeat_per_beat"), None),
    ("off-beat hits per beat", "W4", g_hat("offbeat_per_beat"), l_hat("offbeat_per_beat")),
    ("16th hits per beat", "W4", g_hat("sixteenth_per_beat"), l_hat("sixteenth_per_beat")),
    ("ON share, flux (+-1/24 beat)", "W4", g_hat("flux_on"), l_hat("flux_on")),
    ("OFF share, flux (+-1/24 beat)", "W4", g_hat("flux_off"), l_hat("flux_off")),
    ("16th share, flux (+-1/24 beat)", "W4", g_hat("flux_16"), l_hat("flux_16")),
    ("ON share, flux 16-step", "W4", g_hat("fluxN_on"), None),
    ("OFF share, flux 16-step", "W4", g_hat("fluxN_off"), None),
    ("16th share, flux 16-step", "W4", g_hat("fluxN_16"), None),
    ("ON share, energy 16-step", "W4", g_hat("en_on"), None),
    ("OFF share, energy 16-step", "W4", g_hat("en_off"), None),
    ("16th share, energy 16-step", "W4", g_hat("en_16"), None),
    ("open share (T20 > 120 ms), all", "W4", g_hat("hat_open_share"), l_hat("hat_open_share")),
    ("open share, off-beat hits", "W4", g_hat("open_share_offbeat"), l_hat("open_share_offbeat")),
    ("open share, on-beat hits", "W4", g_hat("open_share_onbeat"), None),
    ("open share, 16th hits", "W4", g_hat("open_share_16"), None),
    ("open off-beat hits per beat", "W4", g_hat("open_offbeat_per_beat"), None),
    ("hat decay T20 median (ms)", "W4", g_hat("hat_decay_ms"), l_hat("hat_decay_ms")),
    ("decay T20 off-beat hits (ms)", "W4", g_hat("decay_offbeat_ms"), None),
    ("fold drop @50 ms off-beat (dB)", "W4", g_hat("fold_drop50_off"), None),
    ("fold drop @50 ms on-beat (dB)", "W4", g_hat("fold_drop50_on"), None),
    ("fold drop @50 ms 16th (dB)", "W4", g_hat("fold_drop50_16"), None),
    ("[P] hats per beat", "W4p", g_hat("hats_per_beat", "hatP"), None),
    ("[P] ON share, counts", "W4p", g_hat("onbeat_share", "hatP"), None),
    ("[P] OFF share, counts", "W4p", g_hat("offbeat_share", "hatP"), None),
    ("[P] 16th share, counts", "W4p", g_hat("sixteenth_share", "hatP"), None),
    ("[P] ON share, flux 16-step", "W4p", g_hat("fluxN_on", "hatP"), None),
    ("[P] OFF share, flux 16-step", "W4p", g_hat("fluxN_off", "hatP"), None),
    ("[P] 16th share, flux 16-step", "W4p", g_hat("fluxN_16", "hatP"), None),
    ("[P] ON share, energy 16-step", "W4p", g_hat("en_on", "hatP"), None),
    ("[P] OFF share, energy 16-step", "W4p", g_hat("en_off", "hatP"), None),
    ("[P] 16th share, energy 16-step", "W4p", g_hat("en_16", "hatP"), None),
    ("[P] open share, all", "W4p", g_hat("hat_open_share", "hatP"), None),
    ("[P] open share, off-beat hits", "W4p", g_hat("open_share_offbeat", "hatP"), None),
    ("[P] open off-beat hits per beat", "W4p", g_hat("open_offbeat_per_beat", "hatP"), None),
    ("[P] fold drop @50 ms off-beat (dB)", "W4p", g_hat("fold_drop50_off", "hatP"), None),
]


def col(get, win, name):
    out = np.full(N, np.nan)
    for i, r in enumerate(R):
        v = get(sub(r, win, name))
        if v is not None:
            out[i] = v
    return out


def lcol(get, half, band=None):
    out = np.full(N, np.nan)
    for i, r in enumerate(R):
        try:
            v = get(r["legacy"][half])
        except KeyError:
            v = None
        if v is not None:
            out[i] = v
    return out


print("\n## 1 scalar features: distribution on window M + split Spearman, n = %d" % N)
print("(i) tm = Thue-Morse bars inside M, oe = odd / even bars; (ii) el = early / late half of M, S = first / last 16 main bars; "
      "(iii) leg = baseline functions on the consecutive 60 s halves of the middle 120 s, h12 = masked pipeline on the same halves; "
      "mtm = Thue-Morse bars inside the middle 120 s; M~mid = Spearman of the full-window values")
print(f"{'feature':38s} {'p10':>7s} {'med':>7s} {'p90':>7s} | {'i tm':>5s} {'i oe':>5s} | {'ii el':>5s} {'ii S':>5s} | {'iii leg':>7s} {'iii h12':>7s} | {'mtm':>5s} | {'M~mid':>5s}")
STAB = {}
for name, wish, gm, gl in FEATS:
    a = col(gm, "mx", "all")
    q = np.nanpercentile(a, [10, 50, 90]) if np.isfinite(a).any() else [np.nan] * 3
    v = {
        "tm": spear(col(gm, "mx", "tmA"), col(gm, "mx", "tmB")), "oe": spear(col(gm, "mx", "odd"), col(gm, "mx", "even")),
        "el": spear(col(gm, "mx", "early"), col(gm, "mx", "late")), "S": spear(col(gm, "sx", "S1"), col(gm, "sx", "S2")),
        "leg": spear(lcol(gl, "A1"), lcol(gl, "A2")) if gl else np.nan,
        "h12": spear(col(gm, "midw", "h1"), col(gm, "midw", "h2")),
        "mtm": spear(col(gm, "midw", "tmA"), col(gm, "midw", "tmB")),
        "Mmid": spear(a, col(gm, "midw", "all")),
    }
    STAB[name] = v
    print(f"{name:38s} {q[0]:7.3f} {q[1]:7.3f} {q[2]:7.3f} | {v['tm']:5.2f} {v['oe']:5.2f} | {v['el']:5.2f} {v['S']:5.2f} | {v['leg']:7.2f} {v['h12']:7.2f} | {v['mtm']:5.2f} | {v['Mmid']:5.2f}")

print("\nearlier split-half numbers (40 selection tracks, > 7 kHz band 'h7') recomputed here on the fresh 60 with the unchanged baseline functions (consecutive halves):")
for nm, k, old in (("h7 off-beat share", "offbeat_share", 0.47), ("h7 16th share", "sixteenth_share", 0.87), ("h7 hats per beat", "hats_per_beat", 0.69),
                   ("h7 open share off-beat", "open_share_offbeat", 0.85), ("h7 open share", "hat_open_share", 0.80), ("h7 flux off", "flux_off", 0.68),
                   ("h7 flux 16", "flux_16", 0.76), ("h7 hat decay", "hat_decay_ms", 0.78), ("h7 on-beat share (never reported)", "onbeat_share", np.nan)):
    print(f"  {nm:34s} fresh {spear(lcol(l_hat(k, 'h7'), 'A1'), lcol(l_hat(k, 'h7'), 'A2')):5.2f} | earlier {old:.2f}")
for nm, gl, old in (("sub60_of_200", l_bass("sub60_of_200"), 0.92), ("sub60_of_total", l_bass("sub60_of_total"), 0.89), ("bass_between_db", l_bass("bass_between_db"), 0.95),
                    ("bass f0 mean-spectrum", l_bass("bass_f0_meanspec_hz", True), 0.89), ("perc_frac_7k", lambda L: L["hpss"].get("perc_frac_7k"), 0.88),
                    ("perc_share_5_12k_db", lambda L: L["hpss"].get("perc_share_5_12k_db"), 0.83)):
    print(f"  {nm:34s} fresh {spear(lcol(gl, 'A1'), lcol(gl, 'A2')):5.2f} | earlier {old:.2f}")
print(f"  baseline bass_block raised on a 60 s half (no guard in _acf_f0) for {sum('bass_error' in r['legacy'][h] for r in R for h in ('A1', 'A2'))} halves "
      f"of {sum(any('bass_error' in r['legacy'][h] for h in ('A1', 'A2')) for r in R)} tracks -> those tracks are missing in the legacy W2 columns")

print("\nbootstrap 95 % CI of the split Spearman (2000 resamples of tracks) + paired difference (i tm) - (iii h12):")
for name in ("ON-beat share, counts", "OFF-beat (8th) share, counts", "16th share, counts", "ON share, flux 16-step", "OFF share, flux 16-step",
             "16th share, flux 16-step", "open share, off-beat hits", "open share (T20 > 120 ms), all", "hats per beat (count)",
             "hats energy perc 5-12k / total (dB)", "sub60_of_200", "bass_between_db", "bass note: f0 mean-spectrum (st)"):
    gm = next(f[2] for f in FEATS if f[0] == name)
    a1, a2, b1, b2 = col(gm, "mx", "tmA"), col(gm, "mx", "tmB"), col(gm, "midw", "h1"), col(gm, "midw", "h2")
    e1, e2 = col(gm, "mx", "early"), col(gm, "mx", "late")
    ci_i, ci_ii, ci_iii = boot(a1, a2), boot(e1, e2), boot(b1, b2)
    m = np.isfinite(a1) & np.isfinite(a2) & np.isfinite(b1) & np.isfinite(b2)
    dd = []
    for _ in range(2000):
        ix = RNG.integers(0, m.sum(), m.sum())
        dd.append(stats.spearmanr(a1[m][ix], a2[m][ix])[0] - stats.spearmanr(b1[m][ix], b2[m][ix])[0])
    lo, hi = np.percentile(dd, [2.5, 97.5])
    print(f"  {name:38s} (i) [{ci_i[0]:.2f}, {ci_i[1]:.2f}]  (ii el) [{ci_ii[0]:.2f}, {ci_ii[1]:.2f}]  (iii h12) [{ci_iii[0]:.2f}, {ci_iii[1]:.2f}]  diff (i)-(iii) [{lo:+.2f}, {hi:+.2f}]")

print("\nbass note same within 0.5 st between halves (mean-spectrum f0): " + ", ".join(
    f"{lab_} {np.nanmean(np.abs(col(g_w2('bass_f0_meanspec_hz', True), w, a) - col(g_w2('bass_f0_meanspec_hz', True), w, b)) <= 0.5):.2f}"
    for lab_, w, a, b in (("(i) tm", "mx", "tmA", "tmB"), ("(ii) early/late", "mx", "early", "late"), ("(ii) S1/S2", "sx", "S1", "S2"), ("(iii) h1/h2", "midw", "h1", "h2"))))
dm = np.abs(col(g_w2("bass_f0_meanspec_hz", True), "mx", "all") - col(g_w2("bass_f0_meanspec_hz", True), "midw", "all"))
print(f"bass note M vs middle 120 s: same within 0.5 st {np.nanmean(dm <= 0.5):.2f}; same pitch class {np.nanmean(np.abs(((dm + 6) % 12) - 6) <= 0.5):.2f}")
for nm in ("sub60_of_200", "sub60_of_total", "bass_between_db"):
    a, b = col(g_w2(nm), "mx", "all"), col(g_w2(nm), "midw", "all")
    print(f"{nm}: M vs middle 120 s median |diff| {np.nanmedian(np.abs(a - b)):.3f}, p90 {np.nanpercentile(np.abs(a - b), 90):.3f}, median signed (M - mid) {np.nanmedian(a - b):+.3f}")

# ============================================================================ 2 hat grid: genre contrast
print("\n## 2 hat grid shares on window M: genre medians, contrast soft (House + Trance, n=%d) vs hard (Hard Techno + Raw + Uptempo, n=%d): Mann-Whitney p, rank-biserial r (+ = soft higher)" % (SOFT.sum(), HARD.sum()))
GL = ["House", "Trance", "Techno", "Groove", "Hard Techno", "Raw", "Uptempo"]
print(f"{'feature':38s} " + " ".join(f"{g_[:7]:>7s}" for g_ in GL) + "   p_MW   r_rb")
print(f"{'n':38s} " + " ".join(f"{(g_ == GEN).sum():7d}" for g_ in GL))
for name in ("hats per beat (count)", "ON-beat share, counts", "OFF-beat (8th) share, counts", "16th share, counts", "on-beat hits per beat", "off-beat hits per beat",
             "16th hits per beat", "ON share, flux 16-step", "OFF share, flux 16-step", "16th share, flux 16-step", "ON share, energy 16-step",
             "OFF share, energy 16-step", "16th share, energy 16-step", "open share (T20 > 120 ms), all", "open share, off-beat hits", "open share, 16th hits",
             "open off-beat hits per beat", "fold drop @50 ms off-beat (dB)", "fold drop @50 ms 16th (dB)", "[P] OFF share, counts", "[P] 16th share, counts",
             "[P] OFF share, flux 16-step", "[P] 16th share, flux 16-step", "[P] OFF share, energy 16-step", "[P] open share, off-beat hits",
             "[P] open off-beat hits per beat", "[P] fold drop @50 ms off-beat (dB)", "hats energy perc 5-12k / total (dB)"):
    gm = next(f[2] for f in FEATS if f[0] == name)
    a = col(gm, "mx", "all")
    s, h = a[SOFT & np.isfinite(a)], a[HARD & np.isfinite(a)]
    u, p = stats.mannwhitneyu(s, h, alternative="two-sided")
    print(f"{name:38s} " + " ".join(f"{np.nanmedian(a[g_ == GEN]):7.3f}" for g_ in GL) + f"  {p:6.3f} {2 * u / (len(s) * len(h)) - 1:+6.2f}")
on_, off_, six_ = (col(g_hat(k), "mx", "all") for k in ("onbeat_share", "offbeat_share", "sixteenth_share"))
print(f"correlations on M (Spearman): on~off {spear(on_, off_):+.2f}, on~16th {spear(on_, six_):+.2f}, off~16th {spear(off_, six_):+.2f}; "
      f"count shares vs flux 16-step shares: on {spear(on_, col(g_hat('fluxN_on'), 'mx', 'all')):.2f}, off {spear(off_, col(g_hat('fluxN_off'), 'mx', 'all')):.2f}, "
      f"16th {spear(six_, col(g_hat('fluxN_16'), 'mx', 'all')):.2f}; raw band vs percussive part: on {spear(on_, col(g_hat('onbeat_share', 'hatP'), 'mx', 'all')):.2f}, "
      f"off {spear(off_, col(g_hat('offbeat_share', 'hatP'), 'mx', 'all')):.2f}, 16th {spear(six_, col(g_hat('sixteenth_share', 'hatP'), 'mx', 'all')):.2f}")
op_, pf_ = col(g_hat("hat_open_share"), "mx", "all"), col(g_en("perc_frac_5_12k_band"), "mx", "all")
print(f"open share vs percussive fraction of the band (the 'sustained synth' confound): raw {spear(op_, pf_):+.2f}, off-beat open raw {spear(col(g_hat('open_share_offbeat'), 'mx', 'all'), pf_):+.2f}, "
      f"[P] open {spear(col(g_hat('hat_open_share', 'hatP'), 'mx', 'all'), pf_):+.2f}, [P] off-beat open {spear(col(g_hat('open_share_offbeat', 'hatP'), 'mx', 'all'), pf_):+.2f}; "
      f"fold drop off raw {spear(col(g_hat('fold_drop50_off'), 'mx', 'all'), pf_):+.2f}, [P] {spear(col(g_hat('fold_drop50_off', 'hatP'), 'mx', 'all'), pf_):+.2f}")
hpb_ = col(g_hat("hats_per_beat"), "mx", "all")
print(f"saturation: on-beat hits per beat >= 0.9 in {np.mean(col(g_hat('onbeat_per_beat'), 'mx', 'all') >= 0.9):.2f} of tracks, off-beat hits per beat >= 0.9 in "
      f"{np.mean(col(g_hat('offbeat_per_beat'), 'mx', 'all') >= 0.9):.2f}, 16th hits per beat >= 0.9 in {np.mean(col(g_hat('sixteenth_per_beat'), 'mx', 'all') >= 0.9):.2f}, < 0.3 in "
      f"{np.mean(col(g_hat('sixteenth_per_beat'), 'mx', 'all') < 0.3):.2f} -> count shares vs 1 / hats-per-beat: on {spear(on_, 1 / hpb_):+.2f}, off {spear(off_, 1 / hpb_):+.2f}; 16th vs hats-per-beat {spear(six_, hpb_):+.2f}")
e16_ = np.array([arr(sub(r, "mx", "all")["hat"]["e16"]) for r in R])
back = e16_[:, [4, 12]].sum(1) / e16_[:, [0, 4, 8, 12]].sum(1)
print(f"on-beat 5-12 kHz energy: share on beats 2 + 4 (clap / snare position) median {np.median(back):.2f}, > 0.7 in {np.mean(back > 0.7):.2f} of tracks; "
      f"median T20 of on-beat hits {np.nanmedian(col(g_hat('decay_onbeat_ms'), 'mx', 'all')):.0f} ms, off-beat {np.nanmedian(col(g_hat('decay_offbeat_ms'), 'mx', 'all')):.0f} ms, "
      f"16th {np.nanmedian(col(g_hat('decay_16_ms'), 'mx', 'all')):.0f} ms")
print("between-track SD vs median |difference| of the two halves (count shares):")
for nm, k in (("on-beat", "onbeat_share"), ("off-beat", "offbeat_share"), ("16th", "sixteenth_share")):
    v = {w_: np.nanmedian(np.abs(col(g_hat(k), w, a_) - col(g_hat(k), w, b_))) for w_, w, a_, b_ in (("tm", "mx", "tmA", "tmB"), ("el", "mx", "early", "late"), ("h12", "midw", "h1", "h2"))}
    print(f"   {nm:8s} SD {np.nanstd(col(g_hat(k), 'mx', 'all')):.3f} | interleaved {v['tm']:.3f} | early / late {v['el']:.3f} | consecutive halves of the middle 120 s {v['h12']:.3f} | "
          f"M vs middle 120 s {np.nanmedian(np.abs(col(g_hat(k), 'mx', 'all') - col(g_hat(k), 'midw', 'all'))):.3f}")
REST = ~SOFT
print("soft (n=%d) vs all other genres (n=%d):" % (SOFT.sum(), REST.sum()))
for nm, a in (("16th share counts", six_), ("16th hits per beat", col(g_hat("sixteenth_per_beat"), "mx", "all")), ("OFF share counts", off_), ("OFF share energy", col(g_hat("en_off"), "mx", "all")),
              ("[P] OFF share counts", col(g_hat("offbeat_share", "hatP"), "mx", "all")), ("[P] 16th share counts", col(g_hat("sixteenth_share", "hatP"), "mx", "all")),
              ("open share off-beat", col(g_hat("open_share_offbeat"), "mx", "all"))):
    u, p_ = stats.mannwhitneyu(a[SOFT & np.isfinite(a)], a[REST & np.isfinite(a)])
    print(f"   {nm:22s} median {np.nanmedian(a[SOFT]):.3f} vs {np.nanmedian(a[REST]):.3f}  p {p_:.3f}  r {2 * u / (SOFT.sum() * REST.sum()) - 1:+.2f}")
ov_ = np.array([r["M"]["bars_in_mid120"] for r in R])
lo_ = ov_ < np.median(ov_)
print(f"M vs middle 120 s Spearman for the half of the tracks whose M shares < {np.median(ov_):.2f} of its bars with the middle 120 s (n={lo_.sum()}): " + ", ".join(
    f"{nm} {spear(col(g_hat(k), 'mx', 'all')[lo_], col(g_hat(k), 'midw', 'all')[lo_]):.2f}" for nm, k in (("on", "onbeat_share"), ("off", "offbeat_share"), ("16th", "sixteenth_share"), ("hats per beat", "hats_per_beat"), ("open off", "open_share_offbeat"))))
lossy = np.isin(EXT, ["mp3", "m4a"])
print("lossy vs lossless (Mann-Whitney p): " + ", ".join(
    f"{nm} {stats.mannwhitneyu(a[lossy & np.isfinite(a)], a[~lossy & np.isfinite(a)])[1]:.2f}" for nm, a in (("on", on_), ("off", off_), ("16th", six_), ("open off", col(g_hat('open_share_offbeat'), 'mx', 'all')))))
oo = col(g_hat("open_share_offbeat"), "mx", "all")
print(f"open share off-beat: defined (>= 8 off-beat hits) in {np.isfinite(oo).mean():.2f} of tracks on M; share of tracks with value 0 or 1: {np.nanmean((oo <= 0.02) | (oo >= 0.98)):.2f}")


# ============================================================================ 3 retrieval helpers
def have(h, kind):
    try:
        if kind == "bass":
            return h["bass"]["off"]["hrel"] is not None and h["line"]["flux16"] is not None
        if kind == "hat":
            return all(k in h["hat"] for k in ("post_pow", "pre_pow", "decay_prof_db", "flux16"))
        if kind == "pat":
            return "flux16" in h["hat"] and "flux32" in h["hat"] and "hist16" in h["hat"]
        if kind == "patP":
            return "flux16" in h["hatP"] and "flux32" in h["hatP"]
    except (KeyError, TypeError):
        return False
    return True


PROT = {  # label -> (window key, half 1, half 2); legacy halves come from the unchanged run_sim.py rows
    "(c) legacy A1/A2 (frozen code)": ("legacy", "A1", "A2"), "(c) legacy B1/B2 (frozen code)": ("legacy", "B1", "B2"),
    "(c') mid h1/h2 masked": ("midw", "h1", "h2"), "mid tmA/tmB": ("midw", "tmA", "tmB"),
    "(a) M tmA/tmB": ("mx", "tmA", "tmB"), "(a') M odd/even": ("mx", "odd", "even"),
    "(b) M early/late": ("mx", "early", "late"), "(b') S1/S2": ("sx", "S1", "S2"),
}


def halves_of(prot, kind):
    w, a, b = PROT[prot]
    h1, h2, keep = [], [], []
    for i, r in enumerate(R):
        x, y = (LEG[r["id"]][a], LEG[r["id"]][b]) if w == "legacy" else (sub(r, w, a), sub(r, w, b))
        if have(x, kind) and have(y, kind):
            h1.append(x)
            h2.append(y)
            keep.append(i)
    return h1, h2, np.array(keep)


def dmat(h1, h2, fn, metric):
    return metric(np.vstack((np.array([fn(h) for h in h1]), np.array([fn(h) for h in h2]))))


def stats_D(D):
    n = len(D) // 2
    rk = ranks_from_D(D)
    C = D[:n, n:]
    own, other = np.diag(C), C[~np.eye(n, dtype=bool)]
    dprime = (other.mean() - own.mean()) / np.sqrt(0.5 * (own.var() + other.var()))
    auc = np.mean([(C[i, np.arange(n) != i] > C[i, i]).mean() for i in range(n)])
    return {"n": n, "top1": np.mean(rk == 1), "top10": np.mean(rk <= 10), "mrr": np.mean(1.0 / rk), "dprime": dprime, "auc": auc, "rk": rk}


def fmt(s):
    return f"n={s['n']:2d} top1 {s['top1']:.2f} top10 {s['top10']:.2f} MRR {s['mrr']:.2f} d' {s['dprime']:4.2f} AUC {s['auc']:.3f}"


snd_off = lambda h: G["snd_hrel"](h, "off")  # noqa: E731
snd_on = lambda h: G["snd_hrel"](h, "on", 4.0)  # noqa: E731
pit12 = lambda h: (lambda c: np.round(c / (c.max() + 1e-12) * 255))(np.delete(G["pit_C_abs"](h).reshape(16, 12), [0, 4, 8, 12], axis=0).ravel())  # noqa: E731
postpow = lambda h: (lambda v: v - v.mean())(10 * np.log10(G["hat_bands"](h, "post_pow", 5000, 12000) + 1e-30))  # noqa: E731


def frozen(prot):
    """The frozen W1 / W5 distance matrices for one split protocol."""
    out = {}
    b1, b2, kb = halves_of(prot, "bass")
    line = 0.5 * norm_med(dmat(b1, b2, G["rhy_flux16"], d_cos)) + 0.5 * norm_med(dmat(b1, b2, pit12, d_oti))
    so, son = dmat(b1, b2, snd_off, d_eucz), dmat(b1, b2, snd_on, d_eucz)
    out.update({"W1 sound kick out (hrel 0.5-6)": so, "W1 sound kick in (hrel 0.5-4)": son, "W1 line (flux16 + chroma OTI)": line,
                "W1 combined kick out": 0.5 * norm_med(so) + 0.5 * norm_med(line), "W1 combined kick in": 0.5 * norm_med(son) + 0.5 * norm_med(line)})
    h1, h2, kh = halves_of(prot, "hat")
    snd = 0.75 * norm_med(dmat(h1, h2, postpow, d_eucz)) + 0.25 * norm_med(dmat(h1, h2, G["hat_decay"], d_eucz))
    pat = dmat(h1, h2, G["hat_flux16"], d_cos)
    out.update({"W5 hat timbre + decay": snd, "W5 pattern flux16 (cos)": pat, "W5 0.5 timbre + 0.5 flux16": 0.5 * norm_med(snd) + 0.5 * norm_med(pat),
                "W5 0.75 timbre + 0.25 flux16": 0.75 * norm_med(snd) + 0.25 * norm_med(pat),
                "[control] pre-onset frames 24 bands": dmat(h1, h2, G["hat_pre24"], d_eucz)})
    return out, kb, kh


print("\n## 3 held-out retrieval of the FROZEN W1 / W5 fingerprints (own second half among 2n-1 candidates; chance top1 %.3f, top10 %.3f)" % (1 / (2 * N - 1), 10 / (2 * N - 1)))
print("pass bar of the plan: top10 >= 0.80. Earlier numbers (selection set, n=40, window A): W1 sound out 0.80 / 0.93, sound in 0.65 / 0.82, line 0.82 / 0.90, "
      "combined out 0.88 / 0.95, combined in 0.85 / 0.93, W5 timbre + decay 0.88 / 0.93, W5 + flux16 0.85 / 0.88 (0.75 / 0.25), control 0.62 / 0.80")
FRO = {}
for prot in PROT:
    FRO[prot], kb, kh = frozen(prot)
    print(f"-- {prot}  (bass n={len(kb)}, hat n={len(kh)})")
    for nm, D in FRO[prot].items():
        s = stats_D(D)
        ci = 1.96 * np.sqrt(max(s["top10"] * (1 - s["top10"]), 1e-9) / s["n"])
        print(f"   {nm:38s} {fmt(s)}  (top10 +-{ci:.2f})")
print("genre split, top1 / top10 (candidate set = all halves):")
for prot in ("(c) legacy A1/A2 (frozen code)", "(a) M tmA/tmB", "(b) M early/late"):
    _o, kb, kh = frozen(prot)
    for nm in ("W1 combined kick out", "W1 combined kick in", "W5 hat timbre + decay"):
        rk = stats_D(FRO[prot][nm])["rk"]
        keep = kb if nm.startswith("W1") else kh
        print(f"   {prot:32s} {nm:24s} " + " | ".join(f"{g_} n={m[keep].sum()}: {np.mean(rk[m[keep]] == 1):.2f}/{np.mean(rk[m[keep]] <= 10):.2f}" for g_, m in GRP.items()))
ly = np.isin(EXT, ["mp3", "m4a"])
for nm in ("W1 combined kick out", "W5 hat timbre + decay"):
    _o, kb, kh = frozen("(c) legacy A1/A2 (frozen code)")
    rk = stats_D(FRO["(c) legacy A1/A2 (frozen code)"][nm])["rk"]
    keep = kb if nm.startswith("W1") else kh
    print(f"   lossy vs lossless, legacy A, {nm}: lossy n={ly[keep].sum()} {np.mean(rk[ly[keep]] == 1):.2f}/{np.mean(rk[ly[keep]] <= 10):.2f} | lossless n={(~ly[keep]).sum()} {np.mean(rk[~ly[keep]] == 1):.2f}/{np.mean(rk[~ly[keep]] <= 10):.2f}")

# ============================================================================ 4 hat pattern similarity
print("\n## 4 hat PATTERN fingerprints (exploratory variants on the fresh set -> not held-out), same retrieval")
PAT = {
    "flux16 cos (frozen form)": ("pat", "hat", lambda h: arr(h["flux16"]), d_cos),
    "flux16 centred cos": ("pat", "hat", lambda h: arr(h["flux16"]), d_cosc),
    "flux32 (2 bars) cos": ("pat", "hat", lambda h: arr(h["flux32"]), d_cos),
    "flux32 (2 bars) centred cos": ("pat", "hat", lambda h: arr(h["flux32"]), d_cosc),
    "onset-count hist16 centred cos": ("pat", "hat", lambda h: arr(h["hist16"]), d_cosc),
    "energy e16 dB, centred cos": ("pat", "hat", lambda h: 10 * np.log10(arr(h["e16"]) + 1e-16), d_cosc),
    "[P] flux16 centred cos": ("patP", "hatP", lambda h: arr(h["flux16"]), d_cosc),
    "[P] flux32 centred cos": ("patP", "hatP", lambda h: arr(h["flux32"]), d_cosc),
}
PRES = {}
for prot in ("(c') mid h1/h2 masked", "mid tmA/tmB", "(a) M tmA/tmB", "(a') M odd/even", "(b) M early/late", "(b') S1/S2"):
    print(f"-- {prot}")
    for nm, (kind, ch, fn, met) in PAT.items():
        if "32" in nm and "odd/even" in prot:
            continue
        h1, h2, keep = halves_of(prot, kind)
        D = dmat([h[ch] for h in h1], [h[ch] for h in h2], fn, met)
        PRES[(prot, nm)] = (D, keep)
        print(f"   {nm:32s} {fmt(stats_D(D))}")
print("legacy halves, frozen code (flux16 from RS.hat_sound): " + fmt(stats_D(FRO["(c) legacy A1/A2 (frozen code)"]["W5 pattern flux16 (cos)"])))

print("\npattern alone vs timbre alone vs combined (timbre = frozen W5 timbre + decay; pattern = flux16 centred cos | flux32 centred cos; weights 0.5 / 0.5 and 0.75 / 0.25):")
for prot in ("(c') mid h1/h2 masked", "(a) M tmA/tmB", "(b) M early/late", "(b') S1/S2"):
    h1, h2, keep = halves_of(prot, "hat")
    snd = 0.75 * norm_med(dmat(h1, h2, postpow, d_eucz)) + 0.25 * norm_med(dmat(h1, h2, G["hat_decay"], d_eucz))
    pre = dmat(h1, h2, G["hat_pre24"], d_eucz)
    print(f"-- {prot} (n={len(keep)})")
    print(f"   {'timbre + decay (frozen W5)':44s} {fmt(stats_D(snd))}")
    print(f"   {'[control] frames before the onsets':44s} {fmt(stats_D(pre))}")
    for pn, key in (("flux16 cc", "flux16"), ("flux32 cc", "flux32")):
        pat = dmat([h["hat"] for h in h1], [h["hat"] for h in h2], lambda h, k=key: arr(h[k]), d_cosc)
        print(f"   {'pattern ' + pn + ' alone':44s} {fmt(stats_D(pat))}")
        for w in (0.5, 0.75):
            print(f"   {f'{w:.2f} timbre + {1 - w:.2f} pattern {pn}':44s} {fmt(stats_D(w * norm_med(snd) + (1 - w) * norm_med(pat)))}")
    # does the pattern add information that timbre does not have? rank correlation of the two distance matrices
    n = len(keep)
    pat = dmat([h["hat"] for h in h1], [h["hat"] for h in h2], lambda h: arr(h["flux16"]), d_cosc)
    iu = np.triu_indices(n, 1)
    print(f"   Spearman of pairwise distances timbre vs pattern (first halves, {len(iu[0])} pairs): {stats.spearmanr(snd[:n, :n][iu], pat[:n, :n][iu])[0]:+.2f}")

# pattern: how much is the one-beat repetition, how different are tracks
h1, h2, keep = halves_of("(a) M tmA/tmB", "pat")
allp = np.array([arr(sub(R[i], "mx", "all")["hat"]["flux16"]) for i in keep])
allp = allp / allp.sum(1, keepdims=True)
rep = np.array([np.corrcoef(p, np.tile(p.reshape(4, 4).mean(0), 4))[0, 1] ** 2 for p in allp])
cc = np.corrcoef(allp)
print(f"\n16-step flux profile on M: variance explained by its own 1-beat (4-step) repetition median {np.median(rep):.2f} (p10 {np.percentile(rep, 10):.2f}); "
      f"cross-track Pearson of the profiles median {np.median(cc[np.triu_indices(len(cc), 1)]):.2f}; mean profile (share per step): "
      + " ".join(f"{v:.3f}" for v in allp.mean(0)))
gm_ = allp.mean(0)
print("   between-track SD per step / mean: " + " ".join(f"{v:.2f}" for v in allp.std(0) / gm_))


# ============================================================================ 5 kick tail vs bassline (A3)
print("\n## 5 between-kick low band on window M: kick tail vs own bass event (A3)")
W = {k: col(g_w2(k), "mx", "all") for k in ("mono_share", "bass_rerise_share", "tail_db", "bass_between_db", "bass_f0_meanspec_hz", "kick_f0_hz")}
dst = 12 * np.log2(W["bass_f0_meanspec_hz"] / W["kick_f0_hz"])
full_ = [sub(r, "mx", "all") for r in R]
harm = np.array([h["bass"]["off"]["harm_share"] for h in full_], dtype=float)
voiced = np.array([h["line"]["voiced_share"] for h in full_], dtype=float)


def n_pc(h):
    """Pitch classes carrying >= 15 % of the voiced between-kick 16th segments."""
    H = np.delete(np.nan_to_num(arr(h["line"]["H16"])).reshape(16, 12), [0, 4, 8, 12], axis=0).sum(0)
    return int((H / H.sum() >= 0.15).sum()) if H.sum() > 0 else 0


def rep1(h):
    """Share of the 16-step low-band flux pattern explained by its one-beat repetition."""
    v = np.nan_to_num(arr(h["line"]["flux16"]))
    return float(np.corrcoef(v, np.tile(v.reshape(4, 4).mean(0), 4))[0, 1] ** 2)


npcs, rep_low = np.array([n_pc(h) for h in full_]), np.array([rep1(h) for h in full_])
own = W["bass_rerise_share"] >= 0.5
tail_only = ~own & ((W["mono_share"] >= 0.5) | (W["tail_db"] <= -20.0))
one_note = own & (npcs <= 1) & (rep_low >= 0.8)
cls = np.where(own, np.where(one_note, "own event, one note, 1-beat loop", "own event, notes / longer pattern"),
               np.where(tail_only, "kick tail only", "no dip (sustained)"))
print("definitions (40-120 Hz envelope per beat): own event = bass_rerise_share >= 0.5 (dip >= 6 dB after the kick, then a second event within 12 dB of the beat maximum); "
      "kick tail only = no own event and (level only falls after the kick peak in >= 50 % of the beats, or the level at 0.6-0.9 T is >= 20 dB under the kick peak); "
      "one note / 1-beat loop = own event with a single pitch class (>= 15 % of the voiced between-kick 16ths) and >= 80 % of the low-band 16-step pattern explained by its "
      "one-beat repetition (what a side-chained kick rumble looks like; a one-note bass looks the same)")
print("synthetic check (synth_kicktail.py): pure kick tails give rerise 0.00, a side-chained rumble 0.79, bass notes 1.00")
print(f"distributions: rerise median {np.nanmedian(W['bass_rerise_share']):.2f} (p10 {np.nanpercentile(W['bass_rerise_share'], 10):.2f}); level 0.6-0.9 T vs kick peak median {np.nanmedian(W['tail_db']):.1f} dB; "
      f"between-kick f0 vs on-beat f0: median {np.nanmedian(dst):+.1f} st, lower by > 1 st in {np.mean(dst < -1):.2f}, within 1 st in {np.mean(np.abs(dst) <= 1):.2f} "
      "(the pitch sweep of a kick ends low too -> no discriminator)")
labels = ["kick tail only", "no dip (sustained)", "own event, one note, 1-beat loop", "own event, notes / longer pattern"]
print(f"{'genre':12s} {'n':>3s} " + " ".join(f"{l_[:33]:>33s}" for l_ in labels) + "   rerise  harm.share  voiced")
for g_ in GL + ["ALL"]:
    m = np.ones(N, bool) if g_ == "ALL" else g_ == GEN
    print(f"{g_:12s} {m.sum():3d} " + " ".join(f"{np.mean(cls[m] == l_):33.2f}" for l_ in labels)
          + f"   {np.nanmedian(W['bass_rerise_share'][m]):.2f}   {np.nanmedian(harm[m]):.2f}   {np.nanmedian(voiced[m]):.2f}")
print("tonality of the between-kick band, soft vs hard (Mann-Whitney p): " + ", ".join(
    f"{nm} {stats.mannwhitneyu(a[SOFT & np.isfinite(a)], a[HARD & np.isfinite(a)])[1]:.2f}" for nm, a in (("harmonic share", harm), ("voiced share", voiced), ("1-beat repetition", rep_low))))

# does the kick-out fingerprint just describe the kick? query = between-kick spectrum, candidates = on-beat spectra of all tracks
okb = np.array([have(h, "bass") for h in full_])
Xoff = np.array([G["snd_hrel"](h, "off", 4.0) for h, k in zip(full_, okb) if k])
Xon = np.array([G["snd_hrel"](h, "on", 4.0) for h, k in zip(full_, okb) if k])
D = d_eucz(np.vstack((Xoff, Xon)))
n = len(Xoff)
C = D[:n, n:]
rk = np.array([(C[i] < C[i, i]).sum() + 1 for i in range(n)])
pct = np.array([(C[i, np.arange(n) != i] < C[i, i]).mean() for i in range(n)])
c2 = cls[okb]
print(f"\nkick-out vs kick-in spectrum of the SAME track (f0-relative, h 0.5-4, window M): own kick is the nearest of {n} kick spectra in {np.mean(rk == 1):.2f} (chance {1 / n:.3f}), "
      f"top-5 {np.mean(rk <= 5):.2f}; median share of other tracks' kicks that are closer {np.median(pct):.2f}")
for l_ in labels:
    m = c2 == l_
    if m.sum() >= 3:
        print(f"   {l_:34s} n={m.sum():2d}: own kick nearest {np.mean(rk[m] == 1):.2f}, top-5 {np.mean(rk[m] <= 5):.2f}, median closer-share {np.median(pct[m]):.2f}")
Doff, Don = D[:n, :n], D[n:, n:]
iu = np.triu_indices(n, 1)
print(f"   Spearman of pairwise track distances kick-out vs kick-in sound: {stats.spearmanr(Doff[iu], Don[iu])[0]:+.2f} (all {len(iu[0])} pairs)")
for l_ in labels:
    m = np.nonzero(c2 == l_)[0]
    if len(m) >= 6:
        i2 = np.triu_indices(len(m), 1)
        print(f"      pairs inside '{l_}' (n={len(m)}): {stats.spearmanr(Doff[np.ix_(m, m)][i2], Don[np.ix_(m, m)][i2])[0]:+.2f}")
for prot in ("(c) legacy A1/A2 (frozen code)", "(b) M early/late"):
    _o, kb, _kh = frozen(prot)
    for nm in ("W1 sound kick out (hrel 0.5-6)", "W1 line (flux16 + chroma OTI)", "W1 combined kick out"):
        rk_ = stats_D(FRO[prot][nm])["rk"]
        print(f"   {prot:30s} {nm:32s} " + " | ".join(f"{l_} n={(cls[kb] == l_).sum()}: {np.mean(rk_[cls[kb] == l_] == 1):.2f}/{np.mean(rk_[cls[kb] == l_] <= 10):.2f}"
                                                         for l_ in labels if (cls[kb] == l_).sum() >= 3))

# ============================================================================ 6 cost
print("\n## 6 cost (process_time CPU-s; decode via librosa: soundfile for aiff / wav / flac / mp3, audioread -> ffmpeg subprocess for m4a, so wall is shown too)")
for e in ("aiff", "wav", "flac", "mp3", "m4a"):
    m = [r for r in R if r["ext"] == e]
    if not m:
        continue
    print(f"  decode {e:5s} n={len(m):2d}: whole track cpu {np.median([r['cpu']['decode_full'] for r in m]):.2f} wall {np.median([r['cpu']['decode_full_wall'] for r in m]):.2f} | "
          f"span of M cpu {np.median([r['cpu']['decode_span'] for r in m]):.2f} wall {np.median([r['cpu']['decode_span_wall'] for r in m]):.2f} | "
          f"M blocks only cpu {np.median([r['cpu']['decode_blocks'] for r in m]):.2f} wall {np.median([r['cpu']['decode_blocks_wall'] for r in m]):.2f} | "
          f"track {np.median([r['file_dur'] for r in m]):.0f} s, span {np.median([r['M']['span_s'] for r in m]):.0f} s, M audio {np.median([r['M']['audio_s'] for r in m]):.0f} s")
keys = ["prep_bass", "prep_hat", "w2", "w1_sound", "w1_line", "w4w5_hat", "prep_hpss_band", "prep_hpss_fine", "prep_hatP", "w4_hatP", "w4_energy"]
single = [json.loads(line) for f in sorted(glob.glob(str(DATA / "cost*" / "sect_shard*.jsonl"))) for line in open(f, encoding="utf-8")]
single = [r for r in single if r["status"] == "ok"]
FILES, LOSSLESS, MP3, M4A = 4633, 3253, 642, 738   # library file counts used by the plan (A5)
for tag, rs in (("12 processes in parallel", R), ("one process, no other load", single)):
    if not rs:
        continue
    med = {k: float(np.median([r["cpu_M"].get(k, 0.0) for r in rs])) for k in keys}
    lag = float(np.median([r["cpu"]["lag"] for r in rs]))
    core = lag + sum(med[k] for k in ("prep_bass", "prep_hat", "w2", "w1_sound", "w1_line", "w4w5_hat"))
    fine = med["prep_hpss_fine"] + med["prep_hatP"] + med["w4_hatP"]
    print(f"  window M features, {tag} (n={len(rs)}), median CPU-s: lag {lag:.2f} (on the middle 120 s) | " + " | ".join(f"{k} {v:.2f}" for k, v in med.items()))
    print(f"     core set (lag + W2 + W1 sound + W1 line + W4 grid + W5) {core:.2f} CPU-s per track; + hats energy (4096 hpss on the 5-12 kHz rows) {med['prep_hpss_band']:.2f}; "
          f"+ percussive-part grid features (fine hpss) {fine:.2f}; M audio median {np.median([r['M']['audio_s'] for r in rs]):.0f} s")

    def dec(kind, rs=rs):
        v = {}
        for e, grp in (("lossless", ("aiff", "wav", "flac")), ("mp3", ("mp3",)), ("m4a", ("m4a",))):
            x = [r["cpu"][kind + ("_wall" if e == "m4a" else "")] for r in rs if r["ext"] in grp]
            v[e] = float(np.median(x)) if x else np.nan
        return (LOSSLESS * v["lossless"] + MP3 * np.nan_to_num(v["mp3"], nan=v["lossless"]) + M4A * np.nan_to_num(v["m4a"], nan=v["lossless"])) / FILES

    d_full, d_span, d_blk = dec("decode_full"), dec("decode_span"), dec("decode_blocks")
    print(f"     decode per track, library-weighted (m4a by wall): whole {d_full:.2f} | one span {d_span:.2f} | blocks {d_blk:.2f} s")
    print(f"     library {FILES} files (Schaetzung): core + whole-track decode {(core + d_full) * FILES / 3600:.1f} CPU-h; core + span decode {(core + d_span) * FILES / 3600:.1f}; "
          f"+ hats energy {med['prep_hpss_band'] * FILES / 3600:.1f}; + fine hpss {fine * FILES / 3600:.1f}")
json.dump({"ids": IDS, "stab": STAB, "class": dict(zip(IDS, cls.tolist()))}, open(DATA / "eval_summary.json", "w", encoding="utf-8"), indent=1)
