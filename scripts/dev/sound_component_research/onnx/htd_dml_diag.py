"""Why does htdemucs_core.onnx diverge on DirectML? One real 7.8 s segment, CPU EP vs DML EP in the same
onnxruntime-directml build, at each graph-optimisation level. Usage: python htd_dml_diag.py [model.onnx]"""
import sys

import numpy as np
import onnxruntime as ort
import oc_common as c
import sep_min

wav = np.load(c.WORK / f"mix44_{c.TRACK_IDS[0]}.npy")
seg = np.ascontiguousarray(wav[:, 60 * c.SR:60 * c.SR + sep_min.SEG])
seg = (seg - seg.mean()) / (seg.std() + 1e-8)
z = sep_min._htd_spec(seg)
feeds = {"mix": seg[None], "mag": np.stack([z.real, z.imag], axis=1).reshape(1, 4, z.shape[1], z.shape[2]).astype(np.float32)}
path = str(c.MODELS / (sys.argv[1] if len(sys.argv) > 1 else "htdemucs_core.onnx"))
ref = ort.InferenceSession(path, providers=["CPUExecutionProvider"]).run(None, feeds)
print("ort", ort.__version__, "cpu ref absmax x/xt", float(np.abs(ref[0]).max()), float(np.abs(ref[1]).max()))
for name, lvl in (("ALL", ort.GraphOptimizationLevel.ORT_ENABLE_ALL), ("BASIC", ort.GraphOptimizationLevel.ORT_ENABLE_BASIC),
                  ("DISABLE", ort.GraphOptimizationLevel.ORT_DISABLE_ALL)):
    so = ort.SessionOptions()
    so.enable_mem_pattern = False
    so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    so.graph_optimization_level = lvl
    try:
        s = ort.InferenceSession(path, so, providers=["DmlExecutionProvider", "CPUExecutionProvider"])
        out = s.run(None, feeds)
        c.emit("results_htd_dml_diag.jsonl", dict(kind="htd_dml_diag", model=sys.argv[1] if len(sys.argv) > 1 else "htdemucs_core.onnx", opt=name, gpu=c.gpu_state(),
               x_maxdiff=float(np.abs(out[0] - ref[0]).max()), xt_maxdiff=float(np.abs(out[1] - ref[1]).max()),
               x_nan=bool(np.isnan(out[0]).any()), xt_nan=bool(np.isnan(out[1]).any()),
               x_absmax=float(np.nanmax(np.abs(out[0]))), xt_absmax=float(np.nanmax(np.abs(out[1]))),
               sisdr_xt=round(c.si_sdr(ref[1], out[1]), 1), sisdr_x=round(c.si_sdr(ref[0], out[0]), 1), **c.env_info()))
    except Exception as e:  # noqa: BLE001 - the failure text is the probe result
        c.emit("results_htd_dml_diag.jsonl", dict(kind="htd_dml_diag", opt=name, error=f"{type(e).__name__}: {str(e)[:500]}"))
