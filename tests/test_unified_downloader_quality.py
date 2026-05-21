"""Tests for ``app/downloader/quality.py`` — tier classification + policy picking.

Covers :func:`classify` over every tier boundary, :func:`is_lossless`,
:func:`pick_best`, and :func:`pick_with_policy` — in particular the owner's
lossless-first hard rule: ``lossless_only`` returns ``(None, True)`` when no
lossless candidate exists, and a lossless candidate ALWAYS beats a lossy one.

See ``docs/research/implement/accepted_downloader-unified-multi-source.md``
§ "P2.10" and Findings § "Quality policy hardening".
"""

from __future__ import annotations

import pytest

from app.downloader.models import QualityTier, TrackMatch
from app.downloader.quality import classify, is_lossless, pick_best, pick_with_policy

# ──────────────────────────────────────────────────────────────────────────────
# Builder
# ──────────────────────────────────────────────────────────────────────────────


def _track(
    *,
    fmt: str,
    bit_depth: int | None = None,
    sample_rate: int | None = None,
    bitrate: int | None = None,
    filesize: int | None = None,
    platform: str = "qobuz",
) -> TrackMatch:
    """Build a synthetic :class:`TrackMatch` with an internally-consistent tier.

    The stored ``quality_tier`` is derived from :func:`classify` (then frozen
    in via ``model_copy``), exactly as the real resolver builds a TrackMatch
    (``m.model_copy(update={"quality_tier": classify(m)})``). This keeps the
    fixture honest: ``quality_sort_key`` reads the *stored* tier, so a hand-set
    inconsistent tier would silently corrupt the sort-key tests.
    """
    bare = TrackMatch(
        platform=platform,  # type: ignore[arg-type]
        url=f"https://example.com/{platform}/{fmt}-{bit_depth}-{sample_rate}-{bitrate}",
        title="Test Track",
        artist="Test Artist",
        duration_s=200.0,
        claimed_format=fmt,  # type: ignore[arg-type]
        claimed_bit_depth=bit_depth,
        claimed_sample_rate_hz=sample_rate,
        claimed_bitrate_kbps=bitrate,
        claimed_filesize_bytes=filesize,
        quality_tier=QualityTier.LAST_RESORT,  # placeholder — replaced below
    )
    return bare.model_copy(update={"quality_tier": classify(bare)})


# ──────────────────────────────────────────────────────────────────────────────
# classify — lossless tiers
# ──────────────────────────────────────────────────────────────────────────────


def test_classify_flac_24_96_is_hires() -> None:
    """FLAC 24-bit / 96 kHz → HIRES_LOSSLESS."""
    m = _track(fmt="flac", bit_depth=24, sample_rate=96000)
    assert classify(m) == QualityTier.HIRES_LOSSLESS


def test_classify_flac_16_44_is_cd_lossless() -> None:
    """FLAC 16-bit / 44.1 kHz → CD_LOSSLESS."""
    m = _track(fmt="flac", bit_depth=16, sample_rate=44100)
    assert classify(m) == QualityTier.CD_LOSSLESS


def test_classify_hires_via_bit_depth_alone() -> None:
    """24-bit at 44.1 kHz still counts as hi-res (depth OR rate triggers it)."""
    m = _track(fmt="alac", bit_depth=24, sample_rate=44100)
    assert classify(m) == QualityTier.HIRES_LOSSLESS


def test_classify_hires_via_sample_rate_alone() -> None:
    """16-bit at 48 kHz still counts as hi-res (rate > 44100 triggers it)."""
    m = _track(fmt="flac", bit_depth=16, sample_rate=48000)
    assert classify(m) == QualityTier.HIRES_LOSSLESS


def test_classify_wav_aiff_default_to_cd_lossless() -> None:
    """WAV / AIFF with no depth/rate claims default to CD_LOSSLESS (16/44.1)."""
    assert classify(_track(fmt="wav")) == QualityTier.CD_LOSSLESS
    assert classify(_track(fmt="aiff")) == QualityTier.CD_LOSSLESS


@pytest.mark.parametrize("fmt", ["flac", "alac", "wav", "aiff"])
def test_all_lossless_formats_classify_lossless(fmt: str) -> None:
    """Every lossless format lands in a lossless tier at CD-rate defaults."""
    assert classify(_track(fmt=fmt)) in (
        QualityTier.HIRES_LOSSLESS,
        QualityTier.CD_LOSSLESS,
    )


# ──────────────────────────────────────────────────────────────────────────────
# classify — lossy tiers
# ──────────────────────────────────────────────────────────────────────────────


def test_classify_mp3_320_is_high_lossy() -> None:
    """MP3 at 320 kbps → HIGH_LOSSY (>= 256)."""
    m = _track(fmt="mp3", bitrate=320, platform="soundcloud")
    assert classify(m) == QualityTier.HIGH_LOSSY


