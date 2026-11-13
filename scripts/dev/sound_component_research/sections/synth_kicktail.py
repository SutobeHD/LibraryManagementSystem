"""Synthetic check of the kick-tail measures in extract.bass_block_m (known truth).
Scenarios at 145 BPM, 60 s: pure kick (short / long tail), kick + side-chained rumble at the kick
pitch, kick + off-beat bass on another note, kick + rolling 16th bass on the kick note, kick +
off-beat bass line with note changes. Usage: synth_kicktail.py"""
import sys
from pathlib import Path

import numpy as np
import scipy.signal as sg

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extract as X

SR = X.SR
rng = np.random.default_rng(11)


def make(scn, bpm=145.0, dur=60.0):
    n = int(dur * SR)
    y = 0.003 * rng.standard_normal(n)
    T = 60.0 / bpm
    beats = np.arange(0.5, dur - 1.0, T)
    tk = np.arange(int(0.9 * T * SR)) / SR
    fk = 50 + 110 * np.exp(-tk / 0.02)
    kick = np.sin(2 * np.pi * np.cumsum(fk) / SR)
    sos = sg.butter(4, [38, 70], "band", fs=SR, output="sos")
    for bi, b in enumerate(beats):
        i = int(round(b * SR))
        y[i : i + len(tk)] += 0.9 * kick * np.exp(-tk / (0.25 if scn == "tail_long" else 0.05))
        if scn == "rumble":  # reverb-like band noise around the kick pitch, ducked on the kick, swelling mid-beat
            nb = int(T * SR)
            env = np.sin(np.pi * np.arange(nb) / nb) ** 2
            y[i : i + nb] += 0.5 * sg.sosfilt(sos, rng.standard_normal(nb)) * env * 6
        notes = {"offbeat": [(0.5, 43.65)], "roll_same": [(0.25, 50.0), (0.5, 50.0), (0.75, 50.0)],
                 "line": [(0.5, (43.65, 49.0, 55.0, 49.0)[bi % 4])]}.get(scn, [])
        for ph, f in notes:
            tb = np.arange(int(0.2 * T * SR)) / SR
            j = int(round((b + ph * T) * SR))
            y[j : j + len(tb)] += 0.6 * np.sin(2 * np.pi * f * tb) * np.minimum(1, tb / 0.008) * np.exp(-tb / 0.05)
    return y, np.append(beats, beats[-1] + T)


print(f"{'scenario':10s} {'rerise':>6s} {'mono':>5s} {'tail_db':>7s} {'betw_db':>7s} {'f0_between':>10s} {'f0_kick':>7s} {'within1st':>9s}")
for scn in ("tail_short", "tail_long", "rumble", "offbeat", "roll_same", "line"):
    y, bt = make(scn)
    o = X.bass_block_m(X.bass_pre(y), bt, list(range(len(bt) - 1)))
    print(f"{scn:10s} {o['bass_rerise_share']:6.2f} {o['mono_share']:5.2f} {o['tail_db']:7.1f} {o['bass_between_db']:7.1f} "
          f"{o['bass_f0_meanspec_hz']:10.1f} {o['kick_f0_hz']:7.1f} {o['bass_f0_within1st_share']:9.2f}")
