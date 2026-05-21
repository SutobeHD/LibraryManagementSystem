"""Tests for the unified-downloader extensions to ``app/audio_tags.py``.

Two pieces (P4.15):

* **Provenance helpers** — :func:`serialise_provenance` / :func:`read_provenance`
  round-trip the COMMENT-field URL list (picked-first, descending quality).
  These are pure functions — no audio files needed.
* **Write-side ISRC** — the ``isrc`` field now writes a format-correct frame
  (``TSRC`` / ``isrc`` Vorbis / ``----:com.apple.iTunes:ISRC``) and reads
  back via the existing :func:`read_tags`. Verified across MP3 / FLAC / AIFF /
  M4A using ffmpeg-synthesised silence as the sample.

ffmpeg-dependent tests skip cleanly when ffmpeg is not on PATH.

See ``docs/research/implement/accepted_downloader-unified-multi-source.md``
§ "P4.15" and "(D6) Comment-field URL serialisation".
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app import audio_tags
from app.downloader.models import QualityTier, TrackMatch

# ──────────────────────────────────────────────────────────────────────────────
# Provenance — pure-function round-trip
# ──────────────────────────────────────────────────────────────────────────────


def _match(
    *, platform: str, url: str, tier: QualityTier, bit_depth: int | None = None
) -> TrackMatch:
    """Minimal :class:`TrackMatch` for provenance-ordering tests."""
    return TrackMatch(
        platform=platform,  # type: ignore[arg-type]
        url=url,
        title="Track",
        artist="Artist",
        duration_s=200.0,
        claimed_format="flac" if tier <= QualityTier.CD_LOSSLESS else "mp3",
        claimed_bit_depth=bit_depth,
        quality_tier=tier,
    )


def test_serialise_provenance_picked_leads() -> None:
    picked = _match(
        platform="qobuz",
        url="https://qobuz.com/t/1",
        tier=QualityTier.HIRES_LOSSLESS,
        bit_depth=24,
    )
    others = [
        _match(
            platform="tidal",
            url="https://tidal.com/t/2",
            tier=QualityTier.CD_LOSSLESS,
            bit_depth=16,
        ),
        _match(
            platform="soundcloud", url="https://soundcloud.com/a/t", tier=QualityTier.HIGH_LOSSY
        ),
    ]
    out = audio_tags.serialise_provenance([picked, *others], picked)
    urls = [u.strip() for u in out.split(",")]
    assert urls[0] == "https://qobuz.com/t/1"  # picked is always the head
    assert urls == [
        "https://qobuz.com/t/1",
        "https://tidal.com/t/2",
        "https://soundcloud.com/a/t",
    ]


def test_serialise_provenance_orders_rest_by_quality() -> None:
    picked = _match(
        platform="soundcloud",
        url="https://soundcloud.com/a/t",
        tier=QualityTier.HIGH_LOSSY,
    )
    # Deliberately unsorted input; expect descending-quality after the head.
    candidates = [
        _match(
            platform="spotify",
            url="https://open.spotify.com/track/lossy",
            tier=QualityTier.STANDARD_LOSSY,
        ),
        picked,
        _match(
            platform="qobuz",
            url="https://qobuz.com/t/hires",
            tier=QualityTier.HIRES_LOSSLESS,
            bit_depth=24,
        ),
        _match(
            platform="tidal",
            url="https://tidal.com/t/cd",
            tier=QualityTier.CD_LOSSLESS,
            bit_depth=16,
        ),
    ]
    out = audio_tags.serialise_provenance(candidates, picked)
    urls = [u.strip() for u in out.split(",")]
    assert urls == [
        "https://soundcloud.com/a/t",  # picked
        "https://qobuz.com/t/hires",  # tier 0
        "https://tidal.com/t/cd",  # tier 1
        "https://open.spotify.com/track/lossy",  # tier 3
    ]


def test_serialise_provenance_dedups_picked() -> None:
    picked = _match(
        platform="qobuz",
        url="https://qobuz.com/t/1",
        tier=QualityTier.HIRES_LOSSLESS,
        bit_depth=24,
    )
    # picked also appears in the candidates list — must not be emitted twice.
    out = audio_tags.serialise_provenance([picked, picked], picked)
    assert out == "https://qobuz.com/t/1"


def test_read_provenance_round_trip() -> None:
    comment = (
        "https://qobuz.com/track/1, https://tidal.com/track/2, https://open.spotify.com/track/3"
    )
    parsed = audio_tags.read_provenance(comment)
    assert [p for _, _, p in parsed] == [True, False, False]
    assert [plat for plat, _, _ in parsed] == ["qobuz", "tidal", "spotify"]
    assert parsed[0][1] == "https://qobuz.com/track/1"


def test_read_provenance_infers_platforms() -> None:
    comment = ", ".join(
        [
            "https://soundcloud.com/artist/track",
            "https://music.amazon.de/albums/x",
            "https://music.apple.com/us/album/y",
            "https://www.deezer.com/track/z",
            "https://youtu.be/abc",
        ]
    )
    plats = [plat for plat, _, _ in audio_tags.read_provenance(comment)]
    assert plats == ["soundcloud", "amazon", "apple_music", "deezer", "youtube"]


def test_read_provenance_unknown_host_defaults_soundcloud() -> None:
    parsed = audio_tags.read_provenance("https://unknown-store.example/track/1")
    assert parsed[0][0] == "soundcloud"


def test_read_provenance_empty_input() -> None:
    assert audio_tags.read_provenance("") == []
    assert audio_tags.read_provenance(None) == []  # type: ignore[arg-type]


def test_read_provenance_ignores_non_url_tokens() -> None:
    parsed = audio_tags.read_provenance("not a url, https://qobuz.com/t/1, also junk")
    assert len(parsed) == 1
    assert parsed[0][1] == "https://qobuz.com/t/1"


def test_serialise_read_full_round_trip() -> None:
    picked = _match(
        platform="qobuz",
        url="https://qobuz.com/t/1",
        tier=QualityTier.HIRES_LOSSLESS,
        bit_depth=24,
    )
    others = [
        _match(
            platform="tidal",
            url="https://tidal.com/t/2",
            tier=QualityTier.CD_LOSSLESS,
            bit_depth=16,
        ),
    ]
    serialised = audio_tags.serialise_provenance([picked, *others], picked)
    parsed = audio_tags.read_provenance(serialised)
    assert parsed[0] == ("qobuz", "https://qobuz.com/t/1", True)
    assert parsed[1] == ("tidal", "https://tidal.com/t/2", False)


# ──────────────────────────────────────────────────────────────────────────────
# Write-side ISRC — real files
# ──────────────────────────────────────────────────────────────────────────────
# Sample files are synthesised with `soundfile` (libsndfile: WAV/FLAC/AIFF) and
# `lameenc` (MP3) — both pinned production deps, so MP3/FLAC/AIFF run
# unconditionally. M4A/AAC has no pure-Python encoder; that one test builds the
# sample via ffmpeg and skips cleanly when ffmpeg lacks an AAC encoder.

_SAMPLE_ISRC = "GBAYE0000123"

#: ~0.3 s of silent stereo 16-bit PCM — enough for a structurally valid file.
_PCM_FRAMES = 13230


def _silence_int16() -> object:
    """A zero-filled ``(_PCM_FRAMES, 2)`` int16 numpy array."""
    import numpy as np

    return np.zeros((_PCM_FRAMES, 2), dtype="int16")


def _write_sf(path: Path, fmt: str, subtype: str = "PCM_16") -> None:
    """Write a silent sample via soundfile (libsndfile) in the given format."""
    import soundfile as sf

    sf.write(str(path), _silence_int16(), 44100, format=fmt, subtype=subtype)


def _write_mp3(path: Path) -> None:
    """Encode a silent MP3 via lameenc (pure-Python LAME binding)."""
    import lameenc

    enc = lameenc.Encoder()
    enc.set_bit_rate(128)
    enc.set_in_sample_rate(44100)
    enc.set_channels(2)
    enc.set_quality(5)
    payload = enc.encode(_silence_int16().tobytes()) + enc.flush()
    path.write_bytes(payload)


def test_isrc_write_read_mp3(tmp_path: Path) -> None:
    f = tmp_path / "track.mp3"
    _write_mp3(f)
    assert audio_tags.write_tags(f, {"ISRC": _SAMPLE_ISRC}) is True
    assert audio_tags.read_tags(f)["isrc"] == _SAMPLE_ISRC


def test_isrc_write_read_flac(tmp_path: Path) -> None:
    f = tmp_path / "track.flac"
    _write_sf(f, "FLAC")
    # Lower-case alias also resolves to the canonical `isrc` field.
    assert audio_tags.write_tags(f, {"isrc": _SAMPLE_ISRC}) is True
    assert audio_tags.read_tags(f)["isrc"] == _SAMPLE_ISRC


def test_isrc_write_read_aiff(tmp_path: Path) -> None:
    f = tmp_path / "track.aiff"
    _write_sf(f, "AIFF")
    assert audio_tags.write_tags(f, {"ISRC": _SAMPLE_ISRC}) is True
    assert audio_tags.read_tags(f)["isrc"] == _SAMPLE_ISRC


def test_isrc_write_read_wav(tmp_path: Path) -> None:
    f = tmp_path / "track.wav"
    _write_sf(f, "WAV")
    assert audio_tags.write_tags(f, {"ISRC": _SAMPLE_ISRC}) is True
    assert audio_tags.read_tags(f)["isrc"] == _SAMPLE_ISRC


def test_isrc_write_read_m4a(tmp_path: Path) -> None:
    # M4A/AAC has no pure-Python encoder — build the sample via ffmpeg, and
    # skip if this environment's ffmpeg is a stripped build with no AAC encoder.
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        pytest.skip("ffmpeg not on PATH — cannot synthesise an .m4a sample")
    seed = tmp_path / "seed.wav"
    _write_sf(seed, "WAV")
    f = tmp_path / "track.m4a"
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(seed),
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-y",
        str(f),
    ]
    try:
        ok = subprocess.run(cmd, capture_output=True, timeout=30).returncode == 0
    except (subprocess.SubprocessError, OSError):
        ok = False
    if not ok or not f.is_file():
        pytest.skip("ffmpeg build has no AAC encoder — cannot synthesise .m4a")
    assert audio_tags.write_tags(f, {"ISRC": _SAMPLE_ISRC}) is True
    assert audio_tags.read_tags(f)["isrc"] == _SAMPLE_ISRC


def test_isrc_written_alongside_other_tags(tmp_path: Path) -> None:
    """ISRC must coexist with the standard metadata fields, not clobber them."""
    f = tmp_path / "full.flac"
    _write_sf(f, "FLAC")
    ok = audio_tags.write_tags(
        f,
        {
            "Title": "Provenance Test",
            "Artist": "Test Artist",
            "Genre": "Tech House",
            "ISRC": _SAMPLE_ISRC,
            "Comment": "https://qobuz.com/t/1, https://tidal.com/t/2",
        },
    )
    assert ok is True
    tags = audio_tags.read_tags(f)
    assert tags["isrc"] == _SAMPLE_ISRC
    assert tags["title"] == "Provenance Test"
    assert tags["artist"] == "Test Artist"
    assert tags["genre"] == "Tech House"
    # The provenance string survives in COMMENT and parses back.
    parsed = audio_tags.read_provenance(tags["comment"])
    assert parsed[0] == ("qobuz", "https://qobuz.com/t/1", True)
