"""DirectML workaround attempt: rewrite every 1-D Conv / ConvTranspose of htdemucs_core.onnx as a 2-D op with a
(1, k) kernel (Unsqueeze -> Conv2D -> Squeeze). The dilated 1-D Conv in the time-branch DConv diverges on DML.
Run in the torch env (needs `onnx`): python htd_conv1d_to_2d.py <models_dir>"""
import sys
from pathlib import Path

import numpy as np
import onnx
from onnx import helper, numpy_helper

d = Path(sys.argv[1])
m = onnx.load(str(d / "htdemucs_core.onnx"))
g = m.graph
init = {i.name: i for i in g.initializer}
axes = numpy_helper.from_array(np.array([2], dtype=np.int64), "conv2d_axis2")
g.initializer.append(axes)
new_nodes, n_conv = [], 0
for n in g.node:
    if n.op_type in ("Conv", "ConvTranspose") and n.input[1] in init and len(init[n.input[1]].dims) == 3:
        w = numpy_helper.to_array(init[n.input[1]])
        wn = n.input[1] + "_2d"
        if wn not in init:
            t = numpy_helper.from_array(w[:, :, None, :].copy(), wn)
            g.initializer.append(t)
            init[wn] = t
        for a in n.attribute:
            if a.name in ("kernel_shape", "dilations", "strides", "output_padding"):
                v = list(a.ints)
                del a.ints[:]
                a.ints.extend([1 if a.name != "output_padding" else 0] + v)
            elif a.name == "pads":
                v = list(a.ints)
                del a.ints[:]
                a.ints.extend([0, v[0], 0, v[1]])
        xin, yout = n.input[0], n.output[0]
        new_nodes.append(helper.make_node("Unsqueeze", [xin, "conv2d_axis2"], [yout + "_in2d"], name=n.name + "_unsq"))
        n.input[0], n.input[1], n.output[0] = yout + "_in2d", wn, yout + "_out2d"
        new_nodes.append(n)
        new_nodes.append(helper.make_node("Squeeze", [yout + "_out2d", "conv2d_axis2"], [yout], name=n.name + "_sq"))
        n_conv += 1
    else:
        new_nodes.append(n)
del g.node[:]
g.node.extend(new_nodes)
used = {i for n in g.node for i in n.input}
keep = [i for i in g.initializer if i.name in used]
del g.initializer[:]
g.initializer.extend(keep)
del g.value_info[:]
onnx.checker.check_model(m)
out = d / "htdemucs_core_conv2d.onnx"
onnx.save(m, str(out))
print("rewrote", n_conv, "1-D convs ->", out.name, round(out.stat().st_size / 2**20, 1), "MiB")
