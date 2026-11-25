"""Cost of hpss variants on the middle 120 s (CPU s, process_time) + effect on hpr_mid_db."""
import json, os, sys, time, warnings
from pathlib import Path
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMBA_NUM_THREADS"):
    os.environ[_k] = "1"
warnings.filterwarnings("ignore")
import numpy as np, librosa, psutil, soundfile as sf
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import features as F
sample = json.load(open(HERE / "sample.json", encoding="utf-8"))["tracks"]
picks = [t for t in sample if t["path"].lower().endswith((".aiff", ".wav", ".flac"))][::5][:6]
f = librosa.fft_frequencies(sr=F.SR, n_fft=F.N_FFT)
mid = (f >= 300) & (f <= 5000)
hi = f >= 5000
res = []
librosa.decompose.hpss(np.abs(librosa.stft(np.random.randn(F.SR * 5), n_fft=F.N_FFT, hop_length=F.HOP)))
for t in picks:
    d = sf.info(t["path"]).duration
    y, _ = librosa.load(t["path"], sr=F.SR, mono=True, offset=(d - 120) / 2, duration=120)
    row = {"id": t["id"]}
    c = time.process_time(); S = np.abs(librosa.stft(y, n_fft=F.N_FFT, hop_length=F.HOP)).astype(np.float32); row["stft"] = time.process_time() - c
    c = time.process_time(); H, P = librosa.decompose.hpss(S, kernel_size=31, power=2.0); row["hpss_full"] = time.process_time() - c
    full = 10 * np.log10((H[mid].astype(float) ** 2).sum() / (P[mid].astype(float) ** 2).sum())
    c = time.process_time(); Hm, Pm = librosa.decompose.hpss(S[mid], kernel_size=31, power=2.0); row["hpss_mid_only"] = time.process_time() - c
    row["hpr_mid_full"], row["hpr_mid_bandonly"] = full, 10 * np.log10((Hm.astype(float) ** 2).sum() / (Pm.astype(float) ** 2).sum())
    c = time.process_time(); Hh, Ph = librosa.decompose.hpss(S[hi], kernel_size=31, power=2.0); row["hpss_hi_only"] = time.process_time() - c
    c = time.process_time(); S2 = np.abs(librosa.stft(y, n_fft=2048, hop_length=512)); librosa.decompose.hpss(S2, kernel_size=31, power=2.0); row["stft+hpss_2048_512"] = time.process_time() - c
    row["rss_peak_mb"] = psutil.Process().memory_info().peak_wset / 2 ** 20
    res.append(row); print({k: (round(v, 2) if isinstance(v, float) else v) for k, v in row.items()}, flush=True)
print("median", {k: round(float(np.median([r[k] for r in res])), 2) for k in res[0] if k != "id"})
json.dump(res, open(HERE / "bench_hpss.json", "w"), indent=1)
