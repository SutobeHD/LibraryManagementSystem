"""Raw per-half descriptors for the W1 (bass sound + line) and W5 (hat sound) similarity fingerprints.

Usage: run_sim.py <shard> <n_shards> <sample.json> [extra.json ...]
Windows: A = middle 120 s, B = 120 s from 5 % of the duration; each split into two 60 s halves
(A1 / A2, B1 / B2). Grid lag estimated once on A (baseline `estimate_lag`), reused for every half.
Writes sim_shard<k>.jsonl to $SC_SIM_OUT (default <repo>/tmp/sc-similarity). Audio opened read-only. Fingerprints are built
offline from these raw descriptors by eval_sim.py."""
import json
import os
import sys
import time
import traceback
import warnings
from pathlib import Path

for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMBA_NUM_THREADS"):
    os.environ[_k] = "1"
warnings.filterwarnings("ignore")

import numpy as np
import scipy.signal as sg

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / "app").is_dir())
sys.path.insert(0, str(ROOT / "scripts" / "dev" / "sound_component_research" / "baseline"))
import features as F  # noqa: E402
from run import file_duration, load  # noqa: E402

WIN = 120.0
FS = F.FS_LOW
SOS_LP300_L = sg.butter(6, 300, "low", fs=FS, output="sos")
NFFT_L = 8192
FL = np.fft.rfftfreq(NFFT_L, 1.0 / FS)
BAND_L = (FL >= 20.0) & (FL <= 300.0)
FB = FL[BAND_L]
M_30_250 = (FB >= 30.0) & (FB <= 250.0)
M_F0 = (FB >= 30.0) & (FB <= 150.0)
PC_OF_BIN = np.round(69 + 12 * np.log2(np.maximum(FB, 1.0) / 440.0)).astype(int) % 12

NFFT_H = 2048
FH = np.fft.rfftfreq(NFFT_H, 1.0 / F.SR)
HB_EDGES = np.concatenate((np.geomspace(5000, 12000, 25), np.geomspace(12000, 20000, 9)[1:]))
HB_IDX = [np.nonzero((FH >= lo) & (FH < hi))[0] for lo, hi in zip(HB_EDGES[:-1], HB_EDGES[1:])]
TUKEY = sg.windows.tukey(NFFT_H, 0.2)
HGRID = np.arange(0.5, 6.001, 0.125)  # harmonic-relative frequency grid (multiples of the segment f0)
DECAY_OFFS_MS = (5, 15, 30, 60)


def rl(a, nd=5):
    a = np.asarray(a, dtype=float)
    return [None if not np.isfinite(v) else float(f"{v:.{nd}g}") for v in a.ravel()]


class Clock:
    def __init__(self):
        self.t: dict = {}

    def run(self, name, fn, *a, **k):
        c0, w0 = time.process_time(), time.perf_counter()
        r = fn(*a, **k)
        self.t[name] = self.t.get(name, 0.0) + time.process_time() - c0
        self.t[name + "_wall"] = self.t.get(name + "_wall", 0.0) + time.perf_counter() - w0
        return r


def full_beats(bt, bn, dur):
    out = []
    for i in range(len(bt) - 1):
        if bt[i] >= 0.05 and bt[i + 1] <= dur - 0.05:
            out.append((bt[i], bt[i + 1], int(bn[i])))
    return out


def seg_stack(x, starts, n):
    idx = np.asarray(starts)[:, None] + np.arange(n)[None, :]
    return x[idx]


def spectra_l(segs):
    w = np.hanning(segs.shape[1])
    p = np.abs(np.fft.rfft((segs - segs.mean(1, keepdims=True)) * w, n=NFFT_L, axis=1)) ** 2
    return p[:, BAND_L] / (w ** 2).sum()


def seg_descriptors(P, seg_s):
    """Per-segment timbre scalars of the 30-250 Hz band + harmonic profile (h1..h6, dB re max)."""
    Pm, f = P[:, M_30_250], FB[M_30_250]
    tot = Pm.sum(1) + 1e-30
    cent = (Pm * f).sum(1) / tot
    flat = np.exp(np.log(Pm + 1e-30).mean(1)) / (Pm.mean(1) + 1e-30)
    f0 = np.full(len(P), np.nan)
    fb0 = FB[M_F0]
    for r in range(len(P)):
        f0[r] = F._strong_peaks(P[r, M_F0], fb0)[1]
    half_w = max(1.5 / seg_s, 1.0)
    harm = np.full((len(P), 6), np.nan)
    hshare = np.full(len(P), np.nan)
    for r in range(len(P)):
        if not np.isfinite(f0[r]):
            continue
        acc = 0.0
        for h in range(1, 7):
            c = h * f0[r]
            if c + half_w > 250.0:
                break
            m = np.abs(FB - c) <= max(half_w, 0.03 * c)
            harm[r, h - 1] = P[r, m].max()
            acc += P[r, m & M_30_250].sum()
        hshare[r] = acc / tot[r]
    hdb = F.db(harm)
    hdb = hdb - np.nanmax(hdb, axis=1, keepdims=True)
    # transposition-invariant envelope: log spectrum sampled at multiples of the segment's own f0
    hrel = np.full((len(P), len(HGRID)), np.nan)
    lp = F.db(P)
    for r in range(len(P)):
        if np.isfinite(f0[r]):
            fq = f0[r] * HGRID
            ok = (fq >= 25.0) & (fq <= 250.0)
            hrel[r, ok] = np.interp(fq[ok], FB, lp[r])
            hrel[r] -= np.nanmax(hrel[r])
    return cent, flat, f0, hdb, hshare, hrel


