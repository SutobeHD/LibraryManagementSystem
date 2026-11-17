"""Section-aware window measurement for the sound-component rework (hats grid position, pattern
similarity, W1 / W5 held-out, W2 on main sections, kick tail vs bassline, cost).

Usage: extract.py <shard> <n_shards> <fresh_sample.json> <out dir>      -> sect_shard<k>.jsonl
       extract.py selftest <fresh_sample.json> [n]                      -> masked == frozen check

Windows per track (Rekordbox PQTZ grid + per-track lag as in baseline/features.py):
  mid  complete bars inside the middle 120 s (one contiguous block)
  M    up to 64 bars of PSSI main phrases (Chorus: high mood kind 5, mid / low mood kind 9),
       8-bar blocks taken round-robin over the main phrases in a spread order, concatenated
  SX   first / last up-to-16 main bars (S1 / S2), concatenated
Subsets are bar masks on one prepared window, so both halves of a split share filters, onset
thresholds and envelopes; only the set of bars differs. The frozen W1 / W5 raw descriptors come
from similarity/run_sim.py (bass_sound / bass_line called unchanged with a beat subset; hat_sound
re-implemented with a beat mask and checked against the original by `selftest`).
Audio is opened read-only; nothing is written outside <out dir>."""
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

import librosa  # noqa: E402
import numpy as np  # noqa: E402
import scipy.signal as sg  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / "app").is_dir())
BASE = ROOT / "scripts" / "dev" / "sound_component_research"
sys.path.insert(0, str(BASE / "similarity"))
sys.path.insert(0, str(BASE / "baseline"))
import features as F  # noqa: E402
import run as BR  # noqa: E402  (baseline run.py: load, file_duration, hats_all)
import run_sim as RS  # noqa: E402  (frozen W1 / W5 raw descriptors)

SR = F.SR
WIN = 120.0
PRE = 0.060                 # a block starts this long before its first downbeat
XF = int(0.005 * SR)        # crossfade between non-adjacent blocks
PAD = 0.5                   # real audio before the first / after the last block
M_BARS, M_BLOCK, S_BARS = 64, 8, 16
MAIN_KIND = {1: (5,), 2: (9,), 3: (9,)}
EDGE_KIND = {1: (1, 6), 2: (1, 10), 3: (1, 10)}
LABEL = {1: {1: "I", 2: "U", 3: "D", 5: "C", 6: "O"},
         2: {1: "I", 2: "V", 3: "V", 4: "V", 5: "V", 6: "V", 7: "V", 8: "B", 9: "C", 10: "O"}}
LABEL[3] = LABEL[2]
FOLD = 192                  # fine bins per bar of the folded envelope (12 per 16th step)
ON_STEPS, OFF_STEPS = np.array([0, 4, 8, 12]), np.array([2, 6, 10, 14])
SIX_STEPS = np.arange(1, 16, 2)


class Clock:
    def __init__(self):
        self.t: dict = {}

    def run(self, name, fn, *a, **k):
        c0, w0 = time.process_time(), time.perf_counter()
        r = fn(*a, **k)
        self.t[name] = self.t.get(name, 0.0) + time.process_time() - c0
        self.t[name + "_wall"] = self.t.get(name + "_wall", 0.0) + time.perf_counter() - w0
        return r


NOCLOCK = Clock()


def fl(v, nd=6):
    if v is None:
        return None
    v = float(v)
    return float(f"{v:.{nd}g}") if np.isfinite(v) else None


def popcount_parity(k):
    return bin(int(k)).count("1") & 1


# ----------------------------------------------------------------------------- bars, phrases, windows
def grid_bars(grid, lag):
    arr = np.asarray(grid, dtype=float)
    t, bn = arr[:, 2] / 1000.0 + lag, arr[:, 0].astype(int)
    i0 = [i for i in np.nonzero(bn == 1)[0] if i + 4 < len(bn) and tuple(bn[i : i + 5]) == (1, 2, 3, 4, 1)]
    return t, bn, np.array(i0, dtype=int)


def phrase_list(pssi, n_beats):
    e = sorted(pssi["e"])
    starts = [min(max(x[0] - 1, 0), n_beats - 1) for x in e]
    ends = starts[1:] + [min(max(pssi["end_beat"] - 1, starts[-1]), n_beats - 1)]
    return [(s, max(s, en), int(x[1])) for s, en, x in zip(starts, ends, e)]


def spread_order(n):
    if n <= 2:
        return list(range(n))
    chosen = [0, n - 1]
    while len(chosen) < n:
        chosen.append(max((i for i in range(n) if i not in chosen),
                          key=lambda i: (min(abs(i - c) for c in chosen), -i)))
    return chosen


def select_m(ph_bars, cap=M_BARS, block=M_BLOCK):
    if sum(len(b) for b in ph_bars) <= cap:
        return sorted(x for b in ph_bars for x in b)
    out, k, order = [], 0, spread_order(len(ph_bars))
    while len(out) < cap:
        progressed = False
        for i in order:
            blk = ph_bars[i][block * k : block * (k + 1)]
            if blk and len(out) < cap:
                out += blk[: cap - len(out)]
                progressed = True
        if not progressed:
            break
        k += 1
    return sorted(out)


class Win:
    """One analysis signal with its beat grid. beat_bar[i] = bar id of beat interval i (-1 = none)."""

    def __init__(self, y, bt, bn, beat_bar=None, bars=None):
        self.y = np.ascontiguousarray(y, dtype=np.float64)
        self.bt, self.bn = np.asarray(bt, dtype=float), np.asarray(bn, dtype=int)
        self.dur = len(self.y) / SR
        self.beat_bar = np.full(len(self.bt), -1) if beat_bar is None else np.asarray(beat_bar, dtype=int)
        self.bars = [] if bars is None else list(bars)

    def mask(self, bar_ids):
        return np.isin(self.beat_bar, np.asarray(list(bar_ids), dtype=int)) & (self.beat_bar >= 0)


