"""No-new-dependency baseline features for sound components (W2 bass, W4/W5 hats, W6 melody).

Scratch prototype for a planning doc. numpy / scipy / librosa only. All times in seconds unless
the name ends in _ms. Every function is pure (signal in, dict out)."""
from __future__ import annotations

import os

for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMBA_NUM_THREADS"):
    os.environ.setdefault(_k, "1")

import numpy as np
import scipy.ndimage as ndi
import scipy.signal as sg
from scipy.fft import next_fast_len
import librosa

SR = 44100
DEC_LOW = 20
FS_LOW = SR / DEC_LOW            # 2205 Hz, low-band working rate
DEC_ENV = 42
FS_ENV = SR / DEC_ENV            # 1050 Hz, envelope rate for high bands
N_FFT = 4096
HOP = 1024
TOL = 1.0 / 24.0                 # grid tolerance in beats (half the 16th <-> triplet distance)
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

SOS_HP25_L = sg.butter(4, 25, "high", fs=FS_LOW, output="sos")
SOS_LP200_L = sg.butter(6, 200, "low", fs=FS_LOW, output="sos")
SOS_LP120_L = sg.butter(6, 120, "low", fs=FS_LOW, output="sos")
SOS_BP40_120_L = sg.butter(4, [40, 120], "band", fs=FS_LOW, output="sos")
SOS_HP7K = sg.butter(6, 7000, "high", fs=SR, output="sos")
SOS_HP2K = sg.butter(4, 2000, "high", fs=SR, output="sos")
SOS_BP5_12K = sg.butter(4, [5000, 12000], "band", fs=SR, output="sos")


def db(x, floor=1e-12):
    return 10.0 * np.log10(np.maximum(x, floor))


def note_of(f):
    if f is None or not np.isfinite(f) or f <= 0:
        return None, None, None
    m = 69 + 12 * np.log2(f / 440.0)
    mi = int(round(m))
    return f"{NOTE_NAMES[mi % 12]}{mi // 12 - 1}", mi % 12, round(float((m - mi) * 100), 1)


# ----------------------------------------------------------------------------- grid
def window_grid(grid, t0, length, lag=0.0):
    """grid = [[beat_in_bar, bpm, time_ms], ...] -> beat times relative to the window start."""
    arr = np.asarray(grid, dtype=float)
    bt = arr[:, 2] / 1000.0 - t0 + lag
    bn = arr[:, 0].astype(int)
    sel = (bt >= -1.5) & (bt <= length + 1.5)
    return bt[sel], bn[sel]


def beat_phase(t, bt):
    """beat index i and phase in [0,1) for times t (array) on beat times bt."""
    i = np.searchsorted(bt, t, side="right") - 1
    ok = (i >= 0) & (i < len(bt) - 1)
    ph = np.full(len(t), np.nan)
    ii = np.clip(i, 0, len(bt) - 2)
    ph[ok] = (t[ok] - bt[ii[ok]]) / (bt[ii[ok] + 1] - bt[ii[ok]])
    return ii, ph, ok


def env_power(x, dec=DEC_ENV, smooth_ms=5.0, fs_in=SR):
    """Power envelope: boxcar 2*dec samples, decimate by dec, Hann of smooth_ms. Rate fs_in/dec."""
    e = ndi.uniform_filter1d(x * x, size=2 * dec, mode="nearest")[::dec]
    n = max(3, int(round(smooth_ms * (fs_in / dec) / 1000.0)) | 1)
    w = np.hanning(n + 2)[1:-1]
    return np.maximum(np.convolve(e, w / w.sum(), mode="same"), 1e-14)


