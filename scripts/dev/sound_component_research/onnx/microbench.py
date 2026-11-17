"""Best-case forward time of one ONNX graph: N runs on fixed random input, report min / median (the minimum is robust
against the other agent's GPU / CPU load). Usage: python microbench.py <model> <provider> <iters> name=shape ..."""
import statistics as st
import sys
import time

import numpy as np
import oc_common as c

model, provider, iters = sys.argv[1], sys.argv[2], int(sys.argv[3])
threads = 0
feeds = {}
rs = np.random.RandomState(0)
for spec in sys.argv[4:]:
    k, v = spec.split("=")
    if k == "threads":
        threads = int(v)
        continue
    feeds[k] = (rs.rand(*[int(d) for d in v.split("x")]).astype(np.float32) * 0.1)
sess = c.session(c.MODELS / model, provider, threads)
sess.run(None, feeds)
gu = c.gpu_wait() if provider == "dml" else (None, None, 0)
load = c.sys_load()
wall, cpu = [], []
for _ in range(iters):
    w0, c0 = time.perf_counter(), time.process_time()
    sess.run(None, feeds)
    wall.append(time.perf_counter() - w0)
    cpu.append(time.process_time() - c0)
c.emit("results_microbench.jsonl", dict(kind="micro", model=model, provider=provider, threads=threads, iters=iters,
                                        shapes={k: list(v.shape) for k, v in feeds.items()},
                                        wall_min_ms=round(min(wall) * 1e3, 1), wall_med_ms=round(st.median(wall) * 1e3, 1),
                                        cpu_med_ms=round(st.median(cpu) * 1e3, 1), sysload_before=load,
                                        gpu_util_before=gu[0], gpu_mem_before=gu[1], gpu_waited_s=gu[2], **c.env_info()))
