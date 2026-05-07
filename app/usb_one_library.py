"""
USB OneLibrary writer — uses rbox.OneLibrary to build PIONEER/rekordbox/exportLibrary.db
that CDJ-3000 (and other modern Pioneer hardware) reads natively.

Workflow:
  1. Create empty exportLibrary.db at PIONEER/rekordbox/
  2. Iterate LibrarySource → insert artists, albums, genres, keys, labels (deduped)
  3. Insert contents (tracks) with FK references
  4. Build playlist tree (folders → playlists → playlist_contents)
  5. Copy ANLZ sidecars from .lms_anlz/<hash>/ to PIONEER/USBANLZ/<bucket>/<hash>/
  6. Copy audio files to a stable USB layout
"""

from __future__ import annotations
import logging
import shutil
import hashlib
from pathlib import Path
from typing import Callable, Dict, List, Optional, Generator

logger = logging.getLogger(__name__)

try:
    import rbox
    RBOX_AVAILABLE = True
except Exception as e:
    rbox = None
    RBOX_AVAILABLE = False
    logger.warning(f"rbox library unavailable: {e}")


class OneLibraryUsbWriter:
    """
    Writes the modern Library One DB (exportLibrary.db) plus ANLZ sidecars
    and audio files to a USB stick CDJ-3000 understands.
    """

    def __init__(
        self,
        usb_root: str,
        dest_resolver: Optional[Callable[[str, str, str], Path]] = None,
    ):
        """
        dest_resolver(artist, album, filename) -> absolute Path on the USB.
        When provided, OneLibrary uses the SAME destination logic as the
        legacy XML writer so files are not copied twice into different
        directory trees. Falls back to an internal `_dest_audio_path` when
        no resolver is passed (older callers, tests).
        """
        if len(usb_root) == 2 and usb_root[1] == ":":
            usb_root = usb_root + "\\"
        self.usb_root = Path(usb_root)
        self.pioneer = self.usb_root / "PIONEER"
        self.rb_dir = self.pioneer / "rekordbox"
        self.anlz_root = self.pioneer / "USBANLZ"
        self.artwork_dir = self.pioneer / "Artwork"
        # Default music_dir aligned with UsbSyncEngine._get_safe_dest_path
        # so library_one and library_legacy can run side-by-side without
        # duplicating audio. The actual file path is determined by
        # `dest_resolver` when one is supplied.
        self.music_dir = self.pioneer / "Contents"
        self.db_path = self.rb_dir / "exportLibrary.db"
        self._dest_resolver = dest_resolver

    def ensure_structure(self):
        for d in (self.rb_dir, self.anlz_root, self.artwork_dir, self.music_dir):
            d.mkdir(parents=True, exist_ok=True)

    def sync(self, source, audio_copy: bool = True, copy_anlz: bool = True) -> Generator[Dict, None, None]:
        """Main entry: yields progress events."""
        if not RBOX_AVAILABLE:
            yield {"stage": "error", "message": "rbox library missing — cannot write OneLibrary", "progress": -1}
            return

        yield {"stage": "preparing", "message": "Creating USB structure", "progress": 1}
        self.ensure_structure()

        # Wipe + recreate exportLibrary.db (cleaner than diff-merge for now)
        if self.db_path.exists():
            try:
                self.db_path.unlink()
            except OSError as e:
                yield {"stage": "error", "message": f"Cannot remove old DB: {e}", "progress": -1}
                return

        try:
            # rbox.OneLibrary.create(path, my_tag_master_dbid)
            # my_tag_master_dbid: device-unique identifier for MyTags
            mytag_dbid = "lms_export_" + hashlib.sha1(str(self.usb_root).encode()).hexdigest()[:8]
            db = rbox.OneLibrary.create(str(self.db_path), mytag_dbid)
        except Exception as e:
            yield {"stage": "error", "message": f"OneLibrary.create failed: {e}", "progress": -1}
            return

        yield {"stage": "preparing", "message": "DB created. Building lookups…", "progress": 5}

        # Caches: name → id (avoid duplicate inserts)
        artist_cache: Dict[str, str] = {}
        album_cache: Dict[str, str] = {}
        genre_cache: Dict[str, str] = {}
        key_cache: Dict[str, str] = {}
        label_cache: Dict[str, str] = {}

        # Track id mapping: source-track-id → onelibrary content-id
        content_id_map: Dict[str, str] = {}

        all_tracks = list(source.iter_tracks())
        total = max(1, len(all_tracks))

        for i, t in enumerate(all_tracks):
            try:
                # Resolve refs (artist/album/genre/key/label)
                artist_id = self._get_or_create_artist(db, artist_cache, t["artist"])
                album_id = self._get_or_create_album(db, album_cache, t["album"], artist_id)
                genre_id = self._get_or_create_genre(db, genre_cache, t["genre"])
                key_id = self._get_or_create_key(db, key_cache, t["key"])
                label_id = self._get_or_create_label(db, label_cache, t["label"])

                # Audio file copy → USB
                src_path = Path(t["path"]) if t["path"] else None
                if audio_copy and src_path and src_path.exists():
                    if self._dest_resolver is not None:
                        dest_path = self._dest_resolver(
                            t.get("artist") or "",
                            t.get("album") or "",
                            src_path.name,
                        )
                    else:
                        dest_path = self._dest_audio_path(t, src_path)
                    if not dest_path.exists():
                        dest_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(str(src_path), str(dest_path))
                    usb_relative_path = "/" + str(dest_path.relative_to(self.usb_root)).replace("\\", "/")
                else:
                    usb_relative_path = ""

                # Insert content (track) — rbox API expects path as primary arg
                content = db.create_content(usb_relative_path)
                content_id = str(getattr(content, "id", "") or content)
                content_id_map[t["id"]] = content_id

                # Update track metadata
                try:
                    db.update_content(
                        content_id,
                        title=t["title"],
                        artist_id=artist_id,
                        album_id=album_id,
                        genre_id=genre_id,
                        key_id=key_id,
                        label_id=label_id,
                        bpm=int(t["bpm"] * 100) if t["bpm"] else 0,  # CDJ stores BPM × 100
                        rating=t["rating"] * 51 if t["rating"] else 0,  # 0–5 stars → 0–255
                        comment=t["comment"],
                        play_count=t["play_count"],
                        release_year=t["release_year"],
                        bitrate=t["bitrate"],
                    )
                except Exception as e:
                    logger.debug(f"update_content partial failure for {t['id']}: {e}")

                # ANLZ sidecar copy
                if copy_anlz:
                    self._copy_anlz_for(t, content_id, source)

                # Cover artwork copy → PIONEER/Artwork/
                self._copy_artwork(t, content_id)

                if i % 10 == 0 or i == total - 1:
                    yield {
                        "stage": "tracks",
                        "message": f"Imported {i+1}/{total}: {t['title'][:40]}",
                        "progress": 5 + int(70 * (i + 1) / total),
                    }
            except Exception as e:
                logger.warning(f"Track sync skipped (id={t.get('id')}): {e}")

        # Build playlist tree
        yield {"stage": "playlists", "message": "Writing playlist tree…", "progress": 80}
        self._write_playlists(db, source, content_id_map)

        yield {"stage": "complete", "message": f"OneLibrary export written: {len(content_id_map)} tracks", "progress": 100}

    # ─── helpers ─────────────────────────────────────────────────────────

    def _get_or_create_artist(self, db, cache: Dict, name: str) -> Optional[str]:
        if not name:
            return None
        if name in cache:
            return cache[name]
        try:
            existing = db.get_artist_by_name(name)
            if existing:
                cache[name] = str(existing.id)
                return cache[name]
        except Exception:
            pass
        try:
            obj = db.create_artist(name)
            cache[name] = str(obj.id)
            return cache[name]
        except Exception as e:
            logger.debug(f"create_artist failed for {name}: {e}")
            return None

    def _get_or_create_album(self, db, cache: Dict, name: str, artist_id: Optional[str]) -> Optional[str]:
        if not name:
            return None
        key = f"{name}|{artist_id or ''}"
        if key in cache:
            return cache[key]
        try:
            existing = db.get_album_by_name(name)
            if existing:
                cache[key] = str(existing.id)
                return cache[key]
        except Exception:
            pass
        try:
            obj = db.create_album(name, artist_id, None)
            cache[key] = str(obj.id)
            return cache[key]
        except Exception as e:
            logger.debug(f"create_album failed: {e}")
            return None

    def _get_or_create_genre(self, db, cache: Dict, name: str) -> Optional[str]:
        if not name:
            return None
        if name in cache:
            return cache[name]
        try:
            existing = db.get_genre_by_name(name)
            if existing:
                cache[name] = str(existing.id)
                return cache[name]
        except Exception:
            pass
        try:
            obj = db.create_genre(name)
            cache[name] = str(obj.id)
            return cache[name]
        except Exception:
            return None

    def _get_or_create_key(self, db, cache: Dict, name: str) -> Optional[str]:
        if not name:
            return None
        if name in cache:
            return cache[name]
        try:
            existing = db.get_key_by_name(name)
            if existing:
                cache[name] = str(existing.id)
                return cache[name]
        except Exception:
            pass
        try:
            obj = db.create_key(name)
            cache[name] = str(obj.id)
            return cache[name]
        except Exception:
            return None

    def _get_or_create_label(self, db, cache: Dict, name: str) -> Optional[str]:
        if not name:
            return None
        if name in cache:
            return cache[name]
        try:
            existing = db.get_label_by_name(name)
            if existing:
                cache[name] = str(existing.id)
                return cache[name]
        except Exception:
            pass
        try:
            obj = db.create_label(name)
            cache[name] = str(obj.id)
            return cache[name]
        except Exception:
            return None

    def _dest_audio_path(self, track: Dict, src_path: Path) -> Path:
        """Layout: <usb>/Contents/<Artist>/<Album>/<filename>"""
        from .usb_manager import UsbSyncEngine
        # Reuse FAT-safe filename logic if available
        artist = self._safe_segment(track["artist"] or "Unknown Artist")
        album = self._safe_segment(track["album"] or "Unknown Album")
        return self.music_dir / artist / album / src_path.name

    @staticmethod
    def _safe_segment(s: str) -> str:
        bad = '<>:"/\\|?*'
        out = "".join(c if c not in bad else "_" for c in s).strip()
        return out[:80] or "Unknown"

    def _copy_artwork(self, track: Dict, content_id: str) -> None:
        """Copy cover-art into PIONEER/Artwork/<bucket>/<hash>.jpg if available."""
        art = track.get("artwork")
        if not art:
            return
        src = Path(art)
        if not src.exists():
            return
        bucket = "P" + str(int(content_id) // 1000).zfill(3) if content_id.isdigit() else "P000"
        target_dir = self.artwork_dir / bucket
        target_dir.mkdir(parents=True, exist_ok=True)
        h = hashlib.sha1(content_id.encode()).hexdigest()[:8].upper()
        try:
            shutil.copy2(str(src), str(target_dir / f"{h}.jpg"))
        except Exception as e:
            logger.debug(f"Artwork copy skipped: {e}")

    def _copy_anlz_for(self, track: Dict, content_id: str, source) -> None:
        """Copy companion ANLZ files to the CDJ-bucket layout."""
        sidecar_dir = source.get_anlz_sidecar_dir(track)
        if not sidecar_dir or not sidecar_dir.exists():
            return
        # CDJ layout: PIONEER/USBANLZ/P000/<8-hex>/ANLZ0000.{DAT,EXT,2EX}
        bucket = "P" + str(int(content_id) // 1000).zfill(3) if content_id.isdigit() else "P000"
        h = hashlib.sha1(content_id.encode()).hexdigest()[:8].upper()
        target = self.anlz_root / bucket / h
        target.mkdir(parents=True, exist_ok=True)
        for src in sidecar_dir.glob("ANLZ*"):
            shutil.copy2(str(src), str(target / src.name))

    def _write_playlists(self, db, source, content_id_map: Dict[str, str]) -> None:
        """Walks playlist tree, creates folders / playlists, links tracks."""
        playlists = list(source.iter_playlists())
        # Build parent → children map
        by_parent: Dict[str, List[Dict]] = {}
        for p in playlists:
            by_parent.setdefault(p["parent_id"], []).append(p)

        # ID-translation: source-pid → onelibrary-pid
        id_map: Dict[str, str] = {"ROOT": None}

        def _emit(parent_src_id: str, parent_one_id):
            children = by_parent.get(parent_src_id, [])
            for seq, child in enumerate(children):
                try:
                    if child["type"] == "0":
                        obj = db.create_playlist_folder(child["name"], parent_one_id, seq) \
                            if hasattr(db, "create_playlist_folder") \
                            else db.create_playlist(child["name"], parent_one_id, seq)
                    else:
                        obj = db.create_playlist(child["name"], parent_one_id, seq)
                    one_id = str(getattr(obj, "id", obj))
                    id_map[child["id"]] = one_id
                    # Link tracks (skip for folders/smart-without-materialised)
                    if child["type"] in ("1", "4"):
                        for ti, t_src_id in enumerate(child["track_ids"]):
                            content_id = content_id_map.get(str(t_src_id))
                            if content_id:
                                try:
                                    db.create_playlist_content(one_id, content_id, ti)
                                except Exception as e:
                                    logger.debug(f"playlist_content link failed: {e}")
                    _emit(child["id"], one_id)
                except Exception as e:
                    logger.warning(f"playlist '{child['name']}' skipped: {e}")

        _emit("ROOT", None)
