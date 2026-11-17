"""Probe 2 extraction: 4 x 30 s windows -> htdemucs (GPU, shifts 0, overlap 0.1) -> basic-pitch
ONNX notes per stem variant + CLAP window embeddings + stem energy shares.

Outputs (tmp/sc-rework-m, gitignored): notes.jsonl (note events, numbers only), clap/<id>.npy
(float16 (2, 12, 512): mix, other). Stems are never written. Resumable: finished ids are skipped.

Run order: build_pairs.py + build_samples.py (project venv) -> extract.py -> analyze_melody.py ->
analyze_w6.py -> fewshot_clap.py; time_windows.py for the whole-track comparison (torch env).
Measured on an RTX 2070 SUPER (8 GB): one process 11 jobs / min; two processes via --part filled
the VRAM (7.9 GB) and dropped to 8 jobs / min -> run one process.
"""

import argparse
import json
import time

import mcommon as M
import numpy as np
import soxr
import torch

ap = argparse.ArgumentParser()
ap.add_argument("--limit", type=int, default=0)
ap.add_argument("--sets", default="pair,distract,syn,tag,neg,genre,folder")
ap.add_argument("--no-clap", action="store_true")
ap.add_argument("--part", default="0/1", help="i/n: take every n-th job starting at i (parallel processes)")
ap.add_argument("--no-lock", action="store_true", help="the caller holds tmp/gpu.lock")
a = ap.parse_args()

S = M.load_samples()
META = M.load_meta()
PART_I, PART_N = (int(x) for x in a.part.split("/"))
NOTES = M.OUT / ("notes.jsonl" if PART_N == 1 else f"notes_part{PART_I}.jsonl")
CLAP_DIR = M.OUT / "clap"
CLAP_DIR.mkdir(exist_ok=True)
SYN_SHIFTS = (2, -3)  # semitones; resampling = tempo and pitch move together ("sped up" / "slowed")
N_SYN = 20
STEMS = ("drums", "bass", "other", "vocals")
BP_SR = 22050
CSR, CWIN = 48000, 480000

done = set()
for f in M.OUT.glob("notes*.jsonl"):
    with open(f, encoding="utf-8") as fh:
        done |= {r["id"] for r in map(json.loads, fh) if "notes" in r}

jobs = []  # (job id, track id, semitone shift, variants)
ALL4 = ("other", "vocals", "ov", "mix")
sets = S["sets"]
want = a.sets.split(",")
if "pair" in want:
    jobs += [(i, i, 0, ALL4) for i in sets["pair"]]
if "distract" in want:
    jobs += [(i, i, 0, ALL4) for i in sets["distract"]]
if "syn" in want:
    jobs += [(f"syn:{i}:{k:+d}", i, k, ALL4) for i in sets["distract"][:N_SYN] for k in SYN_SHIFTS]
for name, ids in sets.items():
    if name.split("_")[0] in want and name.split("_")[0] in ("tag", "neg", "genre", "folder"):
        jobs += [(i, i, 0, ("other", "mix")) for i in ids]
seen, uniq = set(), []
for j in jobs:
    if j[0] not in seen:
        seen.add(j[0])
        uniq.append(j)
uniq = [j for n, j in enumerate(uniq) if n % PART_N == PART_I and j[0] not in done]
jobs = uniq[: a.limit] if a.limit else uniq
print(f"jobs {len(jobs)} (done before: {len(done)})", flush=True)

import basic_pitch  # noqa: E402
import basic_pitch.inference as inf  # noqa: E402
from basic_pitch import note_creation as infer  # noqa: E402

bp_model = inf.Model(basic_pitch.ICASSP_2022_MODEL_PATH)
_buf = {}
inf.librosa.load = lambda path, sr=BP_SR, mono=True: (_buf["y"], sr)


def transcribe(y44_mono):
    """-> [[start_s, end_s, midi, amp*100, bend_range]], onset 0.5 / frame 0.3 / min length 5 frames (58 ms)."""
    _buf["y"] = soxr.resample(y44_mono, M.SR, BP_SR).astype(np.float32)
    out = inf.run_inference("in-memory", bp_model)
    _midi, notes = infer.model_output_to_notes(out, onset_thresh=0.5, frame_thresh=0.3, min_note_len=5)
    return [[round(float(s), 3), round(float(e), 3), int(p), round(float(amp) * 100), int(max(b) - min(b)) if b else 0]
            for s, e, p, amp, b in notes]


