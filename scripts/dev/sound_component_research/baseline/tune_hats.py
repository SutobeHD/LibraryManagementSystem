"""Label-free tuning of the high-band onset picker.

Idea: electronic music is quantised, so true onsets sit on the 16th / triplet lattice and spurious
ones land uniformly in beat phase. With lattice windows of +-1/24 beat, 'other' covers 12/24 of the
phase circle -> spurious fraction s ~= 2 * other_share. Yield = onsets/beat * (1 - s)."""
import json
import os
import sys
import warnings
from pathlib import Path

for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMBA_NUM_THREADS"):
    os.environ[_k] = "1"
warnings.filterwarnings("ignore")
import numpy as np
import scipy.ndimage as ndi
import scipy.signal as sg
import librosa

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import features as F

sample = json.load(open(HERE / "sample.json", encoding="utf-8"))["tracks"]
want = sys.argv[1].split(",") if len(sys.argv) > 1 else None
picks = [t for t in sample if (want is None or t["id"] in want)]


def env_smooth(x, ms):
    """Power envelope at FS_ENV with a Hann smoother of total length ms."""
    e = ndi.uniform_filter1d(x * x, size=2 * F.DEC_ENV, mode="nearest")[:: F.DEC_ENV]
    n = max(3, int(round(ms * F.FS_ENV / 1000.0)) | 1)
    w = np.hanning(n + 2)[1:-1]
    return np.maximum(np.convolve(e, w / w.sum(), mode="same"), 1e-14)


def shares(t, bt):
    ii, ph, ok = F.beat_phase(t, bt)
    p = ph[ok]
    d = lambda c: np.abs(((p - c + 0.5) % 1.0) - 0.5)
    on, off = d(0.0) <= F.TOL, d(0.5) <= F.TOL
    six = (d(0.25) <= F.TOL) | (d(0.75) <= F.TOL)
    tri = (d(1 / 3) <= F.TOL) | (d(2 / 3) <= F.TOL)
    oth = ~(on | off | six | tri)
    return len(p), on.mean(), off.mean(), six.mean(), tri.mean(), oth.mean(), p


agg = {}
for tr in picks:
    d = float(tr["total_time"])
    try:
        import soundfile as sf
        d = sf.info(tr["path"]).duration
    except Exception:
        pass
    a0 = (d - 120) / 2
    y, _ = librosa.load(tr["path"], sr=F.SR, mono=True, offset=a0, duration=120)
    y = y.astype(np.float64)
    bt0, bn = F.window_grid(tr["grid"], a0, 120.0)
    lag, c = F.estimate_lag(y, bt0)
    bt = bt0 + lag
    nb = ((bt >= 0) & (bt <= 120)).sum()
    x = sg.sosfiltfilt(F.SOS_HP7K, y)
    print(f"== {tr['genre']} {tr['bpm']} {tr['artist']} - {tr['title']}  lag {lag*1000:.1f} ms")
    for sm in (5, 10, 20):
        e = env_smooth(x, sm)
        for lb in (12, 25):
            for delta in (0.15, 0.25, 0.4, 0.6):
                on, pk, st = F.pick_onsets(e, F.FS_ENV, delta=delta, wait_ms=40.0, lookback_ms=lb)
                n, s_on, s_off, s_six, s_tri, s_oth, p = shares(on / F.FS_ENV, bt)
                s = min(1.0, 2 * s_oth)
                key = (sm, lb, delta)
                agg.setdefault(key, []).append((n / nb, s, n / nb * (1 - s)))
                print(f"  sm{sm:2d} lb{lb:2d} d{delta:.2f}  n/beat {n/nb:5.2f}  on {s_on:.2f} off {s_off:.2f} 16th {s_six:.2f} tri {s_tri:.2f} other {s_oth:.2f}  spur~{s:.2f} yield {n/nb*(1-s):.2f}")
                if (sm, lb, delta) == (5, 12, 0.25):
                    h = np.bincount((np.round(p * 24).astype(int)) % 24, minlength=24)
                    print("     phase hist /24:", " ".join(f"{v:3d}" for v in h))
print("\n== mean over tracks: sm lb delta | n/beat | spurious | yield")
for key, v in sorted(agg.items()):
    a = np.array(v)
    print(key, np.round(a.mean(0), 2), " median spur", round(float(np.median(a[:, 1])), 2))
