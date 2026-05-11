import os
import json
import logging
import threading
import time
import re
import xml.etree.ElementTree as ET
import shutil
from urllib.parse import unquote
from pathlib import Path
from collections import defaultdict
from contextlib import contextmanager
from functools import lru_cache, wraps
from .config import REKORDBOX_ROOT, DB_FILENAME, BACKUP_DIR
from .live_database import LiveRekordboxDB

logger = logging.getLogger(__name__)

# Module-level reentrant lock that serialises all mutating operations on the
# global `db` singleton against concurrent FastAPI request threads.
# RLock is used so methods that internally call other mutating methods
# (e.g. `update_tracks_metadata` → `save_xml`) don't deadlock themselves.
_db_write_lock = threading.RLock()


@contextmanager
def db_lock():
    """Acquire `_db_write_lock` for the duration of the `with` block.

    Use this when several mutations must form one atomic transaction
    from a route handler, e.g.::

        with db_lock():
            db.add_track(...)
            db.add_track_to_playlist(...)

    Individual mutating methods on `RekordboxDB` are already wrapped, so
    you only need this for multi-step transactions.
    """
    with _db_write_lock:
        yield


def _serialised(method):
    """Decorator: serialise a method against `_db_write_lock`.

    Applied below to every mutating method on `RekordboxDB` so individual
    calls are already lock-safe without callers needing to remember.
    """
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with _db_write_lock:
            return method(self, *args, **kwargs)
    return wrapper

