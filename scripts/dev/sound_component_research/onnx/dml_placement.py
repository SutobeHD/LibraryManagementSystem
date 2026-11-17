"""Count how many graph nodes DirectML takes vs CPU fallback (verbose session log parsed from stderr).

Usage: python dml_placement.py <model.onnx>   (run in the onnxruntime-directml env)
"""
import re
import subprocess
import sys

if len(sys.argv) > 2 and sys.argv[2] == "child":
    import onnxruntime as ort
    so = ort.SessionOptions()
    so.log_severity_level = 0
    so.enable_mem_pattern = False
    ort.InferenceSession(sys.argv[1], so, providers=["DmlExecutionProvider", "CPUExecutionProvider"])
    sys.exit(0)

p = subprocess.run([sys.executable, __file__, sys.argv[1], "child"], capture_output=True)
log = (p.stderr + p.stdout).replace(bytes([0]), b"").decode("utf-8", "replace")
ops, counts, sect = {}, {}, None
for line in log.splitlines():
    m = re.search(r"placed on \[(\w+)\]\. Number of nodes: (\d+)", line)
    if m:
        sect = m.group(1)
        counts[sect] = int(m.group(2))
        continue
    m = re.match(r"\s+(\w+) \(", line)
    if m and sect:
        ops.setdefault(sect, {})
        ops[sect][m.group(1)] = ops[sect].get(m.group(1), 0) + 1
print("nodes per provider:", counts)
for prov, d in ops.items():
    print(prov, "op types:", dict(sorted(d.items(), key=lambda kv: -kv[1])[:25]))
if not counts:
    print(log[-2500:])
