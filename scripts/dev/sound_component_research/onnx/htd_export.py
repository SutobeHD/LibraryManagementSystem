"""htdemucs (official demucs 4.1.0 weights from dl.fbaipublicfiles.com) -> ONNX core network.
STFT / iSTFT and the complex-as-channels packing stay OUTSIDE the graph (numpy side: htd_min.py).
Graph inputs: mix (1, 2, 343980) waveform segment, mag (1, 4, 2048, 336) = real / imag of the segment spectrogram.
Graph outputs: x (1, 4, 4, 2048, 336) freq branch (complex-as-channels), xt (1, 4, 2, 343980) time branch.
Run in the torch env: python htd_export.py <probe_root> [--skip-export] [--skip-ref]"""
import os
import sys
import time
from pathlib import Path

root = Path(sys.argv[1]).resolve()
bench = root.parent / "sc-bench"
os.environ.setdefault("TORCH_HOME", str(bench / "cache" / "torch"))

import numpy as np
import torch
from einops import rearrange

from demucs import pretrained
from demucs.apply import apply_model


def get_demucs(name="htdemucs"):
    models = pretrained._parse_remote_files(pretrained.REMOTE_ROOT / "files.txt")
    model_repo = pretrained.RemoteRepo(models)
    bag_repo = pretrained.BagOnlyRepo(pretrained.REMOTE_ROOT, model_repo)
    return pretrained.AnyModelRepo(model_repo, bag_repo).get_model(name).eval()


class Core(torch.nn.Module):
    """HTDemucs.forward without _spec / _magnitude / _mask / _ispec (body copied from demucs 4.1.0 htdemucs.py)."""

    def __init__(self, m):
        super().__init__()
        self.m = m

    def forward(self, mix, mag):
        m = self.m
        x = mag
        B, C, Fq, T = x.shape
        mean = x.mean(dim=(1, 2, 3), keepdim=True)
        std = x.std(dim=(1, 2, 3), keepdim=True)
        x = (x - mean) / (1e-5 + std)
        xt = mix
        meant = xt.mean(dim=(1, 2), keepdim=True)
        stdt = xt.std(dim=(1, 2), keepdim=True)
        xt = (xt - meant) / (1e-5 + stdt)
        saved, saved_t, lengths, lengths_t = [], [], [], []
        for idx, encode in enumerate(m.encoder):
            lengths.append(x.shape[-1])
            inject = None
            if idx < len(m.tencoder):
                lengths_t.append(xt.shape[-1])
                tenc = m.tencoder[idx]
                xt = tenc(xt)
                if not tenc.empty:
                    saved_t.append(xt)
                else:
                    inject = xt
            x = encode(x, inject)
            if idx == 0 and m.freq_emb is not None:
                frs = torch.arange(x.shape[-2], device=x.device)
                emb = m.freq_emb(frs).t()[None, :, :, None].expand_as(x)
                x = x + m.freq_emb_scale * emb
            saved.append(x)
        if m.crosstransformer:
            if m.bottom_channels:
                b, c, f, t = x.shape
                x = rearrange(x, "b c f t-> b c (f t)")
                x = m.channel_upsampler(x)
                x = rearrange(x, "b c (f t)-> b c f t", f=f)
                xt = m.channel_upsampler_t(xt)
            x, xt = m.crosstransformer(x, xt)
            if m.bottom_channels:
                x = rearrange(x, "b c f t-> b c (f t)")
                x = m.channel_downsampler(x)
                x = rearrange(x, "b c (f t)-> b c f t", f=f)
                xt = m.channel_downsampler_t(xt)
        for idx, decode in enumerate(m.decoder):
            skip = saved.pop(-1)
            x, pre = decode(x, skip, lengths.pop(-1))
            offset = m.depth - len(m.tdecoder)
            if idx >= offset:
                tdec = m.tdecoder[idx - offset]
                length_t = lengths_t.pop(-1)
                if tdec.empty:
                    pre = pre[:, :, 0]
                    xt, _ = tdec(pre, None, length_t)
                else:
                    skip = saved_t.pop(-1)
                    xt, _ = tdec(xt, skip, length_t)
        S = len(m.sources)
        x = x.view(B, S, -1, Fq, T)
        x = x * std[:, None] + mean[:, None]
        xt = xt.view(B, S, -1, mix.shape[-1])
        xt = xt * stdt[:, None] + meant[:, None]
        return x, xt


