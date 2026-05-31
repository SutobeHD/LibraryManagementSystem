"""Pure (dependency-free) decision logic for the library format converter.

These functions carry the correctness-critical choices — FFmpeg codec args
(wrong args silently corrupt the output / shift the beatgrid), bit-depth
detection, target-size estimation and the disk pre-flight verdict. They are
deliberately split out from the rbox/FFmpeg/subprocess orchestration
(`app/format_converter.py`, runner-only) so they are unit-testable without
FFmpeg, rbox or a real `master.db`.

Cross-refs: research doc `library-format-converter` Steps 3-6, OQ1/OQ3/OQ4/OQ6.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

VALID_TARGETS = ("AIFF", "FLAC", "WAV", "MP3")


@dataclass(frozen=True)
class TargetSpec:
    extension: str
    # Multiplier vs source bytes for disk pre-flight (OQ4). Lossless PCM expands
    # ~5.5x from AAC; FLAC ~3x; MP3 re-encode ~1x. Conservative upper bounds.
    expansion_ratio: float
    lossless: bool
    # Rekordbox `DjmdContent.FileType` integer the engine writes via
    # `update_content` so RB renders the right Kind. Values per pyrekordbox /
    # rekordbox6 conventions (MP3=1, M4A=4, FLAC=5, WAV=11, AIFF=12).
    # PROVISIONAL — byte-level RB value, MUST be verified against a real
    # master.db / pyrekordbox FileType enum before graduating to implemented_
    # (CLAUDE.md byte-verification rule). Pinned by test_format_swap so any
    # change is deliberate. M4A=4 is the common source (kept for the engine's
    # reverse lookup), not a conversion target.
    rekordbox_file_type: int


TARGET_SPECS: dict[str, TargetSpec] = {
    "AIFF": TargetSpec(
        extension=".aiff", expansion_ratio=5.5, lossless=True, rekordbox_file_type=12
    ),
    "WAV": TargetSpec(extension=".wav", expansion_ratio=5.5, lossless=True, rekordbox_file_type=11),
    "FLAC": TargetSpec(
        extension=".flac", expansion_ratio=3.0, lossless=True, rekordbox_file_type=5
    ),
    "MP3": TargetSpec(extension=".mp3", expansion_ratio=1.0, lossless=False, rekordbox_file_type=1),
}

# Source FileType codes the engine may encounter (reverse lookup / reporting).
# M4A/AAC is the headline source. PROVISIONAL — verify with TARGET_SPECS values.
SOURCE_FILE_TYPES: dict[str, int] = {"MP3": 1, "M4A": 4, "FLAC": 5, "WAV": 11, "AIFF": 12}

# Disk pre-flight thresholds vs estimated target size (OQ4).
DISK_ABORT_FACTOR = 1.5
DISK_WARN_FACTOR = 1.2


def target_extension(target: str) -> str:
    return _spec(target).extension


def rekordbox_file_type(target: str) -> int:
    """The `DjmdContent.FileType` int the engine sets for a converted file."""
    return _spec(target).rekordbox_file_type


def _spec(target: str) -> TargetSpec:
    try:
        return TARGET_SPECS[target.upper()]
    except (AttributeError, KeyError) as e:
        raise ValueError(f"unknown target format {target!r}; valid: {VALID_TARGETS}") from e


def parse_bit_depth(ffprobe_out: str) -> int:
    """Map `ffprobe -show_entries stream=sample_fmt,bits_per_raw_sample` output
    to 16 or 24. `sample_fmt` is primary (OQ6); `bits_per_raw_sample` (often
    N/A for PCM) is the fallback. Anything ambiguous → 16 (safe, never upsamples
    a 16-bit source to a 24-bit container)."""
    text = (ffprobe_out or "").strip().lower()
    if not text:
        return 16
    tokens = re.split(r"[,\n\r\t ]+", text)
    for tok in tokens:
        if tok in ("s32", "s32p", "s24", "s24le", "s24be"):
            return 24
        if tok in ("s16", "s16p", "s16le", "s16be", "u8", "s8"):
            return 16
    # bits_per_raw_sample fallback: first 1-2 digit integer in the output.
    for tok in tokens:
        if tok.isdigit():
            return 24 if int(tok) >= 24 else 16
    return 16


def build_ffmpeg_cmd(
    ffmpeg_bin: str,
    src: str,
    dst: str,
    target: str,
    *,
    bit_depth: int = 16,
    sample_rate: int | None = None,
    mp3_quality: int = 0,
) -> list[str]:
    """Build the FFmpeg arg list (never a shell string — paths are list
    elements, defeating command injection, Threat CI-1).

    Invariants: `-vn` drops embedded art (RB artwork cache is content_id-keyed),
    `-map_metadata 0` preserves tags, `-ar <source SR>` locks the sample rate so
    no resample shifts cues/beatgrid (OQ1). `-y` overwrites the temp dst.
    """
    spec = _spec(target)
    cmd = [ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-i", src, "-vn", "-map_metadata", "0"]
    if sample_rate:
        cmd += ["-ar", str(int(sample_rate))]

    t = target.upper()
    if t in ("AIFF", "WAV"):
        cmd += ["-c:a", "pcm_s24le" if bit_depth >= 24 else "pcm_s16le"]
    elif t == "FLAC":
        # FLAC stores 24-bit samples in an s32 container.
        cmd += ["-c:a", "flac", "-sample_fmt", "s32" if bit_depth >= 24 else "s16"]
    elif t == "MP3":
        cmd += ["-c:a", "libmp3lame", "-q:a", str(int(mp3_quality)), "-write_id3v2", "1"]
    else:  # pragma: no cover - _spec already validated
        raise ValueError(f"unknown target {target!r}")

    cmd += ["-y", dst]
    _ = spec  # spec validated target; extension applied by the caller naming dst
    return cmd


def estimate_target_bytes(source_total_bytes: int, target: str) -> int:
    """Estimated on-disk size of the converted batch (sum of sources × ratio)."""
    return int(max(0, source_total_bytes) * _spec(target).expansion_ratio)


def disk_verdict(free_bytes: int, estimated_target_bytes: int) -> dict:
    """Pre-flight verdict (OQ4). Aborts before any write if free space can't
    hold target + snapshot-copies-of-originals + temp overhead (1.5x); warns at
    1.2x ('borderline, expect to need cleanup mid-run')."""
    need_abort = free_bytes < estimated_target_bytes * DISK_ABORT_FACTOR
    need_warn = (not need_abort) and free_bytes < estimated_target_bytes * DISK_WARN_FACTOR
    return {
        "abort": need_abort,
        "warning": need_warn,
        "free_bytes": int(free_bytes),
        "estimated_target_bytes": int(estimated_target_bytes),
        "abort_threshold_bytes": int(estimated_target_bytes * DISK_ABORT_FACTOR),
        "warn_threshold_bytes": int(estimated_target_bytes * DISK_WARN_FACTOR),
    }
