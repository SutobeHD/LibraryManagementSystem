#!/usr/bin/env python3
"""
selftest_analysis.py — autonomous accuracy self-test (no Rekordbox needed).

Generates synthetic tracks with KNOWN ground-truth BPM and key (four-on-the-
floor kick = unambiguous tempo + sustained triad/bass = unambiguous key),
runs the real analysis engine, and scores BPM / key recovery using the same
comparison helpers the Rekordbox A/B harness uses.

This is the "test it without the user / without a library" path: ground truth
comes from the generator instead of Rekordbox. Real-library accuracy still
needs scripts/compare_rekordbox.py run locally.

    python scripts/selftest_analysis.py
    python scripts/selftest_analysis.py --dur 24 --seed 0
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402
from compare_rekordbox import bpm_relation, key_relation  # noqa: E402

SR = 44100
_SEMI = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
# note -> Hz (octave 3/4 mix for body)
_NOTE_HZ = {n: 261.63 * (2 ** (i / 12.0)) for i, n in enumerate(_SEMI)}


def _camelot(root: str, mode: str) -> str:
    """Ground-truth Camelot code from root+mode via the engine's own map."""
    from app.analysis_engine import _CAMELOT_MAP

    return _CAMELOT_MAP.get(f"{root} {mode}", "")


def synth_track(bpm: float, root: str, mode: str, dur: float = 24.0, sr: int = SR) -> np.ndarray:
    """Four-on-the-floor kick + offbeat hat + root bass + sustained triad pad."""
    n = int(sr * dur)
    t = np.arange(n) / sr
    y = np.zeros(n, dtype=np.float32)
    bp = 60.0 / bpm

    def kick(length: float = 0.14) -> np.ndarray:
        m = int(length * sr)
        env = np.exp(-np.linspace(0, 9, m))
        sweep = np.linspace(110, 45, m)
        return (np.sin(2 * np.pi * np.cumsum(sweep) / sr) * env * 0.7).astype(np.float32)

    def hat(length: float = 0.04) -> np.ndarray:
        m = int(length * sr)
        env = np.exp(-np.linspace(0, 30, m))
        return np.random.randn(m).astype(np.float32) * env * 0.15

    # Rhythm: kick every beat (tempo fundamental), hat on the off-8th.
    beat = 0
    tt = 0.0
    while tt < dur - 0.2:
        s = int(tt * sr)
        k = kick()
        y[s : s + len(k)] += k[: max(0, n - s)]
        sh = int((tt + bp / 2) * sr)
        if sh < n:
            h = hat()
            y[sh : sh + len(h)] += h[: max(0, n - sh)]
        tt += bp
        beat += 1

    # Harmony: root bass pulse + sustained triad (root, third, fifth).
    r = _SEMI.index(root)
    third = 4 if mode == "major" else 3
    triad = [r, (r + third) % 12, (r + 7) % 12]
    bass_hz = _NOTE_HZ[_SEMI[r]] / 2.0
    pad = np.zeros(n, dtype=np.float32)
    for semi in triad:
        f = _NOTE_HZ[_SEMI[semi]]
        for h_, amp in [(1, 0.5), (2, 0.25)]:
            pad += (amp * np.sin(2 * np.pi * f * h_ * t)).astype(np.float32)
    pad *= 0.25
    # bass on each beat
    tt = 0.0
    while tt < dur - 0.2:
        s = int(tt * sr)
        m = int(min(bp * 0.9, 0.4) * sr)
        env = np.exp(-np.linspace(0, 4, m))
        seg = (np.sin(2 * np.pi * bass_hz * np.arange(m) / sr) * env * 0.5).astype(np.float32)
        y[s : s + len(seg)] += seg[: max(0, n - s)]
        tt += bp
    y += pad
    y /= np.max(np.abs(y)) + 1e-9
    return (y * 0.9).astype(np.float32)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Autonomous analysis accuracy self-test")
    ap.add_argument("--dur", type=float, default=24.0, help="track length (s)")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)

    import soundfile as sf

    from app import analysis_engine as ae

    ae._ensure_libs()
    np.random.seed(args.seed)
    rng = np.random.default_rng(args.seed)

    # Spread of tempos incl. the new high range, each with a random key.
    bpms = [90, 100, 110, 124, 128, 140, 150, 160, 174, 186, 200, 210]
    cases = []
    for b in bpms:
        root = _SEMI[int(rng.integers(0, 12))]
        mode = "minor" if rng.random() < 0.5 else "major"
        cases.append((float(b), root, mode))

    print(f"Self-test: {len(cases)} synthetic tracks, dur={args.dur}s, seed={args.seed}")
    print(
        f"BPM method: {ae.AnalysisEngine.capabilities()['beat_method']} | "
        f"key: {ae.AnalysisEngine.capabilities()['key_method']}\n"
    )

    bpm_ok = key_exact = key_compat = 0
    rows = []
    for bpm, root, mode in cases:
        y = synth_track(bpm, root, mode, dur=args.dur)
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        sf.write(path, y, SR)
        try:
            r = ae.run_full_analysis(path, use_cache=False)
        finally:
            os.unlink(path)
        gt_cam = _camelot(root, mode)
        rel, err = bpm_relation(bpm, float(r["bpm"]))
        krel = key_relation(gt_cam, r.get("camelot", ""))
        bpm_ok += rel == "match"
        key_exact += krel == "exact"
        key_compat += krel in ("exact", "relative", "fifth")
        gt_key = f"{root}{'m' if mode == 'minor' else ''}"
        rows.append(
            f"  GT {bpm:>5.0f}/{gt_key:<3}({gt_cam:<3}) → "
            f"ours {r['bpm']:>6}/{r.get('key', '?'):<3}({r.get('camelot', ''):<3})  "
            f"BPM:{rel:<6}({err:>4.1f}%)  KEY:{krel}"
        )

    print("\n".join(rows))
    n = len(cases)
    print("\n=== Summary ===")
    print(f"  BPM exact (<=1%, same octave): {bpm_ok}/{n}")
    print(f"  KEY exact                    : {key_exact}/{n}")
    print(f"  KEY harmonic-compatible      : {key_compat}/{n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
