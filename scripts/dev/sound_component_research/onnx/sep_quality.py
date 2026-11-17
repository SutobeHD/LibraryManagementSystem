"""Can licence-clean umxhq replace htdemucs for the melody path? `other` stem only.
Pseudo-reference = torch htdemucs `other` (shifts 0, overlap 0.25). Compared: torch umxhq niter 0 (= the ONNX path),
torch umxhq niter 1 (package default, Wiener EM over 4 targets), and the unseparated mix as the floor.
Metrics: SI-SDR vs the pseudo-reference (full track) + basic-pitch note agreement on 4 x 30 s windows."""
import numpy as np
import soxr
import oc_common as c
import bp_min

OUT = "results_quality.jsonl"
FRACS = (0.2, 0.4, 0.6, 0.8)
sess = c.session(c.MODELS / "nmp.onnx", "cpu", 4)


def f1(ref, est, tol=0.05):
    used, hit = set(), 0
    for s, _e, p, _a in est:
        for j, r in enumerate(ref):
            if j not in used and r[2] == p and abs(r[0] - s) <= tol:
                used.add(j)
                hit += 1
                break
    return 2 * hit / max(1, len(ref) + len(est))


def pc_hist(notes):
    h = np.zeros(12)
    for s, e, p, _a in notes:
        h[p % 12] += e - s
    return h


def cos(u, v):
    d = np.linalg.norm(u) * np.linalg.norm(v)
    return float(u @ v / d) if d else None


for tid in c.TRACK_IDS:
    mix = np.load(c.WORK / f"mix44_{tid}.npy")
    src = {"htd": np.load(c.WORK / f"ref_htd_{tid}.npy")[2],
           "umx0": np.load(c.WORK / f"ref_umx0_other_{tid}.npy"),
           "umx1": np.load(c.WORK / f"ref_umx1_other_{tid}.npy"),
           "mix": mix}
    n = mix.shape[1]
    rec = dict(kind="quality", id=tid,
               other_energy_share_htd=round(float((src["htd"] ** 2).sum() / (mix ** 2).sum()), 3),
               **{f"sisdr_{k}_vs_htd": round(c.si_sdr(src["htd"], src[k]), 2) for k in ("umx0", "umx1", "mix")})
    notes = {k: [] for k in src}
    for fr in FRACS:
        s = max(0, int(fr * n) - 15 * c.SR)
        for k, v in src.items():
            y = soxr.resample(v[:, s:s + 30 * c.SR].mean(0), c.SR, 22050).astype(np.float32)
            notes[k].append(bp_min.predict(sess, y, 19))
    for k in src:
        flat = [x for w in notes[k] for x in w]
        rec[f"notes_{k}"] = len(flat)
        rec[f"midi_med_{k}"] = float(np.median([x[2] for x in flat])) if flat else None
    for k in ("umx0", "umx1", "mix"):
        f = [f1(notes["htd"][i], notes[k][i]) for i in range(len(FRACS))]
        pcs = [cos(pc_hist(notes["htd"][i]), pc_hist(notes[k][i])) for i in range(len(FRACS))]
        pcs = [p for p in pcs if p is not None]
        rec[f"note_f1_{k}_vs_htd"] = round(float(np.mean(f)), 3)
        rec[f"pitchclass_cos_{k}_vs_htd"] = round(float(np.mean(pcs)), 3) if pcs else None
    c.emit(OUT, rec)
