"""basic-pitch (ONNX backend, CPU) on the `other` stem 30 s window. In memory: librosa.load is patched."""
import time
import common
from common import emit
import numpy as np
import soxr
import basic_pitch
import basic_pitch.inference as inf
import onnxruntime as ort

OUT = "results_basicpitch.jsonl"
SR = common.SR
dm = common.get_demucs("htdemucs").to("cuda")
model = inf.Model(basic_pitch.ICASSP_2022_MODEL_PATH)
emit(OUT, dict(kind="bp_info", onnxruntime=ort.__version__, providers=ort.get_available_providers(),
               tf_present=basic_pitch.TF_PRESENT, onnx_present=basic_pitch.ONNX_PRESENT))
_buf = {}
inf.librosa.load = lambda path, sr=22050, mono=True: (_buf["y"], sr)
for tr in common.load_tracks():
    wav, _ = common.load_audio(tr["path"])
    other = common.separate(dm, wav, "cuda")["other"].mean(0)
    e = np.add.reduceat(other ** 2, np.arange(0, len(other), SR))
    t0 = int(np.argmax(np.convolve(e, np.ones(30), "valid")))
    _buf["y"] = soxr.resample(other[t0 * SR:(t0 + 30) * SR], SR, 22050).astype(np.float32)
    w0, c0 = time.perf_counter(), time.process_time()
    out, midi, notes = inf.predict("in-memory", model)
    wall, cpu = time.perf_counter() - w0, time.process_time() - c0
    pitches = [n[2] for n in notes]
    emit(OUT, dict(kind="basic_pitch", id=tr["ID"], track=common.label(tr), win_start_s=t0, wall=round(wall, 2), cpu=round(cpu, 2),
                   notes=len(notes), notes_per_s=round(len(notes) / 30, 1),
                   midi_med=int(np.median(pitches)) if pitches else None,
                   frames=int(out["note"].shape[0]), sysload_before=common.sys_load(0.3)))