class RekordboxXMLDB:
    def __init__(self):
        self.xml_path = Path("rekordbox.xml")
        self.tracks = {} # ID -> Track Dict
        self.playlists = [] # List of playlist nodes
        self.playlists_tracks = defaultdict(list)
        self.artists = []
        self.genres = []
        self.loaded = False

    def load_xml(self, path: str):
        try:
            tree = ET.parse(path)
            root = tree.getroot()
            self.xml_path = Path(path)
            
            # PARSE COLLECTION
            collection = root.find("COLLECTION")
            self.tracks = {}
            if collection is not None:
                for t in collection.findall("TRACK"):
                    self._parse_track(t)
            
            # PARSE PLAYLISTS (accept both schemas: with or without ROOT wrapper)
            playlists_root = root.find("PLAYLISTS")
            self.playlists = []
            if playlists_root is not None:
                top_nodes = playlists_root.findall("NODE")
                # Standard Rekordbox-XML: single ROOT wrapper of Type=0 carrying all top-level playlists
                if len(top_nodes) == 1 and top_nodes[0].get("Type") == "0":
                    self.playlists = self._parse_playlist_node(top_nodes[0], parent_id="ROOT")
                else:
                    # Flat fallback: NODEs directly under PLAYLISTS are the top-level playlists
                    self.playlists = self._recursive_playlist_parse(playlists_root, "ROOT")

            # Extract Metadata
            self._extract_metadata()
            self.loaded = True
            logger.info(f"Loaded XML: {len(self.tracks)} tracks, {len(self.playlists)} playlist nodes")
            return True
        except Exception as e:
            logger.error(f"Failed to load XML: {e}")
            return False

    def _parse_track(self, node):
        tid = node.get("TrackID")
        if not tid: return
        
        self.tracks[tid] = {
            "id": tid,
            "Title": node.get("Name"),
            "Artist": node.get("Artist"),
            "Album": node.get("Album"),
            "BPM": float(node.get("AverageBpm", 0) or 0),
            "Rating": int(node.get("Rating") or 0),
            "ColorID": node.get("ColorID"),
            "Comment": node.get("Comments"),
            "path": self._decode_path(node.get("Location", "")),
            "Key": node.get("Tonality"),
            "Genre": node.get("Genre"),
            "Label": node.get("Label"),
            "TotalTime": float(node.get("TotalTime", 0) or 0),
            "Bitrate": int(node.get("BitRate") or 0),
            "PlayCount": int(node.get("PlayCount") or 0),
            "Composer": node.get("Composer", ""),
            "Remixer": node.get("Remixer", ""),
            "Lyricist": node.get("Lyricist", ""),
            "Subtitle": node.get("Subtitle", ""),
            "ReleaseYear": int(node.get("Year", 0) or 0),
            "StockDate": node.get("DateAdded", ""),
            "SampleRate": int(node.get("SampleRate", 0) or 0),
            "ISRC": node.get("ISRC", "")
        }
        
        beat_grid = []
        for tempo in node.findall("TEMPO"):
            beat_grid.append({
                "time": float(tempo.get("Inizio", 0)),
                "bpm": float(tempo.get("Bpm", 0)),
                "beat": int(tempo.get("Battito", 1)),
                "metro": tempo.get("Metro", "4/4")
            })
        self.tracks[tid]["beatGrid"] = beat_grid
        
        position_marks = []
        for mark in node.findall("POSITION_MARK"):
            m_data = {
                "Name": mark.get("Name", ""),
                "Type": mark.get("Type", "0"),
                "Start": float(mark.get("Start", 0)),
                "Num": int(mark.get("Num", -1)),
                "Red": int(mark.get("Red") or 0),
                "Green": int(mark.get("Green") or 0),
                "Blue": int(mark.get("Blue") or 0)
            }
            if mark.get("End"):
                m_data["End"] = float(mark.get("End"))
            position_marks.append(m_data)
        self.tracks[tid]["positionMarks"] = position_marks

    def _decode_path(self, location: str) -> str:
        if not location: return ""
        try:
            decoded = unquote(location)
            if decoded.startswith("file://localhost/"):
                decoded = decoded.replace("file://localhost/", "")
            elif decoded.startswith("file://"):
                decoded = decoded.replace("file://", "")
                
            if os.name == 'nt' and decoded.startswith("/") and ":" in decoded[0:10]:
                decoded = decoded.lstrip("/")
            return os.path.normpath(decoded)
        except Exception as e:
            logger.error(f"Error decoding path {location}: {e}")
            return location

    def _parse_playlist_node(self, node, parent_id):
        if node is None: return []
        return self._recursive_playlist_parse(node, parent_id)

    def _recursive_playlist_parse(self, node, parent_id, seq_start=0):
        flat_list = []
        if node is None: return []
        for i, child in enumerate(node.findall("NODE")):
            child_name = child.get("Name")
            child_type = child.get("Type")
            my_id = f"{parent_id}_{i}_{child_name}"
            node_data = {
                "ID": my_id,
                "Name": child_name,
                "ParentID": parent_id,
                "Type": child_type,
                "Seq": seq_start + i
            }
            if child_type == "1":
                self._cache_playlist_tracks(my_id, child)
                node_data["Count"] = len(self.playlists_tracks[my_id])
                node_data["Entries"] = child.get("Entries", "0")
            elif child_type == "4":
                # Smart playlist — parse SmartList sub-element if present
                from .smart_playlist_engine import from_xml_node
                sl = child.find("SmartList")
                node_data["SmartList"] = from_xml_node(sl) if sl is not None else {}
                # Cache materialised tracks too (snapshot at load)
                self._cache_playlist_tracks(my_id, child)
                node_data["Entries"] = child.get("Entries", "0")
            flat_list.append(node_data)
            if child_type == "0":
                flat_list.extend(self._recursive_playlist_parse(child, my_id))
        return flat_list

    def _cache_playlist_tracks(self, pid, node):
        if not hasattr(self, 'playlists_tracks'): self.playlists_tracks = defaultdict(list)
        existing_keys = {t['id'] for t in self.playlists_tracks[pid]}
        for t in node.findall("TRACK"):
            key = t.get("Key")
            if key in self.tracks and key not in existing_keys:
                self.playlists_tracks[pid].append(self.tracks[key])
                existing_keys.add(key)

    def get_playlist_tracks(self, pid):
        return self.playlists_tracks.get(str(pid), [])

    def get_track_details(self, tid):
        return self.tracks.get(str(tid))

    def _extract_metadata(self):
        artist_counts = defaultdict(int)
        genre_counts = defaultdict(int)
        for t in self.tracks.values():
            if t.get("Artist"): 
                track_artists = self._split_artists(t["Artist"])
                for artist in track_artists:
                    artist_counts[artist] += 1
            if t.get("Genre"): genre_counts[t["Genre"]] += 1
        
        self.artists = []
        threshold = 0
        try:
            from .services import SettingsManager
            threshold = SettingsManager.load().get("artist_view_threshold", 0)
        except (OSError, ValueError, KeyError, AttributeError) as e:
            logger.warning(
                "database: failed to load artist_view_threshold — using 0 (%s)", e,
            )

        for i, (name, count) in enumerate(sorted(artist_counts.items())):
            if count >= threshold:
                self.artists.append({
                    "id": f"art_{i}", 
                    "name": name, 
                    "track_count": count
                })
        self.genres = [{"id": f"gen_{i}", "name": name, "track_count": count} for i, (name, count) in enumerate(sorted(genre_counts.items()))]

    @lru_cache(maxsize=1)
    def get_all_labels(self):
        label_counts = defaultdict(int)
        for t in self.tracks.values():
            label = t.get("Label")
            if label:
                normalized = self._normalize_artist_name(label)
                label_counts[normalized] += 1
        return [{"id": f"lbl_{i}", "name": name, "track_count": count} for i, (name, count) in enumerate(sorted(label_counts.items()))]

    @lru_cache(maxsize=1)
    def get_all_albums(self):
        album_counts = defaultdict(int)
        for t in self.tracks.values():
            album = t.get("Album")
            if album: album_counts[album] += 1
        return [{"id": f"alb_{i}", "name": name, "track_count": count} for i, (name, count) in enumerate(sorted(album_counts.items()))]

    def _split_artists(self, artist_str):
        if not artist_str: return []
        # Split by common separators: , & / ; feat. ft. vs. with
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
                "database: artist-name mapping failed for %r (%s)", name, e,
            )

        # 1. Strip leading numbers like "01 ", "1. ", "02-", "1 "
        name = re.sub(r'^\d{1,2}[\s.-]+', '', name)
        
        # 2. Strip common prefixes (case insensitive)
        name = re.sub(r'(?i)^.*(supported by|premiere:?|exclusive:?|dj\s+)\s*', '', name)
        
        # 3. Strip common suffixes (case insensitive)
        name = re.sub(r'(?i)\s+(re-?edit|edit|r[em]+ix|rework|bootleg|flip|cut|vip)\s*.*$', '', name)
        
        return name.strip()

    def get_tracks_by_artist(self, aid):
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

    def get_tracks_by_label(self, aid):
        label_name = next((l["name"] for l in self.get_all_labels() if l["id"] == aid), None)
        if not label_name: return []
        return [t for t in self.tracks.values() if self._normalize_artist_name(t.get("Label", "")) == label_name]

    def get_tracks_by_album(self, aid):
        album_name = next((a["name"] for a in self.get_all_albums() if a["id"] == aid), None)
        if not album_name: return []
        return [t for t in self.tracks.values() if t.get("Album") == album_name]

    def get_tracks_by_artist(self, aid):
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

    def add_track(self, track_data):
        tid = track_data.get("TrackID") or str(int(time.time() * 1000))
        track_data["id"] = tid
        self.tracks[tid] = track_data
        self.save_xml()
        self.get_all_labels.cache_clear()
        self.get_all_albums.cache_clear()
        logger.info(f"Added track {tid} to XML library.")
        return tid

    def create_playlist(self, name, parent_id="ROOT", is_folder=False):
        """Create a new playlist node in the XML library.
        Type "1" = playlist (holds tracks), Type "0" = folder (holds children).
        """
        pid = f"pl_{int(time.time() * 1000)}"
        node = {
            "ID": pid,
            "Name": name,
            "Type": "0" if is_folder else "1",
            "ParentID": parent_id,
            "Tracks": [],
        }
        self.playlists.append(node)
        self.playlists_tracks[pid] = []
        self.save_xml()
        logger.info(f"Created XML playlist '{name}' (pid={pid})")
        return node

    def add_track_to_playlist(self, pid, tid):
        """Append track tid to playlist pid in the XML library."""
        pid = str(pid)
        tid = str(tid)
        track = self.tracks.get(tid)
        if not track:
            logger.warning(f"add_track_to_playlist: track {tid} not in library")
            return False
        existing_ids = {str(t.get("id") or t.get("TrackID")) for t in self.playlists_tracks.get(pid, [])}
        if tid in existing_ids:
            return True  # already there
        self.playlists_tracks[pid].append(track)
        self.save_xml()
        return True

    def find_playlist_by_name(self, name):
        """Walk playlists tree, return first matching node."""
        def _walk(nodes):
            for n in nodes:
                if n.get("Name") == name:
                    return n
                children = n.get("Children") or []
                hit = _walk(children)
                if hit:
                    return hit
            return None
        return _walk(self.playlists)

    def find_playlist(self, pid):
        """Get playlist node by ID."""
        pid = str(pid)
        for p in self.playlists:
            if str(p.get("ID")) == pid:
                return p
        return None

    def get_playlist_tree(self):
        """Build hierarchical tree (same shape as LiveRekordboxDB.get_playlist_tree)."""
        if not self.playlists:
            return []
        node_map = {r['ID']: {**r, 'Children': []} for r in self.playlists}
        tree = []
        for r in self.playlists:
            pid = r.get('ParentID')
            if pid in node_map:
                node_map[pid]['Children'].append(node_map[r['ID']])
            elif str(pid).upper() == "ROOT":
                tree.append(node_map[r['ID']])
        for node in node_map.values():
            node['Children'].sort(key=lambda x: x.get('Seq', 0))
        tree.sort(key=lambda x: x.get('Seq', 0))
        return tree

    def remove_track_from_playlist(self, pid, tid):
        """Remove track tid from playlist pid (does not delete from collection)."""
        pid = str(pid); tid = str(tid)
        if pid not in self.playlists_tracks:
            return False
        before = len(self.playlists_tracks[pid])
        self.playlists_tracks[pid] = [
            t for t in self.playlists_tracks[pid]
            if str(t.get("id") or t.get("TrackID")) != tid
        ]
        if len(self.playlists_tracks[pid]) < before:
            self.save_xml()
            return True
        return False

    def reorder_playlist_track(self, pid, tid, new_index):
        """Move track tid within playlist pid to position new_index (0-based)."""
        pid = str(pid); tid = str(tid)
        if pid not in self.playlists_tracks:
            return False
        tracks = self.playlists_tracks[pid]
        idx = next((i for i, t in enumerate(tracks)
                    if str(t.get("id") or t.get("TrackID")) == tid), -1)
        if idx < 0:
            return False
        track = tracks.pop(idx)
        new_index = max(0, min(new_index, len(tracks)))
        tracks.insert(new_index, track)
        self.save_xml()
        return True

    def rename_playlist(self, pid, new_name):
        """Rename playlist/folder by id."""
        node = self.find_playlist(pid)
        if not node:
            return False
        node["Name"] = new_name
        self.save_xml()
        return True

    def move_playlist(self, pid, new_parent_id, target_id=None, position=None):
        """Move playlist node. position can be:
           - int (XML-native order)
           - "inside"/"before"/"after" with target_id (Live-DB style)
        """
        node = self.find_playlist(pid)
        if not node:
            return False
        # Determine final parent
        if position in ("inside",) and target_id:
            new_parent_id = target_id
        elif position in ("before", "after") and target_id:
            sibling = self.find_playlist(target_id)
            if sibling:
                new_parent_id = sibling.get("ParentID") or "ROOT"
        # Cycle protection
        target = self.find_playlist(new_parent_id) if new_parent_id and new_parent_id != "ROOT" else None
        if target:
            cur = target
            while cur:
                if str(cur.get("ID")) == str(pid):
                    logger.warning("move_playlist: cycle detected")
                    return False
                pp = cur.get("ParentID")
                cur = self.find_playlist(pp) if pp and pp != "ROOT" else None
        node["ParentID"] = str(new_parent_id) if new_parent_id else "ROOT"
        if isinstance(position, int):
            self.playlists.remove(node)
            siblings = [p for p in self.playlists if p.get("ParentID") == node["ParentID"]]
            if 0 <= position < len(siblings):
                insert_at = self.playlists.index(siblings[position])
            else:
                insert_at = len(self.playlists)
            self.playlists.insert(insert_at, node)
        self.save_xml()
        return True

    def delete_playlist(self, pid):
        """Delete playlist + all child playlists/folders recursively."""
        pid = str(pid)
        node = self.find_playlist(pid)
        if not node:
            return False

        def _collect_descendants(parent_id):
            result = [parent_id]
            for p in self.playlists:
                if p.get("ParentID") == parent_id:
                    result.extend(_collect_descendants(str(p.get("ID"))))
            return result

        to_delete = set(_collect_descendants(pid))
        self.playlists = [p for p in self.playlists if str(p.get("ID")) not in to_delete]
        for did in to_delete:
            self.playlists_tracks.pop(did, None)
        self.save_xml()
        logger.info(f"Deleted XML playlist tree rooted at {pid} ({len(to_delete)} nodes)")
        return True

    def create_folder(self, name, parent_id="ROOT"):
        """Convenience wrapper: create_playlist(is_folder=True)."""
        return self.create_playlist(name, parent_id=parent_id, is_folder=True)

    def create_smart_playlist(self, name, criteria, parent_id="ROOT"):
        """Smart playlist (Type=4). criteria = dict matching Rekordbox <SmartList> spec.
        Example: {"LogicalOperator": "all", "AutomaticUpdate": "1",
                  "conditions": [{"Field": "8", "Operator": "0", "ValueLeft": "120", "ValueRight": "130", "ValueUnit": "0"}]}
        """
        pid = f"pl_{int(time.time() * 1000)}"
        node = {
            "ID": pid,
            "Name": name,
            "Type": "4",
            "ParentID": parent_id,
            "Tracks": [],
            "SmartList": criteria or {},
        }
        self.playlists.append(node)
        self.playlists_tracks[pid] = []
        self.save_xml()
        return node

    def update_smart_playlist(self, pid, criteria):
        node = self.find_playlist(pid)
        if not node:
            return False
        node["SmartList"] = criteria
        self.save_xml()
        return True

    def evaluate_smart_playlist(self, pid):
        """Apply smart-list criteria → list of matching tracks."""
        from .smart_playlist_engine import evaluate
        node = self.find_playlist(pid)
        if not node or node.get("Type") != "4":
            return []
        return evaluate(node.get("SmartList", {}), list(self.tracks.values()))

    # ── MyTags (Pioneer parity for XML mode) ───────────────────────────────
    def _ensure_mytags(self):
        if not hasattr(self, "_mytags"):
            self._mytags = {}            # tag_id → name
            self._track_mytags = {}      # track_id → set(tag_ids)

    def list_mytags(self):
        self._ensure_mytags()
        return [{"id": tid, "name": n} for tid, n in self._mytags.items()]

    def create_mytag(self, name):
        self._ensure_mytags()
        tid = f"mt_{int(time.time() * 1000)}"
        self._mytags[tid] = name
        self.save_xml()
        return tid

    def delete_mytag(self, tag_id):
        self._ensure_mytags()
        self._mytags.pop(str(tag_id), None)
        for tids in self._track_mytags.values():
            tids.discard(str(tag_id))
        self.save_xml()
        return True

    def get_track_mytags(self, tid):
        self._ensure_mytags()
        ids = list(self._track_mytags.get(str(tid), set()))
        return [{"id": i, "name": self._mytags.get(i, "")} for i in ids]

    def set_track_mytags(self, tid, tag_ids):
        self._ensure_mytags()
        self._track_mytags[str(tid)] = set(str(x) for x in tag_ids)
        self.save_xml()
        return {"track_id": str(tid), "tag_ids": list(self._track_mytags[str(tid)])}

    def delete_track(self, tid):
        tid = str(tid)
        if tid in self.tracks:
            del self.tracks[tid]
            # Remove from every playlist
            for pid in list(self.playlists_tracks.keys()):
                self.playlists_tracks[pid] = [
                    t for t in self.playlists_tracks[pid]
                    if str(t.get("id") or t.get("TrackID")) != tid
                ]
            self.save_xml()
            self.get_all_labels.cache_clear()
            self.get_all_albums.cache_clear()
            logger.info(f"Deleted track {tid} from XML library.")
            return True
        return False

    def save_xml(self):
        try:
            root = ET.Element("DJ_PLAYLISTS", Version="1.0.0")
            collection = ET.SubElement(root, "COLLECTION", Entries=str(len(self.tracks)))
            for tid, track in self.tracks.items():
                t_node = ET.SubElement(collection, "TRACK")
                t_node.set("TrackID", str(tid))
                t_node.set("Name", track.get("Title") or "")
                t_node.set("Artist", track.get("Artist") or "")
                t_node.set("Album", track.get("Album") or "")
                t_node.set("AverageBpm", str(track.get("BPM") or 0))
                p = track.get("path", "")
                safe_path = p.replace(os.sep, "/").replace(" ", "%20")
                if not safe_path.startswith("file://") and not safe_path.startswith("http"):
                    if ":" in safe_path or safe_path.startswith("/"):
                        safe_path = "file://localhost/" + safe_path.lstrip("/")
                t_node.set("Location", safe_path)
                t_node.set("Tonality", track.get("Key") or "")
                t_node.set("Genre", track.get("Genre") or "")
                t_node.set("Label", track.get("Label") or "")
                t_node.set("TotalTime", str(track.get("TotalTime") or 0))
                t_node.set("Comments", track.get("Comment") or "")
                for beat in track.get("beatGrid", []):
                    tempo = ET.SubElement(t_node, "TEMPO")
                    tempo.set("Inizio", str(beat.get("time", 0)))
                    tempo.set("Bpm", str(beat.get("bpm", 0)))
                    tempo.set("Battito", str(beat.get("beat", 1)))
                    tempo.set("Metro", beat.get("metro", "4/4"))
                for mark in track.get("positionMarks", []):
                    pm = ET.SubElement(t_node, "POSITION_MARK")
                    pm.set("Name", str(mark.get("Name") or ""))
                    pm.set("Type", str(mark.get("Type", "0")))
                    pm.set("Start", str(mark.get("Start", 0)))
                    pm.set("Num", str(mark.get("Num", -1)))
                    pm.set("Red", str(mark.get("Red", 0)))
                    pm.set("Green", str(mark.get("Green", 0)))
                    pm.set("Blue", str(mark.get("Blue", 0)))
                    if mark.get("End"):
                        pm.set("End", str(mark["End"]))
            playlists_root = ET.SubElement(root, "PLAYLISTS")
            # Wrap in a top-level ROOT NODE (Type=0) so the Rekordbox XML schema
            # — and our own _recursive_playlist_parse — can walk the tree.
            playlists_root_node = ET.SubElement(
                playlists_root, "NODE", Name="ROOT", Type="0",
                Count=str(len([p for p in self.playlists if p.get('ParentID') == 'ROOT'])),
            )

            def _add_smart_list(parent_node, criteria):
                """Append <SmartList> with conditions inside a Type=4 playlist."""
                if not criteria:
                    return
                sl = ET.SubElement(parent_node, "SmartList")
                sl.set("LogicalOperator", str(criteria.get("LogicalOperator", "all")))
                sl.set("AutomaticUpdate", str(criteria.get("AutomaticUpdate", "1")))
                for c in criteria.get("conditions", []):
                    cn = ET.SubElement(sl, "CONDITION")
                    cn.set("Field", str(c.get("Field", "")))
                    cn.set("Operator", str(c.get("Operator", "1")))
                    cn.set("ValueLeft", str(c.get("ValueLeft", "")))
                    cn.set("ValueRight", str(c.get("ValueRight", "")))
                    cn.set("ValueUnit", str(c.get("ValueUnit", "0")))

            def build_xml_node(parent_node, pid):
                children = [p for p in self.playlists if p['ParentID'] == pid]
                for child in sorted(children, key=lambda x: x.get('Seq', 0)):
                    ctype = child.get('Type', '1')
                    node = ET.SubElement(parent_node, "NODE", Name=child['Name'], Type=ctype)
                    if ctype == "0":
                        # Folder
                        node.set("Count", str(len([p for p in self.playlists if p['ParentID'] == child['ID']])))
                        build_xml_node(node, child['ID'])
                    elif ctype == "4":
                        # Smart playlist
                        _add_smart_list(node, child.get("SmartList") or {})
                        # Optional: also persist current materialised matches for tools that read XML literally
                        try:
                            from .smart_playlist_engine import evaluate as _eval_smart
                            matched = _eval_smart(child.get("SmartList") or {}, list(self.tracks.values()))
                        except Exception:
                            matched = []
                        node.set("Entries", str(len(matched)))
                        for t in matched:
                            ET.SubElement(node, "TRACK", Key=str(t.get('id') or t.get('TrackID')))
                    else:
                        # Normal playlist (Type=1)
                        tracks_in_pl = self.playlists_tracks.get(child['ID'], [])
                        node.set("Entries", str(len(tracks_in_pl)))
                        for t in tracks_in_pl:
                            ET.SubElement(node, "TRACK", Key=str(t['id']))
            build_xml_node(playlists_root_node, "ROOT")
            tree = ET.ElementTree(root)
            tree.write(str(self.xml_path), encoding="utf-8", xml_declaration=True)
            logger.info(f"Saved XML to {self.xml_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to save XML: {e}", exc_info=True)
            return False

