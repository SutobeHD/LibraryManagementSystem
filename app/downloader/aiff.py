"""AIFF post-download conversion — bit-depth-aware (D4).

The unified downloader's single AIFF converter. Lossless sources are lifted
into an uncompressed PCM AIFF container; lossy sources are left untouched
(no fake-lossless re-encode — see Findings § "Quality policy hardening").

Bit depth is preserved: a 24-bit FLAC/ALAC/WAV source becomes a 24-bit AIFF
(``pcm_s24le``), a 16-bit source becomes a 16-bit AIFF (``pcm_s16le``). The
old SC-only ``_convert_to_aiff`` hardcoded ``pcm_s16le`` and silently
downgraded hi-res sources — this module is the fix, and the SC pipeline is
re-pointed here so there is exactly one AIFF converter.

``-map_metadata 0`` carries source tags through the conversion; the caller
(orchestrator) overlays its own additions (provenance, genre, ISRC) via
``audio_tags.write_tags`` afterwards.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from ..config import FFMPEG_BIN

logger = logging.getLogger("DOWNLOADER_AIFF")

#: Lossless containers that are worth swapping into an AIFF wrapper.
_LOSSLESS_SUFFIXES = (".flac", ".alac", ".wav")

#: ``.m4a`` is a container that, for our sources, may hold either ALAC
#: (lossless) or AAC (lossy). It is probed at conversion time rather than
#: assumed — see :func:`convert_to_aiff`.
_AMBIGUOUS_SUFFIXES = (".m4a", ".mp4")

#: Suffixes that are already AIFF — conversion is a no-op passthrough.
_AIFF_SUFFIXES = (".aiff", ".aif")

#: ffprobe codec names that mean "lossy" — an ``.m4a`` carrying one of these
#: must NOT be re-containered into AIFF (would be fake-lossless).
_LOSSY_CODECS = frozenset({"aac", "mp3", "vorbis", "opus", "ac3", "wmav2"})

_FFPROBE_TIMEOUT = 10  # seconds — metadata probe only
_CONVERT_TIMEOUT = 300  # seconds — full transcode of files up to ~500 MB


def _ffprobe_bin() -> str:
    """Resolve the ffprobe binary from the configured ffmpeg path.

    ``FFMPEG_BIN`` is the project-wide ffmpeg handle (a bare name or a full
    path). ffprobe ships alongside ffmpeg, so the sibling binary is derived
    by name substitution rather than a separate config knob.
    """
    return FFMPEG_BIN.replace("ffmpeg", "ffprobe")


def _probe_audio_stream(src: Path) -> dict[str, str]:
    """Return the first audio stream's ffprobe info dict (empty on failure).

    ffprobe's ``-of json`` emits every ``stream=...`` value as a JSON string,
    so the result is narrowed to ``dict[str, str]`` — non-string entries (if
    any ever appear) are dropped rather than passed on untyped.
    """
    cmd = [
        _ffprobe_bin(),
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=codec_name,bits_per_raw_sample,sample_fmt",
        "-of",
        "json",
        str(src),
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=_FFPROBE_TIMEOUT).stdout
        streams = json.loads(out).get("streams") or [{}]
        first = streams[0] if isinstance(streams[0], dict) else {}
        return {k: v for k, v in first.items() if isinstance(v, str)}
    except (subprocess.SubprocessError, OSError, json.JSONDecodeError, ValueError) as exc:
        logger.debug("ffprobe failed for %s: %s", src, exc)
        return {}


def detect_bit_depth(src: Path) -> int:
    """Return 24 if the source is 24-bit (or wider) lossless, else 16.

    Best-effort via ffprobe. Two signals are checked:

    * ``bits_per_raw_sample`` >= 24 — the explicit, authoritative case.
    * ``sample_fmt`` ending in ``32`` / ``32p`` while ``bits_per_raw_sample``
      is not 16 — some 24-bit FLACs are decoded into a 32-bit sample format
      and report no ``bits_per_raw_sample``; treat those as 24-bit.

    Falls back to 16 on any probe failure (the safe, never-downgrade-by-
    accident default for the common 16/44.1 case).
    """
    info = _probe_audio_stream(src)
    try:
        bps = int(info.get("bits_per_raw_sample") or 0)
    except (TypeError, ValueError):
        bps = 0
    if bps >= 24:
        return 24
    sample_fmt = str(info.get("sample_fmt") or "")
    if sample_fmt.endswith(("32", "32p")) and bps != 16:
        return 24
    return 16


def _is_lossy_m4a(src: Path) -> bool:
    """True if an ``.m4a`` / ``.mp4`` source carries a lossy codec (AAC).

    Re-containering AAC into AIFF produces a misleading "lossless-looking"
    file without recovering any quality — explicitly forbidden by D4. A
    lossy ``.m4a`` therefore stays ``.m4a``.
    """
    codec = str(_probe_audio_stream(src).get("codec_name") or "").lower()
    return codec in _LOSSY_CODECS


def convert_to_aiff(src: Path) -> Path | None:
    """Convert a lossless source to a bit-depth-matched AIFF.

    Behaviour by source type:

    * Already ``.aiff`` / ``.aif`` — returned unchanged (no-op).
    * ``.flac`` / ``.alac`` / ``.wav`` — converted; bit depth preserved.
    * ``.m4a`` / ``.mp4`` — probed: ALAC is converted, AAC is left as-is
      (returns the original path, *not* ``None`` — it is a valid keep).
    * Any lossy container (``.mp3`` / ``.aac`` / ``.ogg`` / ``.opus``) —
      returns ``None`` to signal "no conversion; caller keeps the original".

    On a successful conversion the source file is deleted (its bytes now
    live in the AIFF) and the AIFF path is returned. On any ffmpeg failure
    the partial AIFF is removed and ``None`` is returned so the caller falls
    back to the untouched source.
    """
    suffix = src.suffix.lower()
    if suffix in _AIFF_SUFFIXES:
        return src

    if suffix in _AMBIGUOUS_SUFFIXES:
        if _is_lossy_m4a(src):
            logger.info("Lossy AAC source — keeping original, no AIFF: %s", src.name)
            return src
    elif suffix not in _LOSSLESS_SUFFIXES:
        # Genuinely lossy container — caller decides what to do with it.
        return None

    bit_depth = detect_bit_depth(src)
    codec = "pcm_s24le" if bit_depth == 24 else "pcm_s16le"
    dst = src.with_suffix(".aiff")
    cmd = [
        FFMPEG_BIN,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(src),
        "-c:a",
        codec,
        "-map_metadata",
        "0",
        "-vn",  # drop embedded artwork — re-applied via mutagen afterwards
        "-y",
        str(dst),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=_CONVERT_TIMEOUT)
    except subprocess.TimeoutExpired:
        logger.error("ffmpeg AIFF conversion timed out for %s", src.name)
        dst.unlink(missing_ok=True)
        return None
    except OSError as exc:
        logger.error("ffmpeg unavailable for AIFF conversion: %s", exc)
        return None

    if result.returncode != 0 or not dst.exists() or dst.stat().st_size < 1024:
        logger.error(
            "AIFF conversion failed (code=%s): %s",
            result.returncode,
            (result.stderr or "")[:300],
        )
        dst.unlink(missing_ok=True)
        return None

    logger.info(
        "Converted to AIFF (%d-bit): %s (%d bytes)",
        bit_depth,
        dst.name,
        dst.stat().st_size,
    )
    src.unlink(missing_ok=True)
    return dst


__all__ = ["convert_to_aiff", "detect_bit_depth"]