if not a.no_lock:
    M.gpu_lock_acquire("melody-extract")
dm = M.get_demucs("htdemucs").to("cuda")
clap = proc = None
if not a.no_clap:
    from transformers import ClapModel, ClapProcessor

    proc = ClapProcessor.from_pretrained("laion/clap-htsat-unfused")
    clap = ClapModel.from_pretrained("laion/clap-htsat-unfused").eval().to("cuda")
M.separate_batch(dm, (np.random.randn(1, 2, M.SR * 10) * 0.1).astype(np.float32))  # warm-up


def clap_embed(sig44_list):
    wins = []
    for y in sig44_list:  # each: mono 30 s @ 44.1k -> 3 x 10 s @ 48k
        z = soxr.resample(y, M.SR, CSR).astype(np.float32)
        wins += [z[i:i + CWIN] for i in range(0, 3 * CWIN, CWIN)]
    wins = [np.pad(w, (0, CWIN - len(w))) for w in wins]
    embs = []
    for i in range(0, len(wins), 24):
        inp = proc(audio=wins[i:i + 24], sampling_rate=CSR, return_tensors="pt")
        inp = {k: v.to("cuda") for k, v in inp.items()}
        with torch.inference_mode():
            o = clap.get_audio_features(**inp)
        e = o if isinstance(o, torch.Tensor) else o.pooler_output
        embs.append(e.float().cpu().numpy())
    torch.cuda.synchronize()
    return np.concatenate(embs)


t_run = time.perf_counter()
try:
    for n, (jid, tid, k, variants) in enumerate(jobs):
        tr = S["tracks"][tid]
        ratio = 2.0 ** (k / 12.0)
        rec = {"id": jid, "tid": tid, "k": k, "wins": tr["wins"], "win_src": tr["win_src"]}
        try:
            t0 = time.perf_counter()
            wav = []
            for s in tr["wins"]:
                y = M.read_window(META[tid]["path"], s, M.WIN_S * ratio)
                if k:
                    y = soxr.resample(y.T, M.SR * ratio, M.SR).T.astype(np.float32)
                n30 = int(M.WIN_S * M.SR)
                y = np.pad(y, ((0, 0), (0, max(0, n30 - y.shape[1]))))[:, :n30]
                wav.append(y)
            wav = np.stack(wav)
            t1 = time.perf_counter()
            stems = M.separate_batch(dm, wav)  # (4 windows, 4 stems, 2, n)
            t2 = time.perf_counter()
            mono = {name: stems[:, STEMS.index(name)].mean(1) for name in STEMS}
            sig = {"other": mono["other"], "vocals": mono["vocals"], "ov": mono["other"] + mono["vocals"],
                   "mix": wav.mean(1)}
            en = np.array([[float(np.mean(mono[s][w] ** 2)) for s in STEMS] for w in range(len(wav))])
            rec["energy"] = [[round(float(x), 4) for x in row] for row in en / (en.sum(1, keepdims=True) + 1e-12)]
            rec["rms_mix"] = [round(float(np.sqrt(np.mean(sig["mix"][w] ** 2))), 4) for w in range(len(wav))]
            c0 = time.process_time()
            rec["notes"] = {v: [transcribe(sig[v][w]) for w in range(len(wav))] for v in variants}
            t3 = time.perf_counter()
            bp_cpu = time.process_time() - c0
            if clap is not None and k == 0:
                e = np.stack([clap_embed(list(sig["mix"])), clap_embed(list(sig["other"]))])
                np.save(CLAP_DIR / f"{tid}.npy", e.astype(np.float16))
            t4 = time.perf_counter()
            rec["t"] = {"decode": round(t1 - t0, 3), "sep": round(t2 - t1, 3), "bp": round(t3 - t2, 3),
                        "bp_runs": 4 * len(variants), "bp_cpu": round(bp_cpu, 2), "clap": round(t4 - t3, 3)}
            del stems, wav, sig, mono
        except Exception as exc:  # one unreadable file must not stop the batch
            rec["error"] = f"{type(exc).__name__}: {exc}"[:120]
        with open(NOTES, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
        if n % 20 == 0:
            print(n, jid, rec.get("t"), rec.get("error"), f"elapsed {time.perf_counter() - t_run:.0f}s", flush=True)
finally:
    if not a.no_lock:
        M.gpu_lock_release()
print(f"done {len(jobs)} jobs in {time.perf_counter() - t_run:.0f}s", flush=True)