def test_classify_aac_257_is_high_lossy() -> None:
    """The flagged SoundCloud .m4a / AAC 257 kbps → HIGH_LOSSY (>= 256)."""
    m = _track(fmt="m4a", bitrate=257, platform="soundcloud")
    assert classify(m) == QualityTier.HIGH_LOSSY


def test_classify_lossy_256_boundary() -> None:
    """Exactly 256 kbps → HIGH_LOSSY (>= 256, inclusive)."""
    assert classify(_track(fmt="aac", bitrate=256)) == QualityTier.HIGH_LOSSY


def test_classify_mp3_192_is_standard_lossy() -> None:
    """MP3 at 192 kbps → STANDARD_LOSSY (128-256)."""
    assert classify(_track(fmt="mp3", bitrate=192)) == QualityTier.STANDARD_LOSSY


def test_classify_lossy_128_boundary() -> None:
    """Exactly 128 kbps → STANDARD_LOSSY (>= 128, inclusive)."""
    assert classify(_track(fmt="mp3", bitrate=128)) == QualityTier.STANDARD_LOSSY


def test_classify_low_bitrate_is_last_resort() -> None:
    """Below 128 kbps → LAST_RESORT."""
    assert classify(_track(fmt="mp3", bitrate=96)) == QualityTier.LAST_RESORT


def test_classify_lossy_missing_bitrate_is_last_resort() -> None:
    """A lossy format with no bitrate claim (e.g. variable YouTube MP3) → LAST_RESORT."""
    assert classify(_track(fmt="mp3", bitrate=None)) == QualityTier.LAST_RESORT


@pytest.mark.parametrize("fmt", ["mp3", "aac", "ogg", "opus", "m4a"])
def test_all_lossy_formats_classify_lossy(fmt: str) -> None:
    """Every lossy format lands in a lossy tier, never a lossless one."""
    assert classify(_track(fmt=fmt, bitrate=320)) not in (
        QualityTier.HIRES_LOSSLESS,
        QualityTier.CD_LOSSLESS,
    )


def test_classify_format_neutral_within_lossy_tier() -> None:
    """MP3 and AAC at the same bitrate classify identically — format-neutral."""
    assert classify(_track(fmt="mp3", bitrate=320)) == classify(_track(fmt="aac", bitrate=320))


# ──────────────────────────────────────────────────────────────────────────────
# is_lossless
# ──────────────────────────────────────────────────────────────────────────────


def test_is_lossless_true_for_flac_and_wav() -> None:
    """is_lossless is True for lossless formats."""
    assert is_lossless(_track(fmt="flac", bit_depth=24, sample_rate=96000)) is True
    assert is_lossless(_track(fmt="wav")) is True


def test_is_lossless_false_for_mp3_and_m4a() -> None:
    """is_lossless is False for lossy formats — including high-bitrate AAC."""
    assert is_lossless(_track(fmt="mp3", bitrate=320)) is False
    assert is_lossless(_track(fmt="m4a", bitrate=257)) is False


# ──────────────────────────────────────────────────────────────────────────────
# pick_best
# ──────────────────────────────────────────────────────────────────────────────


def test_pick_best_empty_raises() -> None:
    """pick_best on an empty list raises ValueError."""
    with pytest.raises(ValueError, match="no candidates"):
        pick_best([])


def test_pick_best_single_candidate() -> None:
    """pick_best on a one-element list returns index 0."""
    assert pick_best([_track(fmt="mp3", bitrate=128)]) == 0


def test_pick_best_lossless_beats_lossy_regardless_of_order() -> None:
    """A lossless candidate is picked even when listed after a lossy one."""
    lossy = _track(fmt="m4a", bitrate=320, platform="soundcloud")
    lossless = _track(fmt="flac", bit_depth=16, sample_rate=44100, platform="qobuz")
    assert pick_best([lossy, lossless]) == 1
    assert pick_best([lossless, lossy]) == 0


def test_pick_best_hires_beats_cd_lossless() -> None:
    """Among lossless candidates, hi-res outranks CD-rate."""
    cd = _track(fmt="flac", bit_depth=16, sample_rate=44100)
    hires = _track(fmt="flac", bit_depth=24, sample_rate=96000, platform="tidal")
    assert pick_best([cd, hires]) == 1


def test_pick_best_higher_bitrate_wins_within_lossy_tier() -> None:
    """Within the same lossy tier, the higher claimed bitrate wins."""
    lower = _track(fmt="mp3", bitrate=256)
    higher = _track(fmt="mp3", bitrate=320, platform="soundcloud")
    assert pick_best([lower, higher]) == 1


def test_pick_best_filesize_tiebreaks_equal_quality() -> None:
    """With identical tier/depth/rate/bitrate, the larger filesize tiebreaks."""
    small = _track(fmt="flac", bit_depth=24, sample_rate=96000, filesize=40_000_000)
    large = _track(
        fmt="flac",
        bit_depth=24,
        sample_rate=96000,
        filesize=55_000_000,
        platform="tidal",
    )
    assert pick_best([small, large]) == 1