def build_window(y_full, t, bn, bar_i0, bar_ids):
    """Concatenate the given bars (ids into bar_i0, sorted) into one signal + synthetic beat grid."""
    blocks: list = []
    for b in sorted(bar_ids):
        if blocks and bar_i0[b] == bar_i0[blocks[-1][-1]] + 4:
            blocks[-1].append(b)
        else:
            blocks.append([b])
    pad, half = int(PAD * SR), XF // 2
    n0s = [int(round((t[bar_i0[bl[0]]] - PRE) * SR)) for bl in blocks]
    n1s = [int(round((t[bar_i0[bl[-1]] + 4] - PRE) * SR)) for bl in blocks]
    lead = min(pad, n0s[0])
    tail = min(pad, len(y_full) - n1s[-1])
    out = np.zeros(lead + sum(b - a for a, b in zip(n0s, n1s)) + tail)
    fade = 0.5 - 0.5 * np.cos(np.pi * (np.arange(XF) + 0.5) / XF)
    bt, bnn, bbar, off = [], [], [], lead
    for j, (bl, n0, n1) in enumerate(zip(blocks, n0s, n1s)):
        a = n0 - (lead if j == 0 else half)
        b = n1 + (tail if j == len(blocks) - 1 else XF - half)
        seg = y_full[a:b].astype(np.float64).copy()
        if j > 0:
            seg[:XF] *= fade
        if j < len(blocks) - 1:
            seg[-XF:] *= fade[::-1]
        o = off - (n0 - a)
        out[o : o + len(seg)] += seg
        for bar in bl:
            for q in range(bar_i0[bar], bar_i0[bar] + 4):
                bt.append((off + int(round(t[q] * SR)) - n0) / SR)
                bnn.append(int(bn[q]))
                bbar.append(bar)
        last_end = (off + int(round(t[bar_i0[bl[-1]] + 4] * SR)) - n0) / SR
        off += n1 - n0
    bt.append(last_end)
    bnn.append(1)
    bbar.append(-1)
    return Win(out, bt, bnn, bbar, sorted(bar_ids)), blocks


# ----------------------------------------------------------------------------- preparation (once per window)
def bass_pre(y):
    yl = sg.resample_poly(y, 1, F.DEC_LOW)
    fs = F.FS_LOW
    x200 = sg.sosfiltfilt(F.SOS_LP200_L, sg.sosfiltfilt(F.SOS_HP25_L, yl))
    x120 = sg.sosfiltfilt(F.SOS_LP120_L, x200)
    xbp = sg.sosfiltfilt(F.SOS_BP40_120_L, yl)
    sm = int(round(0.008 * fs))
    envbp = np.maximum(F._smooth(F._hilbert_env(xbp), sm), 1e-9)
    on, pk, _h = F.pick_onsets(envbp ** 2, fs, delta=0.30, wait_ms=90.0, lookback_ms=40.0)
    ev_t20, _ = F._decay_t20(envbp ** 2, pk, fs, cap_ms=1000.0, guard_ms=10.0)
    # band shares: the baseline Welch frames (32768, 1.35 Hz bins) at hop 8192, assigned to a bar by their centre
    f, tt, sxx = sg.spectrogram(y, fs=SR, window="hann", nperseg=32768, noverlap=24576, detrend="constant", mode="psd")
    return {
        "n": len(yl), "x200": x200, "xbp": xbp, "envbp": envbp, "ebpdb": 2 * F.db(envbp),
        "e120db": 2 * F.db(np.maximum(F._smooth(F._hilbert_env(x120), sm), 1e-9)),
        "low_on": on, "low_t20": ev_t20, "w_t": tt,
        "w_e60": sxx[f < 60].sum(0), "w_e120": sxx[f < 120].sum(0), "w_e200": sxx[f < 200].sum(0), "w_tot": sxx.sum(0),
        "w_5_12": sxx[(f >= 5000) & (f < 12000)].sum(0),
    }


def hat_channel(e_fine, e_pick):
    on, pk, _s = F.pick_onsets(e_pick, F.FS_ENV, delta=F.PICK_DELTA)
    t20, t10 = F._decay_t20(e_fine, pk, F.FS_ENV)
    _nov, lg = F.novelty(e_pick, F.FS_ENV)
    return {"e_fine": e_fine, "on": on, "pk": pk, "t20": t20, "t10": t10,
            "dl": np.maximum(np.diff(lg, prepend=lg[0]), 0.0)}


def hat_raw(y):
    """5-12 kHz band exactly as F.hat_onsets + the per-onset 46 ms frames of RS.hat_sound."""
    x = sg.sosfiltfilt(F.SOS_BP5_12K, y)
    ch = hat_channel(F.env_power(x, smooth_ms=5.0), F.env_power(x, smooth_ms=F.PICK_SMOOTH_MS))
    t_on = ch["on"] / F.FS_ENV
    i0 = np.round(t_on * SR).astype(int) - int(0.002 * SR)
    pre_end = i0 - int(0.005 * SR)
    fr_ok = (i0 + RS.NFFT_H < len(y)) & (pre_end - RS.NFFT_H >= 0)

    def bands(starts):
        fr = RS.seg_stack(y, starts, RS.NFFT_H) * RS.TUKEY
        p = np.abs(np.fft.rfft(fr, axis=1)) ** 2
        return np.stack([p[:, ix].mean(1) for ix in RS.HB_IDX], axis=1)

    post = np.full((len(t_on), len(RS.HB_IDX)), np.nan)
    pre = np.full((len(t_on), len(RS.HB_IDX)), np.nan)
    if fr_ok.any():
        post[fr_ok] = bands(i0[fr_ok])
        pre[fr_ok] = bands(pre_end[fr_ok] - RS.NFFT_H)
    ch.update(fr_ok=fr_ok, post=post, pre=pre)
    return ch


