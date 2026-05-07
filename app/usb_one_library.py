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
        # Pioneer-canonical: audio at <USB>/Contents/, NOT under PIONEER/.
        # Verified against a real Rekordbox-exported stick. The actual final
        # path is determined by `dest_resolver` when one is supplied — the
        # legacy XML writer passes its own resolver so both writers land in
        # the same directory tree (no duplication).
        self.music_dir = self.usb_root / "Contents"
        self.db_path = self.rb_dir / "exportLibrary.db"
        self._dest_resolver = dest_resolver

    def ensure_structure(self):
        for d in (self.rb_dir, self.anlz_root, self.artwork_dir, self.music_dir):
            d.mkdir(parents=True, exist_ok=True)

        # Legacy export.pdb / exportExt.pdb policy:
        # * Stub disabled (default): DELETE any stale PDB left over from a
        #   previous Rekordbox-native sync. Without this Rekordbox shows an
        #   empty "Device Library" branch alongside our healthy "OneLibrary"
        #   branch — looks broken even though OneLibrary is fine.
        # * Stub enabled (`legacy_pdb_stub=true`): write the header-only
        #   stub so older CDJ firmware sees a valid (if empty) PDB. Real
        #   row encoders aren't implemented — see app/usb_pdb.py.
        try:
            from .services import SettingsManager
            stub_enabled = SettingsManager.load().get("legacy_pdb_stub", False)
        except Exception:
            stub_enabled = False

        if stub_enabled:
            try:
                from . import usb_pdb
                usb_pdb.write_export_pdb(self.usb_root)
                usb_pdb.write_export_ext_pdb(self.usb_root)
            except Exception as exc:
                logger.debug("[OneLibrary] legacy PDB stub skipped: %s", exc)
        else:
            for stale_name in ("export.pdb", "exportExt.pdb"):
                stale_path = self.rb_dir / stale_name
                if stale_path.exists():
                    try:
                        stale_path.unlink()
                        logger.info(
                            "[OneLibrary] removed stale %s (no row encoder yet — "
                            "prevents empty 'Device Library' branch in Rekordbox)",
                            stale_name,
                        )
                    except OSError as exc:
                        logger.warning("[OneLibrary] could not remove stale %s: %s",
                                       stale_path, exc)

    # Path to the bundled template DB (built by app.templates.build_template
    # from any Rekordbox-exported stick). The template ships with N
    # placeholder content rows that we mutate via update_content, working
    # around rbox 0.1.7's broken create_content path.
    TEMPLATE_DB = Path(__file__).parent / "templates" / "exportLibrary_template.db"

    def sync(self, source, audio_copy: bool = True, copy_anlz: bool = True) -> Generator[Dict, None, None]:
        """Main entry: yields progress events.

        TEMPLATE-BASED APPROACH (rbox 0.1.7 workaround):

        rbox 0.1.7's `OneLibrary.create()` returns a DB whose schema fails
        Diesel FK validation on every subsequent insert (verified
        empirically). Even on a real Rekordbox-created DB,
        `create_content(path)` raises "Unexpected null for non-null column".
        There is no Python-level constructor for `NewContent` so
        `insert_content` is unreachable too.

        Workaround: ship a clean template DB derived from a real Rekordbox
        export (see app/templates/build_template.py). The template contains
        N placeholder content rows. We copy it onto the USB, then mutate
        each row via `update_content` to populate user data — that path
        works fine. `create_image`, `create_artist`, `create_album` etc.
        also work, so reference tables get populated normally.

        Hard limit: the number of user tracks per OneLibrary sync is capped
        at the template's slot count (currently 16 from F: drive). Beyond
        that we skip the extras and log clearly. The legacy rekordbox.xml
        export (always written) covers the full library.
        """
        if not RBOX_AVAILABLE:
            yield {"stage": "error", "message": "rbox library missing — cannot write OneLibrary", "progress": -1}
            return

        if not self.TEMPLATE_DB.exists():
            logger.warning(
                "[OneLibrary] No template DB at %s — Rekordbox auto-detect "
                "will be unavailable. Build one with: python -m "
                "app.templates.build_template <path_to_rekordbox_stick>",
                self.TEMPLATE_DB,
            )
            yield {
                "stage": "warning",
                "message": (
                    "OneLibrary template missing — Rekordbox won't auto-detect this stick. "
                    "Run `python -m app.templates.build_template <Rekordbox-exported-stick>` "
                    "once to build the template, then re-sync. Legacy XML still works for manual import."
                ),
                "progress": 100,
            }
            return

        yield {"stage": "preparing", "message": "Creating USB structure", "progress": 1}
        self.ensure_structure()

        # Stage 1 — copy template to USB (DB + WAL + SHM together)
        for ext in ("", "-shm", "-wal"):
            src = Path(str(self.TEMPLATE_DB) + ext)
            dst = Path(str(self.db_path) + ext)
            dst.unlink(missing_ok=True)
            if src.exists():
                shutil.copy2(str(src), str(dst))
        logger.info("[OneLibrary] Copied template to %s (%d B)",
                    self.db_path, self.db_path.stat().st_size)

        try:
            db = rbox.OneLibrary(str(self.db_path))
        except Exception as e:
            logger.error("[OneLibrary] Failed to open templated DB: %s", e, exc_info=True)
            yield {"stage": "error", "message": f"Cannot open template DB: {e}", "progress": -1}
            return

        # Set our device-unique my_tag_master_dbid so different sticks have
        # distinct Property records (CDJ behaviour expectation).
        try:
            mytag_dbid = int(
                hashlib.sha1(str(self.usb_root).encode()).hexdigest()[:8], 16
            ) & 0x7FFFFFFF
            prop = list(db.get_properties())[0]
            prop.my_tag_master_dbid = mytag_dbid
            try:
                db.update_property(prop)
            except Exception as exc:
                logger.debug("[OneLibrary] update_property skipped: %s", exc)
        except Exception as exc:
            logger.debug("[OneLibrary] property dbid update skipped: %s", exc)

        yield {"stage": "preparing", "message": "Reading placeholder slots…", "progress": 5}

        # Sorted by id — gives deterministic slot allocation
        placeholders = sorted(db.get_contents(), key=lambda c: c.id)
        slot_count = len(placeholders)
        logger.info("[OneLibrary] Template provides %d content slots", slot_count)

        # Reference-table caches (these CAN be created fresh — only
        # create_content is broken, the others work).
        artist_cache: Dict[str, str] = {}
        album_cache: Dict[str, str] = {}
        genre_cache: Dict[str, str] = {}
        key_cache: Dict[str, str] = {}
        label_cache: Dict[str, str] = {}

        # Pre-warm caches with what's already in the template
        try:
            for a in db.get_artists():
                artist_cache.setdefault((a.name or ""), str(a.id))
            for a in db.get_albums():
                album_cache.setdefault((a.name or ""), str(a.id))
            for g in db.get_genres():
                genre_cache.setdefault((g.name or ""), str(g.id))
            for k in db.get_keys():
                key_cache.setdefault((k.name or ""), str(k.id))
            for lab in db.get_labels():
                label_cache.setdefault((lab.name or ""), str(lab.id))
        except Exception as exc:
            logger.debug("[OneLibrary] cache pre-warm skipped: %s", exc)

        content_id_map: Dict[str, str] = {}
        all_tracks = list(source.iter_tracks())
        total = len(all_tracks)
        used_slots = 0
        skipped_overflow = 0

        # Stage 2 — populate slots via update_content (the working path)
        for i, t in enumerate(all_tracks):
            if i >= slot_count:
                skipped_overflow += 1
                continue
            try:
                slot = placeholders[i]

                # Resolve refs
                artist_id = self._get_or_create_artist(db, artist_cache, t.get("artist") or "")
                album_id = self._get_or_create_album(db, album_cache, t.get("album") or "", artist_id)
                genre_id = self._get_or_create_genre(db, genre_cache, t.get("genre") or "")
                key_id = self._get_or_create_key(db, key_cache, t.get("key") or "")
                label_id = self._get_or_create_label(db, label_cache, t.get("label") or "")

                # Audio file copy → USB (Pioneer-canonical /Contents/<Artist>/<Title>/)
                src_path = Path(t["path"]) if t.get("path") else None
                if audio_copy and src_path and src_path.exists():
                    if self._dest_resolver is not None:
                        dest_path = self._dest_resolver(
                            t.get("artist") or "",
                            t.get("title") or "",
                            src_path.name,
                        )
                    else:
                        dest_path = self._dest_audio_path(t, src_path)
                    if not dest_path.exists():
                        dest_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(str(src_path), str(dest_path))
                    usb_rel_path = "/" + str(dest_path.relative_to(self.usb_root)).replace("\\", "/")
                else:
                    usb_rel_path = ""

                # Mutate the placeholder slot with user track data
                slot.title = t.get("title") or ""
                slot.title_for_search = (t.get("title") or "").lower()
                slot.subtitle = ""
                slot.path = usb_rel_path
                slot.file_name = (src_path.name if src_path else "")
                slot.dj_comment = t.get("comment") or ""
                slot.bpmx100 = int((t.get("bpm") or 0) * 100)
                slot.length = int((t.get("duration_ms") or 0) / 1000)
                slot.rating = int(t.get("rating") or 0) * 51  # 0-5 → 0-255
                slot.release_year = int(t.get("release_year") or 0)
                slot.bitrate = int(t.get("bitrate") or 0)
                slot.isrc = ""
                if artist_id is not None:
                    slot.artist_id = int(artist_id)
                if album_id is not None:
                    slot.album_id = int(album_id)
                if genre_id is not None:
                    slot.genre_id = int(genre_id)
                if key_id is not None:
                    slot.key_id = int(key_id)
                if label_id is not None:
                    slot.label_id = int(label_id)

                # Artwork — extract embedded cover, write small+medium JPEGs
                # to PIONEER/Artwork/<bucket>/, point the existing image row
                # (image_id is preserved from the placeholder slot) at the
                # small variant. Done BEFORE update_content so the FK stays
                # valid in case the user-data overlay shifts image_id.
                if src_path and src_path.exists():
                    try:
                        self._write_track_artwork(db, slot, src_path)
                    except Exception as exc:
                        logger.debug("[OneLibrary] artwork skipped for slot %s: %s", slot.id, exc)

                # ANLZ sidecars (DAT/EXT/2EX) — beatgrid + cues + waveforms.
                # Done before update_content so the analysis_data_file_path
                # field can land in the same write.
                if copy_anlz:
                    try:
                        anlz_rel = self._generate_or_copy_anlz_for(t, str(slot.id), source)
                        if anlz_rel:
                            slot.analysis_data_file_path = anlz_rel
                    except Exception as exc:
                        logger.debug("[OneLibrary] ANLZ skipped for slot %s: %s", slot.id, exc)

                db.update_content(slot)
                content_id_map[t["id"]] = str(slot.id)
                used_slots += 1

                if i % 5 == 0 or i == slot_count - 1:
                    yield {
                        "stage": "tracks",
                        "message": f"Slot {i+1}/{slot_count}: {(t.get('title') or '?')[:40]}",
                        "progress": 5 + int(70 * (i + 1) / max(slot_count, 1)),
                    }
            except Exception as e:
                logger.warning(f"[OneLibrary] Slot {i} update failed for track {t.get('id')}: {e}",
                               exc_info=False)

        # Stage 3 — delete unused placeholder rows so the CDJ menu doesn't
        # show "__placeholder_X__" entries
        for unused in placeholders[used_slots:]:
            try:
                db.delete_content(unused.id)
            except Exception as exc:
                logger.debug(f"[OneLibrary] couldn't delete unused slot {unused.id}: {exc}")

        # Stage 4 — playlist tree (create_playlist works, no template needed)
        yield {"stage": "playlists", "message": "Writing playlist tree…", "progress": 80}
        try:
            self._write_playlists(db, source, content_id_map)
        except Exception as e:
            logger.warning(f"[OneLibrary] playlist tree write skipped: {e}")

        # Final summary
        if skipped_overflow > 0:
            yield {
                "stage": "warning",
                "message": (
                    f"OneLibrary: {used_slots}/{total} tracks written "
                    f"({skipped_overflow} skipped — template has only {slot_count} slots). "
                    f"Rebuild template from a Rekordbox stick with more tracks for a higher cap. "
                    f"All {total} tracks are in rekordbox.xml for manual import."
                ),
                "progress": 100,
            }
        else:
            yield {
                "stage": "complete",
                "message": f"OneLibrary export written: {used_slots} tracks",
                "progress": 100,
            }

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

    def _write_track_artwork(self, db, slot, audio_path: Path) -> None:
        """Generate the bucketed artwork pair for one track and update the
        OneLibrary `image` row to point at the small JPEG.

        Reuses whichever image_id the placeholder slot already references
        (template-baseline images carry empty paths after anonymisation).
        """
        from . import usb_artwork

        image_id = getattr(slot, "image_id", None)
        if image_id in (None, 0):
            # No FK — try to create a fresh image row (works on real DBs).
            try:
                img = db.create_image(usb_artwork.usb_relative_path(1))  # placeholder path
                image_id = int(img.id)
                slot.image_id = image_id
            except Exception as exc:
                logger.debug("[OneLibrary] create_image failed: %s", exc)
                return

        result = usb_artwork.write_artwork_pair(audio_path, int(image_id), self.pioneer)
        if not result:
            return  # no embedded art — leave existing image FK in place

        # Point the image record at our small JPEG so CDJ list-view can find it
        try:
            img_row = db.get_image_by_id(int(image_id))
            if img_row is not None:
                img_row.path = usb_artwork.usb_relative_path(int(image_id))
                db.update_image(img_row)
        except Exception as exc:
            logger.debug("[OneLibrary] update_image path skipped: %s", exc)

    def _dest_audio_path(self, track: Dict, src_path: Path) -> Path:
        """Pioneer-canonical layout: <usb>/Contents/<Artist>/<Title>/<filename>.

        Used as a fallback when no `dest_resolver` is supplied. Title (not
        Album) is the second segment to match Rekordbox's own export format.
        """
        artist = self._safe_segment(track.get("artist") or "Unknown Artist")
        title = self._safe_segment(track.get("title") or src_path.stem or "Unknown Title")
        return self.music_dir / artist / title / src_path.name

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

    @staticmethod
    def _anlz_bucket(content_id: int) -> tuple:
        """CDJ bucket layout: PIONEER/USBANLZ/P<bucket-hex>/<inner-hex>/.

        Real Rekordbox exports use bucket = `P{(id // 256):03X}` and inner =
        `{id:08X}`. Both are upper-case hex. Verified against an F: drive
        export. The exact convention isn't strictly required — Rekordbox
        and CDJs read the path from the DB — but matching it makes the
        result indistinguishable from a real Rekordbox stick.
        """
        cid = max(int(content_id), 0)
        bucket = f"P{(cid // 256):03X}".upper()
        inner = f"{cid:08X}".upper()
        return bucket, inner

    def _generate_or_copy_anlz_for(
        self, track: Dict, content_id: str, source,
    ) -> Optional[str]:
        """Drop the per-track ANLZ sidecar trio into PIONEER/USBANLZ/.

        Strategy:
          1. Look for cached sidecars in <music_dir>/.lms_anlz/<hash>/ —
             written at import-time by `anlz_sidecar.write_companion_anlz`.
             If present, just copy.
          2. Otherwise run the analysis on demand (slow but bounded — same
             code path as the importer uses) and cache the output.
          3. Either way, copy the resulting DAT/EXT/2EX into the CDJ
             bucket layout so they ride out to the stick.

        Returns the relative `analysis_data_file_path` (matches
        Rekordbox's own value in exportLibrary.db) or None on failure.
        """
        sidecar_dir = source.get_anlz_sidecar_dir(track)

        # Auto-generate if no cached sidecar — but only if we have an audio
        # source. Streaming pseudo-tracks (SoundCloud URI etc.) get None.
        if not (sidecar_dir and sidecar_dir.exists()):
            audio_path_str = track.get("path")
            if not audio_path_str:
                return None
            audio_path = Path(audio_path_str)
            if not audio_path.exists():
                return None
            try:
                from . import anlz_sidecar
                sidecar_dir = anlz_sidecar.write_companion_anlz(audio_path)
            except Exception as exc:
                logger.debug("[ANLZ] generation failed for %s: %s", audio_path.name, exc)
                return None
            if not sidecar_dir or not sidecar_dir.exists():
                return None

        bucket, inner = self._anlz_bucket(int(content_id))
        target_dir = self.anlz_root / bucket / inner
        target_dir.mkdir(parents=True, exist_ok=True)

        copied = []
        for src in sidecar_dir.glob("ANLZ*"):
            dst = target_dir / src.name
            try:
                shutil.copy2(str(src), str(dst))
                copied.append(src.name)
            except OSError as exc:
                logger.debug("[ANLZ] copy %s -> %s failed: %s", src, dst, exc)

        if not copied:
            return None

        # Relative path stored in OneLibrary `content.analysis_data_file_path`
        # — must point at the .DAT specifically (CDJ infers .EXT/.2EX from there)
        return f"/PIONEER/USBANLZ/{bucket}/{inner}/ANLZ0000.DAT"

    # Back-compat shim — old `_copy_anlz_for` callers should switch to
    # `_generate_or_copy_anlz_for`. Kept while we transition the call sites.
    def _copy_anlz_for(self, track: Dict, content_id: str, source) -> None:
        self._generate_or_copy_anlz_for(track, content_id, source)

    def _write_playlists(self, db, source, content_id_map: Dict[str, str]) -> None:
        """Walks playlist tree, creates folders / playlists, links tracks.

        rbox 0.1.7 caveat: `create_playlist_content(playlist_id, content_id,
        seq)` rejects str ids with TypeError ("'str' object cannot be
        interpreted as an integer"). Earlier code stored ids as str and the
        TypeError got silently swallowed — playlists shipped to USB but were
        empty on the CDJ. We now pass ints throughout.

        System playlists like "Import" are filtered out — see
        usb_manager.EXCLUDED_USB_PLAYLISTS.
        """
        from .usb_manager import _is_excluded_playlist
        playlists = [
            p for p in source.iter_playlists()
            if not _is_excluded_playlist(p.get("name", ""))
        ]
        # Build parent → children map
        by_parent: Dict[str, List[Dict]] = {}
        for p in playlists:
            by_parent.setdefault(p["parent_id"], []).append(p)

        # ID-translation: source-pid → onelibrary-pid (kept as int)
        id_map: Dict[str, Optional[int]] = {"ROOT": None}

        def _emit(parent_src_id: str, parent_one_id: Optional[int]):
            children = by_parent.get(parent_src_id, [])
            for seq, child in enumerate(children):
                try:
                    if child["type"] == "0":
                        obj = db.create_playlist_folder(child["name"], parent_one_id, seq) \
                            if hasattr(db, "create_playlist_folder") \
                            else db.create_playlist(child["name"], parent_one_id, seq)
                    else:
                        obj = db.create_playlist(child["name"], parent_one_id, seq)
                    one_id = int(getattr(obj, "id", 0)) or None
                    id_map[child["id"]] = one_id
                    # Link tracks (skip for folders/smart-without-materialised).
                    # Both ids MUST be int for rbox's create_playlist_content.
                    if child["type"] in ("1", "4") and one_id is not None:
                        linked = 0
                        for ti, t_src_id in enumerate(child["track_ids"]):
                            content_id_str = content_id_map.get(str(t_src_id))
                            if not content_id_str:
                                continue
                            try:
                                db.create_playlist_content(
                                    int(one_id), int(content_id_str), ti,
                                )
                                linked += 1
                            except Exception as e:
                                logger.warning(
                                    "[OneLibrary] playlist_content link failed "
                                    "(pl=%s,content=%s): %s",
                                    one_id, content_id_str, e,
                                )
                        logger.info(
                            "[OneLibrary] playlist '%s' linked %d/%d tracks",
                            child["name"], linked, len(child["track_ids"]),
                        )
                    _emit(child["id"], one_id)
                except Exception as e:
                    logger.warning(f"playlist '{child['name']}' skipped: {e}")

        _emit("ROOT", None)
