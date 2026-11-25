"""Dump the 44.1 kHz stereo mixes (temporary, tmp/ only) so torch env and onnx env separate identical samples."""
import numpy as np
import oc_common as c

for tr in c.load_tracks():
    y = c.load_audio(tr["path"])
    np.save(c.WORK / f"mix44_{tr['ID']}.npy", y)
    print(tr["ID"], y.shape, round(y.shape[1] / c.SR, 1), "s")