bag = get_demucs()
model = bag.models[0]
seg = int(model.segment * model.samplerate)
print("sources", model.sources, "segment samples", seg, "cac", model.cac, "params M",
      round(sum(p.numel() for p in model.parameters()) / 1e6, 2), flush=True)
core = Core(model).eval()
if hasattr(torch.backends, "mha"):
    torch.backends.mha.set_fastpath_enabled(False)

mix = torch.randn(1, 2, seg) * 0.1
with torch.no_grad():
    z = model._spec(mix)
    mag = model._magnitude(z)
    x, xt = core(mix, mag)
    full = model._ispec(model._mask(z, x), seg) + xt
    ref = model(mix)
print("core + outside spec == model.forward: maxdiff", float((full - ref).abs().max()), "mag", tuple(mag.shape), flush=True)

out = root / "models" / "htdemucs_core.onnx"
if "--skip-export" not in sys.argv:
    t0 = time.time()
    try:
        torch.onnx.export(core, (mix, mag), str(out), input_names=["mix", "mag"], output_names=["x", "xt"],
                          opset_version=17, dynamo=False, do_constant_folding=True)
        print("export legacy ok", round(time.time() - t0, 1), "s", round(out.stat().st_size / 2**20, 1), "MiB", flush=True)
    except Exception as e:  # noqa: BLE001 - the failure text is the probe result
        import traceback
        print("LEGACY EXPORT FAILED:", type(e).__name__, str(e)[:1500])
        traceback.print_exc(limit=6)
        t0 = time.time()
        try:
            prog = torch.onnx.export(core, (mix, mag), input_names=["mix", "mag"], output_names=["x", "xt"],
                                     opset_version=18, dynamo=True)
            prog.save(str(out))
            print("export dynamo ok", round(time.time() - t0, 1), "s", round(out.stat().st_size / 2**20, 1), "MiB", flush=True)
        except Exception as e2:  # noqa: BLE001
            print("DYNAMO EXPORT FAILED:", type(e2).__name__, str(e2)[:1500])
            traceback.print_exc(limit=6)
            sys.exit(2)
    import onnx
    from collections import Counter
    mo = onnx.load(str(out), load_external_data=False)
    print("opset", [(o.domain, o.version) for o in mo.opset_import], "nodes", len(mo.graph.node))
    print("ops", dict(Counter(n.op_type for n in mo.graph.node).most_common(45)))
    import onnxruntime as ort
    s = ort.InferenceSession(str(out), providers=["CPUExecutionProvider"])
    ox, oxt = s.run(None, {"mix": mix.numpy(), "mag": mag.numpy()})
    print("ORT", ort.__version__, "vs torch core: maxdiff x", float(np.abs(ox - x.numpy()).max()), "xt", float(np.abs(oxt - xt.numpy()).max()), flush=True)

if "--skip-ref" not in sys.argv:
    free = torch.cuda.mem_get_info()[0] / 2**30 if torch.cuda.is_available() else 0
    dev = "cuda" if free > 3.5 else "cpu"
    torch.set_num_threads(16)
    bag.to(dev)
    print("reference device", dev, "free VRAM GiB", round(free, 1), flush=True)
    for f in sorted((root / "work").glob("mix44_*.npy")):
        tid = f.stem.split("_")[1]
        wav = torch.from_numpy(np.load(f))
        r = wav.mean(0)
        mean, std = r.mean(), r.std() + 1e-8
        t0, c0 = time.perf_counter(), time.process_time()
        with torch.no_grad():
            est = apply_model(bag, ((wav - mean) / std)[None], shifts=0, split=True, overlap=0.25, device=dev, progress=False)[0]
        est = (est * std + mean).cpu().numpy().astype(np.float32)
        print(tid, est.shape, dev, "wall", round(time.perf_counter() - t0, 1), "cpu-s", round(time.process_time() - c0, 1), flush=True)
        np.save(root / "work" / f"ref_htd_{tid}.npy", est)
