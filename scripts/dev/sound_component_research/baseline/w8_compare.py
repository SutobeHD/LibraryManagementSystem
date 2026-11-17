"""W2b cross-check against the app's own whole-track numbers (audio_w8.jsonl, bass.share_60/120)."""
import json, os, sys, time, warnings
from pathlib import Path
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMBA_NUM_THREADS"):
    os.environ[_k] = "1"
warnings.filterwarnings("ignore")
import numpy as np
import librosa
HERE = Path(__file__).parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(ROOT))
import features as F
from app.analysis_extras import power_spectrum_stats, bass_share

rows = [json.loads(l) for l in open(ROOT / "tmp/library-analysis/measure/audio_w8.jsonl", encoding="utf-8")]
out = open(HERE / "w8_compare.jsonl", "w", encoding="utf-8")
for r in rows:
    p = r["path"]
    if r.get("status") != "ok" or not os.path.isfile(p) or (r.get("duration") or 0) < 180:
        continue
    c0 = time.process_time()
    y, _ = librosa.load(p, sr=F.SR, mono=True)
    y = y.astype(np.float64)
    d = len(y) / F.SR
    a0 = int(max(0.0, (d - 120) / 2) * F.SR)
    ex = y[a0 : a0 + int(120 * F.SR)]
    whole, exc = F.spectrum_shares(y), F.spectrum_shares(ex)
    fa, _m, mp = power_spectrum_stats(ex, F.SR)
    app_ex = bass_share(fa, mp)
    row = {"id": r["id"], "artist": r["artist"], "title": r["title"], "dur": round(d, 1),
           "app_share_60": r["bass"]["share_60"], "app_share_120": r["bass"]["share_120"],
           "whole": whole, "excerpt": exc, "appmethod_excerpt": app_ex, "cpu_s": round(time.process_time() - c0, 2)}
    out.write(json.dumps(row, ensure_ascii=False) + "\n"); out.flush()
    print(r["id"], round(d), row["app_share_60"], round(whole["sub60_of_total"], 4), round(exc["sub60_of_total"], 4), app_ex["share_60"], flush=True)
