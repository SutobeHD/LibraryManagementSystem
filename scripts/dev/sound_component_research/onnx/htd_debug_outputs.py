"""Add intermediate tensors as graph outputs (torch env has `onnx`): python htd_debug_outputs.py <models_dir>."""
import sys
from pathlib import Path

import onnx

d = Path(sys.argv[1])
m = onnx.load(str(d / "htdemucs_core.onnx"))
m = onnx.shape_inference.infer_shapes(m)
vi = {v.name: v for v in m.graph.value_info}
keep = {"InstanceNormalization", "Conv", "ConvTranspose", "ReduceMean", "LayerNormalization", "Sqrt", "Div", "Softmax", "Gemm", "Erf", "Pad"}
names = []
for n in m.graph.node:
    if n.op_type in keep and n.output[0] in vi:
        m.graph.output.append(vi[n.output[0]])
        names.append((n.op_type, n.name, n.output[0]))
onnx.save(m, str(d / "htdemucs_core_debug.onnx"))
(d / "htdemucs_core_debug.txt").write_text("\n".join("\t".join(x) for x in names))
print("debug outputs:", len(names))