def acf_f0_strength(segs, fmin=30.0, fmax=150.0):
    n = segs.shape[1]
    nf = int(2 ** np.ceil(np.log2(2 * n)))
    sp = np.fft.rfft(segs - segs.mean(1, keepdims=True), n=nf, axis=1)
    ac = np.fft.irfft(np.abs(sp) ** 2, axis=1)[:, : n // 2 + 1]
    ac = ac / (ac[:, :1] + 1e-30)
    lags = np.arange(ac.shape[1])
    acu = ac / np.maximum(1.0 - lags / n, 0.3)  # unbiased: a pure tone keeps ~1 at its period
    lo, hi = int(np.floor(FS / fmax)), min(int(np.ceil(FS / fmin)), ac.shape[1] - 2)
    f0 = np.full(len(segs), np.nan)
    st = np.zeros(len(segs))
    for r in range(len(segs)):
        a = acu[r]
        pk, _ = sg.find_peaks(a[lo : hi + 1])
        if len(pk) == 0:
            continue
        pk = pk + lo
        if a[pk].max() <= 0:
            continue
        best = pk[a[pk] >= 0.85 * a[pk].max()][0]
        y0, y1, y2 = a[best - 1], a[best], a[best + 1]
        den = y0 - 2 * y1 + y2
        d = 0.5 * (y0 - y2) / den if den != 0 else 0.0
        f0[r] = FS / (best + d)
        st[r] = min(float(y1), 1.5)
    return f0, st


def bass_sound(y, beats, clock):
    yl = sg.resample_poly(y, 1, F.DEC_LOW)
    xs = sg.sosfiltfilt(SOS_LP300_L, sg.sosfiltfilt(F.SOS_HP25_L, yl))
    x200 = sg.sosfiltfilt(F.SOS_LP200_L, sg.sosfiltfilt(F.SOS_HP25_L, yl))
    n = len(yl)
    T = np.array([b - a for a, b, _ in beats])
    tm = float(np.median(T))
    out: dict = {"n_beats": len(beats), "tm": tm}
    for tag, off, ln in (("off", 0.45, 0.50), ("on", -0.02, 0.45)):
        nseg = int(ln * tm * FS)
        st = [int(round((a + off * T[j]) * FS)) for j, (a, _b, _n) in enumerate(beats)]
        st = [s for s in st if 0 <= s and s + nseg <= n]
        segs = seg_stack(xs, st, nseg)
        rms = F.db((segs ** 2).mean(1))
        keep = rms >= np.percentile(rms, 95) - 20.0
        P = spectra_l(segs[keep])
        cent, flat, f0, hdb, hshare, hrel = seg_descriptors(P, nseg / FS)
        out[tag] = {
            "n_seg": int(len(segs)), "n_keep": int(keep.sum()),
            "mean_pow": rl(P.mean(0)), "mean_log": rl(F.db(P).mean(0)),
            "cent": float(np.median(cent)), "cent_rel": float(np.nanmedian(cent / f0)),
            "flat": float(np.median(flat)), "f0": float(np.nanmedian(f0)),
            "harm_db": rl(np.nanmedian(hdb, axis=0)), "harm_share": float(np.nanmedian(hshare)),
            "hrel": rl(np.nanmean(hrel, axis=0)), "hrel_n": rl(np.isfinite(hrel).sum(0)),
            "level_db": float(np.median(rms[keep])),
        }
    return out, yl, x200


def bass_line(yl, x200, beats, clock):
    """16 grid steps per bar (downbeat-anchored from the Rekordbox beat number)."""
    xbp = sg.sosfiltfilt(F.SOS_BP40_120_L, yl)
    env = np.maximum(F._smooth(F._hilbert_env(xbp), int(round(0.008 * FS))), 1e-9)
    edb = 2 * F.db(env)
    _nov, lg = F.novelty(env ** 2, FS)
    dl = np.maximum(np.diff(lg, prepend=lg[0]), 0.0)
    n = len(yl)
    T = np.array([b - a for a, b, _ in beats])
    tm = float(np.median(T))
    e_sum, e_cnt = np.zeros(16), np.zeros(16)
    f_sum = np.zeros(16)
    rows, pos = [], []
    n16 = int(0.25 * tm * FS)
    for j, (a, b, bnum) in enumerate(beats):
        for s in range(4):
            p = ((bnum - 1) * 4 + s) % 16
            i0, i1 = int(round((a + s / 4 * T[j]) * FS)), int(round((a + (s + 1) / 4 * T[j]) * FS))
            c0, c1 = int(round((a + (s / 4 - 1 / 8) * T[j]) * FS)), int(round((a + (s / 4 + 1 / 8) * T[j]) * FS))
            e_sum[p] += edb[i0:i1].mean()
            e_cnt[p] += 1
            f_sum[p] += dl[max(c0, 0) : min(c1, n)].sum()
            k = int(round((a + (s / 4 + 0.02) * T[j]) * FS))
            if k + n16 <= n:
                rows.append(k)
                pos.append(p)
    segs = seg_stack(x200, rows, n16)
    pos = np.array(pos)
    rms = F.db((segs ** 2).mean(1))
    loud = rms >= np.percentile(rms, 95) - 20.0
    f0, strength = acf_f0_strength(segs)
    voiced = loud & np.isfinite(f0) & (strength >= 0.5)
    pc = np.where(voiced, np.round(69 + 12 * np.log2(np.where(voiced, f0, 440.0) / 440.0)).astype(int) % 12, -1)
    H = np.zeros((16, 12))
    for p_, c_ in zip(pos[voiced], pc[voiced]):
        H[p_, c_] += 1
    P = spectra_l(segs)
    C = np.zeros((16, 12))
    for r in np.nonzero(loud)[0]:
        ch = np.bincount(PC_OF_BIN[M_30_250], weights=P[r, M_30_250], minlength=12)
        C[pos[r]] += ch / (ch.sum() + 1e-30)
    nb = len(beats) / 4.0
    semis = 69 + 12 * np.log2(f0[voiced] / 440.0)
    return {
        "e16_db": rl(e_sum / np.maximum(e_cnt, 1)), "flux16": rl(f_sum / nb),
        "H16": rl(H), "C16": rl(C), "N16": rl(np.bincount(pos, minlength=16)),
        "V16": rl(np.bincount(pos[voiced], minlength=16)), "voiced_share": float(voiced.mean()),
        "f0_semis_med": float(np.median(semis)) if len(semis) else None,
        "f0_semis_iqr": float(np.subtract(*np.percentile(semis, [75, 25]))) if len(semis) > 4 else None,
    }


def hat_sound(y, bt, bn, dur):
    e_fine, e_pick, on, pk = F.hat_onsets(y, F.SOS_BP5_12K)
    feats, hist = F.hat_features(e_fine, on, pk, bt, bn, dur)
    _fl, fhist = F.flux_profile(e_pick, bt, bn, dur)
    t_on = on / F.FS_ENV
    _ii, ph, okp = F.beat_phase(t_on, bt)
    i0 = np.round(t_on * F.SR).astype(int) - int(0.002 * F.SR)
    pre_end = i0 - int(0.005 * F.SR)
    sel = okp & (t_on > 0.08) & (i0 + NFFT_H < len(y)) & (pre_end - NFFT_H >= 0)
    nonbeat = sel & (np.abs(((np.nan_to_num(ph) + 0.5) % 1.0) - 0.5) > F.TOL)
    out = {k: feats.get(k) for k in ("hats_per_beat", "offbeat_share", "sixteenth_share", "hat_decay_ms",
                                      "hat_open_share", "hat_t10_ms", "n_onsets", "n_beats")}
    out["flux16"] = None if fhist is None else rl(fhist)
    out["hist16"] = None if hist is None else rl(hist)
    if sel.sum() < 8:
        return out

    def bands(starts):
        fr = seg_stack(y, starts, NFFT_H) * TUKEY
        p = np.abs(np.fft.rfft(fr, axis=1)) ** 2
        return np.stack([p[:, ix].mean(1) for ix in HB_IDX], axis=1)

    post = bands(i0[sel])
    pre = bands(pre_end[sel] - NFFT_H)
    nbm = nonbeat[sel]
    out["n_sel"], out["n_nonbeat"] = int(sel.sum()), int(nbm.sum())
    out["post_pow"], out["pre_pow"] = rl(post.mean(0)), rl(pre.mean(0))
    out["post_log"] = rl(F.db(post).mean(0))
    out["diff_log"] = rl(np.median(F.db(post) - F.db(pre), axis=0))
    if nbm.sum() >= 8:
        out["post_log_nb"] = rl(F.db(post[nbm]).mean(0))
        out["post_pow_nb"] = rl(post[nbm].mean(0))
    # decay profile of the 5-12 kHz power envelope after each (non-beat) onset peak, dB re the peak
    pks = pk[nonbeat] if nonbeat.sum() >= 8 else pk[sel]
    offs = [int(round(ms * F.FS_ENV / 1000)) for ms in DECAY_OFFS_MS]
    ok = pks + max(offs) < len(e_fine)
    pks = pks[ok]
    ref = F.db(e_fine[pks])
    out["decay_prof_db"] = rl([np.median(F.db(e_fine[pks + o]) - ref) for o in offs])
    return out


def cutoff_psd(y):
    f, pxx = sg.welch(y, fs=F.SR, nperseg=4096, noverlap=2048)
    m = f >= 8000
    return {"f_hz0": float(f[m][0]), "df": float(f[1] - f[0]), "psd_db": rl(F.db(pxx[m], 1e-24), 4)}


def analyse_half(y, grid, t0, lag, clock):
    dur = len(y) / F.SR
    bt0, bn = F.window_grid(grid, t0, dur)
    bt = bt0 + lag
    beats = full_beats(bt, bn, dur)
    res: dict = {"t0": round(t0, 2), "dur": round(dur, 2), "n_full_beats": len(beats)}
    snd, yl, x200 = clock.run("bass_sound", bass_sound, y, beats, clock)
    res["bass"] = snd
    res["line"] = clock.run("bass_line", bass_line, yl, x200, beats, clock)
    res["hat"] = clock.run("hat_sound", hat_sound, y, bt, bn, dur)
    return res


def main():
    shard, n_shards = int(sys.argv[1]), int(sys.argv[2])
    tracks = []
    for p in sys.argv[3:]:
        tracks += json.load(open(p, encoding="utf-8"))["tracks"]
    out_dir = Path(os.environ.get("SC_SIM_OUT", ROOT / "tmp" / "sc-similarity"))
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"sim_shard{shard}.jsonl"
    rng = np.random.default_rng(0)  # warm-up: FFT plans, numba
    yw = rng.standard_normal(int(30 * F.SR)) * 0.1
    gw = [[(i % 4) + 1, 150.0, 400.0 * i] for i in range(80)]
    analyse_half(yw, gw, 0.0, 0.0, Clock())
    with open(out_path, "w", encoding="utf-8") as fh:
        for i, tr in enumerate(tracks):
            if i % n_shards != shard:
                continue
            row = {k: tr.get(k) for k in ("id", "title", "artist", "genre", "bpm", "key", "path", "extra")}
            row["ext"] = tr["path"].rsplit(".", 1)[-1].lower()
            try:
                d = file_duration(tr["path"], tr["total_time"])
                a0 = max(0.0, (d - WIN) / 2)
                b0 = min(0.05 * d, max(0.0, d - WIN))
                row["file_dur"], row["overlap_ab_s"] = round(d, 2), round(max(0.0, min(a0, b0) + WIN - max(a0, b0)), 1)
                clock = Clock()
                ya = clock.run("load", load, tr["path"], a0, WIN)
                bt0, _bn = F.window_grid(tr["grid"], a0, len(ya) / F.SR)
                lag, contrast = clock.run("lag", F.estimate_lag, ya, bt0)
                row["lag_ms"], row["lag_contrast"] = round(lag * 1000, 2), round(contrast, 2)
                row["cutoff"] = cutoff_psd(ya)
                half = len(ya) // 2
                row["A1"] = analyse_half(ya[:half], tr["grid"], a0, lag, clock)
                row["A2"] = analyse_half(ya[half:], tr["grid"], a0 + half / F.SR, lag, clock)
                row["cpu_A"] = {k: round(v, 3) for k, v in clock.t.items()}
                del ya
                cb = Clock()
                yb = cb.run("load", load, tr["path"], b0, WIN)
                half = len(yb) // 2
                row["B1"] = analyse_half(yb[:half], tr["grid"], b0, lag, cb)
                row["B2"] = analyse_half(yb[half:], tr["grid"], b0 + half / F.SR, lag, cb)
                row["cpu_B"] = {k: round(v, 3) for k, v in cb.t.items()}
                row["status"] = "ok"
            except Exception as exc:  # keep the row, never drop silently
                row["status"] = "error"
                row["error"] = f"{type(exc).__name__}: {exc}"[:300]
                row["trace"] = traceback.format_exc()[-1500:]
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            print(shard, i, row["status"], row.get("cpu_A"), row.get("error", ""), flush=True)


if __name__ == "__main__":
    main()
