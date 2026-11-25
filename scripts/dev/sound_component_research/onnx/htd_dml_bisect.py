"""First tensor where DirectML leaves the CPU result (needs htdemucs_core_debug.onnx from htd_debug_outputs.py)."""
import numpy as np
import onnxruntime as ort
import oc_common as c
import sep_min

wav = np.load(c.WORK / f"mix44_{c.TRACK_IDS[0]}.npy")
seg = np.ascontiguousarray(wav[:, 60 * c.SR:60 * c.SR + sep_min.SEG])
seg = (seg - seg.mean()) / (seg.std() + 1e-8)
z = sep_min._htd_spec(seg)
feeds = {"mix": seg[None], "mag": np.stack([z.real, z.imag], axis=1).reshape(1, 4, z.shape[1], z.shape[2]).astype(np.float32)}
path = str(c.MODELS / "htdemucs_core_debug.onnx")
meta = [l.split("\t") for l in (c.MODELS / "htdemucs_core_debug.txt").read_text().splitlines()]
outs = [m[2] for m in meta]
so = ort.SessionOptions()
so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL
so.enable_mem_pattern = False
bad = 0
step = 40
for i in range(0, len(outs), step):
    part = outs[i:i + step]
    ref = ort.InferenceSession(path, so, providers=["CPUExecutionProvider"]).run(part, feeds)
    got = ort.InferenceSession(path, so, providers=["DmlExecutionProvider", "CPUExecutionProvider"]).run(part, feeds)
    for (op, name, _o), r, g in zip(meta[i:i + step], ref, got):
        rel = float(np.abs(r - g).max() / (np.abs(r).max() + 1e-9))
        if rel > 1e-2:
            c.emit("results_htd_dml_diag.jsonl", dict(kind="htd_dml_first_bad", index=i + meta[i:i + step].index([op, name, _o]),
                   op=op, node=name, shape=list(r.shape), rel_maxdiff=rel, ref_absmax=float(np.abs(r).max()), got_absmax=float(np.abs(g).max())))
            bad += 1
            if bad >= 4:
                raise SystemExit
    if bad:
        break
