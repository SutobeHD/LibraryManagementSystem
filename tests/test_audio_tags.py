"""Tests for app/audio_tags.py — native tag write-back (mutates user files → HIGH risk).

Pure helpers (_rating_to_popm, _normalize_fields) run anywhere. The real
write→read round-trip uses FLAC (soundfile writes it, mutagen reads it back),
so it only runs where soundfile + numpy are installed.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import audio_tags  # noqa: E402

# --- pure helpers (no deps) -----------------------------------------------


def test_rating_to_popm_scale():
    f = audio_tags._rating_to_popm
    assert f(0) == 0
    assert f(1) == 1
    assert f(5) == 255
    assert f(3) == 128
    assert f(99) == 255  # clamped to 5
    assert f(-3) == 0  # clamped to 0
    assert f("bad") == 0  # non-int → 0, never raises


def test_normalize_fields_drops_none_and_unknown():
    out = audio_tags._normalize_fields({"title": "T", "boguskey": "x", "artist": None})
    # known alias kept, None dropped, unknown key dropped
    assert out.get("boguskey") is None
    assert "T" in out.values()
    assert all(v is not None for v in out.values())


def test_write_tags_unsupported_and_missing(tmp_path):
    # unsupported extension → False (not a crash)
    p = tmp_path / "x.xyz"
    p.write_bytes(b"\x00")
    assert audio_tags.write_tags(str(p), {"title": "T"}) is False
    # missing file → False
    assert audio_tags.write_tags(str(tmp_path / "nope.flac"), {"title": "T"}) is False
    # empty updates + no artwork → no-op success
    assert audio_tags.write_tags(str(p), {}) is True


# --- real FLAC round-trip --------------------------------------------------


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("soundfile") is None, reason="soundfile missing"
)
def test_flac_tag_roundtrip():
    import numpy as np
    import soundfile as sf
    from mutagen.flac import FLAC

    fd, path = tempfile.mkstemp(suffix=".flac")
    os.close(fd)
    try:
        sf.write(path, np.zeros(44100, dtype="float32"), 44100)  # 1s silent FLAC
        ok = audio_tags.write_tags(
            path, {"title": "Round Trip", "artist": "Tester", "bpm": "128.00"}
        )
        assert ok is True
        f = FLAC(path)
        # Vorbis comments are case-insensitive lists; check the values landed
        flat = {k.lower(): v for k, v in f.tags} if f.tags else {}
        assert flat.get("title") == "Round Trip"
        assert flat.get("artist") == "Tester"
    finally:
        os.unlink(path)
