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
    ap.add_argument("--dur", type=float, default=20.0, help="track length (s)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("-n", type=int, default=12, help="number of tracks (random sample)")
    ap.add_argument("--bpm-min", type=float, default=75.0)
    ap.add_argument("--bpm-max", type=float, default=210.0)
    ap.add_argument(
        "--full", action="store_true", help="use full pipeline (slow); else detect_* direct"
    )
    ap.add_argument("--verbose", action="store_true", help="print every track row")
    args = ap.parse_args(argv)

    from app import analysis_engine as ae

    ae._ensure_libs()
    np.random.seed(args.seed)
    rng = np.random.default_rng(args.seed)

    # Random (bpm, root, mode) cases across the requested tempo range.
    cases = []
    for _ in range(args.n):
        bpm = float(round(rng.uniform(args.bpm_min, args.bpm_max), 1))
        root = _SEMI[int(rng.integers(0, 12))]
        mode = "minor" if rng.random() < 0.5 else "major"
        cases.append((bpm, root, mode))

    caps = ae.AnalysisEngine.capabilities()
    print(
        f"Self-test: {len(cases)} synthetic tracks, dur={args.dur}s, seed={args.seed}, "
        f"bpm={args.bpm_min}-{args.bpm_max}, mode={'full' if args.full else 'direct'}"
    )
    print(f"BPM method: {caps['beat_method']} | key: {caps['key_method']}\n")

    bpm_ok = key_exact = key_compat = 0
    bpm_rel_tally: dict[str, int] = {}
    # BPM accuracy per tempo band
    bands = [(75, 100), (100, 140), (140, 180), (180, 210)]
    band_tot: dict[str, int] = {f"{lo}-{hi}": 0 for lo, hi in bands}
    band_ok: dict[str, int] = {f"{lo}-{hi}": 0 for lo, hi in bands}
    rows = []
    fails = []
    for bpm, root, mode in cases:
        y = synth_track(bpm, root, mode, dur=args.dur)
        if args.full:
            import soundfile as sf

            fd, path = tempfile.mkstemp(suffix=".wav")
            os.close(fd)
            sf.write(path, y, SR)
            try:
                r = ae.run_full_analysis(path, use_cache=False)
                our_bpm, our_cam, our_key = float(r["bpm"]), r.get("camelot", ""), r.get("key", "?")
            finally:
                os.unlink(path)
        else:
            beat = ae.detect_beats(y, SR)
            key = ae.detect_key(y, SR)
            our_bpm, our_cam, our_key = (
                float(beat["bpm"]),
                key.get("camelot", ""),
                key.get("key", "?"),
            )

        gt_cam = _camelot(root, mode)
        rel, err = bpm_relation(bpm, our_bpm)
        krel = key_relation(gt_cam, our_cam)
        bpm_ok += rel == "match"
        key_exact += krel == "exact"
        key_compat += krel in ("exact", "relative", "fifth")
        bpm_rel_tally[rel] = bpm_rel_tally.get(rel, 0) + 1
        for lo, hi in bands:
            if lo <= bpm < hi:
                k = f"{lo}-{hi}"
                band_tot[k] += 1
                band_ok[k] += rel == "match"
                break
        gt_key = f"{root}{'m' if mode == 'minor' else ''}"
        row = (
            f"  GT {bpm:>6.1f}/{gt_key:<3}({gt_cam:<3}) → "
            f"ours {our_bpm:>6.1f}/{our_key:<3}({our_cam:<3})  "
            f"BPM:{rel:<6}({err:>5.1f}%)  KEY:{krel}"
        )
        rows.append(row)
        if rel != "match" or krel == "clash":
            fails.append(row)

    if args.verbose:
        print("\n".join(rows))
    else:
        print("Failures (BPM!=match or KEY clash):")
        print("\n".join(fails) if fails else "  (none)")

    n = len(cases)
    print("\n=== Summary ===")
    print(f"  BPM exact (<=1%, same octave): {bpm_ok}/{n}  ({100 * bpm_ok // n}%)")
    print(f"  BPM relation tally           : {dict(sorted(bpm_rel_tally.items()))}")
    print(
        "  BPM exact by tempo band      : "
        + ", ".join(f"{k}:{band_ok[k]}/{band_tot[k]}" for k in band_tot if band_tot[k])
    )
    print(f"  KEY exact                    : {key_exact}/{n}  ({100 * key_exact // n}%)")
    print(f"  KEY harmonic-compatible      : {key_compat}/{n}  ({100 * key_compat // n}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
