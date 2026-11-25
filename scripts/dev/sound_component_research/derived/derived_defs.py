"""Definitions of the derived values: the stored fingerprints (as the plan stores them) and the
scalars computed from them or from raw descriptors the pass already has.

Input everywhere: one subset dict as written by sections/extract.py (`w2`, `bass`, `line`, `hat`).
Pure numpy; `arr`, `pit_c_abs`, `hat_bands`, `snd_hrel` mirror similarity/eval_sim.py and are
checked against the frozen originals by derive_eval.py on every row."""
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / "app").is_dir())
BASE = ROOT / "scripts" / "dev" / "sound_component_research"
for _p in (BASE / "similarity", BASE / "baseline"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from run_sim import HB_EDGES, HGRID  # noqa: E402

ON4, OFF4, SIX8 = np.array([0, 4, 8, 12]), np.array([2, 6, 10, 14]), np.arange(1, 16, 2)
HB_C = np.sqrt(HB_EDGES[:-1] * HB_EDGES[1:])[:24]      # centres of the 24 bands 5-12 kHz


def arr(x):
    return np.array([np.nan if v is None else v for v in x], dtype=float)


def q16(v):
    return np.asarray(v, dtype=float).astype(np.float16).astype(float)


def st_of(hz):
    return 69 + 12 * np.log2(hz / 440.0) if hz and hz > 0 else None


def pit_c_abs(s):
    c = arr(s["line"]["C16"]).reshape(16, 12)
    return (c / np.maximum(arr(s["line"]["N16"]), 1)[:, None]).ravel()


def hat_bands(s, key, lo, hi):
    v = arr(s["hat"][key])
    edges_lo = HB_EDGES[:-1]
    return v[(edges_lo >= lo - 1) & (edges_lo < hi - 1)]


def snd_hrel(s, tag, hmax=6.0):
    return arr(s["bass"][tag]["hrel"])[HGRID <= hmax + 1e-9]


# ----------------------------------------------------------------------------- stored fingerprints
def fp_snd_off(s):
    """bass sound, kick out: 45 x float16 = 90 B."""
    return q16(snd_hrel(s, "off"))


def fp_snd_on(s):
    """bass sound, kick in: 29 x float16 = 58 B."""
    return q16(snd_hrel(s, "on", 4.0))


def fp_line_flux(s):
    """bass line rhythm: 16-step low-band flux, sum-normalised, 16 x float16 = 32 B."""
    v = np.nan_to_num(arr(s["line"]["flux16"]))
    return q16(v / (v.sum() + 1e-12))


def fp_pit12(s):
    """bass line notes: 12 between-kick steps x 12 pitch classes, uint8 = 144 B."""
    c = np.nan_to_num(np.delete(pit_c_abs(s).reshape(16, 12), [0, 4, 8, 12], axis=0).ravel())
    return np.round(c / (c.max() + 1e-12) * 255)


def fp_hat_timbre(s):
    """hat timbre: 24 bands 5-12 kHz, dB, mean removed, 24 x float16 = 48 B."""
    v = 10 * np.log10(hat_bands(s, "post_pow", 5000, 12000) + 1e-30)
    return q16(v - v.mean())


def fp_hat_decay(s):
    """hat decay: 4-point decay profile + log T20 + log T10 + long-decay share, 7 x float16 = 14 B."""
    x = s["hat"]
    return q16(np.concatenate((arr(x["decay_prof_db"]), [np.log(x["hat_decay_ms"] or 1), np.log(x["hat_t10_ms"] or 1), x["hat_open_share"] or 0])))


def fp_hat_flux(s):
    """hat pattern: 16-step 5-12 kHz flux, 16 x float16 = 32 B."""
    return q16(np.nan_to_num(arr(s["hat"]["flux16"])))


# ----------------------------------------------------------------------------- scalars
def kb_interval(s):
    return 12 * np.log2(s["w2"]["bass_f0_meanspec_hz"] / s["w2"]["kick_f0_hz"])


def lowflux_share(steps, between_only=False):
    def f(s):
        v = fp_line_flux(s)
        return v[steps].sum() / (v.sum() - (v[ON4].sum() if between_only else 0.0))
    return f


def rep1(v):
    """Share of a 16-step profile explained by its own one-beat (4-step) repetition."""
    return float(np.corrcoef(v, np.tile(v.reshape(4, 4).mean(0), 4))[0, 1] ** 2)


def chroma(s):
    m = fp_pit12(s).reshape(12, 12)
    prof = m.sum(0)
    return m, prof / prof.sum()


def entropy12(p):
    p = p[p > 0]
    return float(-(p * np.log(p)).sum() / np.log(12))


def chroma_step_move(s):
    """1 - mean cosine between each step's pitch-class row and the mean row (weights = row sums)."""
    m, p = chroma(s)
    w = m.sum(1)
    cs = (m @ p) / (np.linalg.norm(m, axis=1) * np.linalg.norm(p) + 1e-12)
    return float(1 - (cs * w).sum() / w.sum())


def h12(s):
    """Pitch-class histogram of the voiced between-kick 16ths (ACF f0) - not part of a stored fingerprint."""
    h = np.delete(np.nan_to_num(arr(s["line"]["H16"])).reshape(16, 12), [0, 4, 8, 12], axis=0).sum(0)
    return h / h.sum() if h.sum() > 0 else None


def h_n_pc(s):
    p = h12(s)
    return None if p is None else float((p >= 0.15).sum())


def hat_tilt(s, key="post_pow"):
    """dB per octave across the 24 bands 5-12 kHz (key = pre_pow gives the control: frames before the onsets)."""
    v = 10 * np.log10(hat_bands(s, key, 5000, 12000) + 1e-30)
    return float(np.polyfit(np.log2(HB_C), q16(v - v.mean()), 1)[0])


def hat_centroid(s, key="post_pow"):
    p = hat_bands(s, key, 5000, 12000)
    return float(12 * np.log2((p * HB_C).sum() / p.sum() / 5000.0))


def hat_contrast(s):
    return float(np.median(hat_bands(s, "diff_log", 5000, 12000)))


def hrel_overtones(tag, hmax):
    """Mean level of the f0-relative spectrum at the harmonics 2..hmax re the level at the f0 (dB)."""
    def f(s):
        v = arr(s["bass"][tag]["hrel"])
        ix = [int(np.argmin(np.abs(HGRID - h))) for h in range(2, int(hmax) + 1)]
        return float(np.nanmean(v[ix]) - v[int(np.argmin(np.abs(HGRID - 1.0)))])
    return f


def bass_class(s):
    """Category of eval_sections.py section 5 (thresholds chosen in rework A)."""
    try:
        rr, mono, tail = s["w2"]["bass_rerise_share"], s["w2"]["mono_share"], s["w2"]["tail_db"]
        npc, rep = h_n_pc(s), rep1(fp_line_flux(s))
    except (KeyError, TypeError):
        return None
    if rr is None or npc is None:
        return None
    if rr >= 0.5:
        return "one-note loop" if (npc <= 1 and rep >= 0.8) else "notes / longer"
    return "kick tail only" if (mono >= 0.5 or tail <= -20.0) else "sustained"