def test_pick_best_stable_on_full_ties() -> None:
    """Two fully-identical-quality candidates → the first-listed wins (stable)."""
    a = _track(fmt="flac", bit_depth=16, sample_rate=44100, platform="qobuz")
    b = _track(fmt="flac", bit_depth=16, sample_rate=44100, platform="tidal")
    assert pick_best([a, b]) == 0


# ──────────────────────────────────────────────────────────────────────────────
# pick_with_policy — empty
# ──────────────────────────────────────────────────────────────────────────────


def test_pick_with_policy_empty_returns_none_false() -> None:
    """Empty candidate list → (None, False): nothing picked, nothing lossy."""
    assert pick_with_policy([], lossless_only=False) == (None, False)
    assert pick_with_policy([], lossless_only=True) == (None, False)


# ──────────────────────────────────────────────────────────────────────────────
# pick_with_policy — lossless_only = False (default)
# ──────────────────────────────────────────────────────────────────────────────


def test_policy_open_picks_lossless_not_flagged() -> None:
    """lossless_only=False + lossless winner → picked, is_lossy_pick False."""
    lossy = _track(fmt="m4a", bitrate=320, platform="soundcloud")
    lossless = _track(fmt="flac", bit_depth=24, sample_rate=96000, platform="qobuz")
    idx, is_lossy = pick_with_policy([lossy, lossless], lossless_only=False)
    assert idx == 1
    assert is_lossy is False


def test_policy_open_picks_lossy_when_only_lossy_and_flags_it() -> None:
    """lossless_only=False + only lossy candidates → best lossy picked, flagged."""
    aac = _track(fmt="m4a", bitrate=257, platform="soundcloud")
    mp3 = _track(fmt="mp3", bitrate=128, platform="youtube")
    idx, is_lossy = pick_with_policy([aac, mp3], lossless_only=False)
    assert idx == 0  # AAC 257 (HIGH_LOSSY) beats MP3 128 (STANDARD_LOSSY)
    assert is_lossy is True


def test_policy_open_single_lossy_candidate_flagged() -> None:
    """lossless_only=False + one lossy candidate → index 0, flagged lossy."""
    idx, is_lossy = pick_with_policy(
        [_track(fmt="m4a", bitrate=257, platform="soundcloud")],
        lossless_only=False,
    )
    assert idx == 0
    assert is_lossy is True


# ──────────────────────────────────────────────────────────────────────────────
# pick_with_policy — lossless_only = True
# ──────────────────────────────────────────────────────────────────────────────


def test_policy_strict_picks_lossless_when_present() -> None:
    """lossless_only=True + a lossless candidate exists → that one, not flagged."""
    lossy = _track(fmt="m4a", bitrate=320, platform="soundcloud")
    lossless = _track(fmt="flac", bit_depth=16, sample_rate=44100, platform="qobuz")
    idx, is_lossy = pick_with_policy([lossy, lossless], lossless_only=True)
    assert idx == 1
    assert is_lossy is False


def test_policy_strict_no_lossless_returns_none_true() -> None:
    """lossless_only=True + no lossless candidate → (None, True).

    The owner's hard rule: never a silent lossy download — the caller must
    surface "no lossless source found" and let the user decide.
    """
    aac = _track(fmt="m4a", bitrate=257, platform="soundcloud")
    mp3 = _track(fmt="mp3", bitrate=320, platform="youtube")
    idx, is_lossy = pick_with_policy([aac, mp3], lossless_only=True)
    assert idx is None
    assert is_lossy is True


def test_policy_strict_picks_best_lossless_among_several() -> None:
    """lossless_only=True picks the highest-quality lossless candidate."""
    cd = _track(fmt="flac", bit_depth=16, sample_rate=44100, platform="qobuz")
    hires = _track(fmt="flac", bit_depth=24, sample_rate=96000, platform="tidal")
    lossy = _track(fmt="m4a", bitrate=320, platform="soundcloud")
    idx, is_lossy = pick_with_policy([lossy, cd, hires], lossless_only=True)
    assert idx == 2  # the hi-res FLAC
    assert is_lossy is False


def test_policy_strict_ignores_lossy_even_if_higher_bitrate() -> None:
    """lossless_only=True never picks lossy, even a 320 kbps one over a CD FLAC."""
    fat_lossy = _track(fmt="mp3", bitrate=320, platform="soundcloud")
    cd_flac = _track(fmt="flac", bit_depth=16, sample_rate=44100, platform="qobuz")
    idx, is_lossy = pick_with_policy([fat_lossy, cd_flac], lossless_only=True)
    assert idx == 1
    assert is_lossy is False
