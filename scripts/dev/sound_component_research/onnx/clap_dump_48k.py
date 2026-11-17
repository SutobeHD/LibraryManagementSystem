"""Dump the 48 kHz mono mix of the 6 tracks (temporary, tmp/ only) so torch env and onnx env embed identical samples."""
import numpy as np
import soxr
import oc_common as c

for tr in c.load_tracks():
    y = soxr.resample(c.load_audio(tr["path"]).mean(0), c.SR, 48000).astype(np.float32)
    np.save(c.WORK / f"clap48_{tr['ID']}.npy", y)
    print(tr["ID"], y.shape)
