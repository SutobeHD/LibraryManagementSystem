import os
import json
import logging
import time
import re
import xml.etree.ElementTree as ET
import shutil
from urllib.parse import unquote
from pathlib import Path
from collections import defaultdict
from .config import REKORDBOX_ROOT, DB_FILENAME, BACKUP_DIR
from .live_database import LiveRekordboxDB

logger = logging.getLogger(__name__)

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
            
            # PARSE PLAYLISTS
            playlists_root = root.find("PLAYLISTS")
            self.playlists = []
            if playlists_root is not None:
                self.playlists = self._parse_playlist_node(playlists_root.find("NODE"), parent_id="ROOT")

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
        except: pass

        for i, (name, count) in enumerate(sorted(artist_counts.items())):
            if count >= threshold:
                self.artists.append({
                    "id": f"art_{i}", 
                    "name": name, 
                    "track_count": count
                })
        self.genres = [{"id": f"gen_{i}", "name": name, "track_count": count} for i, (name, count) in enumerate(sorted(genre_counts.items()))]

    def get_all_labels(self):
        label_counts = defaultdict(int)
        for t in self.tracks.values():
            label = t.get("Label")
            if label:
                normalized = self._normalize_artist_name(label)
                label_counts[normalized] += 1
        return [{"id": f"lbl_{i}", "name": name, "track_count": count} for i, (name, count) in enumerate(sorted(label_counts.items()))]

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
        except: pass

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
        logger.info(f"Added track {tid} to XML library.")
        return tid

    def delete_track(self, tid):
        tid = str(tid)
        if tid in self.tracks:
            del self.tracks[tid]
            # Also remove from playlists? 
            # Ideally yes, but XML structure might be loose.
            # For now, just remove from collection.
            self.save_xml()
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
            def build_xml_node(parent_node, pid):
                children = [p for p in self.playlists if p['ParentID'] == pid]
                for child in sorted(children, key=lambda x: x.get('Seq', 0)):
                    node = ET.SubElement(parent_node, "NODE", Name=child['Name'], Type=child['Type'])
                    if child['Type'] == "1":
                        tracks_in_pl = self.playlists_tracks.get(child['ID'], [])
                        node.set("Entries", str(len(tracks_in_pl)))
                        for t in tracks_in_pl:
                            ET.SubElement(node, "TRACK", Key=str(t['id']))
                    else:
                        node.set("Count", str(len([p for p in self.playlists if p['ParentID'] == child['ID']])))
                        build_xml_node(node, child['ID'])
            build_xml_node(playlists_root, "ROOT")
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
        self.live_db_path = Path(os.path.expandvars(r"%APPDATA%\Pioneer\rekordbox\master.db"))
        if not self.live_db_path.exists():
            self.live_db_path = Path(os.path.expandvars(r"%APPDATA%\Pioneer\rekordbox6\master.db"))

        self.mode = "live" if self.live_db_path.exists() else "xml"
        self.xml_db = RekordboxXMLDB()
        self.live_db = None
        self.loaded = False
        
        logger.info(f"Database initialized (Mode: {self.mode})")

    def _get_hide_streaming_setting(self):
        try:
            from .services import SettingsManager
            return SettingsManager.load().get("hide_streaming", False)
        except:
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

    def set_mode(self, mode: str):
        if mode not in ["xml", "live"]: return False
        self.mode = mode
        logger.info(f"Switched to mode: {self.mode}")
        return True

    def load_library(self, path=None):
        if self.mode == "live":
            success = self.active_db.load()
            self.loaded = success
            return success
        else:
            if not path: path = "rekordbox.xml"
            success = self.xml_db.load_xml(path)
            self.loaded = success
            return success

    def unload_library(self):
        self.xml_db.tracks = {}
        self.xml_db.playlists = []
        self.xml_db.loaded = False
        if self.live_db:
             self.live_db.tracks = {}
             self.live_db.loaded = False
        self.loaded = False
        return True

    def refresh_metadata(self):
        if not self.active_db: return
        if hasattr(self.active_db, "_finalize_ui_metadata"):
            self.active_db._finalize_ui_metadata()
        elif hasattr(self.active_db, "_extract_metadata"):
            self.active_db._extract_metadata()

    # Delegate methods
    def get_all_tracks(self):
        return list(self.tracks.values())

    def get_all_artists(self): return self.active_db.artists
    def get_all_genres(self): return self.active_db.genres
    def get_all_labels(self):
        if hasattr(self.active_db, "get_all_labels"):
            return self.active_db.get_all_labels()
        return []

    def get_all_albums(self):
        if hasattr(self.active_db, "get_all_albums"):
            return self.active_db.get_all_albums()
        return []
    def get_playlist_tree(self):
        if hasattr(self.active_db, "get_playlist_tree"):
            return self.active_db.get_playlist_tree()
        return []
    def get_tracks_by_artist(self, aid): 
        return self._filter_tracks(self.active_db.get_tracks_by_artist(aid))
    def get_tracks_by_label(self, aid):
        if hasattr(self.active_db, "get_tracks_by_label"):
            return self._filter_tracks(self.active_db.get_tracks_by_label(aid))
        return []
    def get_tracks_by_album(self, aid):
        if hasattr(self.active_db, "get_tracks_by_album"):
            return self._filter_tracks(self.active_db.get_tracks_by_album(aid))
        return []
    def get_playlist_tracks(self, pid): 
        return self._filter_tracks(self.active_db.get_playlist_tracks(pid))
    def get_track_details(self, tid): return self.active_db.get_track_details(tid)
    
    def add_track(self, track_data):
        if hasattr(self.active_db, "add_track"):
            return self.active_db.add_track(track_data)
        return None

    def delete_track(self, tid):
        if hasattr(self.active_db, "delete_track"):
            return self.active_db.delete_track(tid)
        return False

    def rename_playlist(self, pid, name):
        if hasattr(self.active_db, "rename_playlist"):
            return self.active_db.rename_playlist(pid, name)
        return False

    def move_playlist(self, pid, new_parent_id, target_id=None, position=None):
        if hasattr(self.active_db, "move_playlist"):
            return self.active_db.move_playlist(pid, new_parent_id, target_id, position)
        return False

    def delete_playlist(self, pid):
        if hasattr(self.active_db, "delete_playlist"):
            return self.active_db.delete_playlist(pid)
        return False

    def get_tracks_missing_artwork(self):
        """Returns a list of tracks where Artwork is empty or None."""
        missing = []
        for t in self.tracks.values():
            if not t.get('Artwork'):
                missing.append(t)
        return missing

    def create_playlist(self, name, parent_id="ROOT", is_folder=False, tracks=None):
        if hasattr(self.active_db, "create_playlist"):
            pl = self.active_db.create_playlist(name, parent_id, is_folder)
            if pl and tracks:
                pid = pl.get('ID') if isinstance(pl, dict) else getattr(pl, 'id', None)
                if pid:
                    for tid in tracks:
                        self.add_track_to_playlist(str(pid), str(tid))
            return pl
        return None

    def add_track_to_playlist(self, pid, tid):
        if hasattr(self.active_db, "add_track_to_playlist"):
            return self.active_db.add_track_to_playlist(pid, tid)
        return False

    def remove_track_from_playlist(self, pid, tid):
        if hasattr(self.active_db, "remove_track_from_playlist"):
            return self.active_db.remove_track_from_playlist(pid, tid)
        return False
    
    def save(self):
        if hasattr(self.active_db, "save_xml"):
            return self.active_db.save_xml()
        return True # Live DB is auto-saved or handled via updates

    def update_tracks_metadata(self, track_ids, updates):
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

    def update_track_comment(self, tid, comment):
        return self.update_tracks_metadata([tid], {"Comment": comment})

db = RekordboxDB()