class RekordboxDB:
    def __init__(self):
        # Discover Live DB path
        # 1. Try existing Rekordbox installation
        self.live_db_path = Path(os.path.expandvars(r"%APPDATA%\Pioneer\rekordbox\master.db"))
        if not self.live_db_path.exists():
            self.live_db_path = Path(os.path.expandvars(r"%APPDATA%\Pioneer\rekordbox6\master.db"))

        # 2. Fallback: standalone master.db inside our own app-data folder
        # (created on demand via OneLibrary.create — see ensure_standalone_master_db)
        if not self.live_db_path.exists():
            standalone_dir = Path(os.path.expandvars(r"%APPDATA%\LibraryManagementSystem\rekordbox"))
            self.live_db_path = standalone_dir / "master.db"

        self.mode = "live" if self.live_db_path.exists() else "xml"
        self.xml_db = RekordboxXMLDB()
        self.live_db = None
        self.loaded = False
        logger.info(f"Database initialized (Mode: {self.mode})")

    def ensure_standalone_master_db(self) -> bool:
        """Create an empty master.db at our private location if Rekordbox isn't installed.
        Uses rbox.OneLibrary.create — produces a CDJ-compatible Library One DB.
        """
        if self.live_db_path.exists():
            return True
        try:
            import rbox
            self.live_db_path.parent.mkdir(parents=True, exist_ok=True)
            mytag_dbid = "lms_local_master"
            rbox.OneLibrary.create(str(self.live_db_path), mytag_dbid)
            logger.info(f"Created standalone master.db at {self.live_db_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to create standalone master.db: {e}")
            return False

    def _get_hide_streaming_setting(self):
        try:
            from .services import SettingsManager
            return SettingsManager.load().get("hide_streaming", False)
        except (OSError, ValueError, KeyError, AttributeError) as e:
            logger.warning(
                "database: failed to read hide_streaming setting — defaulting to False (%s)",
                e,
            )
            return False

    def _filter_tracks(self, tracks_source):
        hide = self._get_hide_streaming_setting()
        if not hide:
            return tracks_source
            
        def is_streaming(t):
            # Check both 'path' (standardized) and 'Location' (raw XML)
            p = t.get('path', t.get('Location', ''))
            if not p: return False
            return p.startswith('soundcloud:') or p.startswith('spotify:') or p.startswith('tidal:') or p.startswith('beatport:')
            
        if isinstance(tracks_source, dict):
            return {tid: t for tid, t in tracks_source.items() if not is_streaming(t)}
        elif isinstance(tracks_source, list):
            return [t for t in tracks_source if not is_streaming(t)]
        return tracks_source

    @property
    def tracks(self): 
        return self._filter_tracks(self.active_db.tracks)

    @property
    def playlists(self): return self.active_db.playlists

    @property
    def artists(self): return self.active_db.artists

    @property
    def genres(self): return self.active_db.genres

    @property
    def xml_path(self):
        return self.xml_db.xml_path

    @property
    def active_db(self):
        if self.mode == "live":
            if not self.live_db:
                self.live_db = LiveRekordboxDB(str(self.live_db_path))
            return self.live_db
        return self.xml_db

    def set_mode(self, mode: str) -> bool:
        if mode not in ["xml", "live"]: return False
        if mode == "live" and not self.live_db_path.exists():
            # auto-create our private standalone master.db so Live works without Rekordbox
            if not self.ensure_standalone_master_db():
                logger.error("Cannot switch to live mode: master.db unavailable and standalone creation failed")
                return False
        self.mode = mode
        logger.info(f"Switched to mode: {self.mode}")
        return True

    def load_library(self, path: Optional[str] = None) -> bool:
        if self.mode == "live":
            success = self.active_db.load()
            self.loaded = success
            return success
        else:
            if not path: path = "rekordbox.xml"
            success = self.xml_db.load_xml(path)
            self.loaded = success
            return success

    def unload_library(self) -> bool:
        self.xml_db.tracks = {}
        self.xml_db.playlists = []
        self.xml_db.loaded = False
        if self.live_db:
             self.live_db.tracks = {}
             self.live_db.loaded = False
        self.loaded = False
        return True

    def create_new_library(self, path: Optional[str] = None) -> bool:
        target = Path(path) if path else Path("rekordbox.xml")
        target.parent.mkdir(parents=True, exist_ok=True)
        self.xml_db.xml_path = target
        self.xml_db.tracks = {}
        self.xml_db.playlists = []
        self.xml_db.playlists_tracks = defaultdict(list)
        self.xml_db.artists = []
        self.xml_db.genres = []
        self.xml_db.loaded = True
        self.mode = "xml"
        self.loaded = True
        self.xml_db.save_xml()
        logger.info(f"Created new empty library at {target}")
        return True

    def refresh_metadata(self) -> None:
        if not self.active_db: return
        if hasattr(self.active_db, "_finalize_ui_metadata"):
            self.active_db._finalize_ui_metadata()
        elif hasattr(self.active_db, "_extract_metadata"):
            self.active_db._extract_metadata()

    # Delegate methods
    def get_all_tracks(self) -> List[Dict[str, Any]]:
        return list(self.tracks.values())

    def get_all_artists(self) -> List[Dict[str, Any]]: return self.active_db.artists
    def get_all_genres(self) -> List[Dict[str, Any]]: return self.active_db.genres
    def get_all_labels(self) -> List[Dict[str, Any]]:
        if hasattr(self.active_db, "get_all_labels"):
            return self.active_db.get_all_labels()
        return []

    def get_all_albums(self) -> List[Dict[str, Any]]:
        if hasattr(self.active_db, "get_all_albums"):
            return self.active_db.get_all_albums()
        return []
    def get_playlist_tree(self) -> List[Dict[str, Any]]:
        if hasattr(self.active_db, "get_playlist_tree"):
            return self.active_db.get_playlist_tree()
        return []
    def get_tracks_by_artist(self, aid: str) -> List[Dict[str, Any]]:
        return self._filter_tracks(self.active_db.get_tracks_by_artist(aid))
    def get_tracks_by_label(self, aid: str) -> List[Dict[str, Any]]:
        if hasattr(self.active_db, "get_tracks_by_label"):
            return self._filter_tracks(self.active_db.get_tracks_by_label(aid))
        return []
    def get_tracks_by_album(self, aid: str) -> List[Dict[str, Any]]:
        if hasattr(self.active_db, "get_tracks_by_album"):
            return self._filter_tracks(self.active_db.get_tracks_by_album(aid))
        return []
    def get_playlist_tracks(self, pid: str) -> List[Dict[str, Any]]:
        return self._filter_tracks(self.active_db.get_playlist_tracks(pid))
    def get_track_details(self, tid: str) -> Optional[Dict[str, Any]]:
        return self.active_db.get_track_details(tid)

    def add_track(self, track_data: Dict[str, Any]) -> Optional[str]:
        if hasattr(self.active_db, "add_track"):
            return self.active_db.add_track(track_data)
        return None

    def delete_track(self, tid: str) -> bool:
        if hasattr(self.active_db, "delete_track"):
            return self.active_db.delete_track(tid)
        return False

    def rename_playlist(self, pid: str, name: str) -> bool:
        if hasattr(self.active_db, "rename_playlist"):
            return self.active_db.rename_playlist(pid, name)
        return False

    def move_playlist(
        self,
        pid: str,
        new_parent_id: str,
        target_id: Optional[str] = None,
        position: Optional[str] = None,
    ) -> bool:
        if hasattr(self.active_db, "move_playlist"):
            return self.active_db.move_playlist(pid, new_parent_id, target_id, position)
        return False

    def delete_playlist(self, pid: str) -> bool:
        if hasattr(self.active_db, "delete_playlist"):
            return self.active_db.delete_playlist(pid)
        return False

    def reorder_playlist_track(self, pid: str, tid: str, new_index: int) -> bool:
        if hasattr(self.active_db, "reorder_playlist_track"):
            return self.active_db.reorder_playlist_track(pid, tid, new_index)
        return False

    def create_folder(self, name: str, parent_id: str = "ROOT") -> Optional[Dict[str, Any]]:
        if hasattr(self.active_db, "create_folder"):
            return self.active_db.create_folder(name, parent_id)
        if hasattr(self.active_db, "create_playlist"):
            return self.active_db.create_playlist(name, parent_id, is_folder=True)
        return None

    def create_smart_playlist(self, name: str, criteria: Dict[str, Any], parent_id: str = "ROOT") -> Optional[Dict[str, Any]]:
        if hasattr(self.active_db, "create_smart_playlist"):
            return self.active_db.create_smart_playlist(name, criteria, parent_id)
        # Fallback for LiveDB: register the criteria on a normal Type-1 playlist
        # and store SmartList JSON in our SC-side cache so evaluate still works.
        if hasattr(self.active_db, "create_playlist"):
            node = self.active_db.create_playlist(name, parent_id, is_folder=False)
            if not node:
                return None
            pid = node.get("ID") if isinstance(node, dict) else getattr(node, "id", None)
            if pid:
                node["Type"] = "4"
                node["SmartList"] = criteria or {}
                if not hasattr(self, "_smart_overlay"):
                    self._smart_overlay = {}
                self._smart_overlay[str(pid)] = criteria or {}
            return node
        return None

    def update_smart_playlist(self, pid: str, criteria: Dict[str, Any]) -> bool:
        if hasattr(self.active_db, "update_smart_playlist"):
            return self.active_db.update_smart_playlist(pid, criteria)
        if not hasattr(self, "_smart_overlay"):
            self._smart_overlay = {}
        self._smart_overlay[str(pid)] = criteria
        return True

    def evaluate_smart_playlist(self, pid: str) -> List[Dict[str, Any]]:
        if hasattr(self.active_db, "evaluate_smart_playlist"):
            return self.active_db.evaluate_smart_playlist(pid)
        # Fallback evaluator using our smart engine + DB-wrapper tracks
        from .smart_playlist_engine import evaluate as _eval
        criteria = (getattr(self, "_smart_overlay", {}) or {}).get(str(pid)) or {}
        if not criteria:
            return []
        return _eval(criteria, list(self.tracks.values()))

    def get_tracks_missing_artwork(self) -> List[Dict[str, Any]]:
        """Returns a list of tracks where Artwork is empty or None."""
        missing: List[Dict[str, Any]] = []
        for t in self.tracks.values():
            if not t.get('Artwork'):
                missing.append(t)
        return missing

    def create_playlist(
        self,
        name: str,
        parent_id: str = "ROOT",
        is_folder: bool = False,
        tracks: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        if hasattr(self.active_db, "create_playlist"):
            pl = self.active_db.create_playlist(name, parent_id, is_folder)
            if pl and tracks:
                pid = pl.get('ID') if isinstance(pl, dict) else getattr(pl, 'id', None)
                if pid:
                    for tid in tracks:
                        self.add_track_to_playlist(str(pid), str(tid))
            return pl
        return None

    def add_track_to_playlist(self, pid: str, tid: str) -> bool:
        if hasattr(self.active_db, "add_track_to_playlist"):
            return self.active_db.add_track_to_playlist(pid, tid)
        return False

    def remove_track_from_playlist(self, pid: str, tid: str) -> bool:
        if hasattr(self.active_db, "remove_track_from_playlist"):
            return self.active_db.remove_track_from_playlist(pid, tid)
        return False

    def save(self) -> bool:
        if hasattr(self.active_db, "save_xml"):
            return self.active_db.save_xml()
        return True # Live DB is auto-saved or handled via updates

    def update_tracks_metadata(self, track_ids: List[str], updates: Dict[str, Any]) -> bool:
        success = True
        for tid in track_ids:
            if self.mode == "live":
                if not self.active_db.update_track_metadata(tid, updates):
                    success = False
            else:
                # XML Mode
                if tid in self.xml_db.tracks:
                    t = self.xml_db.tracks[tid]
                    for k, v in updates.items():
                        t[k] = v
                else:
                    success = False
        
        if self.mode == "xml" and success:
            self.xml_db.save_xml()
            
        return success

    def update_track_comment(self, tid: str, comment: str) -> bool:
        return self.update_tracks_metadata([tid], {"Comment": comment})


# Wrap every mutating method on the facade with the module-level write
# lock so concurrent route handlers can't race against each other.
# Reads (tracks property, get_track_details, get_playlist_tracks, etc.)
# are NOT wrapped — they snapshot the underlying dicts on access.
for _name in (
    "set_mode", "load_library", "unload_library", "create_new_library",
    "refresh_metadata", "add_track", "delete_track", "rename_playlist",
    "move_playlist", "delete_playlist", "reorder_playlist_track",
    "create_folder", "create_smart_playlist", "update_smart_playlist",
    "create_playlist", "add_track_to_playlist", "remove_track_from_playlist",
    "save", "update_tracks_metadata", "update_track_comment",
):
    setattr(RekordboxDB, _name, _serialised(getattr(RekordboxDB, _name)))
del _name


db = RekordboxDB()
