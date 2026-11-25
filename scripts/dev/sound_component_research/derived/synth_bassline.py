"""Known-truth check of the low-end rhythm and note-movement candidates (no audio files).

Scenarios at 145 BPM, 60 s, kick on every beat (kick model of sections/synth_kicktail.py):
off-beat bass vs rolling 16th bass, one note vs note changes (per beat, inside the beat, every
two bars), kick only, side-chained rumble. The signals run through the unchanged extraction
(sections/extract.py prepare + subset); the derived values come from derived_defs.py.
Usage: synth_bassline.py [out dir]"""
import sys
from pathlib import Path

import numpy as np
import scipy.signal as sg

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import derived_defs as D  # noqa: E402

sys.path.insert(0, str(D.BASE / "sections"))
import extract as EX  # noqa: E402

SR = EX.SR
A1, B1, G1, C2 = 55.0, 61.74, 49.0, 65.41
rng = np.random.default_rng(11)
SCN = {  # name -> function(beat index, bar index) -> [(phase in the beat, f0 Hz)]
    "kick only": lambda bi, bar: [],
    "rumble (side-chained)": lambda bi, bar: [],
    "off-beat, one note": lambda bi, bar: [(0.5, G1)],
    "rolling 16ths, one note": lambda bi, bar: [(0.25, G1), (0.5, G1), (0.75, G1)],
    "off-beat, note per beat (4 notes)": lambda bi, bar: [(0.5, (G1, A1, C2, A1)[bi % 4])],
    "rolling 16ths, note per beat (4)": lambda bi, bar: [(p, (G1, A1, C2, A1)[bi % 4]) for p in (0.25, 0.5, 0.75)],
    "rolling 16ths, 2 notes in the beat": lambda bi, bar: [(0.25, G1), (0.5, C2), (0.75, G1)],
    "off-beat, note change every 2 bars": lambda bi, bar: [(0.5, (G1, B1)[(bar // 2) % 2])],
    "off-beat + 16th pickup (0.5, 0.75)": lambda bi, bar: [(0.5, G1), (0.75, G1)],
}


def make(scn, bpm=145.0, dur=60.0):
    n = int(dur * SR)
    y = 0.003 * rng.standard_normal(n)
    T = 60.0 / bpm
    beats = np.arange(0.5, dur - 1.0, T)
    tk = np.arange(int(0.9 * T * SR)) / SR
    kick = np.sin(2 * np.pi * np.cumsum(50 + 110 * np.exp(-tk / 0.02)) / SR)
    sos = sg.butter(4, [38, 70], "band", fs=SR, output="sos")
    for bi, b in enumerate(beats):
        i = int(round(b * SR))
        y[i: i + len(tk)] += 0.9 * kick * np.exp(-tk / 0.05)
        if scn.startswith("rumble"):
            nb = int(T * SR)
            y[i: i + nb] += 0.5 * sg.sosfilt(sos, rng.standard_normal(nb)) * np.sin(np.pi * np.arange(nb) / nb) ** 2 * 6
        for ph, f in SCN[scn](bi, bi // 4):
            tb = np.arange(int(0.2 * T * SR)) / SR
            j = int(round((b + ph * T) * SR))
            y[j: j + len(tb)] += 0.6 * np.sin(2 * np.pi * f * tb) * np.minimum(1, tb / 0.008) * np.exp(-tb / 0.05)
    bt = np.append(beats, beats[-1] + T)
    return y, bt


def val(fn, s):
    try:
        v = fn(s)
        return float("nan") if v is None else float(v)
    except (KeyError, TypeError, ValueError, IndexError):
        return float("nan")


COLS = [
    ("ons/beat", lambda s: s["w2"]["low_onsets_per_beat"]), ("betw/beat", lambda s: s["w2"]["low_between_per_beat"]),
    ("fl on", D.lowflux_share(D.ON4)), ("fl off8", D.lowflux_share(D.OFF4)), ("fl 16th", D.lowflux_share(D.SIX8)), ("off8/betw", D.lowflux_share(D.OFF4, True)),
    ("rep1", lambda s: D.rep1(D.fp_line_flux(s))), ("within1st", lambda s: s["w2"]["bass_f0_within1st_share"]), ("f0 IQR", lambda s: s["w2"]["bass_f0_iqr_st"]),
    ("H16 n", D.h_n_pc), ("H16 ent", lambda s: D.entropy12(D.h12(s))), ("chr ent", lambda s: D.entropy12(D.chroma(s)[1])), ("chr move", D.chroma_step_move),
    ("kick st", lambda s: D.st_of(s["w2"]["kick_f0_hz"])), ("bass st", lambda s: D.st_of(s["w2"]["bass_f0_meanspec_hz"])), ("tail_db", lambda s: s["w2"]["tail_db"]),
    ("sustain", lambda s: s["w2"]["bass_sustain_ratio"]), ("dip_db", lambda s: s["w2"]["bass_dip_db"]), ("harm", lambda s: s["bass"]["off"]["harm_share"]),
]
lines = [f"{'scenario':36s} " + " ".join(f"{c[0]:>9s}" for c in COLS)]
for scn in SCN:
    y, bt = make(scn)
    nb = len(bt)
    bar = np.where(np.arange(nb) < nb - 1, np.arange(nb) // 4, -1)
    win = EX.Win(y, bt, (np.arange(nb) % 4) + 1, bar)
    s = EX.subset(win, EX.prepare(win, hpss=False), sorted(set(bar[bar >= 0])))
    err = [k for k in s if k.endswith("_error")]
    lines.append(f"{scn:36s} " + " ".join(f"{val(fn, s):9.2f}" for _n, fn in COLS) + (f"   {[(k, s[k]) for k in err if k != 'hat_error']}" if err else ""))
print("\n".join(lines))
if len(sys.argv) > 1:
    Path(sys.argv[1]).mkdir(parents=True, exist_ok=True)
    (Path(sys.argv[1]) / "synth_bassline.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
