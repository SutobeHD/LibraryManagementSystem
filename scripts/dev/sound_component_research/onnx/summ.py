"""Summarise a results JSONL: median of numeric fields grouped by the config keys."""
import json
import statistics as st
import sys
from collections import defaultdict

path, kind = sys.argv[1], sys.argv[2]
keys = sys.argv[3].split(",")
fields = sys.argv[4].split(",")
g = defaultdict(list)
for line in open(path, encoding="utf-8"):
    r = json.loads(line)
    if r.get("kind") == kind:
        g[tuple(r.get(k) for k in keys)].append(r)
for k, rows in g.items():
    out = []
    for f in fields:
        op, name = f.split(":") if ":" in f else ("med", f)
        vals = [r[name] for r in rows if r.get(name) is not None]
        if not vals:
            out.append(f"{name}=-")
            continue
        v = {"med": st.median, "min": min, "max": max, "sum": sum}[op](vals)
        out.append(f"{op}:{name}={v:.4g}")
    print(dict(zip(keys, k)), "n=%d" % len(rows), " ".join(out))
