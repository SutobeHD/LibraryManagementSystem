import logging
import os
import re
import threading
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import rbox

from .anlz_safe import SafeAnlzParser

logger = logging.getLogger(__name__)

class LiveRekordboxDB:
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self._local = threading.local()
        self.tracks = {}
        self.playlists = []
        self.playlists_tracks = defaultdict(list)
        self.artists = []
        self.genres = []
        self.labels = []
        self.albums = []
        self._artist_id_to_name = {}
        self._label_id_to_name = {}
        self._album_id_to_name = {}
        self.loaded = False
        self.loading_status = "Idle"

    @property
    def db(self):
        """Thread-safe access to the database connection."""
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            logger.debug(f"Opening fresh connection for thread {threading.get_ident()}")
            self._local.conn = rbox.MasterDb(str(self.db_path))
        return self._local.conn

    def load(self) -> bool:
        """Loads the library from the live master.db.

        Beatgrid loading is dispatched to a background thread because
        it goes through subprocess-isolated rbox calls (see
        `app.anlz_safe`) and a buggy DB row could otherwise stall the
        library load. Tracks become visible in the UI immediately;
        beatgrids fill in as soon as the worker finishes (typically
        within a few seconds of the load returning).
        """
        try:
            logger.info("Opening Live Database...")
            # Trigger connection on main thread
            _ = self.db
            logger.info(f"Successfully opened live database at {self.db_path}")

            # Pre-load metadata maps for performance
            self._load_metadata_maps()

            # Load MyTags
            self._load_mytags()

            # 1. Load Tracks (Content)
            self._load_tracks()

            # 2. Load Playlists
            self._load_playlists()
            self._load_playlist_tracks()

            # 3. Load Cues (Hot Cues & Memory Cues)
            self._load_cues()

            # 4. Finalize metadata for UI (ID/path normalization, etc.)
            self._finalize_ui_metadata()

            self.loaded = True
            self.loading_status = "Idle"
            logger.info(
                f"LIVE LOAD COMPLETE: {len(self.tracks)} tracks, "
                f"{len(self.playlists)} playlists"
            )

            # 5. Beatgrids — kick off in background so a slow / panicking
            # rbox call cannot delay or break the foreground init path.
            self._start_beatgrid_background_load()

            return True
        except Exception as e:
            logger.error(f"Failed to load live database: {e}", exc_info=True)
            return False

    def _start_beatgrid_background_load(self) -> None:
        """Spawn a daemon thread to populate ANLZ beatgrids out of band."""
        if getattr(self, "_beatgrid_thread", None) and self._beatgrid_thread.is_alive():
            logger.debug("Beatgrid loader already running; skipping new spawn")
            return

        def _runner() -> None:
            try:
                self._load_beatgrids_from_anlz()
            except Exception as e:
                logger.error("Background beatgrid loader crashed: %s", e, exc_info=True)

        self._beatgrid_thread = threading.Thread(
            target=_runner,
            name="anlz-beatgrid-loader",
            daemon=True,
        )
        self._beatgrid_thread.start()
        logger.info("ANLZ beatgrid loader running in background")

    def _load_metadata_maps(self):
        """Creates ID -> Name maps for joined tables."""
        logger.info("Caching metadata maps (artists, genres, etc.)...")
        self.artist_map = {a.id: a.name for a in self.db.get_artists()}
        self.genre_map = {g.id: g.name for g in self.db.get_genres()}
        self.album_map = {a.id: a.name for a in self.db.get_albums()}
        self.label_map = {l.id: l.name for l in self.db.get_labels()}
        self.key_map = {k.id: k.name for k in self.db.get_keys()}

        # Extended metadata maps with graceful fallback. rbox versions older
        # than 0.1.5 don't expose composer/remixer/lyricist accessors at all,
        # so AttributeError + any rbox-internal error is silenced — log only.
        self.composer_map = {}
        try:
            self.composer_map = {c.id: c.name for c in self.db.get_composers()}
        except Exception as e:
            logger.debug("live_database: composer map unavailable (%s)", e)

        self.remixer_map = {}
        try:
            self.remixer_map = {r.id: r.name for r in self.db.get_remixers()}
        except Exception as e:
            logger.debug("live_database: remixer map unavailable (%s)", e)

        self.lyricist_map = {}
        try:
            self.lyricist_map = {l.id: l.name for l in self.db.get_lyricists()}
        except Exception as e:
            logger.debug("live_database: lyricist map unavailable (%s)", e)

        logger.info(f"Metadata maps cached. Artists: {len(self.artist_map)}, Genres: {len(self.genre_map)}")

    def _load_mytags(self):
            self.tag_id_to_name = {}
            self.track_to_tags = defaultdict(list)
            self.track_to_tag_ids = defaultdict(list)
            try:
                raw_tags = self.db.get_my_tags()
                for t in raw_tags:
                    tid = str(t.id) if hasattr(t, 'id') else None
                    name = getattr(t, 'name', 'Unknown')
                    if not tid: continue
                    self.tag_id_to_name[tid] = name

                    # Fetch contents for this specific tag
                    try:
                        tag_contents = self.db.get_my_tag_contents(tid)
                        for content in tag_contents:
                            cid = str(content.id)
                            self.track_to_tags[cid].append(name)
                            self.track_to_tag_ids[cid].append(tid)
                    except Exception as tag_err:
                        logger.warning(f"Failed to fetch contents for tag {name} ({tid}): {tag_err}")

                logger.info(f"MyTags loaded. Definitions: {len(self.tag_id_to_name)}, Mappings (tracks): {len(self.track_to_tag_ids)}")
            except Exception as e:
                logger.error(f"Failed to load MyTags: {e}")

    def _load_tracks(self):
        self.tracks = {}
        content_items = self.db.get_contents()
        for item in content_items:
            tid = str(item.id)
            # Map IDs to names using our pre-loaded maps
            artist = self.artist_map.get(item.artist_id, "")
            album = self.album_map.get(item.album_id, "")
            genre = self.genre_map.get(item.genre_id, "")
            label = self.label_map.get(item.label_id, "")
            key = self.key_map.get(item.key_id, "")

            self.tracks[tid] = {
                "ID": tid,
                "Title": getattr(item, 'title', ''),
                "Artist": artist,
                "Album": album,
                "BPM": float(getattr(item, 'bpm', 0) or 0) / 100.0 if getattr(item, 'bpm', 0) else 0.0,
                "Rating": int(getattr(item, 'rating', 0) or 0),
                "ColorID": int(getattr(item, 'color_id', 0) or 0),
                "Comment": getattr(item, 'commnt', ''),
                "MyTag": ", ".join(self.track_to_tags.get(tid, [])),
                "path": getattr(item, 'folder_path', ''),
                "Key": key,
                "Genre": genre,
                "Label": label,
                "TagIDs": self.track_to_tag_ids.get(tid, []), # NEU: For smart filtering
                "TotalTime": float(getattr(item, 'length', 0) or 0),
                "Artwork": getattr(item, 'image_path', getattr(item, 'image_file_path', '')),
                "Bitrate": int(getattr(item, 'bit_rate', 0) or 0),
                "PlayCount": int(getattr(item, 'dj_play_count', 0) or 0),
                "Composer": self.composer_map.get(getattr(item, 'composer_id', None), "") if hasattr(item, 'composer_id') else "",
                "Remixer": self.remixer_map.get(getattr(item, 'remixer_id', None), "") if hasattr(item, 'remixer_id') else "",
                "Lyricist": self.lyricist_map.get(getattr(item, 'lyricist_id', None), "") if hasattr(item, 'lyricist_id') else "",
                "Subtitle": getattr(item, 'subtitle', ""),
                "ReleaseYear": int(getattr(item, 'release_year', 0) or 0),
                "StockDate": str(getattr(item, 'stock_date', "")),
                "SampleRate": int(getattr(item, 'sample_rate', 0) or 0),
                "ISRC": getattr(item, 'isrc', "")
            }

    def _load_cues(self):
        """Loads Hot Cues and Memory Cues (djmdSongCue) for all tracks."""
        logger.info("Loading Cues (Hot Cues & Memory Points)...")
        try:
            # Check if get_cues is available (safe attribute check)
            if not hasattr(self.db, 'get_cues'):
                logger.warning("rbox.MasterDb does not support get_cues. Skipping cue load.")
                return

            all_cues = self.db.get_cues()
            count = 0

            # Pre-load all content IDs for fast lookup
            tracks_by_id = self.tracks

            for cue in all_cues:
                if not hasattr(cue, 'content_id'): continue
                cid = str(cue.content_id)

                if cid in tracks_by_id:
                    track = tracks_by_id[cid]
                    if "Cues" not in track:
                        track["Cues"] = []

                    # Convert cue object to dict safely
                    cue_data = {
                        "ID": str(cue.id) if hasattr(cue, 'id') else "",
                        "Type": int(getattr(cue, 'type', 0) or 0),
                        "InMsec": int(getattr(cue, 'in_msec', 0) or 0),
                        "Num": int(getattr(cue, 'hot_cue', 0) or 0), # Hot Cue Number (0 if memory cue)
                        "Comment": getattr(cue, 'commnt', "")
                    }
                    track["Cues"].append(cue_data)
                    count += 1

            logger.info(f"Loaded {count} cues across library.")
        except Exception as e:
            logger.error(f"Failed to load cues: {e}")

    def _load_beatgrids_from_anlz(self):
        """Loads high-precision beatgrid (PQTZ) from local Rekordbox ANLZ files.

        Runs the entire iteration in a subprocess worker via
        `SafeAnlzParser.load_all_beatgrids` so panics in `rbox`
        (`masterdb/database.rs:1162` unwrap on None) only kill the
        worker and not the FastAPI backend. Bisects on panic to
        identify the offending track id and blacklist it.

        Designed to run on a background thread (see
        `_start_beatgrid_background_load`); writes only to existing
        `self.tracks[tid]` dict entries (single-key add), which is safe
        under the GIL even with concurrent readers.
        """
        track_ids = list(self.tracks.keys())
        if not track_ids:
            logger.info("Beatgrid loader: no tracks to scan")
            return

        logger.info(
            "Beatgrid loader: scanning %d tracks (subprocess-isolated)...",
            len(track_ids),
        )
        parser = SafeAnlzParser()
        start = time.monotonic()
        try:
            beatgrids = parser.load_all_beatgrids(str(self.db_path), track_ids)
        except Exception as e:
            logger.error("ANLZ batch loader failed: %s", e, exc_info=True)
            beatgrids = {}
        finally:
            parser.shutdown()

        applied = 0
        for tid, entries in beatgrids.items():
            track = self.tracks.get(tid)
            if track is not None and entries:
                track["beatGrid"] = entries
                applied += 1

        elapsed = time.monotonic() - start
        logger.info(
            "Beatgrid loader done in %.2fs: scanned=%d linked=%d "
            "skipped=%d panics=%d",
            elapsed,
            len(track_ids),
            applied,
            parser.stats["bad_ids"],
            parser.stats["panics"],
        )

    def _load_playlists(self):
        self.playlists = []
        # Materialized and stashed so _load_playlist_tracks() can reuse it
        # instead of issuing a second get_playlists() DB scan.
        raw_playlists = list(self.db.get_playlists())
        self._raw_playlists = raw_playlists

        # Rbox Attribute values:  0 = normal playlist, 1 = folder, 4 = intelligent playlist
        # Frontend Type values:   "0" = folder, "1" = normal playlist, "4" = intelligent playlist
        # We must remap 0↔1 to match what PlaylistNode expects.
        ATTR_TO_TYPE = {0: "1", 1: "0", 4: "4"}

        for pl in raw_playlists:
            # rbox 0.1.7+ exposes `attribute` as a `builtins.PlaylistType` enum
            # object that is NOT hashable, so `ATTR_TO_TYPE.get(attr, "1")`
            # raised TypeError on every load. Coerce to int via explicit
            # value/int casting.
            raw_attr = getattr(pl, 'attribute', 0)
            try:
                attr = int(getattr(raw_attr, 'value', raw_attr))
            except (TypeError, ValueError):
                attr = 0
            pl_type = ATTR_TO_TYPE.get(attr, "1")  # default to playlist
            my_id = str(pl.id)

            # Update status for frontend feedback
            self.loading_status = f"Loading: {pl.name}"

            parent_id = str(pl.parent_id) if pl.parent_id else "ROOT"
            if parent_id.lower() == "root": parent_id = "ROOT"

            # pyrekordbox may expose smart playlist XML as 'SmartList', 'smart_list', or
            # via a raw attribute — try all known names so intelligent playlists aren't empty.
            smart_list_xml = None
            if pl_type == "4":
                for attr_name in ('SmartList', 'smart_list', 'smartList', 'criteria'):
                    val = getattr(pl, attr_name, None)
                    if val:
                        smart_list_xml = val
                        break
                if smart_list_xml is None:
                    logger.debug(f"Intelligent playlist '{pl.name}' has no smart_list XML. "
                                 f"Available attrs: {[a for a in dir(pl) if not a.startswith('_')]}")

            node_data = {
                "ID": my_id,
                "Name": pl.name,
                "ParentID": parent_id,
                "Type": pl_type,
                "Seq": pl.seq,
                "smart_list": smart_list_xml
            }
            self.playlists.append(node_data)

        # Ensure playlists are sorted by Seq for baseline
        self.playlists.sort(key=lambda x: x.get("Seq", 0))

    def _load_playlist_tracks(self):
        """Batch-load all playlist contents using rbox's native methods."""
        logger.info("Caching all playlist tracks via rbox...")
        try:
            self.playlists_tracks.clear()
            # Reuse the list materialized by _load_playlists() (runs first in
            # load()) — avoids a redundant second get_playlists() DB scan.
            playlists = self._raw_playlists
            count = 0
            for pl in playlists:
                pid = str(pl.id)
                # Correct method is db.get_playlist_songs(playlist_id)
                try:
                    songs = self.db.get_playlist_songs(pl.id)
                    for s in songs:
                        # s is usually djmdSongPlaylist entry, which has content_id
                        if hasattr(s, 'content_id'):
                            self.playlists_tracks[pid].append(str(s.content_id))
                            count += 1
                except Exception as e:
                    logger.warning(
                        "live_database: get_playlist_songs(%s) failed — skipping (%s)",
                        pid, e,
                    )
                    continue

            logger.info(f"Loaded {count} playlist track mappings via rbox.")
        except Exception as e:
            logger.error(f"Failed to load playlist tracks via rbox: {e}")

    def _finalize_ui_metadata(self):
        # Single pass over all tracks builds the artist/genre/label/album
        # aggregates at once. get_all_labels()/get_all_albums() used to
        # re-iterate the whole library on every call, and get_tracks_by_*()
        # rebuilt those lists just to resolve one id->name. Everything is
        # precomputed here now; the id->name maps give O(1) drill-down.
        artist_counts = defaultdict(int)
        genre_counts = defaultdict(int)
        label_counts = defaultdict(int)
        album_counts = defaultdict(int)
        artist_artworks = {}
        label_artworks = {}
        album_artworks = {}
        for t in self.tracks.values():
            artwork = t.get("Artwork")
            if t.get("Artist"):
                for artist in self._split_artists(t["Artist"]):
                    artist_counts[artist] += 1
                    if artist not in artist_artworks and artwork:
                        artist_artworks[artist] = artwork

            if t.get("Genre"):
                genre_counts[t["Genre"]] += 1

            label = t.get("Label")
            if label:
                normalized = self._normalize_artist_name(label)
                label_counts[normalized] += 1
                if normalized not in label_artworks and artwork:
                    label_artworks[normalized] = artwork

            album = t.get("Album")
            if album:
                album_counts[album] += 1
                if album not in album_artworks and artwork:
                    album_artworks[album] = artwork

        self.artists = []
        self._artist_id_to_name = {}
        threshold = 0
        try:
            from .services import SettingsManager
            threshold = SettingsManager.load().get("artist_view_threshold", 0)
        except (OSError, ValueError, KeyError, AttributeError) as e:
            logger.warning(
                "live_database: failed to load artist_view_threshold — using 0 (%s)", e,
            )

        for i, (name, count) in enumerate(sorted(artist_counts.items())):
            if count >= threshold:
                aid = f"art_{i}"
                self.artists.append({
                    "id": aid,
                    "name": name,
                    "track_count": count,
                    "Artwork": artist_artworks.get(name, "")
                })
                self._artist_id_to_name[aid] = name
        self.genres = [{"id": f"gen_{i}", "name": name, "track_count": count} for i, (name, count) in enumerate(sorted(genre_counts.items()))]

        self.labels = []
        self._label_id_to_name = {}
        for i, (name, count) in enumerate(sorted(label_counts.items())):
            lid = f"lbl_{i}"
            self.labels.append({
                "id": lid,
                "name": name,
                "track_count": count,
                "Artwork": label_artworks.get(name, "")
            })
            self._label_id_to_name[lid] = name

        self.albums = []
        self._album_id_to_name = {}
        for i, (name, count) in enumerate(sorted(album_counts.items())):
            alid = f"alb_{i}"
            self.albums.append({
                "id": alid,
                "name": name,
                "track_count": count,
                "Artwork": album_artworks.get(name, "")
            })
            self._album_id_to_name[alid] = name

    def get_all_labels(self) -> list[dict[str, Any]]:
        return self.labels

    def get_all_albums(self) -> list[dict[str, Any]]:
        return self.albums

    def _split_artists(self, artist_str):
        if not artist_str: return []
        # Split by common separators: , & / ; feat. ft. vs. with
        # Case insensitive regex for feat/ft/vs/with
        parts = re.split(r'(?i),|&|/|;|\s+feat\.?\s+|\s+ft\.?\s+|\s+vs\.?\s+|\s+with\s+', artist_str)
        return [self._normalize_artist_name(p.strip()) for p in parts if p.strip()]

    def _normalize_artist_name(self, name):
        if not name: return ""

        # 0. Check for manual mapping first
        try:
            from .services import MetadataManager
            mapped = MetadataManager.get_mapped_name("artists", name)
            if mapped != name: return mapped
        except Exception as e:
            logger.debug(
                "live_database: artist-name mapping failed for %r (%s)", name, e,
            )

        # 1. Strip leading numbers like "01 ", "1. ", "02-", "1 "
        name = re.sub(r'^\d{1,2}[\s.-]+', '', name)

        # 2. Strip common prefixes (case insensitive) - anywhere near the start
        name = re.sub(r'(?i)^.*(supported by|premiere:?|exclusive:?|dj\s+)\s*', '', name)

        # 3. Strip common suffixes (case insensitive)
        # Avoid stripping if it's part of the name (e.g. "The Edit"), so we use boundaries or specific patterns
        name = re.sub(r'(?i)\s+(re-?edit|edit|r[em]+ix|rework|bootleg|flip|cut|vip)\s*.*$', '', name)

        return name.strip()

    def get_all_tracks(self) -> list[dict[str, Any]]:
        return list(self.tracks.values())

    def get_tracks_by_artist(self, aid: str) -> list[dict[str, Any]]:
        artist_name = self._artist_id_to_name.get(aid)
        if not artist_name: return []
        return [t for t in self.tracks.values() if artist_name in self._split_artists(t.get("Artist", ""))]

    def get_tracks_by_label(self, aid: str) -> list[dict[str, Any]]:
        label_name = self._label_id_to_name.get(aid)
        if not label_name: return []
        return [t for t in self.tracks.values() if self._normalize_artist_name(t.get("Label", "")) == label_name]

    def get_tracks_by_album(self, aid: str) -> list[dict[str, Any]]:
        album_name = self._album_id_to_name.get(aid)
        if not album_name: return []
        return [t for t in self.tracks.values() if t.get("Album") == album_name]

    def get_playlist_tree(self) -> list[dict[str, Any]]:
        if not self.playlists: return []

        # 1. Map all nodes
        node_map = {r['ID']: {**r, 'Children': []} for r in self.playlists}
        tree = []

        # 2. Build Tree
        for r in self.playlists:
            pid = r['ParentID']
            if pid in node_map:
                node_map[pid]['Children'].append(node_map[r['ID']])
            elif str(pid).upper() == "ROOT":
                tree.append(node_map[r['ID']])

        # 3. Sort nodes by Seq
        for node in node_map.values():
            if node['Children']:
                node['Children'].sort(key=lambda x: x.get('Seq', 0))
        tree.sort(key=lambda x: x.get('Seq', 0))

        # 4. Log initial tree state
        logger.info(f"Tree built. Root nodes: {len(tree)}")
        if len(tree) == 1:
            root = tree[0]
            logger.info(f"Single root detected: Name='{root['Name']}', Type='{root.get('Type')}', Children={len(root['Children'])}")

            # Smart Unwrap: Hoist children if root is a generic container
            if root['Name'].lower() in ['root', 'library', 'collection', 'playlists']:
                 if root['Children']:
                     logger.info(f"Hoisting children of generic root: {root['Name']}")
                     return root['Children']

        return tree

    def get_playlist_tracks(self, pid: str) -> list[dict[str, Any]]:
        try:
            # Pre-calculate parent-child mapping for speed
            parent_to_children = defaultdict(list)
            for p in self.playlists:
                p_pid = str(p["ParentID"])
                parent_to_children[p_pid].append(p)

            # Check if it's a folder (Type 0 OR has children)
            node = next((p for p in self.playlists if str(p["ID"]) == str(pid)), None)

            is_folder = False
            if (node and str(node.get("Type")) == "0") or str(pid) in parent_to_children:
                is_folder = True

            # Recursive collection for Folders
            if is_folder:
                logger.info(f"Recursively fetching tracks for folder: {node['Name'] if node else pid}")

                # 1. Collect all node IDs in the tree (including self)
                all_node_ids = [str(pid)]
                queue = [str(pid)]
                while queue:
                    current_pid = queue.pop(0)
                    for child in parent_to_children.get(current_pid, []):
                        child_id = str(child["ID"])
                        all_node_ids.append(child_id)
                        # If it has children, explore it too
                        if child_id in parent_to_children:
                            queue.append(child_id)

                # 2. Fetch tracks for ALL nodes in the set
                all_tracks = {} # Use dict to deduplicate by ID
                for nid in all_node_ids:
                    cids = self.playlists_tracks.get(nid, [])
                    for cid in cids:
                        if cid in self.tracks:
                            all_tracks[cid] = self.tracks[cid]

                logger.info(f"Total tracks collected from folder {pid}: {len(all_tracks)}")
                return list(all_tracks.values())

            # 3. Intelligent Playlist (Type 4)
            if str(node.get("Type")) == "4":
                xml_rules = node.get("smart_list")
                logger.info(f"Generating dynamic content for Intelligent Playlist: {node['Name']}")
                return self._get_smart_playlist_tracks(xml_rules)

            # 4. Regular Playlist
            cids = self.playlists_tracks.get(str(pid), [])
            if not cids:
                return []

            # Preserve order from items
            result = [self.tracks[cid] for cid in cids if cid in self.tracks]

            logger.info(f"Found {len(result)} tracks for playlist {pid} from cache")
            return result
        except Exception as e:
             logger.error(f"Failed to get tracks for playlist {pid}: {e}")
             return []

    def _get_smart_playlist_tracks(self, xml_rules):
        """Filters the entire library based on Intelligent Playlist rules."""
        if not xml_rules:
            logger.warning("_get_smart_playlist_tracks: No xml_rules provided")
            return []

        rules = self._parse_smart_rules(xml_rules)
        if not rules:
            logger.warning("_get_smart_playlist_tracks: Failed to parse rules")
            return []

        logger.debug(f"Filtering with rules: {rules}")
        filtered = []
        for tid, track in self.tracks.items():
            if self._apply_smart_rules(track, rules):
                filtered.append(track)

        logger.debug(f"Dynamic filter complete. Found {len(filtered)} matches.")
        return filtered

    def _parse_smart_rules(self, xml_str):
        try:
            root = ET.fromstring(xml_str)
            logical_op = int(root.get("LogicalOperator", "1")) # 1=AND, 0=OR
            conditions = []
            for cond in root.findall("CONDITION"):
                # Rekordbox uses PropertyName, not RuleId in some versions/XML formats
                rule_id = cond.get("PropertyName") or cond.get("RuleId")
                conditions.append({
                    "RuleId": rule_id,
                    "Operator": int(cond.get("Operator", "1")),
                    "ValueLeft": cond.get("ValueLeft"),
                    "ValueRight": cond.get("ValueRight")
                })
            res = {"op": logical_op, "conditions": conditions}
            # logger.info(f"Parsed smart rules: {res}")
            return res
        except Exception as e:
            logger.error(f"Error parsing smart list XML: {e}")
            return None

    def _apply_smart_rules(self, track, rules):
        logical_op = rules["op"]
        conditions = rules["conditions"]

        if not conditions: return True

        # logger.debug(f"Applying rules to track: {track.get('Title')}")

        # AND (LogicalOperator=1)
        if logical_op == 1:
            for cond in conditions:
                if not self._check_condition(track, cond):
                    return False
            return True
        # OR (LogicalOperator=0)
        else:
            for cond in conditions:
                if self._check_condition(track, cond):
                    return True
            return False

    def _check_condition(self, track, cond):
        rule_id = cond["RuleId"]
        op = cond["Operator"]
        val_l = cond["ValueLeft"]
        val_r = cond["ValueRight"]

        # Map Rekordbox smart-playlist PropertyName → track dict field.
        # "grouping" = ColorID (Rekordbox color tag, stored as integer 0-8).
        # "duration" = TotalTime in seconds (rbox `length` column).
        # "bpm"      = BPM decimal (already ÷100 in track cache); rules store BPM×100.
        field_map = {
            "artist":    "Artist",
            "title":     "Title",
            "album":     "Album",
            "genre":     "Genre",
            "label":     "Label",
            "bpm":       "BPM",
            "rating":    "Rating",
            "comment":   "Comment",
            "key":       "Key",
            "myTag":     "TagIDs",
            "grouping":  "ColorID",   # Rekordbox color label, used as grouping
            "duration":  "TotalTime", # Track length in seconds
        }

        field = field_map.get(rule_id)
        if not field:
            logger.debug("_check_condition: unknown rule_id=%r — skipped", rule_id)
            return False

        target = track.get(field)
        if target is None: return False

        res = False
        # MyTag Matching (Operator 8 = Tag ID is in list, Operator 9 = not in list)
        # IMPORTANT: rbox stores IDs as unsigned 32-bit integers ("3979022742"),
        # but the SmartList XML uses signed 32-bit ("-315944554") for large IDs.
        # Both forms represent the same bit pattern — normalize ValueLeft to unsigned.
        if rule_id == "myTag":
            try:
                n = int(val_l)
                norm = str(n & 0xFFFFFFFF) if n < 0 else val_l
            except (ValueError, TypeError):
                norm = val_l
            if op == 8: return norm in target  # target is list of unsigned tag ID strings
            if op == 9: return norm not in target
            return False

        # String Matching (artist, title, album, genre, label, comment, key)
        # op=8/9 are used when Rekordbox shows a dropdown (e.g. genre picked from list)
        # rather than a free-text box — semantics are "Is" / "Is not".
        if isinstance(target, str):
            t_low = target.lower()
            v_low = val_l.lower() if val_l else ""
            if op == 1:            res = v_low in t_low        # Contains
            elif op == 2:          res = v_low not in t_low    # Does not contain
            elif op in (3, 8):     res = t_low == v_low        # Is / Dropdown-Is
            elif op in (4, 9):     res = t_low != v_low        # Is not / Dropdown-Is not

        # Numeric Matching (bpm, rating, grouping/ColorID, duration)
        elif isinstance(target, (int, float)):
            try:
                l_num = float(val_l) if val_l else 0.0
                r_num = float(val_r) if val_r else 0.0

                compare_val = float(target)
                # BPM: track cache stores decimal BPM (e.g. 132.0).
                # Rekordbox smart-playlist rules store BPM×100 (e.g. 13200).
                # Rule PropertyName is lowercase "bpm" — fix: match lowercase.
                if rule_id == "bpm":
                    compare_val = compare_val * 100.0

                if op == 1 or op == 3:   res = abs(compare_val - l_num) < 0.5  # Equals (wider tolerance for BPM×100)
                elif op == 4:            res = abs(compare_val - l_num) >= 0.5  # Not equals
                elif op == 5:            res = l_num <= compare_val <= r_num    # Between
                elif op == 6:            res = compare_val > l_num              # Greater than
                elif op == 7:            res = compare_val < l_num              # Less than
            except Exception as exc:
                logger.debug("_check_condition numeric error: %s", exc)
                res = False

        return res

    def get_track_details(self, tid: str) -> dict[str, Any] | None:
        return self.tracks.get(tid)

    def add_track(self, track_data: dict[str, Any]) -> str | None:
        path = track_data.get("path")
        if not path:
            raise ValueError("Track path missing")

        try:
            # 1. Create content entry in master.db
            logger.info(f"Creating content entry in master.db for: {path}")
            item = self.db.create_content(path)
            tid = str(item.id)

            # 2. Update metadata (Artist, Album, etc.)
            updates = {
                "Title": track_data.get("Title"),
                "Artist": track_data.get("Artist"),
                "Album": track_data.get("Album"),
                "Genre": track_data.get("Genre"),
                "BPM": track_data.get("BPM"),
                "Comment": track_data.get("Comment")
            }
            # Remove None values
            updates = {k: v for k, v in updates.items() if v is not None}

            if updates:
                self.update_track_metadata(tid, updates)

            # 3. Cache the new track locally
            self.tracks[tid] = {
                "ID": tid,
                "Title": track_data.get("Title", ""),
                "Artist": track_data.get("Artist", ""),
                "Album": track_data.get("Album", ""),
                "BPM": track_data.get("BPM", 0),
                "path": path,
                "TotalTime": track_data.get("TotalTime", 0),
                "beatGrid": track_data.get("beatGrid", []),
                "Comment": track_data.get("Comment", ""),
                "Artwork": track_data.get("Artwork", "")
            }

            return tid
        except Exception as e:
            error_msg = str(e)
            if "Path is not unique" in error_msg:
                logger.warning(f"Duplicate track path: {path}")
                raise ValueError(f"Track already exists in Rekordbox: {os.path.basename(path)}")

            logger.error(f"Failed to add track to live DB: {e}")
            raise e

    def delete_track(self, tid: str) -> bool:
        tid = str(tid)

        # 1. Remove from local cache
        if tid in self.tracks:
            del self.tracks[tid]

        # 2. Remove from all playlists (internal cache)
        for pid, tracks in self.playlists_tracks.items():
            if tid in [str(t.id) if hasattr(t, 'id') else str(t['ID']) for t in tracks]:
                # This is tricky because we store objects or dicts.
                # Ideally we call remove_track_from_playlist
                try:
                    self.remove_track_from_playlist(pid, tid)
                except Exception as e:
                    logger.warning(
                        "live_database: remove_track_from_playlist(%s, %s) failed: %s",
                        pid, tid, e,
                    )

        # 3. Warn about Master DB
        logger.warning(f"Track {tid} removed from cache/playlists, but RBOX library does not support direct deletion from Master DB via this API.")
        return True

    def update_track_comment(self, tid: str, comment: str) -> bool:
        return self.update_track_metadata(tid, {"Comment": comment})

    def update_track_metadata(self, tid: str, updates: dict[str, Any]) -> bool:
        try:
            tid = str(tid)
            logger.info(f"Updating metadata for track ID: '{tid}'")
            item = self.db.get_content_by_id(tid)
            if not item:
                logger.error(f"Track {tid} not found in DB")
                raise Exception(f"Track {tid} not found in Live DB")

            changed = False
            # 1. Direct fields
            if "Comment" in updates:
                item.commnt = str(updates["Comment"])
                changed = True
            if "Rating" in updates:
                try:
                    item.rating = int(updates["Rating"])
                    changed = True
                except (ValueError, TypeError) as e:
                    logger.warning(
                        "live_database: invalid Rating %r for track %s (%s)",
                        updates.get("Rating"), tid, e,
                    )
            if "ColorID" in updates:
                try:
                    item.color_id = int(updates["ColorID"])
                    changed = True
                except (ValueError, TypeError) as e:
                    # rbox occasionally returns ColorID as a string label; fall
                    # back to str() before giving up so theme syncs don't fail
                    # silently. master.db itself stores ColorID as INTEGER.
                    logger.debug(
                        "live_database: ColorID %r not int for track %s (%s) — trying str fallback",
                        updates.get("ColorID"), tid, e,
                    )
                    try:
                        item.color_id = str(updates["ColorID"])
                        changed = True
                    except Exception as inner:
                        logger.warning(
                            "live_database: ColorID for track %s rejected as int and str (%s)",
                            tid, inner,
                        )

            if changed:
                logger.info(f"Applying direct field updates for track {tid}...")
                self.db.update_content(item)
                logger.info(f"DB update_content successful for {tid}")

                # Update in-memory cache
                if tid in self.tracks:
                    if "Comment" in updates: self.tracks[tid]["Comment"] = updates["Comment"]
                    if "Rating" in updates: self.tracks[tid]["Rating"] = int(updates["Rating"])
                    if "ColorID" in updates: self.tracks[tid]["ColorID"] = int(updates["ColorID"])
                logger.info(f"Cache updated for {tid}")

            # 2. Relationship fields (rbox handles joins/inserts)
            if "Artist" in updates:
                logger.info(f"Updating Artist for {tid}...")
                self.db.update_content_artist(str(tid), updates["Artist"])
                if tid in self.tracks: self.tracks[tid]["Artist"] = updates["Artist"]
            if "Genre" in updates:
                logger.info(f"Updating Genre for {tid}...")
                self.db.update_content_genre(str(tid), updates["Genre"])
                if tid in self.tracks: self.tracks[tid]["Genre"] = updates["Genre"]
            if "Album" in updates:
                logger.info(f"Updating Album for {tid}...")
                self.db.update_content_album(str(tid), updates["Album"])
                if tid in self.tracks: self.tracks[tid]["Album"] = updates["Album"]

            logger.info(f"Update sequence complete for {tid}")
            return True
        except Exception as e:
            logger.error(f"Failed to update track metadata {tid}: {e}")
            raise e

    # ── MyTag (Pioneer "My Tag") read/write ────────────────────────────────
    # rbox's wheel API for MyTag write hasn't been used elsewhere in this
    # codebase, so version-to-version method names may differ. We probe a
    # set of plausible names and surface a clear error if none of them work.
    # Reads use the snapshot loaded by `_load_mytags()` (no extra DB hit).

    def list_mytags(self) -> list[dict[str, Any]]:
        """Return all defined MyTag entries as [{id, name}, …]."""
        return [{"id": tid, "name": name} for tid, name in self.tag_id_to_name.items()]

    def get_track_mytags(self, tid: str) -> list[dict[str, Any]]:
        """Return MyTag IDs assigned to the given track."""
        tid = str(tid)
        ids = list(self.track_to_tag_ids.get(tid, []))
        return [{"id": i, "name": self.tag_id_to_name.get(i, "?")} for i in ids]

    def _try_call(self, names, *args, **kwargs):
        """Call the first method on self.db that exists. Return (ok, result, last_err)."""
        last = None
        for name in names:
            fn = getattr(self.db, name, None)
            if callable(fn):
                try:
                    return True, fn(*args, **kwargs), None
                except Exception as exc:
                    last = exc
                    logger.warning("rbox.%s(%s) raised: %s", name, args, exc)
        return False, None, last

    def create_mytag(self, name: str) -> str:
        """Create a new MyTag definition. Returns the new tag id."""
        ok, result, err = self._try_call(
            ["create_my_tag", "add_my_tag", "create_mytag", "add_mytag"],
            name,
        )
        if not ok:
            raise Exception(f"rbox: no create_my_tag method available ({err})")
        new_id = str(getattr(result, "id", result))
        self.tag_id_to_name[new_id] = name
        return new_id

    def delete_mytag(self, tag_id: str) -> bool:
        ok, _, err = self._try_call(
            ["delete_my_tag", "remove_my_tag", "delete_mytag"],
            str(tag_id),
        )
        if not ok:
            raise Exception(f"rbox: no delete_my_tag method available ({err})")
        self.tag_id_to_name.pop(str(tag_id), None)
        for cid, ids in list(self.track_to_tag_ids.items()):
            self.track_to_tag_ids[cid] = [i for i in ids if i != str(tag_id)]
        return True

    def set_track_mytags(self, tid: str, tag_ids: list) -> dict:
        """
        Replace the set of MyTags on a track. Adds tags missing from the
        current set and removes tags no longer wanted. Returns a summary.
        """
        tid = str(tid)
        wanted = {str(x) for x in tag_ids}
        current = {str(x) for x in self.track_to_tag_ids.get(tid, [])}

        added, removed, errors = [], [], []

        for new_id in wanted - current:
            ok, _, err = self._try_call(
                ["add_to_my_tag", "add_song_to_my_tag", "create_my_tag_song",
                 "add_content_to_my_tag", "add_my_tag_song"],
                str(new_id), tid,
            )
            if not ok:
                # Try (tid, tag) argument order as a fallback.
                ok, _, err = self._try_call(
                    ["add_to_my_tag", "add_song_to_my_tag", "create_my_tag_song",
                     "add_content_to_my_tag", "add_my_tag_song"],
                    tid, str(new_id),
                )
            if ok:
                added.append(str(new_id))
            else:
                errors.append({"tag_id": str(new_id), "error": str(err) or "no method"})

        for old_id in current - wanted:
            ok, _, err = self._try_call(
                ["remove_from_my_tag", "delete_my_tag_song", "delete_song_from_my_tag",
                 "remove_content_from_my_tag", "remove_my_tag_song"],
                str(old_id), tid,
            )
            if not ok:
                ok, _, err = self._try_call(
                    ["remove_from_my_tag", "delete_my_tag_song", "delete_song_from_my_tag",
                     "remove_content_from_my_tag", "remove_my_tag_song"],
                    tid, str(old_id),
                )
            if ok:
                removed.append(str(old_id))
            else:
                errors.append({"tag_id": str(old_id), "error": str(err) or "no method"})

        # Refresh in-memory cache so subsequent reads reflect the change.
        new_set = (current - {x["tag_id"] for x in errors if x["tag_id"] in current - wanted}) \
                  | set(added) - set(removed)
        self.track_to_tag_ids[tid] = list(new_set)
        self.track_to_tags[tid] = [self.tag_id_to_name.get(i, "?") for i in new_set]

        return {"added": added, "removed": removed, "errors": errors}

    def get_analysis_writer(self):
        """
        Returns an AnalysisDBWriter instance bound to this database.
        Used for analyzing tracks and writing results back to master.db + ANLZ files.
        """
        from .analysis_db_writer import AnalysisDBWriter
        if not hasattr(self, '_analysis_writer') or self._analysis_writer is None:
            self._analysis_writer = AnalysisDBWriter(self)
        return self._analysis_writer

    def get_unanalyzed_track_ids(self) -> list:
        """Returns list of track IDs that have BPM=0 or no beatgrid."""
        return [
            tid for tid, t in self.tracks.items()
            if not t.get("BPM") or t["BPM"] <= 0
        ]

    def rename_playlist(self, pid, new_name):
        try:

            self.db.rename_playlist(str(pid), new_name)
            # Update cache
            for p in self.playlists:
                if p['ID'] == str(pid):
                    p['Name'] = new_name
                    break
            return True
        except Exception as e:
            logger.error(f"Failed to rename playlist {pid}: {e}")
            return False

    def move_playlist(self, pid, new_parent_id, target_id=None, position=None):
        try:
            # 1. Determine actual parent and target sequence
            sibling = None
            actual_parent = None
            target_seq = 0

            if position == "inside" and target_id:
                actual_parent = None if str(target_id).upper() == "ROOT" else str(target_id)
                # Max seq + 1 for new parent
                siblings = [p for p in self.playlists if p['ParentID'] == (target_id or "ROOT")]
                target_seq = max([p.get('Seq', 0) for p in siblings], default=-1) + 1
            elif target_id and position in ("before", "after"):
                sibling = next((p for p in self.playlists if p['ID'] == str(target_id)), None)
                if sibling:
                    sp = sibling.get('ParentID', 'ROOT')
                    actual_parent = None if str(sp).upper() == "ROOT" else str(sp)
                    target_seq = sibling.get('Seq', 0)
                    if position == "after": target_seq += 1
                else:
                    actual_parent = None if str(new_parent_id).upper() == "ROOT" else str(new_parent_id)
                    target_seq = 0
            else:
                actual_parent = None if str(new_parent_id).upper() == "ROOT" else str(new_parent_id)
                target_seq = 0

            logger.info(f"Moving playlist {pid} to parent_id={actual_parent}, seq={target_seq}")

            # 2. Call DB (rbox should handle the shift if seq is provided)
            # If rbox move_playlist(pid, seq=target_seq, parent_id=actual_parent) works as expected:
            self.db.move_playlist(str(pid), seq=target_seq, parent_id=actual_parent)

            # 3. Update Cache & Re-sort siblings locally to reflect the move
            resolved_parent = str(actual_parent) if actual_parent else "ROOT"

            for p in self.playlists:
                if p['ID'] == str(pid):
                    p['ParentID'] = resolved_parent
                    p['Seq'] = target_seq
                    break

            # Simple local re-sequencing for siblings to keep cache in sync
            parent_siblings = [p for p in self.playlists if p['ParentID'] == resolved_parent]
            parent_siblings.sort(key=lambda x: (x.get('Seq', 0), 0 if x['ID'] == str(pid) else 1))

            for i, p in enumerate(parent_siblings):
                p['Seq'] = i

            self.playlists.sort(key=lambda x: x.get('Seq', 0))
            return True
        except Exception as e:
            logger.error(f"Failed to move playlist {pid}: {e}")
            return False

    def delete_playlist(self, pid):
        try:

            self.db.delete_playlist(str(pid))
            # Update cache
            self.playlists = [p for p in self.playlists if p['ID'] != str(pid)]
            return True
        except Exception as e:
            logger.error(f"Failed to delete playlist {pid}: {e}")
            return False

    def create_playlist(self, name, parent_id="ROOT", is_folder=False):
        try:

            target_parent = None if str(parent_id).upper() == "ROOT" else str(parent_id)
            if is_folder:
                new_pl = self.db.create_playlist_folder(name, target_parent)
            else:
                new_pl = self.db.create_playlist(name, target_parent)

            # Add to cache (simplistic, real schema has more attributes)
            node_data = {
                "ID": str(new_pl.id),
                "Name": new_pl.name,
                "ParentID": parent_id,
                "Type": "0" if is_folder else "1",
                "Seq": getattr(new_pl, 'seq', 0)
            }
            self.playlists.append(node_data)
            return node_data
        except Exception as e:
            logger.error(f"Failed to create playlist {name}: {e}")
            return None

    def add_track_to_playlist(self, pid, tid):
        try:

            # rbox uses create_playlist_song(playlist_id, track_id)
            self.db.create_playlist_song(str(pid), str(tid))
            return True
        except Exception as e:
            logger.error(f"Failed to add track {tid} to playlist {pid}: {e}")
            return False

    def remove_track_from_playlist(self, pid, tid):
        try:

            # delete_playlist_song expects (playlist_id, track_id) ?
            # Actually dir showed: delete_playlist_song and delete_playlist_songs
            # Usually it takes the playlist ID and the track ID.
            self.db.delete_playlist_song(str(pid), str(tid))
            return True
        except Exception as e:
            logger.error(f"Failed to remove track {tid} from playlist {pid}: {e}")
            return False

    def reorder_playlist_track(self, pid: str, track_id: str, new_index: int) -> bool:
        """
        Reorders a track in a playlist.
        For now, this performs a Remove + Add, which effectively moves it to the end.
        True index-based reordering requires deeper SQL access not yet implemented in rbox wrapper.
        """
        try:
            # 1. Remove
            self.remove_track_from_playlist(pid, track_id)
            # 2. Add (Appends to end)
            self.add_track_to_playlist(pid, track_id)
            return True
        except Exception as e:
            logger.error(f"Failed to reorder playlist track: {e}")
            return False
