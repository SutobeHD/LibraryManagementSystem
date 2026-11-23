"""USB artwork extraction + bucketed write to PIONEER/Artwork/.

Pioneer's Rekordbox stores cover art as two JPEG variants per track, each twice:
  PIONEER/Artwork/<bucket>/a<N>.jpg     ~3 KB  — small thumbnail   (CDJ list view)
  PIONEER/Artwork/<bucket>/a<N>_m.jpg   ~20 KB — medium / now-playing  (CDJ now-playing)
  PIONEER/Artwork/<bucket>/b<N>.jpg, b<N>_m.jpg — the same bytes again

Where:
  <bucket> = `f"{image_id // 20 + 1:05d}"`: 20 images per folder, first folder
             00001 (our F: reference stick has /PIONEER/Artwork/00001/a1.jpg;
             20 per folder and the b copies are from rbxport's captures of real
             Rekordbox exports, docs/reference/rbxport/export.md §5).
  <N>      = the OneLibrary `image.id` integer (matches the FK on content)

Extraction order:
  1. Embedded ID3 APIC (MP3) / FLAC Picture / MP4 covr atom
  2. Sidecar `cover.jpg` next to the audio file
  3. None — caller falls back to no image_id reference

Returned image is always JPEG so the CDJ is happy regardless of the source
format (PNG, BMP, etc. all converted via Pillow).

Slots are reused across syncs, so an image id can belong to another track next
time. `PIONEER/Artwork/.lms-artwork.json` maps each image id to a digest of the
source image (plus the resize recipe): a slot is rewritten when that digest
changes and left alone when it matches. After a sync `prune_artwork` removes the
files of image ids the new database no longer points at.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# CDJ-displayed thumbnail sizes — chosen empirically against F: drive's
# Rekordbox-exported artwork (~80x80 small, ~500x500 medium).
SMALL_SIZE = (80, 80)
MEDIUM_SIZE = (500, 500)
JPEG_QUALITY_SMALL = 80
JPEG_QUALITY_MEDIUM = 85

MANIFEST_NAME = ".lms-artwork.json"
_RECIPE = f"{SMALL_SIZE}|{MEDIUM_SIZE}|{JPEG_QUALITY_SMALL}|{JPEG_QUALITY_MEDIUM}".encode()
_ART_FILE = re.compile(r"^[ab](\d+)(?:_m)?\.jpg$", re.IGNORECASE)
_BUCKET_DIR = re.compile(r"^\d{5}$")


def _bucket_for(image_id: int) -> str:
    """Rekordbox's artwork folder for an image id: 20 ids per folder, starting at 00001."""
    return f"{int(image_id) // 20 + 1:05d}"


def _extract_embedded(audio_path: Path) -> bytes | None:
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


def _extract_sidecar(audio_path: Path) -> bytes | None:
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


def get_artwork_bytes(audio_path: Path) -> bytes | None:
    """Public single-shot extractor — embedded → sidecar → None.

    Returned bytes are guaranteed only to be a non-empty image; the caller
    must run them through Pillow to normalise to JPEG.
    """
    if not audio_path.is_file():
        return None
    return _extract_embedded(audio_path) or _extract_sidecar(audio_path)


def _resize_to_jpeg(raw: bytes, size: tuple[int, int], quality: int) -> bytes | None:
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
            resample = Image.LANCZOS  # type: ignore[attr-defined]  # PIL re-exports the enum at module level; stubs miss it
        img.thumbnail(size, resample=resample)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        return buf.getvalue()
    except Exception as exc:
        logger.warning("[artwork] resize failed: %s", exc)
        return None


def source_digest(raw: bytes) -> str:
    """Identity of one source image under the current resize recipe."""
    return hashlib.sha1(_RECIPE + raw, usedforsecurity=False).hexdigest()


def load_manifest(pioneer_dir: Path) -> dict[str, str]:
    """{image id: source digest} of the artwork on the stick; empty when unreadable."""
    path = Path(pioneer_dir) / "Artwork" / MANIFEST_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items()}


def save_manifest(pioneer_dir: Path, manifest: dict[str, str]) -> None:
    folder = Path(pioneer_dir) / "Artwork"
    path = folder / MANIFEST_NAME
    tmp = path.with_name(path.name + ".tmp")
    try:
        folder.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        logger.warning("[artwork] manifest %s not written: %s", path, exc)


