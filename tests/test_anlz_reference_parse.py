"""Validate produced ANLZ files against an INDEPENDENT reference parser.

`write_anlz_files` output (.DAT/.EXT/.2EX) is parsed back with
`pyrekordbox.AnlzFile` — a pure-Python implementation of the Deep-Symmetry
ANLZ spec by a different author. If our byte layout drifts from the format
(as the PCPT cue-entry constants once did), this parser raises and the test
fails. Catches cue/waveform/beatgrid format regressions automatically.

Skips unless both the heavy analysis stack (librosa) and pyrekordbox are
installed — i.e. it runs locally / in any env with the audio deps, and is a
no-op on minimal CI runners.
"""

from __future__ import annotations

import os
import sys
import tempfile

import pytest

pytest.importorskip("librosa", reason="heavy audio stack not installed")
pytest.importorskip("pyrekordbox", reason="reference ANLZ parser not installed")
pytest.importorskip("soundfile", reason="soundfile not installed")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

SR = 44100


def _energy_track(bpm: float = 128.0, dur: float = 60.0) -> np.ndarray:
    """Four-on-floor with an intro/drop/breakdown energy arc so the phrase
    detector emits PSSI phrases + memory cues (exercises PCOB/PCPT/PSSI)."""
    n = int(SR * dur)
    t = np.arange(n) / SR
    y = np.zeros(n, dtype=np.float32)
    bp = 60.0 / bpm

    def kick(length: float = 0.14) -> np.ndarray:
        m = int(length * SR)
        env = np.exp(-np.linspace(0, 9, m))
        sweep = np.linspace(110, 45, m)
        return (np.sin(2 * np.pi * np.cumsum(sweep) / SR) * env * 0.8).astype(np.float32)

    tt = 0.0
    while tt < dur - 0.2:
        s = int(tt * SR)
        amp = 0.3 if tt < 15 else (1.0 if tt < 40 else (0.2 if tt < 50 else 0.6))
        k = kick() * amp
        y[s : s + len(k)] += k[: max(0, n - s)]
        tt += bp
    for semi in (9, 1, 4):  # A C# E
        y += (0.15 * np.sin(2 * np.pi * 261.63 * 2 ** (semi / 12) * t)).astype(np.float32)
    y /= np.max(np.abs(y)) + 1e-9
    return (y * 0.9).astype(np.float32)


def test_produced_anlz_parses_with_reference_parser():
    from pyrekordbox import AnlzFile

    from app.analysis_engine import run_full_analysis
    from app.anlz_writer import write_anlz_files

    # pyrekordbox's construct grammar recurses per waveform entry; give it room.
    old_limit = sys.getrecursionlimit()
    sys.setrecursionlimit(max(old_limit, 8000))
    fd, wav = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    out = tempfile.mkdtemp()
    try:
        sf.write(wav, _energy_track(), SR)
        res = run_full_analysis(wav, use_cache=False)
        assert res["status"] == "ok"
        paths = write_anlz_files(out, wav, res)

        # Every produced file must parse cleanly by the independent reference.
        for kind in ("dat", "ext", "2ex"):
            assert kind in paths, f"missing {kind}"
            anlz = AnlzFile.parse_file(paths[kind])  # raises on format drift
            assert anlz is not None

        # Cue positions written must survive the round-trip through the parser.
        ext = AnlzFile.parse_file(paths["ext"])
        rb_cue_times = set()
        for tag in ext.tags if hasattr(ext, "tags") else list(ext):
            if getattr(tag, "type", getattr(tag, "name", "")) == "PCOB":
                content = getattr(tag, "content", None)
                for e in getattr(content, "entries", []) or []:
                    rb_cue_times.add(int(getattr(e, "time", -1)))
        our_cue_times = {int(c["time_ms"]) for c in res.get("hot_cues", [])}
        our_cue_times |= {int(c["time_ms"]) for c in res.get("memory_cues", [])}
        # Every position we wrote is present in the parsed-back set (the parser
        # splits hot/memory across two PCOB lists; we only assert containment).
        if our_cue_times:
            assert our_cue_times <= rb_cue_times, (
                f"cue positions lost in round-trip: wrote {sorted(our_cue_times)}, "
                f"read {sorted(rb_cue_times)}"
            )
    finally:
        sys.setrecursionlimit(old_limit)
        os.unlink(wav)
        import shutil

        shutil.rmtree(out, ignore_errors=True)
