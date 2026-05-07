"""USB artwork extraction + bucketed write to PIONEER/Artwork/.

Pioneer's Rekordbox stores cover art as two JPEG variants per track:
  PIONEER/Artwork/<bucket>/a<N>.jpg     ~3 KB  — small thumbnail   (CDJ list view)
  PIONEER/Artwork/<bucket>/a<N>_m.jpg   ~20 KB — medium / now-playing  (CDJ now-playing)

Where:
  <bucket> = zero-padded artwork-id-page index (`f"{image_id // 1000:05d}"`)
             — keeps each directory sane for FAT32 and matches Rekordbox's
             own bucketing on real export sticks.
  <N>      = the OneLibrary `image.id` integer (matches the FK on content)

Extraction order:
  1. Embedded ID3 APIC (MP3) / FLAC Picture / MP4 covr atom
  2. Sidecar `cover.jpg` next to the audio file
  3. None — caller falls back to no image_id reference

Returned image is always JPEG so the CDJ is happy regardless of the source
format (PNG, BMP, etc. all converted via Pillow).
"""
from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# CDJ-displayed thumbnail sizes — chosen empirically against F: drive's
# Rekordbox-exported artwork (~80x80 small, ~500x500 medium).
SMALL_SIZE  = (80,  80)
MEDIUM_SIZE = (500, 500)
JPEG_QUALITY_SMALL  = 80
JPEG_QUALITY_MEDIUM = 85


def _bucket_for(image_id: int) -> str:
    """Match Rekordbox's bucket layout: 1 bucket per 1000 image ids."""
    return f"{int(image_id) // 1000:05d}"


def _extract_embedded(audio_path: Path) -> Optional[bytes]:
    """Try to pull a cover image out of an audio file's embedded tags.

    Supports MP3 (APIC), FLAC (Picture block), MP4/M4A/AAC (covr atom).
    Returns the raw image bytes (any format) or None.
    """
    suffix = audio_path.suffix.lower()
    try:
        if suffix == ".mp3":
            from mutagen.id3 import ID3
            try:
                tags = ID3(str(audio_path))
            except Exception:
                return None
            for tag in tags.values():
                if tag.FrameID == "APIC" and getattr(tag, "data", None):
                    return tag.data
            return None

        if suffix == ".flac":
            from mutagen.flac import FLAC
            f = FLAC(str(audio_path))
            if f.pictures:
                return f.pictures[0].data
            return None

        if suffix in (".m4a", ".mp4", ".aac", ".alac"):
            from mutagen.mp4 import MP4
            f = MP4(str(audio_path))
            covers = f.tags.get("covr") if f.tags else None
            if covers:
                # MP4Cover bytes-like
                return bytes(covers[0])
            return None

        if suffix in (".ogg", ".opus"):
            # Vorbis comments rarely carry pictures inline — skip
            return None

        if suffix in (".wav", ".aiff", ".aif"):
            # ID3 in RIFF/AIFF container — try ID3 reader
            from mutagen.id3 import ID3
            try:
                tags = ID3(str(audio_path))
            except Exception:
                return None
            for tag in tags.values():
                if tag.FrameID == "APIC" and getattr(tag, "data", None):
                    return tag.data
            return None

    except Exception as exc:
        logger.debug("[artwork] embedded extraction failed for %s: %s", audio_path, exc)
        return None
    return None


def _extract_sidecar(audio_path: Path) -> Optional[bytes]:
    """Sidecar fallback — try common cover filenames next to the audio."""
    parent = audio_path.parent
    for name in ("cover.jpg", "cover.jpeg", "cover.png", "folder.jpg", "folder.png"):
        candidate = parent / name
        if candidate.is_file():
            try:
                return candidate.read_bytes()
            except OSError:
                continue
    return None


def get_artwork_bytes(audio_path: Path) -> Optional[bytes]:
    """Public single-shot extractor — embedded → sidecar → None.

    Returned bytes are guaranteed only to be a non-empty image; the caller
    must run them through Pillow to normalise to JPEG.
    """
    if not audio_path.is_file():
        return None
    return _extract_embedded(audio_path) or _extract_sidecar(audio_path)


def _resize_to_jpeg(raw: bytes, size: Tuple[int, int], quality: int) -> Optional[bytes]:
    """Decode any image format → resize → reencode as JPEG."""
    try:
        from PIL import Image
    except ImportError:
        logger.warning("[artwork] Pillow not installed — cannot resize artwork")
        return None
    try:
        img = Image.open(io.BytesIO(raw))
        # Some PNGs / TIFFs have alpha — flatten onto white before JPEG encode
        if img.mode in ("RGBA", "LA", "P"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            try:
                if img.mode == "P":
                    img = img.convert("RGBA")
                background.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
                img = background
            except Exception:
                img = img.convert("RGB")
        elif img.mode != "RGB":
            img = img.convert("RGB")
        # PIL 10+ uses Resampling.LANCZOS, older pre-10 uses Image.LANCZOS
        try:
            resample = Image.Resampling.LANCZOS
        except AttributeError:
            resample = Image.LANCZOS
        img.thumbnail(size, resample=resample)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        return buf.getvalue()
    except Exception as exc:
        logger.warning("[artwork] resize failed: %s", exc)
        return None


def write_artwork_pair(
    audio_path: Path,
    image_id: int,
    pioneer_dir: Path,
) -> Optional[Tuple[Path, Path]]:
    """Extract+write small/medium artwork JPEGs to the bucketed CDJ layout.

    Returns (small_path, medium_path) on success, or None when no usable art
    was found or Pillow is unavailable. Idempotent: skips writing if both
    target files already exist (per-track artwork doesn't change between
    syncs unless the source file changes).
    """
    bucket = _bucket_for(image_id)
    target_dir = pioneer_dir / "Artwork" / bucket
    target_dir.mkdir(parents=True, exist_ok=True)
    small_path  = target_dir / f"a{image_id}.jpg"
    medium_path = target_dir / f"a{image_id}_m.jpg"

    if small_path.exists() and medium_path.exists():
        return small_path, medium_path

    raw = get_artwork_bytes(audio_path)
    if not raw:
        logger.debug("[artwork] no embedded/sidecar art for %s", audio_path)
        return None

    small_bytes = _resize_to_jpeg(raw, SMALL_SIZE, JPEG_QUALITY_SMALL)
    medium_bytes = _resize_to_jpeg(raw, MEDIUM_SIZE, JPEG_QUALITY_MEDIUM)
    if not small_bytes and not medium_bytes:
        return None

    if small_bytes:
        small_path.write_bytes(small_bytes)
    if medium_bytes:
        medium_path.write_bytes(medium_bytes)

    logger.debug("[artwork] wrote %s + _m.jpg", small_path.name)
    return small_path, medium_path


def usb_relative_path(image_id: int, suffix: str = "") -> str:
    """Return the relative path string used inside the OneLibrary `image` row.

    Format: `/PIONEER/Artwork/<bucket>/a<id>.jpg`. When `suffix='_m'` returns
    the medium variant. The leading slash matches Rekordbox's own
    convention.
    """
    bucket = _bucket_for(image_id)
    return f"/PIONEER/Artwork/{bucket}/a{image_id}{suffix}.jpg"
