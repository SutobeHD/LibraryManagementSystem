"""Marginal cost of the candidate values: (a) everything derived from stored fingerprints, timed on
real stored rows; (b) the pieces of the pass that a few end values lean on, timed on arrays of
realistic shape (64 bars at 140 BPM = 256 beats, 1024 sixteenths, ~1000 hat onsets). One thread,
wall time of repeated calls (process_time ticks at 15.6 ms on Windows).
Usage: cost_probe.py <tmp/sc-rework-a> [out dir]"""
import glob
import json
import os
import sys
import time
from pathlib import Path

for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMBA_NUM_THREADS"):
    os.environ[_k] = "1"

import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import derived_defs as D  # noqa: E402
import features as F  # noqa: E402  (baseline)
import run_sim as RS  # noqa: E402

DATA = Path(sys.argv[1])
rows = []
for f in sorted(glob.glob(str(DATA / "run1" / "sect_shard*.jsonl")))[:3]:
    rows += [json.loads(line) for line in open(f, encoding="utf-8")]
subs = [r["mx"]["all"] for r in rows if r.get("status") == "ok"][:12]
L = []


def bench(name, fn, reps):
    fn()
    t0 = time.perf_counter()
    for _ in range(reps):
        fn()
    ms = (time.perf_counter() - t0) / reps * 1000
    L.append(f"   {name:78s} {ms:8.3f} ms")
    return ms


FP_SCALARS = [
    D.lowflux_share(D.ON4), D.lowflux_share(D.OFF4), D.lowflux_share(D.SIX8), D.lowflux_share(D.OFF4, True), lambda s: D.rep1(D.fp_line_flux(s)),
    lambda s: D.entropy12(D.chroma(s)[1]), D.chroma_step_move, D.hat_tilt, lambda s: D.fp_hat_flux(s)[[4, 12]].sum() / D.fp_hat_flux(s)[D.ON4].sum(),
    lambda s: D.rep1(D.fp_hat_flux(s)), D.hrel_overtones("off", 6), D.hrel_overtones("on", 4), D.kb_interval,
]
L.append("(a) derived from stored fingerprints / stored columns, per track (includes re-parsing the JSON lists):")
bench(f"all {len(FP_SCALARS)} fingerprint-derived scalars for one track", lambda: [[fn(s) for fn in FP_SCALARS] for s in subs[:1]], 200)

rng = np.random.default_rng(0)
fs = F.FS_LOW
tm = 60.0 / 140.0
n16, n_on, n_off = int(0.25 * tm * fs), int(0.35 * tm * fs), int(0.50 * tm * fs)
seg16 = rng.standard_normal((1024, n16))
sk, so = rng.standard_normal((256, n_on)), rng.standard_normal((256, n_off))
band_so, fb = F._spec_band(so, fs)
env = np.abs(rng.standard_normal(int(110 * fs))) + 0.1
y = rng.standard_normal(int(110 * F.SR)) * 0.1
starts = np.sort(rng.integers(5000, len(y) - 5000, 1000))
L.append("(b) pieces of the pass on arrays of realistic shape:")
bench("ACF f0 of 1024 sixteenth segments (needed by: H16 classes / entropy, voiced share)", lambda: RS.acf_f0_strength(seg16), 5)
bench("kick f0: spectra of 256 on-beat segments + one peak pick", lambda: F._strong_peaks(F._spec_band(sk, fs)[0].mean(0), fb), 5)
bench("per-beat bass f0: 256 peak picks on spectra the bass note already needs (within-1-st share, f0 IQR)", lambda: [F._strong_peaks(r, fb) for r in band_so], 5)
bench("low-band onset picking on 110 s (needed by: low onsets per beat)", lambda: F.pick_onsets(env ** 2, fs, delta=0.30, wait_ms=90.0, lookback_ms=40.0), 5)


def pre_frames():
    p = np.abs(np.fft.rfft(RS.seg_stack(y, starts, RS.NFFT_H) * RS.TUKEY, axis=1)) ** 2
    return np.stack([p[:, ix].mean(1) for ix in RS.HB_IDX], axis=1)


bench("24-band spectra of 1000 frames BEFORE the onsets (needed by: onset contrast; harness control)", pre_frames, 5)
L.append("   reference: the 0.99 CPU-s core set measured in rework A (eval_sections.txt section 6) already runs every piece listed under (b)")
print("\n".join(L))
if len(sys.argv) > 2:
    (Path(sys.argv[2]) / "cost_probe.txt").write_text("\n".join(L) + "\n", encoding="utf-8")