def novelty(e, fs, c=100.0, lookback_ms=12.0, ref=None):
    """Rise of log-compressed energy over the minimum of the previous lookback window."""
    ref = float(np.percentile(e, 95)) if ref is None else ref
    lg = np.log10(1.0 + c * e / max(ref, 1e-14))
    k = max(3, int(round(lookback_ms * fs / 1000.0)) | 1)
    prev_min = ndi.minimum_filter1d(lg, size=k, origin=k // 2, mode="nearest")
    return lg - prev_min, lg


def pick_onsets(e, fs, delta=0.25, wait_ms=40.0, c=100.0, lookback_ms=12.0):
    """Per-band tuned picker. Thresholds are relative to the band's own p95 energy:
    onset = novelty peak >= delta (log10 units of 1 + c*e/p95), min distance wait_ms.
    Returns (onset_idx = steepest rise before the peak, peak_idx, strength)."""
    nov, lg = novelty(e, fs, c=c, lookback_ms=lookback_ms)
    peaks, props = sg.find_peaks(nov, height=delta, distance=max(1, int(wait_ms * fs / 1000.0)))
    k = max(3, int(round(lookback_ms * fs / 1000.0)))
    dl = np.diff(lg, prepend=lg[0])
    on = np.empty(len(peaks), dtype=int)
    for j, p in enumerate(peaks):
        a = max(0, p - k)
        on[j] = a + int(np.argmax(dl[a : p + 1]))
    return on, peaks, props["peak_heights"]


def estimate_lag(y, bt, max_ms=50.0):
    """Global grid offset: lag (s) maximising the > 2 kHz energy novelty at beat + lag.
    (Full-band power follows the bass waveform itself: 2*f0 ripple, wrong lags on rumble kicks.)"""
    e = env_power(sg.sosfiltfilt(SOS_HP2K, y))
    nov, _ = novelty(e, FS_ENV)
    m = int(max_ms * FS_ENV / 1000)
    lags = np.arange(-m, m + 1)
    b = bt[(bt > 0.2) & (bt < len(e) / FS_ENV - 0.2)]
    if len(b) < 8:
        return 0.0, 0.0
    idx = np.round(b * FS_ENV).astype(int)
    score = np.array([nov[idx + l].sum() for l in lags])
    best = int(np.argmax(score))
    contrast = float(score[best] / (np.median(score) + 1e-9))
    if contrast < 1.5:
        return 0.0, contrast
    return float(lags[best] / FS_ENV), contrast


# ----------------------------------------------------------------------------- W2 bass
def _smooth(x, n):
    return ndi.uniform_filter1d(x, size=max(1, int(n)), mode="nearest")


def _hilbert_env(x):
    n = len(x)
    return np.abs(sg.hilbert(x, N=next_fast_len(n)))[:n]


def _spec_band(segs, fs, nfft=16384, fmin=30.0, fmax=150.0):
    """Zero-padded Hann power spectra of the rows, cut to fmin..fmax."""
    w = np.hanning(segs.shape[1])
    pw = np.abs(np.fft.rfft(segs * w, n=nfft, axis=1)) ** 2
    f = np.fft.rfftfreq(nfft, 1.0 / fs)
    lo, hi = np.searchsorted(f, [fmin, fmax])
    return pw[:, lo:hi], f[lo:hi]


def _strong_peaks(spec, fb, rel_db=10.0):
    """(dominant_hz, lowest peak within rel_db of the max), parabolic interpolation in log power."""
    pk, _ = sg.find_peaks(spec)
    if len(pk) == 0 or spec.max() <= 0:
        return np.nan, np.nan

    def interp(i):
        a, b, c = (np.log(spec[k] + 1e-30) for k in (i - 1, i, i + 1))
        den = a - 2 * b + c
        d = 0.5 * (a - c) / den if den != 0 else 0.0
        return fb[i] + d * (fb[1] - fb[0])

    top = pk[np.argmax(spec[pk])]
    strong = pk[spec[pk] >= spec[top] * 10 ** (-rel_db / 10)]
    return interp(top), interp(strong[0])


def _acf_f0(segs, fs, fmin=30.0, fmax=150.0):
    """Autocorrelation f0 per row: shortest lag whose ACF peak is >= 0.85 of the best peak."""
    n = segs.shape[1]
    nf = int(2 ** np.ceil(np.log2(2 * n)))
    sp = np.fft.rfft(segs - segs.mean(1, keepdims=True), n=nf, axis=1)
    ac = np.fft.irfft(np.abs(sp) ** 2, axis=1)[:, : n // 2 + 1]
    ac = ac / (ac[:, :1] + 1e-30)
    lo, hi = int(np.floor(fs / fmax)), min(int(np.ceil(fs / fmin)), ac.shape[1] - 2)
    out = np.full(len(segs), np.nan)
    for r in range(len(segs)):
        a = ac[r]
        pk, _ = sg.find_peaks(a[lo : hi + 1])
        if len(pk) == 0:
            continue
        pk = pk + lo
        best = pk[a[pk] >= 0.85 * a[pk].max()][0]
        y0, y1, y2 = a[best - 1], a[best], a[best + 1]
        den = y0 - 2 * y1 + y2
        d = 0.5 * (y0 - y2) / den if den != 0 else 0.0
        out[r] = fs / (best + d)
    return out


def spectrum_shares(y):
    """W2b + plain band shares from one Welch PSD (1.35 Hz bins)."""
    f, pxx = sg.welch(y, fs=SR, nperseg=32768, noverlap=16384, detrend="constant")
    tot = float(pxx.sum())
    if tot <= 0:
        return {}
    e60, e120, e200 = (float(pxx[f < c].sum()) for c in (60.0, 120.0, 200.0))
    return {
        "sub60_of_200": e60 / e200 if e200 > 0 else None,
        "sub60_of_total": e60 / tot,
        "sub120_of_total": e120 / tot,
        "hi7k_share_db": float(db(pxx[f >= 7000].sum() / tot)),
        "hi5_12k_share_db": float(db(pxx[(f >= 5000) & (f < 12000)].sum() / tot)),
    }


def bass_block(y, bt):
    """W2. y mono 44.1k, bt beat times (s, window relative, lag corrected)."""
    out: dict = spectrum_shares(y)
    yl = sg.resample_poly(y, 1, DEC_LOW)
    fs = FS_LOW
    x200 = sg.sosfiltfilt(SOS_LP200_L, sg.sosfiltfilt(SOS_HP25_L, yl))
    x120 = sg.sosfiltfilt(SOS_LP120_L, x200)
    xbp = sg.sosfiltfilt(SOS_BP40_120_L, yl)
    sm = int(round(0.008 * fs))
    e120db = 2 * db(np.maximum(_smooth(_hilbert_env(x120), sm), 1e-9))
    envbp = np.maximum(_smooth(_hilbert_env(xbp), sm), 1e-9)
    ebpdb = 2 * db(envbp)
    n = len(yl)
    dur = n / fs

    beats = [(bt[i], bt[i + 1]) for i in range(len(bt) - 1) if bt[i] >= 0.05 and bt[i + 1] <= dur - 0.05]
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

    t20, t10, cens, sustain, dip, rerise, t20rel, p_on, p_off = ([] for _ in range(9))
    slots = np.zeros(4)
    for j, (a, b) in enumerate(beats):
        if not valid[j]:
            continue
        seg = e120db[peak_i[j] : ix(b - 0.05 * T[j])]
        if len(seg) < 8:
            continue
        below20 = np.nonzero(seg < peak_db[j] - 20.0)[0]
        below10 = np.nonzero(seg < peak_db[j] - 10.0)[0]
        c = len(below20) == 0
        d20 = (len(seg) if c else below20[0]) / fs
        t20.append(d20 * 1000.0)
        t20rel.append(d20 / T[j])
        t10.append((len(seg) if len(below10) == 0 else below10[0]) / fs * 1000.0)
        cens.append(c)
        dip.append(float(seg.min() - peak_db[j]))
        sb = ebpdb[ix(a) : ix(b)]
        sustain.append(float((sb >= sb.max() - 12.0).mean()))
        i_a, i_b, i_c = ix(a + 0.10 * T[j]), ix(a + 0.60 * T[j]), ix(a + 0.92 * T[j])
        k_min = i_a + int(np.argmin(ebpdb[i_a:i_b]))
        second = ebpdb[k_min:i_c].max()
        rerise.append(bool(second - ebpdb[k_min] >= 6.0 and second >= sb.max() - 12.0))
        pw = xbp[ix(a) : ix(b)] ** 2
        nq = len(pw) // 4
        slots += np.array([pw[q * nq : (q + 1) * nq].mean() for q in range(4)])
        p_on.append(float((xbp[ix(a) : ix(a + 0.40 * T[j])] ** 2).mean()))
        p_off.append(float((xbp[ix(a + 0.45 * T[j]) : ix(a + 0.95 * T[j])] ** 2).mean()))
    out["boom_t20_ms"] = float(np.median(t20))
    out["boom_t10_ms"] = float(np.median(t10))
    out["boom_t20_rel"] = float(np.median(t20rel))
    out["boom_censored_share"] = float(np.mean(cens))
    out["bass_dip_db"] = float(np.median(dip))
    out["bass_sustain_ratio"] = float(np.median(sustain))
    out["bass_rerise_share"] = float(np.mean(rerise))
    out["bass_between_db"] = float(db(np.mean(p_off) / np.mean(p_on)))
    out["low_slot_share"] = [round(float(v), 4) for v in slots / slots.sum()]

    # low-band onsets (40-120 Hz) with a band-tuned picker, by grid position
    on, _pk, _h = pick_onsets(envbp ** 2, fs, delta=0.30, wait_ms=90.0, lookback_ms=40.0)
    t_on = on / fs
    _i, ph, ok = beat_phase(t_on, bt)
    ph = ph[ok & (t_on > 0.05) & (t_on < dur - 0.05)]

    def dist(p, c):
        return np.abs(((p - c + 0.5) % 1.0) - 0.5)

    nb = len(beats)
    out["low_onsets_per_beat"] = float(len(ph) / nb)
    out["low_onbeat_per_beat"] = float((dist(ph, 0.0) <= 0.10).sum() / nb)
    out["low_offbeat_per_beat"] = float((dist(ph, 0.5) <= 0.10).sum() / nb)
    out["low_between_per_beat"] = float((dist(ph, 0.0) > 0.10).sum() / nb)
    # event-based decay: T20 of every low-band onset, censored at the next low onset
    sel = ok & (t_on > 0.05) & (t_on < dur - 0.05)
    ev_t20, _ev_t10 = _decay_t20(envbp ** 2, _pk, fs, cap_ms=1000.0, guard_ms=10.0)
    ev = ev_t20[sel]
    is_on = dist(ph, 0.0) <= 0.10
    fin = np.isfinite(ev)
    out["kick_t20_ms"] = float(np.median(ev[fin & is_on])) if (fin & is_on).sum() >= 8 else None
    out["bassnote_t20_ms"] = float(np.median(ev[fin & ~is_on])) if (fin & ~is_on).sum() >= 8 else None
    out["lowevent_t20_ms"] = float(np.median(ev[fin])) if fin.sum() >= 8 else None

    # (a) fundamental: between-kick segments [0.45T, 0.95T], on-beat segments [0.05T, 0.40T]
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
    rms_off = db((so ** 2).mean(1))
    keep = rms_off >= np.percentile(rms_off, 95) - 20.0
    out["f0_seg_share"] = float(keep.mean())
    band, fb = _spec_band(so[keep], fs)
    dom, low = np.array([_strong_peaks(r, fb) for r in band]).T
    acf = _acf_f0(so[keep], fs)
    mean_dom, mean_low = _strong_peaks(band.mean(0), fb)
    kband, _ = _spec_band(sk, fs)
    k_dom, k_low = _strong_peaks(kband.mean(0), fb)
    f0 = float(np.nanmedian(low))
    out["bass_f0_hz"] = f0
    out["bass_f0_dom_hz"] = float(np.nanmedian(dom))
    out["bass_f0_acf_hz"] = float(np.nanmedian(acf))
    out["bass_f0_meanspec_hz"] = float(mean_low)
    out["bass_f0_meanspec_dom_hz"] = float(mean_dom)
    out["kick_f0_hz"] = float(k_low)
    out["kick_f0_dom_hz"] = float(k_dom)
    st = 12 * np.log2(low[np.isfinite(low)] / f0)
    out["bass_f0_iqr_st"] = float(np.subtract(*np.percentile(st, [75, 25])))
    out["bass_f0_within1st_share"] = float((np.abs(st) <= 1.0).mean())
    name, pc, cents = note_of(f0)
    out["bass_note"], out["bass_pc"], out["bass_cents"] = name, pc, cents
    out["kick_note"] = note_of(k_low)[0]
    return out


# ----------------------------------------------------------------------------- W4 / W5 hats
def _decay_t20(e, pk, fs, cap_ms=400.0, guard_ms=6.0):
    """T20 (ms) per onset peak: time until the power envelope is 20 dB below the peak. Censored
    by the next onset: extrapolated linearly in dB when the drop so far is >= 6 dB, else cap."""
    out = np.full(len(pk), np.nan)
    t10 = np.full(len(pk), np.nan)
    cap, guard = int(cap_ms * fs / 1000), int(guard_ms * fs / 1000)
    for j, p in enumerate(pk):
        a0 = max(0, p - int(0.008 * fs))
        a = a0 + int(np.argmax(e[a0 : p + int(0.010 * fs) + 1]))
        end = min(a + cap, len(e) - 1)
        if j + 1 < len(pk):
            end = min(end, pk[j + 1] - guard)
        if end - a < int(0.012 * fs):
            continue
        seg = db(e[a : end + 1], 1e-16) - db(e[a], 1e-16)
        b20 = np.nonzero(seg <= -20.0)[0]
        b10 = np.nonzero(seg <= -10.0)[0]
        if len(b10):
            t10[j] = b10[0] / fs * 1000.0
        if len(b20):
            out[j] = b20[0] / fs * 1000.0
        else:
            k = int(np.argmin(seg))
            out[j] = min(cap_ms, k / fs * 1000.0 * 20.0 / -seg[k]) if seg[k] <= -6.0 else cap_ms
    return out, t10


PICK_SMOOTH_MS = 10.0     # label-free tuning (tune_hats.py): 10 ms / delta 0.25 -> median
PICK_DELTA = 0.25         # spurious share 11 % (5 ms: 44 %) at the best on-lattice yield


def hat_onsets(y, sos, delta=PICK_DELTA):
    """Returns (fine 5 ms envelope for decays, 10 ms pick envelope, onset idx, peak idx)."""
    x = sg.sosfiltfilt(sos, y)
    e_fine = env_power(x, smooth_ms=5.0)
    e_pick = env_power(x, smooth_ms=PICK_SMOOTH_MS)
    on, pk, _strength = pick_onsets(e_pick, FS_ENV, delta=delta)
    return e_fine, e_pick, on, pk


def flux_profile(e_pick, bt, bn, dur):
    """Threshold-free variant: positive rise of the log-compressed envelope, by grid position."""
    _nov, lg = novelty(e_pick, FS_ENV)
    dl = np.maximum(np.diff(lg, prepend=lg[0]), 0.0)
    t = np.arange(len(dl)) / FS_ENV
    ii, ph, ok = beat_phase(t, bt)
    ok &= (t >= 0.05) & (t <= dur - 0.05)
    nb = int(((bt >= 0.05) & (bt <= dur - 0.05)).sum())
    tot = float(dl[ok].sum())
    if nb < 16 or tot <= 0:
        return {}, None
    p, w = ph[ok], dl[ok]

    def share(*centers):
        m = np.zeros(len(p), dtype=bool)
        for c in centers:
            m |= np.abs(((p - c + 0.5) % 1.0) - 0.5) <= TOL
        return float(w[m].sum() / tot), m

    s_on, m1 = share(0.0)
    s_off, m2 = share(0.5)
    s_16, m3 = share(0.25, 0.75)
    s_tri, m4 = share(1 / 3, 2 / 3)
    out = {"flux_per_beat": tot / nb, "flux_on": s_on, "flux_off": s_off, "flux_16": s_16,
           "flux_tri": s_tri, "flux_other": float(w[~(m1 | m2 | m3 | m4)].sum() / tot)}
    step = ((bn[ii[ok]] - 1) * 4 + np.round(p * 4).astype(int)) % 16
    hist = np.bincount(step, weights=w, minlength=16) / (nb / 4.0)
    return out, hist


def hat_features(e, on, pk, bt, bn, dur):
    """W4 scalars + W5 16-step histogram for one band envelope and its onsets."""
    out: dict = {}
    t = on / FS_ENV
    ii, ph, ok = beat_phase(t, bt)
    ok &= (t >= 0.05) & (t <= dur - 0.05)
    nb = int(((bt >= 0.05) & (bt <= dur - 0.05)).sum())
    out["n_onsets"] = int(ok.sum())
    out["n_beats"] = nb
    if nb < 16:
        return out, None
    out["hats_per_beat"] = float(ok.sum() / nb)
    if ok.sum() < 8:
        return out, np.zeros(16)
    p = ph[ok]

    def dist(c):
        return np.abs(((p - c + 0.5) % 1.0) - 0.5)

    on_b = dist(0.0) <= TOL
    off_b = dist(0.5) <= TOL
    six = (dist(0.25) <= TOL) | (dist(0.75) <= TOL)
    tri = (dist(1 / 3) <= TOL) | (dist(2 / 3) <= TOL)
    other = ~(on_b | off_b | six | tri)
    n = len(p)
    out["onbeat_share"] = float(on_b.sum() / n)
    out["offbeat_share"] = float(off_b.sum() / n)
    out["sixteenth_share"] = float(six.sum() / n)
    out["triplet_share"] = float(tri.sum() / n)
    out["other_share"] = float(other.sum() / n)
    out["hats_per_beat_nonbeat"] = float((~on_b).sum() / nb)
    out["offbeat_per_beat"] = float(off_b.sum() / nb)
    out["sixteenth_per_beat"] = float(six.sum() / nb)
    r16 = ((p * 4 + 0.5) % 1.0) - 0.5
    T = bt[ii[ok] + 1] - bt[ii[ok]]
    out["lattice16_absdev_ms"] = float(np.median(np.abs(r16) / 4 * T) * 1000.0)
    out["lattice16_signed_ms"] = float(np.median(r16 / 4 * T) * 1000.0)
    t20, t10 = _decay_t20(e, pk, FS_ENV)
    t20o = t20[ok]
    fin = np.isfinite(t20o)
    out["hat_decay_ms"] = float(np.median(t20o[fin])) if fin.any() else None
    out["hat_open_share"] = float((t20o[fin] > 120.0).mean()) if fin.any() else None
    t10o = t10[ok]
    out["hat_t10_ms"] = float(np.nanmedian(t10o)) if np.isfinite(t10o).any() else None
    o2 = off_b & fin
    out["open_share_offbeat"] = float((t20o[o2] > 120.0).mean()) if o2.sum() >= 8 else None
    step = ((bn[ii[ok]] - 1) * 4 + np.round(p * 4).astype(int)) % 16
    hist = np.bincount(step, minlength=16).astype(float) / (nb / 4.0)
    return out, hist


# ----------------------------------------------------------------------------- hpss + W6
def hpss_block(y):
    S = np.abs(librosa.stft(y, n_fft=N_FFT, hop_length=HOP)).astype(np.float32)
    H, P = librosa.decompose.hpss(S, kernel_size=31, power=2.0, mask=False)
    return S, H, P


def hpss_shares(H, P):
    f = librosa.fft_frequencies(sr=SR, n_fft=N_FFT)
    eh, ep = (H.astype(np.float64) ** 2).sum(1), (P.astype(np.float64) ** 2).sum(1)
    tot = float(eh.sum() + ep.sum())
    out = {}
    for name, m in (("7k", f >= 7000), ("5_12k", (f >= 5000) & (f < 12000))):
        out[f"perc_share_{name}_db"] = float(db(ep[m].sum() / tot))
        out[f"perc_frac_{name}"] = float(ep[m].sum() / (ep[m].sum() + eh[m].sum()))
    mid = (f >= 300) & (f <= 5000)
    out["hpr_mid_db"] = float(db(eh[mid].sum() / ep[mid].sum()))
    out["hpr_full_db"] = float(db(eh.sum() / ep.sum()))
    return out


_SAL_CACHE: dict = {}


def _salience_matrix():
    if "w" in _SAL_CACHE:
        return _SAL_CACHE["w"], _SAL_CACHE["midi"], _SAL_CACHE["rows"]
    f = librosa.fft_frequencies(sr=SR, n_fft=N_FFT)
    rows = np.nonzero((f >= 300) & (f <= 5000))[0]
    midi = np.arange(62, 97)
    w = np.zeros((len(midi), len(rows)), dtype=np.float32)
    for a, m in enumerate(midi):
        f0 = 440.0 * 2 ** ((m - 69) / 12)
        for h, wt in enumerate((1.0, 0.6, 0.4, 0.3), start=1):
            fh = f0 * h
            if fh > 5000:
                break
            k = int(round(fh / (SR / N_FFT))) - rows[0]
            if 0 <= k < len(rows):
                w[a, k] += wt
    _SAL_CACHE.update(w=w, midi=midi, rows=rows)
    return w, midi, rows


def melody_block(S, H, n_beats):
    """W6 descriptors, all on the 300 Hz - 5 kHz band of one STFT (4096 / 1024)."""
    out: dict = {}
    w, midi, rows = _salience_matrix()
    Hm = H[rows].astype(np.float32)
    Sm = S[rows].astype(np.float32)
    frame_e = db((Hm.astype(np.float64) ** 2).sum(0))
    act = frame_e >= np.percentile(frame_e, 95) - 30.0
    out["mid_active_share"] = float(act.mean())
    Hband = np.zeros_like(H)
    Hband[rows] = Hm
    chroma = librosa.feature.chroma_stft(
        S=Hband ** 2, sr=SR, n_fft=N_FFT, hop_length=HOP, tuning=0.0, norm=None
    )
    p = chroma / (chroma.sum(0, keepdims=True) + 1e-20)
    ent = -(p * np.log(p + 1e-20)).sum(0) / np.log(12.0)
    out["chroma_entropy"] = float(np.median(ent[act]))
    sal = w @ Hm
    top = sal.argmax(0)
    ratio = sal.max(0) / (sal.mean(0) + 1e-12)
    out["pitch_salience"] = float(np.median(ratio[act]))
    out["pitch_salience_p90"] = float(np.percentile(ratio[act], 90))
    secs = S.shape[1] * HOP / SR
    for thr in (3.0, 4.5, 6.0):
        voiced = act & (ratio >= thr)
        pc = np.where(voiced, midi[top] % 12, -1)
        edges = np.nonzero(np.diff(pc) != 0)[0] + 1
        starts = np.concatenate(([0], edges))
        ends = np.concatenate((edges, [len(pc)]))
        notes = [(s, e, pc[s]) for s, e in zip(starts, ends) if pc[s] >= 0 and e - s >= 3]
        changes = sum(1 for a, b in zip(notes, notes[1:]) if b[2] != a[2] and b[0] - a[1] <= 12)
        tag = f"_t{int(thr * 10)}"
        out["voiced_share" + tag] = float(voiced.mean())
        out["note_changes_per_beat" + tag] = float(changes / n_beats) if n_beats else None
        out["notes_per_beat" + tag] = float(len(notes) / n_beats) if n_beats else None
        if thr == 4.5:
            keep_notes = notes
            out["note_changes_per_s"] = float(changes / secs)
    notes = keep_notes
    out["n_notes"] = len(notes)
    if notes:
        durs = np.zeros(12)
        for s, e, c in notes:
            durs[c] += e - s
        out["n_pitch_classes"] = int((durs / durs.sum() >= 0.08).sum())
        out["note_len_ms"] = float(np.median([e - s for s, e, _ in notes]) * HOP / SR * 1000)
    else:
        out["n_pitch_classes"], out["note_len_ms"] = 0, None
    P2 = Sm.astype(np.float64) ** 2
    med = ndi.median_filter(Sm, size=(31, 1), mode="nearest").astype(np.float64) ** 2
    locmax = np.zeros_like(P2, dtype=bool)
    locmax[1:-1] = (P2[1:-1] >= P2[:-2]) & (P2[1:-1] >= P2[2:])
    peaks = locmax & (P2 > med * 10 ** 1.2)
    peaks = ndi.binary_dilation(peaks, structure=np.ones((3, 1), dtype=bool))
    share = (P2 * peaks).sum(0) / (P2.sum(0) + 1e-20)
    out["tonal_share_mid"] = float(np.median(share[act]))
    flat = np.exp(np.log(P2 + 1e-20).mean(0)) / (P2.mean(0) + 1e-20)
    out["tonality_db"] = float(-db(np.median(flat[act])))
    d = np.diff(Hm, axis=1)
    flux = np.maximum(d, 0).sum(0) / (Hm[:, 1:].sum(0) + 1e-12)
    out["harm_flux"] = float(np.median(flux[act[1:]]))
    return out
