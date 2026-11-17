"""Synthetic sanity check for the pickers / classifiers / decay estimators (known truth)."""
import json
import sys
from pathlib import Path

import numpy as np
import scipy.signal as sg

sys.path.insert(0, str(Path(__file__).parent))
import features as F

SR = F.SR
rng = np.random.default_rng(7)


def burst(t20_ms, sos, n=None):
    """Band noise burst whose POWER envelope falls 20 dB in t20_ms."""
    n = n or int(SR * 0.6)
    t = np.arange(n) / SR
    amp = 10 ** (-(20.0 / (t20_ms / 1000.0)) * t / 20.0)   # amplitude: -20 dB power per t20
    x = sg.sosfilt(sos, rng.standard_normal(n)) * amp
    x[: int(0.001 * SR)] *= np.linspace(0, 1, int(0.001 * SR))
    return x


def add(y, x, t):
    i = int(round(t * SR))
    j = min(len(y), i + len(x))
    if i < len(y):
        y[i:j] += x[: j - i]


def make(scn, bpm=150.0, dur=60.0, grid_offset=0.0):
    n = int(dur * SR)
    y = np.zeros(n)
    T = 60.0 / bpm
    beats = np.arange(0.5, dur - 1.0, T)
    sos_hat = sg.butter(4, 8000, "high", fs=SR, output="sos")
    truth = {"hat_times": [], "hat_class": [], "hat_t20": []}
    tk = np.arange(int(0.5 * SR)) / SR
    for bi, b in enumerate(beats):
        # kick: 160 -> 50 Hz sweep, click
        fk = 50 + 110 * np.exp(-tk / 0.02)
        ph = 2 * np.pi * np.cumsum(fk) / SR
        tau = 0.05 if scn != "rumble" else 0.05
        add(y, 0.9 * np.sin(ph) * np.exp(-tk / tau), b)
        add(y, 0.25 * burst(8.0, sos_hat, int(0.03 * SR)), b)
        if scn == "offbeat":
            tb = np.arange(int(0.16 * SR)) / SR
            add(y, 0.7 * np.sin(2 * np.pi * 43.65 * tb) * np.minimum(1, tb / 0.01) * np.exp(-tb / 0.06), b + 0.5 * T)
            for q, ph16 in enumerate((0.25, 0.5, 0.75)):
                is_open = ph16 == 0.5
                t20 = 250.0 if is_open else 40.0
                add(y, (0.20 if is_open else 0.12) * burst(t20, sos_hat), b + ph16 * T)
                truth["hat_times"].append(b + ph16 * T)
                truth["hat_class"].append("off" if is_open else "16")
                truth["hat_t20"].append(t20)
        elif scn == "rumble":
            tb = np.arange(int(T * SR)) / SR
            add(y, 0.55 * np.sin(2 * np.pi * 49.0 * tb) * (0.6 + 0.4 * np.exp(-tb / 0.2)), b)
            add(y, 0.15 * burst(40.0, sos_hat), b + 0.5 * T)
            truth["hat_times"].append(b + 0.5 * T)
            truth["hat_class"].append("off")
            truth["hat_t20"].append(40.0)
        elif scn == "triplet":
            for ph3 in (1 / 3, 2 / 3):
                add(y, 0.15 * burst(40.0, sos_hat), b + ph3 * T)
                truth["hat_times"].append(b + ph3 * T)
                truth["hat_class"].append("tri")
                truth["hat_t20"].append(40.0)
    t = np.arange(n) / SR
    if scn == "offbeat":      # pad: A major chord, static
        for f in (440.0, 554.37, 659.26):
            y += 0.03 * np.sin(2 * np.pi * f * t)
    if scn == "rumble":       # lead arpeggio on 16ths: A4 C5 E5 G5
        notes = [440.0, 523.25, 659.26, 783.99]
        step = T / 4
        k = 0
        for s in np.arange(0.5, dur - 1.0, step):
            tt = np.arange(int(step * SR)) / SR
            f = notes[k % 4]
            add(y, 0.08 * (np.sin(2 * np.pi * f * tt) + 0.5 * np.sin(4 * np.pi * f * tt)) * np.exp(-tt / 0.08), s)
            k += 1
    y += 0.001 * rng.standard_normal(n)
    grid = [[(i % 4) + 1, bpm, (b + grid_offset) * 1000.0] for i, b in enumerate(beats)]
    return (y / np.abs(y).max() * 0.9).astype(np.float32), grid, truth


def run(scn, grid_offset=0.0):
    y, grid, truth = make(scn, grid_offset=grid_offset)
    dur = len(y) / SR
    bt0, bn = F.window_grid(grid, 0.0, dur)
    lag, contrast = F.estimate_lag(y, bt0)
    bt = bt0 + lag
    res = {"scenario": scn, "grid_offset_ms": grid_offset * 1000, "lag_ms": round(lag * 1000, 2), "lag_contrast": round(contrast, 2)}
    b = F.bass_block(y, bt)
    for k in ("bass_f0_hz", "bass_f0_dom_hz", "bass_f0_acf_hz", "kick_f0_hz", "bass_note", "boom_t20_ms", "boom_t10_ms",
              "boom_censored_share", "bass_dip_db", "bass_sustain_ratio", "bass_rerise_share", "bass_between_db",
              "low_onsets_per_beat", "low_onbeat_per_beat", "low_offbeat_per_beat", "kick_t20_ms", "bassnote_t20_ms", "sub60_of_200"):
        res[k] = b.get(k)
    e, e_pick, on, pk = F.hat_onsets(y, F.SOS_HP7K)
    h, hist = F.hat_features(e, on, pk, bt, bn, dur)
    fl, _fh = F.flux_profile(e_pick, bt, bn, dur)
    res.update(fl)
    res.update({k: h.get(k) for k in ("hats_per_beat", "onbeat_share", "offbeat_share", "sixteenth_share", "triplet_share",
                                      "other_share", "hat_decay_ms", "hat_open_share", "open_share_offbeat",
                                      "lattice16_absdev_ms", "lattice16_signed_ms")})
    res["hist16"] = [round(float(v), 2) for v in hist]
    # onset F1 against hat truth + kick clicks (tolerance 15 ms)
    T = 60.0 / 150.0
    true_t = np.sort(np.concatenate([truth["hat_times"], np.arange(0.5, dur - 1.0, T)]))
    det = on / F.FS_ENV
    hit = sum(1 for t in true_t if np.any(np.abs(det - t) <= 0.015))
    tp_det = sum(1 for t in det if np.any(np.abs(true_t - t) <= 0.015))
    prec, rec = tp_det / max(1, len(det)), hit / len(true_t)
    res["onset_precision"], res["onset_recall"] = round(prec, 3), round(rec, 3)
    res["onset_f1"] = round(2 * prec * rec / (prec + rec), 3)
    S, H, P = F.hpss_block(y)
    res.update(F.hpss_shares(H, P))
    m = F.melody_block(S, H, len(bt))
    res.update({k: m[k] for k in ("chroma_entropy", "pitch_salience", "note_changes_per_beat_t45", "voiced_share_t45",
                                  "n_pitch_classes", "tonal_share_mid", "tonality_db", "harm_flux")})
    return res


if __name__ == "__main__":
    out = [run("offbeat"), run("offbeat", grid_offset=0.020), run("rumble"), run("triplet")]
    for r in out:
        print(json.dumps(r, indent=1, default=float))
    json.dump(out, open(Path(__file__).parent / "synth_results.json", "w"), indent=1, default=float)
