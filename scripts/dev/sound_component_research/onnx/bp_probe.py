"""basic-pitch nmp.onnx with the minimal pre/post (bp_min) vs the official package output. CPU or DirectML."""
import argparse
import json

import numpy as np
import oc_common as c
import bp_min

ap = argparse.ArgumentParser()
ap.add_argument("--provider", default="cpu")
ap.add_argument("--threads", type=int, default=0)
ap.add_argument("--batch", type=int, default=1)
ap.add_argument("--tag", default="bpwin")
ap.add_argument("--out", default="results_bp.jsonl")
a = ap.parse_args()


def match(ref, est, tol=0.05):
    """Greedy note match: same MIDI pitch, onset within tol s. -> F1."""
    used, hit = set(), 0
    for s, _e, p, _a in est:
        for j, r in enumerate(ref):
            if j not in used and r[2] == p and abs(r[0] - s) <= tol:
                used.add(j)
                hit += 1
                break
    return 2 * hit / max(1, len(ref) + len(est))


sess = c.session(c.MODELS / "nmp.onnx", a.provider, a.threads)
c.emit(a.out, dict(kind="bp_env", provider=a.provider, used=sess.get_providers(), threads=a.threads, batch=a.batch, **c.env_info()))
warm = np.zeros(22050 * 4, np.float32)
bp_min.predict(sess, warm + 1e-3, a.batch)
for f in sorted(c.WORK.glob(f"{a.tag}_*.npy")):
    tid = f.stem.split("_", 1)[1]
    y = np.load(f)
    ref = json.loads((c.WORK / f"{a.tag.replace('win', 'ref')}_{tid}.json").read_text())
    ref_note = np.load(c.WORK / f"{a.tag.replace('win', 'refnote')}_{tid}.npy")
    gu = c.gpu_wait() if a.provider == "dml" else (None, None, 0)
    load = c.sys_load()
    with c.Timer() as tm:
        frames, onsets = bp_min.run_model(sess, y, a.batch)
    with c.Timer() as tp:
        notes = bp_min.to_notes(frames, onsets)
    rn, en = ref["notes"], notes
    c.emit(a.out, dict(kind="bp", tag=a.tag, provider=a.provider, threads=a.threads, batch=a.batch, id=tid,
                       model_wall=round(tm.wall, 3), model_cpu=round(tm.cpu, 2), post_wall=round(tp.wall, 3),
                       wall=round(tm.wall + tp.wall, 3), cpu=round(tm.cpu + tp.cpu, 2),
                       notes=len(en), notes_ref=len(rn),
                       midi_med=float(np.median([n[2] for n in en])) if en else None,
                       midi_med_ref=float(np.median([n[2] for n in rn])) if rn else None,
                       f1=round(match(rn, en), 4), act_maxdiff=float(np.abs(frames - ref_note).max()),
                       sysload_before=load, ref_wall=ref["wall"], ref_cpu=ref["cpu"], gpu_util_before=gu[0], gpu_mem_before=gu[1]))
