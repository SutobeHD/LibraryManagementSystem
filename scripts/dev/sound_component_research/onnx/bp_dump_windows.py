"""Dump the 30 s mix windows (22050 Hz mono) used by the earlier basic-pitch bench, so both envs read identical input."""
import json
import numpy as np
import soxr
import oc_common as c

starts = {}
for line in (c.ROOT.parent / "sc-bench" / "results_basicpitch.jsonl").read_text(encoding="utf-8").splitlines():
    r = json.loads(line)
    if r.get("kind") == "basic_pitch":
        starts[r["id"]] = r["win_start_s"]
for tr in c.load_tracks():
    wav = c.load_audio(tr["path"]).mean(0)
    t0 = starts[tr["ID"]]
    y = soxr.resample(wav[t0 * c.SR:(t0 + 30) * c.SR], c.SR, 22050).astype(np.float32)
    np.save(c.WORK / f"bpwin_{tr['ID']}.npy", y)
    print(tr["ID"], t0, y.shape, float(np.abs(y).max()))