HP_NFFT, HP_HOP, HP_POOL, HP_KERNEL = 1024, 256, 4, (139, 9)   # 5.8 ms hop; 0.8 s x ~1.5 kHz medians


def hpss_fine(y, n_env):
    """Percussive part of the 5-12 kHz band at 5.8 ms resolution -> envelope on the FS_ENV axis."""
    S = np.abs(librosa.stft(y, n_fft=HP_NFFT, hop_length=HP_HOP)).astype(np.float32)
    f = librosa.fft_frequencies(sr=SR, n_fft=HP_NFFT)
    rows = np.nonzero((f >= 5000) & (f < 12000))[0]
    rows = rows[: len(rows) // HP_POOL * HP_POOL]
    pw = (S[rows].astype(np.float64) ** 2).reshape(-1, HP_POOL, S.shape[1]).sum(1)
    H, P = librosa.decompose.hpss(np.sqrt(pw).astype(np.float32), kernel_size=HP_KERNEL, power=2.0)
    e_p, e_h = (P.astype(np.float64) ** 2).sum(0), (H.astype(np.float64) ** 2).sum(0)
    t_fr = np.arange(len(e_p)) * HP_HOP / SR
    env = np.maximum(np.interp(np.arange(n_env) * F.DEC_ENV / SR, t_fr, e_p), 1e-14)
    return env, {"t": t_fr, "ep": e_p, "eh": e_h}


def hpss_band(y):
    """Baseline STFT / kernel (4096 / 1024, 31) on the 5-12 kHz rows only; per-frame energies."""
    S = np.abs(librosa.stft(y, n_fft=F.N_FFT, hop_length=F.HOP)).astype(np.float32)
    f = librosa.fft_frequencies(sr=SR, n_fft=F.N_FFT)
    m = (f >= 5000) & (f < 12000)
    H, P = librosa.decompose.hpss(S[m], kernel_size=31, power=2.0)
    return {"t": np.arange(S.shape[1]) * F.HOP / SR, "ep": (P.astype(np.float64) ** 2).sum(0),
            "eh": (H.astype(np.float64) ** 2).sum(0), "tot": (S.astype(np.float64) ** 2).sum(0)}


def prepare(win, clock=NOCLOCK, hpss=True):
    P = {"bass": clock.run("prep_bass", bass_pre, win.y), "hat": clock.run("prep_hat", hat_raw, win.y)}
    n_env = len(P["hat"]["e_fine"])
    tf = np.arange(n_env) / F.FS_ENV
    P["fr"] = F.beat_phase(tf, win.bt) + (tf,)
    if hpss:
        env, P["hf"] = clock.run("prep_hpss_fine", hpss_fine, win.y, n_env)
        P["hatP"] = clock.run("prep_hatP", hat_channel, env, env)
        P["hb"] = clock.run("prep_hpss_band", hpss_band, win.y)
    return P


# ----------------------------------------------------------------------------- subset features
def spans_of(bt, idx):
    spans = []
    for i in idx:
        if spans and abs(spans[-1][1] - bt[i]) < 1e-9:
            spans[-1][1] = bt[i + 1]
        else:
            spans.append([bt[i], bt[i + 1]])
    return spans


def frames_in(tc, spans):
    """Frames whose centre lies inside one of the spans."""
    m = np.zeros(len(tc), dtype=bool)
    for a, b in spans:
        m |= (tc >= a) & (tc < b)
    return m


def bass_block_m(bp, bt, idx):
    """F.bass_block on the beat intervals idx (same definitions). Band shares come from the Welch
    frames centred inside the selected intervals. Adds the kick-tail measures (mono_share,
    tail_db)."""
    fs = F.FS_LOW
    e120db, ebpdb, xbp, x200, n = bp["e120db"], bp["ebpdb"], bp["xbp"], bp["x200"], bp["n"]
    dur = n / fs
    idx = [i for i in idx if bt[i] >= 0.05 and bt[i + 1] <= dur - 0.05]
    beats = [(bt[i], bt[i + 1]) for i in idx]
    out: dict = {}
    fm = frames_in(bp["w_t"], spans_of(bt, idx))
    out["welch_frames"] = int(fm.sum())
    if fm.any():
        e60, e200, tot = bp["w_e60"][fm].sum(), bp["w_e200"][fm].sum(), bp["w_tot"][fm].sum()
        out.update(sub60_of_200=e60 / e200, sub60_of_total=e60 / tot, sub120_of_total=bp["w_e120"][fm].sum() / tot,
                   hi5_12k_share_db=float(F.db(bp["w_5_12"][fm].sum() / tot)))
    out["n_beats"] = len(beats)
    if len(beats) < 16:
        return out
    T = np.array([b - a for a, b in beats])

    def ix(t):
        return int(round(t * fs))

    peak_db = np.empty(len(beats))
    peak_i = np.empty(len(beats), dtype=int)
    for j, (a, _b) in enumerate(beats):
        s0, s1 = max(ix(a - 0.05 * T[j]), 0), ix(a + 0.35 * T[j])
        k = s0 + int(np.argmax(e120db[s0:s1]))
        peak_i[j], peak_db[j] = k, e120db[k]
    full_max = np.array([e120db[max(ix(a - 0.05 * T[j]), 0) : ix(b - 0.05 * T[j])].max()
                         for j, (a, b) in enumerate(beats)])
    valid = full_max >= np.percentile(full_max, 90) - 12.0
    out["bass_active_share"] = float(valid.mean())
    if valid.sum() < 12:
        return out
    dip, sustain, rerise, p_on, p_off, mono, tail = ([] for _ in range(7))
    for j, (a, b) in enumerate(beats):
        if not valid[j]:
            continue
        seg = e120db[peak_i[j] : ix(b - 0.05 * T[j])]
        if len(seg) < 8:
            continue
        dip.append(float(seg.min() - peak_db[j]))
        sb = ebpdb[ix(a) : ix(b)]
        sustain.append(float((sb >= sb.max() - 12.0).mean()))
        i_a, i_b, i_c = ix(a + 0.10 * T[j]), ix(a + 0.60 * T[j]), ix(a + 0.92 * T[j])
        k_min = i_a + int(np.argmin(ebpdb[i_a:i_b]))
        second = ebpdb[k_min:i_c].max()
        rerise.append(bool(second - ebpdb[k_min] >= 6.0 and second >= sb.max() - 12.0))
        p_on.append(float((xbp[ix(a) : ix(a + 0.40 * T[j])] ** 2).mean()))
        p_off.append(float((xbp[ix(a + 0.45 * T[j]) : ix(a + 0.95 * T[j])] ** 2).mean()))
        # kick-tail measures on the 40-120 Hz envelope: after its peak near the beat the level only
        # falls (no rise >= 3 dB above the running minimum until 0.92 T) = monotone decay
        s0, s1 = max(ix(a - 0.05 * T[j]), 0), ix(a + 0.35 * T[j])
        kp = s0 + int(np.argmax(ebpdb[s0:s1]))
        dec = ebpdb[kp:i_c]
        mono.append(bool((dec - np.minimum.accumulate(dec)).max() < 3.0))
        tail.append(float(ebpdb[ix(a + 0.60 * T[j]) : ix(a + 0.90 * T[j])].mean() - ebpdb[kp]))
    out["bass_dip_db"] = float(np.median(dip))
    out["bass_sustain_ratio"] = float(np.median(sustain))
    out["bass_rerise_share"] = float(np.mean(rerise))
    out["bass_between_db"] = float(F.db(np.mean(p_off) / np.mean(p_on)))
    out["mono_share"] = float(np.mean(mono))
    out["tail_db"] = float(np.median(tail))

    t_on = bp["low_on"] / fs
    ii, ph, ok = F.beat_phase(t_on, bt)
    selm = np.zeros(len(bt), dtype=bool)
    selm[idx] = True
    sel = ok & selm[ii] & (t_on > 0.05) & (t_on < dur - 0.05)
    ph = ph[sel]
    d0 = np.abs(((ph + 0.5) % 1.0) - 0.5)
    out["low_onsets_per_beat"] = float(len(ph) / len(beats))
    out["low_between_per_beat"] = float((d0 > 0.10).sum() / len(beats))

    tm = float(np.median(T))
    n_off, n_on = int(0.50 * tm * fs), int(0.35 * tm * fs)
    so, sk = [], []
    for j, (a, _b) in enumerate(beats):
        if not valid[j]:
            continue
        s, k = ix(a + 0.45 * T[j]), ix(a + 0.05 * T[j])
        if s + n_off <= n and k + n_on <= n:
            so.append(x200[s : s + n_off])
            sk.append(x200[k : k + n_on])
    so, sk = np.array(so), np.array(sk)
    rms_off = F.db((so ** 2).mean(1))
    keep = rms_off >= np.percentile(rms_off, 95) - 20.0
    band, fb = F._spec_band(so[keep], fs)
    low = np.array([F._strong_peaks(r, fb)[1] for r in band])
    _md, mean_low = F._strong_peaks(band.mean(0), fb)
    kband, _ = F._spec_band(sk, fs)
    _kd, k_low = F._strong_peaks(kband.mean(0), fb)
    f0 = float(np.nanmedian(low))
    out["bass_f0_hz"] = f0
    out["bass_f0_meanspec_hz"] = float(mean_low)
    out["kick_f0_hz"] = float(k_low)
    st = 12 * np.log2(low[np.isfinite(low)] / f0)
    out["bass_f0_iqr_st"] = float(np.subtract(*np.percentile(st, [75, 25])))
    out["bass_f0_within1st_share"] = float((np.abs(st) <= 1.0).mean())
    return out


def hat_subset(ch, P, win, bm, compat_nb=False):
    """F.hat_features + F.flux_profile + RS.hat_sound restricted to the beat intervals bm, plus the
    grid-class shares (counts, flux, energy), per-class open shares and the folded decay."""
    bt, bn, dur = win.bt, win.bn, win.dur
    e, on, pk = ch["e_fine"], ch["on"], ch["pk"]
    out: dict = {}
    t = on / F.FS_ENV
    ii, ph, ok0 = F.beat_phase(t, bt)
    inm = ok0 & bm[ii]
    ok = inm & (t >= 0.05) & (t <= dur - 0.05)
    nbm = np.ones(len(bt), dtype=bool) if compat_nb else bm
    nb = int((nbm & (bt >= 0.05) & (bt <= dur - 0.05)).sum())
    out["n_onsets"], out["n_beats"] = int(ok.sum()), nb
    if nb < 16:
        return out
    out["hats_per_beat"] = float(ok.sum() / nb)
    ii_f, ph_f, ok_f, tf = P["fr"]
    okf = ok_f & bm[ii_f] & (tf >= 0.05) & (tf <= dur - 0.05)
    # ---- threshold-free: flux (F.flux_profile), energy and folded envelope by grid position
    dl = ch["dl"]
    tot = float(dl[okf].sum())
    if tot > 0:
        p, w = ph_f[okf], dl[okf]

        def share(*centers):
            m = np.zeros(len(p), dtype=bool)
            for c in centers:
                m |= np.abs(((p - c + 0.5) % 1.0) - 0.5) <= F.TOL
            return float(w[m].sum() / tot), m

        s_on, m1 = share(0.0)
        s_off, m2 = share(0.5)
        s_16, m3 = share(0.25, 0.75)
        s_tri, m4 = share(1 / 3, 2 / 3)
        out.update(flux_per_beat=tot / nb, flux_on=s_on, flux_off=s_off, flux_16=s_16, flux_tri=s_tri,
                   flux_other=float(w[~(m1 | m2 | m3 | m4)].sum() / tot))
        r4 = np.round(p * 4).astype(int)
        step = ((bn[ii_f[okf]] - 1) * 4 + r4) % 16
        fhist = np.bincount(step, weights=w, minlength=16) / (nb / 4.0)
        out["flux16"] = RS.rl(fhist)
        out.update(fluxN_on=float(fhist[ON_STEPS].sum() / fhist.sum()), fluxN_off=float(fhist[OFF_STEPS].sum() / fhist.sum()),
                   fluxN_16=float(fhist[SIX_STEPS].sum() / fhist.sum()))
        # 2-bar pattern: bar parity from the absolute bar id (a wrapped step belongs to the next bar)
        bar = win.beat_bar[ii_f[okf]] + ((bn[ii_f[okf]] == 4) & (r4 == 4))
        out["flux32"] = RS.rl(np.bincount(step + 16 * (bar % 2), weights=w, minlength=32) / (nb / 8.0))
        ef = e[okf]
        cnt = np.maximum(np.bincount(step, minlength=16), 1)
        e16 = np.bincount(step, weights=ef, minlength=16) / cnt
        out["e16"] = RS.rl(e16)
        out.update(en_on=float(e16[ON_STEPS].sum() / e16.sum()), en_off=float(e16[OFF_STEPS].sum() / e16.sum()),
                   en_16=float(e16[SIX_STEPS].sum() / e16.sum()))
        fbin = np.floor(((bn[ii_f[okf]] - 1) + p) * (FOLD / 4)).astype(int) % FOLD
        prof = F.db(np.bincount(fbin, weights=ef, minlength=FOLD) / np.maximum(np.bincount(fbin, minlength=FOLD), 1), 1e-16)
        bar_s = float(np.median(np.diff(bt))) * 4
        k50 = 0.050 / (bar_s / FOLD)
        per = FOLD // 16

        def drop50(steps):
            v = []
            for s in steps:
                win_i = (np.arange(s * per - 2, s * per + 4)) % FOLD
                k = win_i[int(np.argmax(prof[win_i]))]
                x = k + k50
                lo = int(np.floor(x))
                v.append((1 - (x - lo)) * prof[lo % FOLD] + (x - lo) * prof[(lo + 1) % FOLD] - prof[k])
            return float(np.median(v))

        out.update(fold_drop50_on=drop50(ON_STEPS), fold_drop50_off=drop50(OFF_STEPS), fold_drop50_16=drop50(SIX_STEPS))
    if ok.sum() < 8:
        return out
    # ---- thresholded: onset counts by grid position (F.hat_features)
    p = ph[ok]

    def dist(c):
        return np.abs(((p - c + 0.5) % 1.0) - 0.5)

    on_b, off_b = dist(0.0) <= F.TOL, dist(0.5) <= F.TOL
    six = (dist(0.25) <= F.TOL) | (dist(0.75) <= F.TOL)
    tri = (dist(1 / 3) <= F.TOL) | (dist(2 / 3) <= F.TOL)
    n = len(p)
    out.update(onbeat_share=float(on_b.sum() / n), offbeat_share=float(off_b.sum() / n), sixteenth_share=float(six.sum() / n),
               triplet_share=float(tri.sum() / n), other_share=float((~(on_b | off_b | six | tri)).sum() / n),
               onbeat_per_beat=float(on_b.sum() / nb), offbeat_per_beat=float(off_b.sum() / nb),
               sixteenth_per_beat=float(six.sum() / nb))
    t20o, t10o = ch["t20"][ok], ch["t10"][ok]
    fin = np.isfinite(t20o)
    out["hat_decay_ms"] = float(np.median(t20o[fin])) if fin.any() else None
    out["hat_open_share"] = float((t20o[fin] > 120.0).mean()) if fin.any() else None
    out["hat_t10_ms"] = float(np.nanmedian(t10o)) if np.isfinite(t10o).any() else None
    for nm, cm in (("offbeat", off_b), ("onbeat", on_b), ("16", six)):
        o2 = cm & fin
        out[f"open_share_{nm}"] = float((t20o[o2] > 120.0).mean()) if o2.sum() >= 8 else None
        out[f"decay_{nm}_ms"] = float(np.median(t20o[o2])) if o2.sum() >= 8 else None
    o2 = off_b & fin
    out["open_offbeat_per_beat"] = float((t20o[o2] > 120.0).sum() / nb)
    step = ((bn[ii[ok]] - 1) * 4 + np.round(p * 4).astype(int)) % 16
    out["hist16"] = RS.rl(np.bincount(step, minlength=16).astype(float) / (nb / 4.0))
    if "post" not in ch:
        return out
    # ---- W5 timbre frames + decay profile (RS.hat_sound)
    sel = inm & (t > 0.08) & ch["fr_ok"]
    nonbeat = sel & (np.abs(((np.nan_to_num(ph) + 0.5) % 1.0) - 0.5) > F.TOL)
    if sel.sum() < 8:
        return out
    post, pre = ch["post"][sel], ch["pre"][sel]
    nbm_ = nonbeat[sel]
    out["n_sel"], out["n_nonbeat"] = int(sel.sum()), int(nbm_.sum())
    out["post_pow"], out["pre_pow"] = RS.rl(post.mean(0)), RS.rl(pre.mean(0))
    out["post_log"] = RS.rl(F.db(post).mean(0))
    out["diff_log"] = RS.rl(np.median(F.db(post) - F.db(pre), axis=0))
    if nbm_.sum() >= 8:
        out["post_log_nb"] = RS.rl(F.db(post[nbm_]).mean(0))
        out["post_pow_nb"] = RS.rl(post[nbm_].mean(0))
    pks = pk[nonbeat] if nonbeat.sum() >= 8 else pk[sel]
    offs = [int(round(ms * F.FS_ENV / 1000)) for ms in RS.DECAY_OFFS_MS]
    pks = pks[pks + max(offs) < len(e)]
    ref = F.db(e[pks])
    out["decay_prof_db"] = RS.rl([np.median(F.db(e[pks + o]) - ref) for o in offs])
    return out


def energy_subset(P, win, bm):
    out = {}
    for tag, d in (("band", P["hb"]), ("fine", P["hf"])):
        ii, _ph, ok = F.beat_phase(d["t"], win.bt)
        m = ok & bm[ii]
        if not m.any():
            continue
        ep, eh = d["ep"][m].sum(), d["eh"][m].sum()
        out[f"perc_frac_5_12k_{tag}"] = float(ep / (ep + eh))
        if "tot" in d:
            out["perc_share_5_12k_db"] = float(F.db(ep / d["tot"][m].sum()))
    return out


BASS_KEEP = ("n_seg", "n_keep", "cent", "cent_rel", "flat", "f0", "harm_db", "harm_share", "hrel", "hrel_n", "level_db")


def subset(win, P, bar_ids, clock=NOCLOCK):
    bm = win.mask(bar_ids)
    idx = np.nonzero(bm)[0]
    res: dict = {"n_bars": len(set(win.beat_bar[idx])), "n_beat_intervals": len(idx)}
    if len(idx) < 16:
        return res
    try:
        res["w2"] = clock.run("w2", bass_block_m, P["bass"], win.bt, list(idx))
    except Exception as exc:
        res["w2_error"] = f"{type(exc).__name__}: {exc}"[:200]
    beats = [(win.bt[i], win.bt[i + 1], int(win.bn[i])) for i in idx
             if win.bt[i] >= 0.05 and win.bt[i + 1] <= win.dur - 0.05]
    try:
        snd, yl, x200 = clock.run("w1_sound", RS.bass_sound, win.y, beats, None)
        res["bass"] = {tag: ({k: snd[tag][k] for k in BASS_KEEP}) for tag in ("off", "on")}
        res["line"] = clock.run("w1_line", RS.bass_line, yl, x200, beats, None)
    except Exception as exc:
        res["w1_error"] = f"{type(exc).__name__}: {exc}"[:200]
    try:
        res["hat"] = clock.run("w4w5_hat", hat_subset, P["hat"], P, win, bm)
        if "hatP" in P:
            res["hatP"] = clock.run("w4_hatP", hat_subset, P["hatP"], P, win, bm)
            res["en"] = clock.run("w4_energy", energy_subset, P, win, bm)
    except Exception as exc:
        res["hat_error"] = f"{type(exc).__name__}: {exc}"[:200]
    return res


def legacy_scalars(y, grid, t0, lag):
    """Baseline functions unchanged on one contiguous piece (run.analyse without the melody block)."""
    dur = len(y) / SR
    bt0, bn = F.window_grid(grid, t0, dur)
    bt = bt0 + lag
    try:
        res = {"bass": F.bass_block(y, bt)}
    except Exception as exc:  # baseline _acf_f0 has no guard for segments without a positive ACF peak
        res = {"bass": {}, "bass_error": f"{type(exc).__name__}: {exc}"[:200]}
    _S, H, Pm = F.hpss_block(y)
    res["hpss"] = F.hpss_shares(H, Pm)
    res["hats"] = BR.hats_all(y, bt, bn, dur, False)
    return res


# ----------------------------------------------------------------------------- one track
def analyse_track(tr):
    clock = Clock()
    row: dict = {"id": tr["id"], "genre": tr["genre"], "ext": tr["path"].rsplit(".", 1)[-1].lower(), "bpm": tr["bpm"]}
    path, grid, pssi = tr["path"], tr["grid"], tr["pssi"]
    y_full = clock.run("decode_full", BR.load, path, 0.0, None)
    d = len(y_full) / SR
    row["file_dur"], row["mood"] = round(d, 2), pssi["mood"]
    a0 = max(0.0, (d - WIN) / 2)
    ya = y_full[int(round(a0 * SR)) : int(round(a0 * SR)) + int(WIN * SR)]
    bt0, _bn0 = F.window_grid(grid, a0, len(ya) / SR)
    lag, contrast = clock.run("lag", F.estimate_lag, ya, bt0)
    row["lag_ms"], row["lag_contrast"] = round(lag * 1000, 2), round(contrast, 2)
    t, bn, bar_i0 = grid_bars(grid, lag)
    bar_ok = (t[bar_i0] - PRE - PAD > 0.2) & (t[bar_i0 + 4] + PAD < d - 0.2)

    # ---- phrases
    mood = pssi["mood"] if pssi["mood"] in MAIN_KIND else 1
    phr = phrase_list(pssi, len(t))
    ph_meta = []
    for pi, (s, en, kind) in enumerate(phr):
        bars = [b for b in np.nonzero((bar_i0 >= s) & (bar_i0 + 4 <= en) & bar_ok)[0]]
        seg = y_full[int(max(t[s], 0) * SR) : int(max(t[en], 0) * SR)]
        ph_meta.append({"i": pi, "s": s, "e": en, "kind": kind, "bars": bars, "label": LABEL[mood].get(kind, "X"),
                        "rms_db": float(F.db(np.mean(seg ** 2))) if len(seg) > SR else -120.0})
    main = [p for p in ph_meta if p["kind"] in MAIN_KIND[mood] and p["bars"]]
    main_total = sum(len(p["bars"]) for p in main)
    row["main_bars_pssi"], row["n_main_phrases"], row["fallback"] = main_total, len(main), False
    if main_total < 32:
        row["fallback"] = True
        cand = sorted((p for p in ph_meta if p["kind"] not in EDGE_KIND[mood] and p["bars"]), key=lambda p: -p["rms_db"])
        pick, tot = [], 0
        for p in cand:
            if tot >= M_BARS:
                break
            pick.append(p)
            tot += len(p["bars"])
        main = sorted(pick, key=lambda p: p["i"])
    # phrase-relative bar index k, run id (maximal runs of adjacent selected phrases)
    bar_k, bar_ph, bar_run, run = {}, {}, {}, -1
    for j, p in enumerate(main):
        if j == 0 or main[j - 1]["i"] != p["i"] - 1:
            run += 1
        for k, b in enumerate(p["bars"]):
            bar_k[b], bar_ph[b], bar_run[b] = k, p["i"], run
    main_bars = sorted(bar_k)
    m_bars = select_m([p["bars"] for p in main])
    n_s = min(S_BARS, len(main_bars) // 2)
    s1, s2 = main_bars[:n_s], main_bars[len(main_bars) - n_s :]
    row["M"] = {"n_bars": len(m_bars), "n_phrases": len({bar_ph[b] for b in m_bars}), "n_runs": len({bar_run[b] for b in m_bars}),
                "main_bars_used": len(main_bars)}
    row["S"] = {"n_bars": n_s, "other_run": bool(n_s and bar_run[s1[0]] != bar_run[s2[-1]]),
                "gap_s": round(float(t[bar_i0[s2[0]]] - t[bar_i0[s1[-1]] + 4]), 1) if n_s else None}

    # ---- middle 120 s: phrase-label shares + complete bars inside
    lab = {}
    for p in ph_meta:
        ov = max(0.0, min(t[p["e"]], a0 + WIN) - max(t[p["s"]], a0))
        lab[p["label"]] = lab.get(p["label"], 0.0) + ov / WIN
    mid_bars = [b for b in range(len(bar_i0)) if t[bar_i0[b]] - PRE >= a0 + 0.05 and t[bar_i0[b] + 4] <= a0 + WIN - 0.05 and bar_ok[b]]
    row["mid"] = {"a0": round(a0, 2), "label_share": {k: round(v, 3) for k, v in lab.items()}, "n_bars": len(mid_bars),
                  "main_bar_share": round(float(np.mean([b in bar_k for b in mid_bars])), 3) if mid_bars else None}
    m_set = set(m_bars)
    mid_set = set(mid_bars)
    row["M"]["bars_in_mid120"] = round(len(m_set & mid_set) / max(1, len(m_set)), 3)

    # ---- decode cost of the regions only (M)
    win_m, blocks = build_window(y_full, t, bn, bar_i0, m_bars)
    regs = [(t[bar_i0[bl[0]]] - PRE - (PAD if j == 0 else 0.0), t[bar_i0[bl[-1]] + 4] - PRE + (PAD if j == len(blocks) - 1 else 0.0))
            for j, bl in enumerate(blocks)]
    row["M"].update(n_blocks=len(blocks), audio_s=round(win_m.dur, 2), span_s=round(regs[-1][1] - regs[0][0], 2))
    clock.run("decode_span", BR.load, path, max(0.0, regs[0][0]), regs[-1][1] - regs[0][0])
    for a, b in regs:
        clock.run("decode_blocks", BR.load, path, max(0.0, a), b - a)

    # ---- window M (timed = cost of the section-aware pipeline), subsets
    cm = Clock()
    P = prepare(win_m, cm)
    half = len(m_bars) // 2
    subs = {
        "all": m_bars,
        "odd": [b for b in m_bars if bar_k[b] % 2 == 1], "even": [b for b in m_bars if bar_k[b] % 2 == 0],
        "tmA": [b for b in m_bars if popcount_parity(bar_k[b]) == 0], "tmB": [b for b in m_bars if popcount_parity(bar_k[b]) == 1],
        "early": m_bars[:half], "late": m_bars[len(m_bars) - half :],
    }
    row["mx"] = {"all": subset(win_m, P, subs["all"], cm)}
    row["cpu_M"] = {k: round(v, 3) for k, v in cm.t.items()}
    for nm in ("odd", "even", "tmA", "tmB", "early", "late"):
        row["mx"][nm] = subset(win_m, P, subs[nm])
    # lag estimated on the longest M block only (what an M-only pipeline would have)
    bl = max(blocks, key=len)
    yb = y_full[int((t[bar_i0[bl[0]]] - 0.5) * SR) : int((t[bar_i0[bl[-1]] + 4] + 0.5) * SR)]
    tb0 = t[bar_i0[bl[0]]] - 0.5
    btb = np.asarray(grid, dtype=float)[:, 2] / 1000.0 - tb0
    lag_m, _c = F.estimate_lag(yb, btb[(btb > -1.5) & (btb < len(yb) / SR + 1.5)])
    row["lag_M_ms"] = round(lag_m * 1000, 2)
    del P, win_m

    # ---- S1 / S2
    if n_s >= 4:
        win_s, _b = build_window(y_full, t, bn, bar_i0, sorted(set(s1) | set(s2)))
        Ps = prepare(win_s)
        row["sx"] = {"S1": subset(win_s, Ps, s1), "S2": subset(win_s, Ps, s2)}
        del Ps, win_s

    # ---- middle 120 s, same masked pipeline
    if len(mid_bars) >= 16:
        win_a, _b = build_window(y_full, t, bn, bar_i0, mid_bars)
        Pa = prepare(win_a)
        h = len(mid_bars) // 2
        row["midw"] = {
            "all": subset(win_a, Pa, mid_bars),
            "odd": subset(win_a, Pa, [b for b in mid_bars if b % 2 == 1]), "even": subset(win_a, Pa, [b for b in mid_bars if b % 2 == 0]),
            "tmA": subset(win_a, Pa, [b for b in mid_bars if popcount_parity(b) == 0]),
            "tmB": subset(win_a, Pa, [b for b in mid_bars if popcount_parity(b) == 1]),
            "h1": subset(win_a, Pa, mid_bars[:h]), "h2": subset(win_a, Pa, mid_bars[len(mid_bars) - h :]),
        }
        del Pa, win_a

    # ---- legacy split-half: baseline functions unchanged on the two consecutive 60 s halves
    hs = len(ya) // 2
    row["legacy"] = {"A1": legacy_scalars(ya[:hs], grid, a0, lag), "A2": legacy_scalars(ya[hs:], grid, a0 + hs / SR, lag)}
    row["cpu"] = {k: round(v, 3) for k, v in clock.t.items()}
    return row


def clean(o):
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return fl(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, np.ndarray):
        return clean(o.tolist())
    return o


def warmup():
    rng = np.random.default_rng(0)
    yw = rng.standard_normal(int(30 * SR)) * 0.1
    bt = np.arange(0.5, 29.0, 0.4)
    w = Win(yw, bt, (np.arange(len(bt)) % 4) + 1, np.arange(len(bt)) // 4)
    w.beat_bar[-1] = -1
    subset(w, prepare(w), sorted(set(w.beat_bar[:-1])))
    librosa.resample(yw[:SR].astype(np.float32), orig_sr=48000, target_sr=SR)


def selftest(sample, n):
    """Masked re-implementations must reproduce the frozen functions when every beat is selected."""
    worst = 0.0
    for tr in sample[:n]:
        d = BR.file_duration(tr["path"], tr["total_time"])
        a0 = max(0.0, (d - WIN) / 2)
        y = BR.load(tr["path"], a0 + 10, 40.0)
        bt0, bn = F.window_grid(tr["grid"], a0 + 10, len(y) / SR)
        lag, _c = F.estimate_lag(y, bt0)
        bt = bt0 + lag
        win = Win(y, bt, bn, np.where(np.arange(len(bt)) < len(bt) - 1, np.arange(len(bt)) // 4, -1))
        P = prepare(win, hpss=False)
        bm = np.ones(len(bt), dtype=bool)
        mine = hat_subset(P["hat"], P, win, bm, compat_nb=True)
        ref = RS.hat_sound(y, bt, bn, win.dur)
        e_fine, e_pick, on, pk = F.hat_onsets(y, F.SOS_BP5_12K)
        reff, _h = F.hat_features(e_fine, on, pk, bt, bn, win.dur)
        refl, _fh = F.flux_profile(e_pick, bt, bn, win.dur)
        ref.update({k: v for k, v in reff.items() if k not in ref})
        ref.update(refl)
        bass_m = bass_block_m(P["bass"], bt, list(range(len(bt) - 1)))
        bass_r = F.bass_block(y, bt)
        for nm, a, b in (("hat", mine, ref), ("bass", bass_m, bass_r)):
            for k, v in b.items():
                if k not in a or v is None or isinstance(v, str):
                    continue
                x, r = np.asarray(a[k], dtype=float), np.asarray(v, dtype=float)
                dev = float(np.nanmax(np.abs(x - r) / (np.abs(r) + 1e-9))) if x.shape == r.shape else np.inf
                welch = k in ("sub60_of_200", "sub60_of_total", "sub120_of_total", "hi5_12k_share_db")
                if not welch:
                    worst = max(worst, dev)
                if dev > 1e-6:
                    print(f"  {tr['id']} {nm}.{k}: rel dev {dev:.3g}" + (" (Welch frame selection, expected)" if welch else "  <-- MISMATCH"))
        print(tr["id"], "checked keys hat", len([k for k in ref if k in mine]), "bass", len([k for k in bass_r if k in bass_m]))
    print("worst relative deviation (non-Welch keys):", worst)


def main():
    if sys.argv[1] == "selftest":
        sample = json.load(open(sys.argv[2], encoding="utf-8"))["tracks"]
        selftest(sample, int(sys.argv[3]) if len(sys.argv) > 3 else 3)
        return
    shard, n_shards = int(sys.argv[1]), int(sys.argv[2])
    sample = json.load(open(sys.argv[3], encoding="utf-8"))["tracks"]
    out_dir = Path(sys.argv[4])
    out_dir.mkdir(parents=True, exist_ok=True)
    warmup()
    with open(out_dir / f"sect_shard{shard}.jsonl", "w", encoding="utf-8") as fh:
        for i, tr in enumerate(sample):
            if i % n_shards != shard:
                continue
            w0 = time.perf_counter()
            try:
                row = analyse_track(tr)
                row["status"] = "ok"
            except Exception as exc:  # keep the row, never drop silently
                row = {"id": tr["id"], "genre": tr["genre"], "status": "error", "error": f"{type(exc).__name__}: {exc}"[:300],
                       "trace": traceback.format_exc()[-2000:]}
            fh.write(json.dumps(clean(row), ensure_ascii=False) + "\n")
            fh.flush()
            print(shard, i, row["status"], round(time.perf_counter() - w0, 1), "s", row.get("cpu_M"), row.get("error", ""), flush=True)


if __name__ == "__main__":
    main()
