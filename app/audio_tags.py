"""
audio_tags — write metadata back to the source audio file.

Until now metadata edits (title, artist, comment, rating, genre, …) lived only
in the Rekordbox database / XML library. This module mirrors the changes onto
disk so the file's own ID3 / Vorbis / MP4 tags match — useful for portability
to other DJ apps, media players, and DJ pools.

Format coverage:
  * MP3            — ID3v2.4 (TIT2/TPE1/TALB/TCON/COMM, POPM rating, APIC)
  * FLAC           — Vorbis comments + Picture block
  * M4A / MP4 / AAC— iTunes-style atoms (©nam/©ART/©alb/©gen + covr)
  * OGG / OPUS     — Vorbis comments
  * AIFF / WAV     — ID3 chunk (mutagen.aiff / mutagen.wave)

Failures are non-fatal: if a file is locked, missing, or in an unsupported
format the function logs and returns False; the DB write still stands.
"""

from __future__ import annotations

import logging
import mimetypes
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("AUDIO_TAGS")

# Map app-level field names → format-agnostic keys we know how to write.
# The "rating" channel is special (POPM in ID3, "rating" Vorbis tag).
_FIELD_ALIASES = {
    "Title": "title", "Name": "title", "title": "title",
    "Artist": "artist", "ArtistName": "artist", "artist": "artist",
    "Album": "album", "album": "album",
    "Genre": "genre", "genre": "genre",
    "Comment": "comment", "Comments": "comment", "comment": "comment",
    "Rating": "rating", "rating": "rating",  # 0-5 stars in our DB
    "Year": "year", "year": "year",
    "Bpm": "bpm", "BPM": "bpm", "bpm": "bpm",
    "Key": "key", "key": "key",
}


def _normalize_fields(updates: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in (updates or {}).items():
        if v is None:
            continue
        canonical = _FIELD_ALIASES.get(k)
        if canonical:
            out[canonical] = v
    return out


def _rating_to_popm(stars: int) -> int:
    """Convert 0-5 star rating to ID3 POPM 0-255 byte (Windows Media scale)."""
    try:
        s = int(stars)
    except (TypeError, ValueError):
        return 0
    s = max(0, min(5, s))
    return {0: 0, 1: 1, 2: 64, 3: 128, 4: 196, 5: 255}[s]


def _write_mp3(path: Path, fields: Dict[str, Any], artwork: Optional[bytes]) -> bool:
    from mutagen.id3 import (
        ID3, ID3NoHeaderError, TIT2, TPE1, TALB, TCON, TYER, TBPM, TKEY,
        COMM, POPM, APIC,
    )
    try:
        try:
            tags = ID3(str(path))
        except ID3NoHeaderError:
            tags = ID3()

        if "title" in fields:    tags.delall("TIT2"); tags.add(TIT2(encoding=3, text=str(fields["title"])))
        if "artist" in fields:   tags.delall("TPE1"); tags.add(TPE1(encoding=3, text=str(fields["artist"])))
        if "album" in fields:    tags.delall("TALB"); tags.add(TALB(encoding=3, text=str(fields["album"])))
        if "genre" in fields:    tags.delall("TCON"); tags.add(TCON(encoding=3, text=str(fields["genre"])))
        if "year" in fields:     tags.delall("TYER"); tags.add(TYER(encoding=3, text=str(fields["year"])))
        if "bpm" in fields:      tags.delall("TBPM"); tags.add(TBPM(encoding=3, text=str(fields["bpm"])))
        if "key" in fields:      tags.delall("TKEY"); tags.add(TKEY(encoding=3, text=str(fields["key"])))
        if "comment" in fields:
            tags.delall("COMM")
            tags.add(COMM(encoding=3, lang="eng", desc="", text=str(fields["comment"])))
        if "rating" in fields:
            tags.delall("POPM")
            tags.add(POPM(email="rating@rb-editor", rating=_rating_to_popm(fields["rating"]), count=0))
        if artwork:
            tags.delall("APIC")
            tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=artwork))

        tags.save(str(path), v2_version=4)
        return True
    except Exception as exc:
        logger.warning("MP3 tag write failed for %s: %s", path, exc)
        return False


def _write_flac(path: Path, fields: Dict[str, Any], artwork: Optional[bytes]) -> bool:
    from mutagen.flac import FLAC, Picture
    try:
        f = FLAC(str(path))
        for src, dst in (
            ("title", "title"), ("artist", "artist"), ("album", "album"),
            ("genre", "genre"), ("year", "date"), ("bpm", "bpm"),
            ("key", "initialkey"), ("comment", "comment"),
        ):
            if src in fields:
                f[dst] = str(fields[src])
        if "rating" in fields:
            # FMPS-style rating: 0.0–1.0 float, 5 stars = 1.0
            try:
                stars = max(0, min(5, int(fields["rating"])))
                f["rating"] = str(stars / 5.0)
            except (TypeError, ValueError):
                pass
        if artwork:
            pic = Picture()
            pic.type = 3
            pic.mime = "image/jpeg"
            pic.desc = "Cover"
            pic.data = artwork
            f.clear_pictures()
            f.add_picture(pic)
        f.save()
        return True
    except Exception as exc:
        logger.warning("FLAC tag write failed for %s: %s", path, exc)
        return False


