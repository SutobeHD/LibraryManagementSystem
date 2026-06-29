"""Validate the produced ANLZ files (.DAT/.EXT/.2EX).

Two layers:
  * test_produced_anlz_structure — pure byte tag-walk (PMAI header, every tag's
    length sane, len_file == file size, expected tag set per file). Needs only
    librosa, so it runs in CI and catches structural/length regressions.
  * test_produced_anlz_parses_with_reference_parser — parses with the INDEPENDENT
    `pyrekordbox.AnlzFile` (pure-Python Deep-Symmetry impl by another author),
    which also checks the spec CONSTANTS (it caught the PCPT cue-const drift).
    Needs pyrekordbox, so it runs locally / in the analysis-accuracy-watchdog
    routine and skips on minimal CI.
"""

from __future__ import annotations

import os
import struct
import sys
import tempfile

import pytest

pytest.importorskip("librosa", reason="heavy audio stack not installed")
pytest.importorskip("soundfile", reason="soundfile not installed")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

SR = 44100

# Tag sets the writer documents per file (anlz_writer module docstring).
_EXPECTED_TAGS = {
    "dat": {"PPTH", "PVBR", "PQTZ", "PWAV", "PWV2", "PCOB"},
    "ext": {"PPTH", "PWV3", "PCOB", "PCO2", "PQT2", "PWV5", "PWV4"},
    "2ex": {"PPTH", "PWV7", "PWV6", "PWVC"},
}


def _walk_tags(path: str) -> list[tuple[str, int, int]]:
    """Independent ANLZ tag walk → [(fourcc, len_header, len_tag)]. Asserts the
    PMAI root + that len_file matches the actual size and no tag length loops."""
    data = open(path, "rb").read()  # noqa: SIM115
    assert data[:4] == b"PMAI", f"{path}: bad root magic {data[:4]!r}"
    len_header = struct.unpack(">I", data[4:8])[0]
    len_file = struct.unpack(">I", data[8:12])[0]
    assert len_file == len(data), f"{path}: len_file {len_file} != actual {len(data)}"
    tags: list[tuple[str, int, int]] = []
    pos = len_header
    while pos + 12 <= len(data):
        fourcc = data[pos : pos + 4].decode("ascii", "replace")
        lh = struct.unpack(">I", data[pos + 4 : pos + 8])[0]
        lt = struct.unpack(">I", data[pos + 8 : pos + 12])[0]
        assert lt > 0, f"{path}: tag {fourcc} has non-positive total_len {lt} (parser would loop)"
        tags.append((fourcc, lh, lt))
        pos += lt
    return tags


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


def test_produced_anlz_structure():
    """Byte-level structural validation — runs in CI (librosa only, no pyrekordbox)."""
    from app.analysis_engine import run_full_analysis
    from app.anlz_writer import write_anlz_files

    fd, wav = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    out = tempfile.mkdtemp()
    try:
        sf.write(wav, _energy_track(), SR)
        res = run_full_analysis(wav, use_cache=False)
        assert res["status"] == "ok"
        paths = write_anlz_files(out, wav, res)
        for kind, expected in _EXPECTED_TAGS.items():
            assert kind in paths, f"missing {kind}"
            tags = _walk_tags(paths[kind])
            present = {fourcc for fourcc, _, _ in tags}
            missing = expected - present
            assert not missing, f"{kind}: missing tags {missing} (have {present})"
    finally:
        os.unlink(wav)
        import shutil

        shutil.rmtree(out, ignore_errors=True)


def test_produced_anlz_parses_with_reference_parser():
    pytest.importorskip("pyrekordbox", reason="reference ANLZ parser not installed")
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
