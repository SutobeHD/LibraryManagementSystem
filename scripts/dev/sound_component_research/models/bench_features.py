"""Per-stem cheap features after in-memory separation (GPU, default config). No stems written."""
import argparse
import time

import common
from common import PeakRSS, Timer, emit

import librosa
import numpy as np
import scipy.signal as ss
import soxr
import torch

ap = argparse.ArgumentParser()
ap.add_argument("--out", default="results_features.jsonl")
ap.add_argument("--tracks", default="all")
a = ap.parse_args()
SR = common.SR


def timed(fn, *args, **kw):
    w0, c0 = time.perf_counter(), time.process_time()
    r = fn(*args, **kw)
    return r, round(time.perf_counter() - w0, 2), round(time.process_time() - c0, 2)


def sub_share(y, sr, fc=60.0):
    p = np.abs(np.fft.rfft(y)) ** 2
    f = np.fft.rfftfreq(len(y), 1 / sr)
    return float(p[f < fc].sum() / (p.sum() + 1e-20))


def pyin_f0(y, sr, frame_length, hop):
    f0, vflag, vprob = librosa.pyin(y, fmin=30, fmax=200, sr=sr, frame_length=frame_length, hop_length=hop)
    v = f0[vflag]
    return dict(f0_med=round(float(np.median(v)), 1) if len(v) else None,
                voiced=round(float(vflag.mean()), 3), frames=int(len(f0)))


def hats_density(y, sr, bpm, fc=6000.0):
    sos = ss.butter(4, fc, "highpass", fs=sr, output="sos")
    yh = ss.sosfiltfilt(sos, y).astype(np.float32)
    env = librosa.onset.onset_strength(y=yh, sr=sr, hop_length=512)
    on = librosa.onset.onset_detect(onset_envelope=env, sr=sr, hop_length=512)
    beats = len(y) / sr * bpm / 60.0
    return dict(onsets=int(len(on)), per_beat=round(len(on) / beats, 3))


def harmonic_ratio(y, sr):
    y22 = soxr.resample(y, sr, 22050)
    S = np.abs(librosa.stft(y22, n_fft=2048, hop_length=512))
    H, P = librosa.decompose.hpss(S)
    h, p = float((H ** 2).sum()), float((P ** 2).sum())
    return round(h / (h + p + 1e-20), 3)


# numba / JIT warm-up, cold cost reported once
noise = (np.random.randn(22050 * 2) * 0.1).astype(np.float32)
_, cold_a, _ = timed(pyin_f0, noise, 22050, 2048, 512)
_, cold_b, _ = timed(pyin_f0, noise[:8000], 4000, 512, 64)
emit(a.out, dict(kind="pyin_cold_jit", sr22050_s=cold_a, sr4000_s=cold_b))

model = common.get_demucs("htdemucs").to("cuda")
common.separate(model, (np.random.randn(2, SR * 10) * 0.1).astype(np.float32), "cuda")

ids = None if a.tracks == "all" else a.tracks.split(",")
for tr in common.load_tracks(ids):
    wav, _ = common.load_audio(tr["path"])
    dur = wav.shape[1] / SR
    load_before = common.sys_load(0.5)
    with Timer() as tsep:
        stems = common.separate(model, wav, "cuda", shifts=1, overlap=0.25)
    with Timer() as tall, PeakRSS() as r:
        mix = wav.mean(0)
        bass, drums, other = (stems[k].mean(0) for k in ("bass", "drums", "other"))
        # 30 s window where the bass stem is loudest (1 s hop)
        win = 30 * SR
        e = np.add.reduceat(bass ** 2, np.arange(0, len(bass), SR))
        c = np.convolve(e, np.ones(30), "valid")
        t0 = int(np.argmax(c)) * SR
        bw = bass[t0:t0 + win]
        sub, t_sub, _ = timed(sub_share, bass, SR)
        sub_mix = sub_share(mix, SR)
        bass_share = float((bass ** 2).sum() / ((mix ** 2).sum() + 1e-20))
        bw22 = soxr.resample(bw, SR, 22050)
        bw4 = soxr.resample(bw, SR, 4000)
        p22, t_p22, c_p22 = timed(pyin_f0, bw22, 22050, 2048, 512)
        p4, t_p4, c_p4 = timed(pyin_f0, bw4, 4000, 512, 64)
        hd, t_hd, _ = timed(hats_density, drums, SR, float(tr["BPM"]))
        hm, t_hm, _ = timed(hats_density, mix, SR, float(tr["BPM"]))
        hr_o, t_hr, c_hr = timed(harmonic_ratio, other, SR)
        hr_m, _, _ = timed(harmonic_ratio, mix, SR)
    emit(a.out, dict(kind="features", id=tr["ID"], track=common.label(tr), dur=round(dur, 1), bpm=tr["BPM"],
                     sep_wall=round(tsep.wall, 2), win_start_s=t0 // SR,
                     bass_sub_share_lt60=round(sub, 3), mix_sub_share_lt60=round(sub_mix, 3),
                     bass_energy_share_of_mix=round(bass_share, 3), t_sub=t_sub,
                     pyin22=p22, t_pyin22=t_p22, cpu_pyin22=c_p22, pyin4k=p4, t_pyin4k=t_p4, cpu_pyin4k=c_p4,
                     hats_drums=hd, t_hats_drums=t_hd, hats_mix=hm, t_hats_mix=t_hm,
                     hr_other=hr_o, hr_mix=hr_m, t_hr=t_hr, cpu_hr=c_hr,
                     feat_wall_total=round(tall.wall, 2), feat_cpu_total=round(tall.cpu, 2), rss_mb=r.mb,
                     sysload_before=load_before))
    del stems