def _write_mp4(path: Path, fields: Dict[str, Any], artwork: Optional[bytes]) -> bool:
    from mutagen.mp4 import MP4, MP4Cover
    try:
        m = MP4(str(path))
        atom_map = {
            "title": "\xa9nam", "artist": "\xa9ART", "album": "\xa9alb",
            "genre": "\xa9gen", "year": "\xa9day", "comment": "\xa9cmt",
        }
        for src, atom in atom_map.items():
            if src in fields:
                m[atom] = [str(fields[src])]
        if "bpm" in fields:
            try:
                m["tmpo"] = [int(round(float(fields["bpm"])))]
            except (TypeError, ValueError):
                pass
        if "rating" in fields:
            # MP4 uses 0-100 in iTunes "rate" atom (custom freeform).
            try:
                stars = max(0, min(5, int(fields["rating"])))
                m["----:com.apple.iTunes:RATING"] = [str(stars * 20).encode()]
            except (TypeError, ValueError):
                pass
        if artwork:
            m["covr"] = [MP4Cover(artwork, imageformat=MP4Cover.FORMAT_JPEG)]
        m.save()
        return True
    except Exception as exc:
        logger.warning("MP4 tag write failed for %s: %s", path, exc)
        return False


def _write_ogg(path: Path, fields: Dict[str, Any], artwork: Optional[bytes]) -> bool:
    """Covers .ogg (Vorbis) and .opus (OggOpus). Artwork in Ogg is rare; skipped."""
    try:
        if path.suffix.lower() == ".opus":
            from mutagen.oggopus import OggOpus as Ogg
        else:
            from mutagen.oggvorbis import OggVorbis as Ogg
        f = Ogg(str(path))
        for src, dst in (
            ("title", "title"), ("artist", "artist"), ("album", "album"),
            ("genre", "genre"), ("year", "date"), ("bpm", "bpm"),
            ("key", "initialkey"), ("comment", "comment"),
        ):
            if src in fields:
                f[dst] = str(fields[src])
        f.save()
        return True
    except Exception as exc:
        logger.warning("OGG/OPUS tag write failed for %s: %s", path, exc)
        return False


def _write_aiff_wav(path: Path, fields: Dict[str, Any], artwork: Optional[bytes]) -> bool:
    """AIFF and WAV both store an ID3 chunk; mutagen has dedicated wrappers."""
    try:
        suffix = path.suffix.lower()
        if suffix == ".wav":
            from mutagen.wave import WAVE as Container
        else:  # .aiff / .aif
            from mutagen.aiff import AIFF as Container
        c = Container(str(path))
        if c.tags is None:
            c.add_tags()
        from mutagen.id3 import (
            TIT2, TPE1, TALB, TCON, TYER, TBPM, TKEY, COMM, POPM, APIC,
        )
        tags = c.tags
        if "title" in fields:    tags.delall("TIT2"); tags.add(TIT2(encoding=3, text=str(fields["title"])))
        if "artist" in fields:   tags.delall("TPE1"); tags.add(TPE1(encoding=3, text=str(fields["artist"])))
        if "album" in fields:    tags.delall("TALB"); tags.add(TALB(encoding=3, text=str(fields["album"])))
        if "genre" in fields:    tags.delall("TCON"); tags.add(TCON(encoding=3, text=str(fields["genre"])))
        if "year" in fields:     tags.delall("TYER"); tags.add(TYER(encoding=3, text=str(fields["year"])))
        if "bpm" in fields:      tags.delall("TBPM"); tags.add(TBPM(encoding=3, text=str(fields["bpm"])))
        if "key" in fields:      tags.delall("TKEY"); tags.add(TKEY(encoding=3, text=str(fields["key"])))
        if "comment" in fields:
            tags.delall("COMM")
            tags.add(COMM(encoding=3, lang="eng", desc="", text=str(fields["comment"])))
        if "rating" in fields:
            tags.delall("POPM")
            tags.add(POPM(email="rating@rb-editor", rating=_rating_to_popm(fields["rating"]), count=0))
        if artwork:
            tags.delall("APIC")
            tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=artwork))
        c.save()
        return True
    except Exception as exc:
        logger.warning("AIFF/WAV tag write failed for %s: %s", path, exc)
        return False


_DISPATCH = {
    ".mp3":  _write_mp3,
    ".flac": _write_flac,
    ".m4a":  _write_mp4, ".mp4": _write_mp4, ".aac": _write_mp4, ".alac": _write_mp4,
    ".ogg":  _write_ogg, ".opus": _write_ogg,
    ".aiff": _write_aiff_wav, ".aif": _write_aiff_wav, ".wav": _write_aiff_wav,
}


def write_tags(
    path: str | Path,
    updates: Dict[str, Any],
    artwork: Optional[bytes] = None,
) -> bool:
    """
    Mirror updates into the audio file's native tag format.

    Returns True on success, False on any failure (the DB write should still
    proceed regardless — file write-back is best-effort).
    """
    if not updates and not artwork:
        return True
    p = Path(path)
    if not p.is_file():
        logger.info("Skipping tag write — file not found: %s", path)
        return False
    handler = _DISPATCH.get(p.suffix.lower())
    if handler is None:
        logger.info("Skipping tag write — unsupported format: %s", p.suffix)
        return False
    fields = _normalize_fields(updates)
    if not fields and not artwork:
        return True
    try:
        return handler(p, fields, artwork)
    except PermissionError as exc:
        # Common on Windows when Rekordbox or another player holds the file.
        logger.warning("Tag write blocked (file in use): %s — %s", path, exc)
        return False
    except Exception as exc:
        logger.error("Tag write crashed for %s: %s", path, exc, exc_info=True)
        return False


def load_artwork(image_path: str | Path) -> Optional[bytes]:
    """Read an artwork file from disk into bytes, or None on any failure."""
    if not image_path:
        return None
    p = Path(image_path)
    if not p.is_file():
        return None
    try:
        return p.read_bytes()
    except Exception as exc:
        logger.warning("Could not load artwork %s: %s", image_path, exc)
        return None
