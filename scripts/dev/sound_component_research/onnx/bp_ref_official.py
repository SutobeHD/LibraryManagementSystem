"""Reference: official basic_pitch 0.4.0 predict() (ONNX backend) on the dumped windows. Run in the torch env."""
import json
import sys
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort
import basic_pitch
import basic_pitch.inference as inf

work = Path(sys.argv[1])
tag = sys.argv[2] if len(sys.argv) > 2 else "bpwin"
model = inf.Model(basic_pitch.ICASSP_2022_MODEL_PATH)
buf = {}
inf.librosa.load = lambda path, sr=22050, mono=True: (buf["y"], sr)
for f in sorted(work.glob(f"{tag}_*.npy")):
    buf["y"] = np.load(f)
    w0, c0 = time.perf_counter(), time.process_time()
    out, _midi, notes = inf.predict("in-memory", model)
    wall, cpu = time.perf_counter() - w0, time.process_time() - c0
    rec = dict(id=f.stem.split("_", 1)[1], numpy=np.__version__, onnxruntime=ort.__version__, wall=round(wall, 3), cpu=round(cpu, 2),
               frames=int(out["note"].shape[0]),
               notes=[[float(n[0]), float(n[1]), int(n[2]), float(n[3])] for n in notes])
    (work / f"{tag.replace('win', 'ref')}_{rec['id']}.json").write_text(json.dumps(rec))
    np.save(work / f"{tag.replace('win', 'refnote')}_{rec['id']}.npy", out["note"])
    print(rec["id"], len(notes), rec["wall"], rec["cpu"])
