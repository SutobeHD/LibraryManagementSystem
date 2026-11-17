"""Open-Unmix umxhq: export the four spectrogram models to ONNX (STFT stays outside the graph) and write torch
references (`other` stem, niter 0 and niter 1). Run in the torch env: python umx_export.py <probe_root>.
Weights: official `openunmix` package -> zenodo.org/records/3370489 (torch.hub download)."""
import os
import sys
import time
from pathlib import Path

root = Path(sys.argv[1]).resolve()
os.environ["TORCH_HOME"] = str(root / "cache" / "torch")

import numpy as np
import torch
import openunmix

TARGETS = ["vocals", "drums", "bass", "other"]


class UmxWrap(torch.nn.Module):
    """OpenUnmix.forward (openunmix 1.3.0) with trace-friendly reshapes: the stock forward reads
    `x.data.shape`, which the TorchScript exporter bakes in as constants (frames fixed to the dummy input)."""

    def __init__(self, m):
        super().__init__()
        self.m = m

    def forward(self, x):                     # (1, 2, 2049, frames)
        m = self.m
        x = x.permute(3, 0, 1, 2)
        mix = x
        x = (x[..., : m.nb_bins] + m.input_mean) * m.input_scale
        x = m.bn1(m.fc1(x.reshape(-1, 2 * m.nb_bins)))
        x = torch.tanh(x.reshape(-1, 1, m.hidden_size))
        x = torch.cat([x, m.lstm(x)[0]], -1)
        x = torch.relu(m.bn2(m.fc2(x.reshape(-1, 2 * m.hidden_size))))
        x = m.bn3(m.fc3(x)).reshape(-1, 1, 2, m.nb_output_bins)
        x = torch.relu(x * m.output_scale + m.output_mean) * mix
        return x.permute(1, 2, 3, 0)
specs = openunmix.umxhq_spec(targets=TARGETS, device="cpu", pretrained=True)
if "--skip-export" not in sys.argv:
    import onnxruntime as ort
    x = torch.rand(1, 2, 2049, 64)
    x2 = torch.rand(1, 2, 2049, 301)
    for name, m in specs.items():
        m.eval()
        w = UmxWrap(m).eval()
        out = root / "models" / f"umxhq_{name}.onnx"
        t0 = time.time()
        torch.onnx.export(w, (x,), str(out), input_names=["mag"], output_names=["est"],
                          dynamic_axes={"mag": {3: "frames"}, "est": {3: "frames"}},
                          opset_version=17, dynamo=False, do_constant_folding=True)
        with torch.no_grad():
            ref = m(x2).numpy()
        got = ort.InferenceSession(str(out), providers=["CPUExecutionProvider"]).run(None, {"mag": x2.numpy()})[0]
        print("wrapper ONNX vs stock torch forward, 301 frames: maxdiff", float(np.abs(got - ref).max()))
        print("export", name, round(time.time() - t0, 1), "s", round(out.stat().st_size / 2**20, 1), "MiB",
              "params M", round(sum(p.numel() for p in m.parameters()) / 1e6, 2))

if "--skip-ref" in sys.argv:
    sys.exit(0)
torch.set_num_threads(16)
sep0 = openunmix.umxhq(targets=["other"], niter=0, device="cpu", pretrained=True).eval()
sep1 = openunmix.umxhq(targets=TARGETS, niter=1, device="cpu", pretrained=True).eval()
for f in sorted((root / "work").glob("mix44_*.npy")):
    tid = f.stem.split("_")[1]
    wav = torch.from_numpy(np.load(f))[None]
    for tag, sep, idx in (("umx0", sep0, 0), ("umx1", sep1, TARGETS.index("other"))):
        t0, c0 = time.perf_counter(), time.process_time()
        with torch.inference_mode():
            est = sep(wav)[0, idx].numpy()
        print(tid, tag, est.shape, "torch cpu wall", round(time.perf_counter() - t0, 1), "cpu-s", round(time.process_time() - c0, 1), flush=True)
        np.save(root / "work" / f"ref_{tag}_other_{tid}.npy", est.astype(np.float32))
