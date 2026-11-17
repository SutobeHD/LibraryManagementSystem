"""Export the CLAP audio tower (+ projection) of laion/clap-htsat-unfused to ONNX and write torch reference
features / embeddings. Run in the torch env:
  python clap_export.py <probe_root> [--skip-export]      dynamic-batch fp32 (+ fp16 attempts) + references
  python clap_export.py <probe_root> --static-batch 8     static-shape variant for DirectML (no Shape/Gather chains)"""
import os
import sys
import time
from pathlib import Path

root = Path(sys.argv[1]).resolve()
os.environ.setdefault("HF_HOME", str(root.parent / "sc-bench" / "cache" / "hf"))
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

import numpy as np
import torch
from transformers import ClapModel, ClapProcessor

NAME = "laion/clap-htsat-unfused"
WIN, CSR = 480000, 48000
out = root / "models" / "clap_audio_fp32.onnx"
proc = ClapProcessor.from_pretrained(NAME)
model = ClapModel.from_pretrained(NAME).eval()


class AudioTower(torch.nn.Module):
    def __init__(self, m):
        super().__init__()
        self.audio_model, self.audio_projection = m.audio_model, m.audio_projection

    def forward(self, input_features):
        pooled = self.audio_model(input_features=input_features, is_longer=None).pooler_output
        return self.audio_projection(pooled)


tower = AudioTower(model).eval()
print("audio tower params M:", round(sum(p.numel() for p in tower.parameters()) / 1e6, 2))
x = torch.randn(2, 1, 1001, 64)
with torch.inference_mode():
    a = tower(x)
    o = model.get_audio_features(input_features=x)
    b = o if isinstance(o, torch.Tensor) else o.pooler_output
print("wrapper == get_audio_features:", float((a - b).abs().max()), "norm of output:", float(b.norm(dim=-1).mean()))

if "--static-batch" in sys.argv:
    nb = int(sys.argv[sys.argv.index("--static-batch") + 1])
    ps = root / "models" / f"clap_audio_fp32_b{nb}.onnx"
    torch.onnx.export(tower, (torch.randn(nb, 1, 1001, 64),), str(ps), input_names=["input_features"],
                      output_names=["audio_embeds"], opset_version=17, dynamo=False, do_constant_folding=True)
    import onnx
    print("static batch", nb, round(ps.stat().st_size / 2**20, 1), "MiB", "nodes", len(onnx.load(str(ps)).graph.node))
    sys.exit(0)

if "--fp16-only" in sys.argv:
    import onnx
    from onnxruntime.transformers.float16 import convert_float_to_float16 as conv
    m = onnx.load(str(out))
    for tag, kw in (("ort", dict(keep_io_types=True)),
                    ("ort_block", dict(keep_io_types=True, op_block_list=["Resize", "Range", "Cast", "BatchNormalization"]))):
        try:
            m16 = conv(onnx.load(str(out)), **kw)
            p16 = root / "models" / f"clap_audio_fp16_{tag}.onnx"
            onnx.save(m16, str(p16))
            import onnxruntime as ort
            s = ort.InferenceSession(str(p16), providers=["CPUExecutionProvider"])
            y16 = s.run(None, {"input_features": x.numpy()})[0]
            c = torch.nn.functional.cosine_similarity(torch.from_numpy(y16.astype(np.float32)), a).min()
            print("fp16", tag, "ok", round(p16.stat().st_size / 2**20, 1), "MiB", "cos vs torch (random input)", float(c))
        except Exception as e:  # noqa: BLE001 - the failure text is the probe result
            print("fp16", tag, "FAILED:", type(e).__name__, str(e)[:300])
    sys.exit(0)

if "--skip-export" not in sys.argv:
    t0 = time.time()
    mode = "legacy"
    try:
        torch.onnx.export(tower, (x,), str(out), input_names=["input_features"], output_names=["audio_embeds"],
                          dynamic_axes={"input_features": {0: "batch"}, "audio_embeds": {0: "batch"}},
                          opset_version=17, dynamo=False, do_constant_folding=True)
    except Exception as e:  # noqa: BLE001 - record the exporter failure, then try the dynamo exporter
        print("LEGACY EXPORT FAILED:", type(e).__name__, str(e)[:600])
        mode = "dynamo"
        prog = torch.onnx.export(tower, (x,), input_names=["input_features"], output_names=["audio_embeds"],
                                 dynamic_shapes={"input_features": {0: torch.export.Dim("batch", min=1, max=64)}},
                                 opset_version=18, dynamo=True)
        prog.save(str(out))
    print("export", mode, round(time.time() - t0, 1), "s", round(out.stat().st_size / 2**20, 1), "MiB")
    import onnx
    m = onnx.load(str(out))
    print("opset:", [(o.domain, o.version) for o in m.opset_import], "nodes:", len(m.graph.node))
    from collections import Counter
    print("ops:", dict(Counter(n.op_type for n in m.graph.node).most_common(40)))
    try:
        from onnxconverter_common import float16
        m16 = float16.convert_float_to_float16(m, keep_io_types=True)
        p16 = root / "models" / "clap_audio_fp16.onnx"
        onnx.save(m16, str(p16))
        print("fp16:", round(p16.stat().st_size / 2**20, 1), "MiB")
    except Exception as e:  # noqa: BLE001
        print("FP16 FAILED:", type(e).__name__, str(e)[:400])

# torch reference on the dumped 48 kHz signals
torch.set_num_threads(16)
for f in sorted((root / "work").glob("clap48_*.npy")):
    y = np.load(f)
    wins = [y[i:i + WIN] for i in range(0, len(y), WIN) if len(y[i:i + WIN]) >= CSR]
    np.random.seed(0)
    inp = proc(audio=wins, sampling_rate=CSR, return_tensors="pt")
    feats = inp["input_features"]
    t0, c0 = time.perf_counter(), time.process_time()
    with torch.inference_mode():
        o = model.get_audio_features(**inp)
    emb = (o if isinstance(o, torch.Tensor) else o.pooler_output).float().numpy()
    print(f.stem, feats.shape, emb.shape, "torch cpu forward", round(time.perf_counter() - t0, 2), "s wall",
          round(time.process_time() - c0, 1), "cpu-s", "keys", list(inp.keys()))
    np.savez(root / "work" / f"clapref_{f.stem.split('_')[1]}.npz", feats=feats.numpy(), emb=emb)