def write_artwork_pair(
    audio_path: Path,
    image_id: int,
    pioneer_dir: Path,
    manifest: dict[str, str] | None = None,
) -> tuple[Path, Path] | None:
    """Extract+write small/medium artwork JPEGs to the bucketed CDJ layout.

    Returns (small_path, medium_path) on success, or None when no usable art
    was found or Pillow is unavailable.

    With `manifest` ({image id: source digest}, updated in place) the four files
    are rewritten only when the source image differs from the one they were made
    from (another track in this slot, or a changed cover) and left untouched
    when it matches. Without a manifest every call writes.
    """
    bucket = _bucket_for(image_id)
    target_dir = pioneer_dir / "Artwork" / bucket
    small_path = target_dir / f"a{image_id}.jpg"
    medium_path = target_dir / f"a{image_id}_m.jpg"
    copies = [target_dir / f"b{image_id}.jpg", target_dir / f"b{image_id}_m.jpg"]

    raw = get_artwork_bytes(audio_path)
    if not raw:
        logger.debug("[artwork] no embedded/sidecar art for %s", audio_path)
        return None

    digest = source_digest(raw)
    key = str(int(image_id))
    if (
        manifest is not None
        and manifest.get(key) == digest
        and all(p.exists() for p in (small_path, medium_path, *copies))
    ):
        return small_path, medium_path

    small_bytes = _resize_to_jpeg(raw, SMALL_SIZE, JPEG_QUALITY_SMALL)
    medium_bytes = _resize_to_jpeg(raw, MEDIUM_SIZE, JPEG_QUALITY_MEDIUM)
    if not small_bytes and not medium_bytes:
        return None

    target_dir.mkdir(parents=True, exist_ok=True)
    if small_bytes:
        small_path.write_bytes(small_bytes)
        copies[0].write_bytes(small_bytes)
    if medium_bytes:
        medium_path.write_bytes(medium_bytes)
        copies[1].write_bytes(medium_bytes)
    if manifest is not None:
        # A variant that failed to encode fails the exists() check next time.
        manifest[key] = digest

    logger.debug("[artwork] wrote %s + _m.jpg", small_path.name)
    return small_path, medium_path


def prune_artwork(pioneer_dir: Path, live_ids: set[int], manifest: dict[str, str]) -> int:
    """Delete artwork files no image row of the new database points at.

    Touches only `[ab]<id>[_m].jpg` inside five-digit bucket folders: an id that
    is not live, or a live id outside its own bucket (left by an older layout).
    Emptied buckets are removed, stale manifest entries dropped. Returns the
    number of files deleted.
    """
    root = Path(pioneer_dir) / "Artwork"
    removed = 0
    try:
        buckets = [d for d in root.iterdir() if d.is_dir() and _BUCKET_DIR.match(d.name)]
    except OSError:
        buckets = []
    for bucket in buckets:
        try:
            names = os.listdir(bucket)
        except OSError:
            continue
        for name in names:
            m = _ART_FILE.match(name)
            if not m:
                continue
            image_id = int(m.group(1))
            if image_id in live_ids and bucket.name == _bucket_for(image_id):
                continue
            try:
                (bucket / name).unlink()
                removed += 1
            except OSError as exc:
                logger.warning("[artwork] stale %s not removed: %s", bucket / name, exc)
        try:
            if not os.listdir(bucket):
                bucket.rmdir()
        except OSError as exc:
            logger.debug("[artwork] bucket %s kept: %s", bucket, exc)
    for key in list(manifest):
        if not key.isdigit() or int(key) not in live_ids:
            del manifest[key]
    if removed:
        logger.info("[artwork] removed %d stale artwork file(s)", removed)
    return removed


def usb_relative_path(image_id: int, suffix: str = "") -> str:
    """Return the relative path string used inside the OneLibrary `image` row.

    Format: `/PIONEER/Artwork/<bucket>/a<id>.jpg`. When `suffix='_m'` returns
    the medium variant. The leading slash matches Rekordbox's own
    convention.
    """
    bucket = _bucket_for(image_id)
    return f"/PIONEER/Artwork/{bucket}/a{image_id}{suffix}.jpg"
