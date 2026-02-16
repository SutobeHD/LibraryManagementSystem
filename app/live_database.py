import os
import shutil
import logging
import time
from datetime import datetime
import re
import threading
from pathlib import Path
from collections import defaultdict
import rbox
from .config import BACKUP_DIR

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
        self.loaded = False
        self.loading_status = "Idle"

    @property
    def db(self):
        """Thread-safe access to the database connection."""
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            logger.debug(f"Opening fresh connection for thread {threading.get_ident()}")
            self._local.conn = rbox.MasterDb(str(self.db_path))
        return self._local.conn

    def _ensure_backup(self):
        """
        Creates a session backup and manages archival schedule.
        Keeps only the last 3 session backups.
        """
        if not self.db_path.exists():
            logger.error(f"Cannot backup: {self.db_path} does not exist.")
            return False
        
        from .services import SettingsManager
        settings = SettingsManager.load()
        
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        
        # 1. Session Backup
        session_backup_name = f"master_session_{timestamp}.db"
        session_backup_path = BACKUP_DIR / session_backup_name
        
        try:
            shutil.copy2(self.db_path, session_backup_path)
            logger.info(f"Created session backup: {session_backup_path}")
            self._cleanup_session_backups()
            
            # 2. Check for Archival
            self._handle_archival(settings)
            
            return True
        except Exception as e:
            logger.error(f"Backup system failed: {e}")
            return False

    def _cleanup_session_backups(self):
        """Keeps only the latest 3 session backups."""
        try:
            backups = sorted(BACKUP_DIR.glob("master_session_*.db"), key=os.path.getmtime, reverse=True)
            if len(backups) > 3:
                for old_backup in backups[3:]:
                    os.remove(old_backup)
                    logger.debug(f"Removed old session backup: {old_backup}")
        except Exception as e:
            logger.error(f"Failed to cleanup session backups: {e}")

    def get_available_backups(self):
        """Returns a sorted list of available backups."""
        backups = []
        if not BACKUP_DIR.exists(): return []
        
        for f in BACKUP_DIR.glob("*.db"):
            try:
                # Parse filename: master_session_20260215_225416.db or master_ARCHIVE_20260215.db
                name = f.name
                path = str(f)
                size = f.stat().st_size
                mtime = f.stat().st_mtime
                
                b_type = "Unknown"
                if "session" in name: b_type = "Session"
                elif "ARCHIVE" in name: b_type = "Archive"
                elif "prerestore" in name: b_type = "Pre-Restore"
                
                # Extract timestamp string for display if possible, else use mtime
                # Simple extraction based on known formats
                display_date = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
                
                backups.append({
                    "filename": name,
                    "path": path,
                    "type": b_type,
                    "size": size,
                    "date": display_date,
                    "timestamp": mtime
                })
            except Exception as e:
                logger.error(f"Error parsing backup {f}: {e}")

        # Sort by timestamp descending (newest first)
        return sorted(backups, key=lambda x: x["timestamp"], reverse=True)

    def restore_backup(self, filename):
        """
        Restores a backup file to master.db.
        Create a 'Pre-Restore' backup of current state first.
        """
        target_path = BACKUP_DIR / filename
        if not target_path.exists():
            logger.error(f"Restore failed: File not found {target_path}")
            return False, "Backup file not found"
            
        try:
            # 1. Safety Backup
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            pre_restore_name = f"master_prerestore_{timestamp}.db"
            pre_restore_path = BACKUP_DIR / pre_restore_name
            shutil.copy2(self.db_path, pre_restore_path)
            logger.info(f"Created pre-restore backup: {pre_restore_path}")
            
            # 2. Restore
            # We must close the DB connection if possible, but rbox might hold it.
            # In a live app, replacing the file while open is risky but often works on Windows if just reading.
            # Ideally we'd close 'self.db' here but rbox wrapper might not expose close().
            # Let's try copy2 replace.
            
            shutil.copy2(target_path, self.db_path)
            logger.info(f"Restored backup {filename} to {self.db_path}")
            
            return True, "Backup restored successfully. Please restart the application."
        except Exception as e:
            logger.error(f"Restore failed: {e}")
            return False, str(e)

    def _handle_archival(self, settings):
        """Creates a permanent archive backup based on user-defined frequency."""
        freq = settings.get("archive_frequency", "daily")
        if freq == "off": return
        
        last_archive_str = settings.get("last_archive_date", "")
        now = datetime.now()
        
        should_archive = False
        if not last_archive_str:
            should_archive = True
        else:
            try:
                last_archive = datetime.fromisoformat(last_archive_str)
                delta = now - last_archive
                
                if freq == "daily" and delta.days >= 1: should_archive = True
                elif freq == "weekly" and delta.days >= 7: should_archive = True
                elif freq == "monthly" and delta.days >= 30: should_archive = True
            except:
                should_archive = True
        
        if should_archive:
            timestamp = now.strftime("%Y%m%d")
            archive_name = f"master_ARCHIVE_{timestamp}.db"
            archive_path = BACKUP_DIR / archive_name
            try:
                shutil.copy2(self.db_path, archive_path)
                logger.info(f"Created archival backup: {archive_path}")
                
                # Update settings
                settings["last_archive_date"] = now.isoformat()
                from .services import SettingsManager
                SettingsManager.save(settings)
            except Exception as e:
                logger.error(f"Failed to create archival backup: {e}")

    def load(self):
        """Loads the library from the live master.db."""
        try:
            # Always backup before opening
            self._ensure_backup()
            
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
            
            # 3. Finalize metadata for UI
            self._finalize_ui_metadata()
            
            self.loaded = True
            self.loading_status = "Idle"
            logger.info(f"LIVE LOAD COMPLETE: {len(self.tracks)} tracks, {len(self.playlists)} playlists")
            return True
        except Exception as e:
            logger.error(f"Failed to load live database: {e}", exc_info=True)
            return False

    def _load_metadata_maps(self):
        """Creates ID -> Name maps for joined tables."""
        logger.info("Caching metadata maps (artists, genres, etc.)...")
        self.artist_map = {a.id: a.name for a in self.db.get_artists()}
        self.genre_map = {g.id: g.name for g in self.db.get_genres()}
        self.album_map = {a.id: a.name for a in self.db.get_albums()}
        self.label_map = {l.id: l.name for l in self.db.get_labels()}
        self.key_map = {k.id: k.name for k in self.db.get_keys()}
        
        # Extended metadata maps with graceful fallback
        self.composer_map = {}
        try: self.composer_map = {c.id: c.name for c in self.db.get_composers()}
        except: pass
        
        self.remixer_map = {}
        try: self.remixer_map = {r.id: r.name for r in self.db.get_remixers()}
        except: pass
        
        self.lyricist_map = {}
        try: self.lyricist_map = {l.id: l.name for l in self.db.get_lyricists()}
        except: pass

        logger.info(f"Metadata maps cached. Artists: {len(self.artist_map)}, Genres: {len(self.genre_map)}")

    def _load_mytags(self):
        self.tag_id_to_name = {}
        self.track_to_tags = defaultdict(list)
        try:
            raw_tags = self.db.get_my_tags()
            for t in raw_tags:
                tid = str(t.id) if hasattr(t, 'id') else None
                name = getattr(t, 'name', 'Unknown')
                if tid: self.tag_id_to_name[tid] = name
            
            mappings = self.db.get_song_tag_lists()
            for m in mappings:
                cid = str(m.content_id) if hasattr(m, 'content_id') else None
                tid = str(m.mytag_id) if hasattr(m, 'mytag_id') else None
                if cid and tid and tid in self.tag_id_to_name:
                    self.track_to_tags[cid].append(self.tag_id_to_name[tid])
            
            logger.info(f"MyTags loaded. Definitions: {len(self.tag_id_to_name)}, Mappings: {len(self.track_to_tags)}")
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

    def _load_playlists(self):
        self.playlists = []
        raw_playlists = self.db.get_playlists()
        for pl in raw_playlists:
            # attribute 0 = folder, 1 = playlist entry node, 2 = playlist? 
            # Actually, standard RB schema is: attribute 0: folder, 1: playlist.
            pl_type = "0" if getattr(pl, 'attribute', 1) == 0 else "1"
            my_id = str(pl.id)
            
            # Update status for frontend feedback
            self.loading_status = f"Loading: {pl.name}"
            
            parent_id = str(pl.parent_id) if pl.parent_id else "ROOT"
            if parent_id.lower() == "root": parent_id = "ROOT"
            
            node_data = {
                "ID": my_id,
                "Name": pl.name,
                "ParentID": parent_id,
                "Type": pl_type,
                "Seq": pl.seq
            }
            self.playlists.append(node_data)

    def _finalize_ui_metadata(self):
        artist_counts = defaultdict(int)
        genre_counts = defaultdict(int)
        artist_artworks = {}
        for t in self.tracks.values():
            if t.get("Artist"): 
                track_artists = self._split_artists(t["Artist"])
                for artist in track_artists:
                    artist_counts[artist] += 1
                    # Capture first available artwork for this artist
                    if artist not in artist_artworks and t.get("Artwork"):
                        artist_artworks[artist] = t["Artwork"]

            if t.get("Genre"): genre_counts[t["Genre"]] += 1
        
        self.artists = []
        threshold = 0
        try:
            from .services import SettingsManager
            threshold = SettingsManager.load().get("artist_view_threshold", 0)
        except: pass

        for i, (name, count) in enumerate(sorted(artist_counts.items())):
            if count >= threshold:
                self.artists.append({
                    "id": f"art_{i}", 
                    "name": name, 
                    "track_count": count,
                    "Artwork": artist_artworks.get(name, "")
                })
        self.genres = [{"id": f"gen_{i}", "name": name, "track_count": count} for i, (name, count) in enumerate(sorted(genre_counts.items()))]

    def get_all_labels(self):
        label_counts = defaultdict(int)
        label_artworks = {}
        for t in self.tracks.values():
            label = t.get("Label")
            if label:
                normalized = self._normalize_artist_name(label) # Use same normalization for simplicity
                label_counts[normalized] += 1
                if normalized not in label_artworks and t.get("Artwork"):
                    label_artworks[normalized] = t["Artwork"]
        
        return [
            {"id": f"lbl_{i}", "name": name, "track_count": count, "Artwork": label_artworks.get(name, "")}
            for i, (name, count) in enumerate(sorted(label_counts.items()))
            if count >= 0 # Respect threshold?
        ]

    def get_all_albums(self):
        album_counts = defaultdict(int)
        album_artworks = {}
        for t in self.tracks.values():
            album = t.get("Album")
            if album:
                album_counts[album] += 1
                if album not in album_artworks and t.get("Artwork"):
                    album_artworks[album] = t["Artwork"]
        
        return [
            {"id": f"alb_{i}", "name": name, "track_count": count, "Artwork": album_artworks.get(name, "")}
            for i, (name, count) in enumerate(sorted(album_counts.items()))
        ]

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
        except: pass

        # 1. Strip leading numbers like "01 ", "1. ", "02-", "1 "
        name = re.sub(r'^\d{1,2}[\s.-]+', '', name)
        
        # 2. Strip common prefixes (case insensitive) - anywhere near the start
        name = re.sub(r'(?i)^.*(supported by|premiere:?|exclusive:?|dj\s+)\s*', '', name)
        
        # 3. Strip common suffixes (case insensitive)
        # Avoid stripping if it's part of the name (e.g. "The Edit"), so we use boundaries or specific patterns
        name = re.sub(r'(?i)\s+(re-?edit|edit|r[em]+ix|rework|bootleg|flip|cut|vip)\s*.*$', '', name)
        
        return name.strip()

    def get_all_tracks(self):
        return list(self.tracks.values())

    def get_tracks_by_artist(self, aid):
        # find artist name by id
        artist_name = next((a["name"] for a in self.artists if a["id"] == aid), None)
        if not artist_name: return []
        return [t for t in self.tracks.values() if artist_name in self._split_artists(t.get("Artist", ""))]

    def get_tracks_by_label(self, aid):
        label_name = next((l["name"] for l in self.get_all_labels() if l["id"] == aid), None)
        if not label_name: return []
        return [t for t in self.tracks.values() if self._normalize_artist_name(t.get("Label", "")) == label_name]

    def get_tracks_by_album(self, aid):
        album_name = next((a["name"] for a in self.get_all_albums() if a["id"] == aid), None)
        if not album_name: return []
        return [t for t in self.tracks.values() if t.get("Album") == album_name]

    def get_playlist_tree(self):
        if not self.playlists: return []
        
        # 1. Map all nodes
        node_map = {r['ID']: {**r, 'children': []} for r in self.playlists}
        tree = []
        
        # 2. Build Tree
        for r in self.playlists:
            pid = r['ParentID']
            if pid in node_map:
                node_map[pid]['children'].append(node_map[r['ID']])
            elif str(pid).upper() == "ROOT":
                tree.append(node_map[r['ID']])
        
        # 3. Log initial tree state
        logger.info(f"Tree built. Root nodes: {len(tree)}")
        if len(tree) == 1:
            root = tree[0]
            logger.info(f"Single root detected: Name='{root['Name']}', Type='{root.get('Type')}', Children={len(root['children'])}")
            
            # Smart Unwrap: Hoist children if root is a generic container
            if root['Name'].lower() in ['root', 'library', 'collection', 'playlists']:
                 if root['children']:
                     logger.info(f"Hoisting children of generic root: {root['Name']}")
                     return root['children']
        
        return tree

    def get_playlist_tracks(self, pid):
        try:
            # Pre-calculate parent-child mapping for speed
            parent_to_children = defaultdict(list)
            for p in self.playlists:
                p_pid = str(p["ParentID"])
                parent_to_children[p_pid].append(p)

            # Check if it's a folder (Type 0 OR has children)
            node = next((p for p in self.playlists if str(p["ID"]) == str(pid)), None)
            
            is_folder = False
            if node and str(node.get("Type")) == "0":
                is_folder = True
            elif str(pid) in parent_to_children:
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
                    try:
                        p_items = self.db.get_playlist_contents(nid)
                        if p_items:
                            for item in p_items:
                                tid = str(item.id)
                                if tid in self.tracks:
                                    all_tracks[tid] = self.tracks[tid]
                    except Exception as e:
                        logger.warning(f"Failed to fetch tracks for node {nid}: {e}")
                
                logger.info(f"Total tracks collected from folder {pid}: {len(all_tracks)}")
                return list(all_tracks.values())

            # Regular Playlist
            items = self.db.get_playlist_contents(str(pid))
            
            if not items: 
                return []

            result = []
            for item in items:
                tid = str(item.id)
                if tid in self.tracks:
                    result.append(self.tracks[tid])
            
            logger.info(f"Found {len(result)} tracks for playlist {pid}")
            return result
        except Exception as e:
             logger.error(f"Failed to get tracks for playlist {pid}: {e}")
             return []

    def get_track_details(self, tid):
        return self.tracks.get(tid)

    def add_track(self, track_data):
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

    def delete_track(self, tid):
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
                except:
                    pass

        # 3. Warn about Master DB
        logger.warning(f"Track {tid} removed from cache/playlists, but RBOX library does not support direct deletion from Master DB via this API.")
        return True

    def update_track_comment(self, tid, comment):
        return self.update_track_metadata(tid, {"Comment": comment})

    def update_track_metadata(self, tid, updates):
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
                except: pass
            if "ColorID" in updates:
                try:
                    item.color_id = int(updates["ColorID"])
                    changed = True
                except:
                    # Fallback to string if rbox expects it? (logs suggest it wants str for ID)
                    # But master.db uses INTEGER for ColorID. 
                    # If rbox complains about 'int' object, maybe it DOES want str?
                    try:
                        item.color_id = str(updates["ColorID"])
                        changed = True
                    except: pass
            
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

    def move_playlist(self, pid, new_parent_id, position=None):
        try:

            # rbox.move_playlist(id, parent_id, position)
            # parent_id "ROOT" usually maps to a specific value or None in rbox
            target_parent = None if str(new_parent_id).upper() == "ROOT" else str(new_parent_id)
            self.db.move_playlist(str(pid), target_parent, position)
            # Update cache
            for p in self.playlists:
                if p['ID'] == str(pid):
                    p['ParentID'] = new_parent_id if target_parent else "ROOT"
                    if position is not None: p['Seq'] = position
                    break
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
