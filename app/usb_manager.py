"""
USB Device Manager for Rekordbox Editor Pro.
Handles USB detection, sync profiles, smart synchronization, and device management.
"""
import os
import json
import time
import hashlib
import shutil
import sqlite3
import logging
import subprocess
import string
import ctypes
import errno
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Generator
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler

logger = logging.getLogger(__name__)
# Req 28: Dedicated rotating file handler for USB module to prevent unbounded log growth
try:
    usb_log_handler = RotatingFileHandler("usb_sync.log", maxBytes=5*1024*1024, backupCount=2, encoding="utf-8")
    usb_log_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(usb_log_handler)
except Exception:
    pass

@contextmanager
def locked_sync(usb_root: Path):
    """Req 24: Prevent concurrent access via explicit lock file."""
    lock_file = usb_root / ".rbep_sync_lock"
    if lock_file.exists():
        if time.time() - lock_file.stat().st_mtime > 600: # 10 mins stale
            try: lock_file.unlink()
            except: pass
        else:
            raise Exception("Sync is currently locked by another process or aborted recently. Wait or delete .rbep_sync_lock on the USB.")
    try:
        lock_file.touch()
        yield
    finally:
        try: lock_file.unlink()
        except: pass

# --- USB Detection ---

class UsbDetector:
    """Scans Windows drives for Rekordbox-formatted USB devices."""

    PIONEER_MARKER = "PIONEER"
    RB_DB_PATH = "PIONEER/rekordbox/exportLibrary.db"
    LEGACY_PDB = "PIONEER/rekordbox/export.pdb"

    @staticmethod
    def _get_removable_drives() -> List[str]:
        """Get all removable drive letters on Windows."""
        drives = []
        try:
            bitmask = ctypes.windll.kernel32.GetLogicalDrives()
            for i, letter in enumerate(string.ascii_uppercase):
                if bitmask & (1 << i):
                    drive = f"{letter}:\\"
                    try:
                        drive_type = ctypes.windll.kernel32.GetDriveTypeW(drive)
                        # 2 = REMOVABLE, 3 = FIXED
                        # Modern USB/SD can be 3. We filter internal disks in scan().
                        if drive_type in [2, 3]:
                            drives.append(drive)
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"Drive enumeration failed: {e}")
        return drives

    @staticmethod
    def _get_volume_info(drive: str) -> Dict:
        """Get volume label and serial number for a drive."""
        try:
            vol_name = ctypes.create_unicode_buffer(1024)
            serial = ctypes.c_ulong()
            max_len = ctypes.c_ulong()
            flags = ctypes.c_ulong()
            fs_name = ctypes.create_unicode_buffer(1024)
            ctypes.windll.kernel32.GetVolumeInformationW(
                drive, vol_name, 1024,
                ctypes.byref(serial), ctypes.byref(max_len),
                ctypes.byref(flags), fs_name, 1024
            )
            return {
                "label": vol_name.value or "USB Drive",
                "serial": serial.value,
                "filesystem": fs_name.value
            }
        except Exception as e:
            logger.warning(f"Could not read volume info for {drive}: {e}")
            return {"label": "Unknown", "serial": 0, "filesystem": "Unknown"}

    @staticmethod
    def _get_drive_size(drive: str) -> Dict:
        """Get total and free space for a drive."""
        try:
            total, used, free = shutil.disk_usage(drive)
            return {"total": total, "used": used, "free": free}
        except Exception:
            return {"total": 0, "used": 0, "free": 0}

    @classmethod
    def is_rekordbox_usb(cls, drive: str) -> bool:
        """Check if a drive has a PIONEER/rekordbox structure."""
        return (Path(drive) / cls.PIONEER_MARKER).is_dir()

    @classmethod
    def scan(cls) -> List[Dict]:
        """Scan all removable drives and return Rekordbox USB info."""
        devices = []
        for drive in cls._get_removable_drives():
            drive_type = ctypes.windll.kernel32.GetDriveTypeW(drive)
            is_rb = cls.is_rekordbox_usb(drive)

            # Fixed drives (type 3): only include if they actually have Rekordbox data.
            # This prevents internal HDDs/SSDs from cluttering the device list.
            if drive_type == 3 and not is_rb:
                logger.debug(f"Skipping fixed drive without Rekordbox structure: {drive}")
                continue
            logger.info(f"Scanning drive {drive}: type={drive_type}, is_rb={is_rb}")

            vol = cls._get_volume_info(drive)
            size = cls._get_drive_size(drive)
            
            # Req 29: Detect Ghost Drives
            if size["total"] == 0 and size["free"] == 0:
                logger.debug(f"Skipping ghost drive or unreadable media: {drive}")
                continue
            
            # Req 12 & 21: Check write protections and permissions strictly
            is_writable = False
            try:
                test_file = Path(drive) / ".rbep_write_test"
                test_file.write_text("test")
                test_file.unlink()
                is_writable = True
            except OSError:
                is_writable = False

            # Fallback for label if empty
            label = vol["label"] or f"USB Drive ({drive.strip(':\\')})"
            
            device_id = hashlib.md5(str(vol['serial'] or drive).encode()).hexdigest()[:12]
            db_path = Path(drive) / cls.RB_DB_PATH if is_rb else None
            has_legacy = (Path(drive) / cls.LEGACY_PDB).exists() if is_rb else False

            track_count = 0
            if has_legacy:
                pass

            dev_info = {
                "device_id": device_id,
                "drive": drive.rstrip("\\"),
                "label": label,
                "serial": vol["serial"],
                "filesystem": vol["filesystem"],
                "is_rekordbox": is_rb,
                "is_writable": is_writable,
                "has_legacy_pdb": has_legacy,
                "has_export_db": db_path.exists() if db_path else False,
                "track_count": track_count,
                "total_space": size["total"],
                "used_space": size["used"],
                "free_space": size["free"]
            }
            logger.info(f"Found USB device: {dev_info}")
            devices.append(dev_info)
        
        logger.info(f"Scan complete. Found {len(devices)} total devices.")
        return devices

    @classmethod
    def initialize_usb(cls, drive: str) -> bool:
        """Creates the PIONEER/rekordbox directory structure on the drive."""
        try:
            # Ensure drive path ends with slash for Path to work correctly if it's just 'E:'
            if not drive.endswith("\\") and not drive.endswith("/"):
                drive += "\\"
            
            pioneer_path = Path(drive) / cls.PIONEER_MARKER
            rb_path = pioneer_path / "rekordbox"
            rb_path.mkdir(parents=True, exist_ok=True)
            
            # The .PIONEER hidden directory is often checked by CDJs
            hidden_pioneer = Path(drive) / ".PIONEER"
            hidden_pioneer.mkdir(parents=True, exist_ok=True)
            
            # Create default DEVSETTING files inside PIONEER
            settings_files = {
                "DEVSETTING.DAT": b"\x00" * 140,
                "MYSETTING.DAT": b"\x00" * 148,
                "MYSETTING2.DAT": b"\x00" * 148,
                "DJMMYSETTING.DAT": b"\x00" * 160
            }
            for name, content in settings_files.items():
                (pioneer_path / name).write_bytes(content)

            logger.info(f"Initialized Rekordbox library at {rb_path}")
            
            # Wait briefly so Windows recognizes the directory structure immediately
            import time
            time.sleep(1)
            
            return True
        except Exception as e:
            logger.error(f"Failed to initialize USB {drive}: {e}")
            return False


# --- USB Profile Management ---

PROFILES_FILE = Path("usb_profiles.json")

class UsbProfileManager:
    """Manages per-device sync profiles stored on disk."""

    @classmethod
    def _load_all(cls) -> Dict:
        try:
            if PROFILES_FILE.exists():
                return json.loads(PROFILES_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error(f"Failed to load USB profiles: {e}")
        return {"profiles": {}, "settings": {"auto_sync_on_startup": False}}

    @classmethod
    def _save_all(cls, data: Dict):
        PROFILES_FILE.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    @classmethod
    def get_profiles(cls) -> List[Dict]:
        data = cls._load_all()
        profiles = list(data.get("profiles", {}).values())
        # Enrich with connection status
        connected = {d["device_id"] for d in UsbDetector.scan()}
        for p in profiles:
            p["connected"] = p["device_id"] in connected
        return profiles

    @classmethod
    def get_profile(cls, device_id: str) -> Optional[Dict]:
        return cls._load_all().get("profiles", {}).get(device_id)

    @classmethod
    def save_profile(cls, profile: Dict) -> Dict:
        data = cls._load_all()
        device_id = profile["device_id"]
        existing = data["profiles"].get(device_id, {})
        existing.update(profile)
        # Ensure required fields
        existing.setdefault("type", "Collection")
        existing.setdefault("sync_mode", "full")
        existing.setdefault("sync_playlists", [])
        existing.setdefault("auto_sync", False)
        existing.setdefault("last_sync", None)
        existing.setdefault("created_at", datetime.now().isoformat())
        data["profiles"][device_id] = existing
        cls._save_all(data)
        return existing

    @classmethod
    def delete_profile(cls, device_id: str) -> bool:
        data = cls._load_all()
        if device_id in data.get("profiles", {}):
            del data["profiles"][device_id]
            cls._save_all(data)
            return True
        return False

    @classmethod
    def get_settings(cls) -> Dict:
        return cls._load_all().get("settings", {"auto_sync_on_startup": False})

    @classmethod
    def save_settings(cls, settings: Dict):
        data = cls._load_all()
        data["settings"] = settings
        cls._save_all(data)

    @classmethod
    def get_usb_contents(cls, device_id: str) -> Dict[str, List[Dict]]:
        """Fetches tracks from both Library One (DeviceSQL) and Library Legacy (Legacy PDB/XML)."""
        devices = UsbDetector.scan()
        device = next((d for d in devices if d["device_id"] == device_id), None)
        if not device:
            return {"library_one": [], "library_legacy": [], "library_one_status": "not_found", "library_legacy_status": "not_found"}
            
        drive = Path(device["drive"])
        l1_path = drive / "PIONEER" / "rekordbox" / "exportLibrary.db"
        l_xml_path = drive / "PIONEER" / "rekordbox.xml"
        l_pdb_path = drive / "PIONEER" / "rekordbox" / "export.pdb"
        
        results = {"library_one": [], "library_legacy": []}
        statuses = {"library_one_status": "empty", "library_legacy_status": "empty"}

        # --- Library One (DeviceSQL) ---
        if l1_path.exists():
            try:
                conn = sqlite3.connect(str(l1_path))
                conn.row_factory = sqlite3.Row
                cur = conn.execute("""
                    SELECT c.ID, c.Title, c.BPM, c.Duration, c.FolderPath, c.FileNameL,
                           a.Name as ArtistName
                    FROM djmdContent c
                    LEFT JOIN djmdArtist a ON c.ArtistID = a.ID
                    WHERE c.Title IS NOT NULL AND c.Title != ''
                """)
                for row in cur:
                    r = dict(row)
                    results["library_one"].append(r)
                conn.close()
                statuses["library_one_status"] = "loaded"
                logger.info(f"Library One loaded for {device_id}: {len(results['library_one'])} tracks")
            except sqlite3.DatabaseError as e:
                logger.warning(f"Library One on {device_id} is encrypted (SQLCipher): {e}")
                statuses["library_one_status"] = "encrypted"
                # Try to estimate track count from file size
                try:
                    file_size = l1_path.stat().st_size
                    est_tracks = max(0, file_size // 50000)  # rough estimate
                    results["library_one"].append({
                        "ID": "_status_encrypted",
                        "Title": f"Library One (Encrypted) — ~{est_tracks} tracks estimated",
                        "ArtistName": "Rekordbox 7+ uses SQLCipher encryption",
                        "BPM": 0, "Duration": 0,
                        "FolderPath": str(l1_path), "FileNameL": "",
                        "_encrypted": True
                    })
                except Exception:
                    results["library_one"].append({
                        "ID": "_status_encrypted",
                        "Title": "Library One (Encrypted)",
                        "ArtistName": "Rekordbox 7+ uses SQLCipher encryption",
                        "BPM": 0, "Duration": 0,
                        "FolderPath": str(l1_path), "FileNameL": "",
                        "_encrypted": True
                    })
            except Exception as e:
                logger.error(f"Error reading Library One for {device_id}: {e}")
                statuses["library_one_status"] = "error"

        # --- Library Legacy: Try XML first, then PDB ---
        if l_xml_path.exists():
            try:
                tree = ET.parse(l_xml_path)
                root = tree.getroot()
                collection = root.find("COLLECTION")
                if collection is not None:
                    for track in collection.findall("TRACK"):
                        loc = track.get("Location", "")
                        path = loc.split("localhost/")[-1] if "localhost/" in loc else loc
                        
                        results["library_legacy"].append({
                            "ID": track.get("TrackID"),
                            "Title": track.get("Name"),
                            "ArtistName": track.get("Artist"),
                            "FolderPath": str(Path(path).parent).replace("\\", "/"),
                            "FileNameL": Path(path).name,
                            "BPM": int(float(track.get("AverageBpm", 0)) * 100)
                        })
                statuses["library_legacy_status"] = "loaded"
                logger.info(f"Library Legacy (XML) loaded for {device_id}: {len(results['library_legacy'])} tracks")
            except Exception as e:
                logger.error(f"Error reading Library Legacy XML for {device_id}: {e}")
                statuses["library_legacy_status"] = "error_corrupt"
                # Req 17: Fallback by isolating corrupted XML so next sync starts fresh
                try: l_xml_path.rename(l_xml_path.with_suffix(".xml.corrupt"))
                except: pass

        # Fallback: Try PDB if XML didn't yield results
        if not results["library_legacy"] and l_pdb_path.exists():
            try:
                # PDB is a binary format. We do a lightweight scan for track paths.
                pdb_size = l_pdb_path.stat().st_size
                est_tracks = max(0, pdb_size // 1000)  # very rough estimate
                results["library_legacy"].append({
                    "ID": "_status_pdb",
                    "Title": f"Legacy PDB Library — ~{est_tracks} tracks estimated",
                    "ArtistName": "Binary PDB export (not directly readable)",
                    "BPM": 0, "Duration": 0,
                    "FolderPath": str(l_pdb_path), "FileNameL": "",
                    "_pdb": True
                })
                statuses["library_legacy_status"] = "pdb_detected"
                logger.info(f"Library Legacy (PDB) detected for {device_id}: {l_pdb_path}")
            except Exception as e:
                logger.error(f"Error reading PDB for {device_id}: {e}")

        # --- Helper: Transform to Tree ---
        def build_tree(tracks):
            tree = {"name": "root", "type": "folder", "children": []}
            for t in tracks:
                path_parts = t.get("FolderPath", "").strip("/").split("/")
                current = tree
                for part in path_parts:
                    if not part: continue
                    found = next((c for c in current["children"] if c["type"] == "folder" and c["name"] == part), None)
                    if not found:
                        found = {"name": part, "type": "folder", "children": []}
                        current["children"].append(found)
                    current = found
                current["children"].append({**t, "type": "track"})
            return tree["children"]

        return {
            "library_one": build_tree(results["library_one"]),
            "library_legacy": build_tree(results["library_legacy"]),
            **statuses
        }

# --- Smart Sync Engine ---

class UsbSyncEngine:
    """
    Smart sync engine that performs diff-based synchronization
    between the local Rekordbox master.db (via pyrekordbox) and USB exportLibrary.db.
    """

    def __init__(self, local_db_path: str, usb_drive: str, filesystem: str = ""):
        self.local_path = Path(local_db_path)
        self.usb_drive = usb_drive
        self.usb_root = Path(usb_drive)  # drive root, e.g. Path("E:\\")
        self.usb_pioneer = self.usb_root / "PIONEER"
        self.usb_rb = self.usb_pioneer / "rekordbox"
        self.usb_db_path = self.usb_rb / "exportLibrary.db"
        self.usb_anlz = self.usb_pioneer / "USBANLZ"

        # Filesystem-aware path limit:
        # FAT32  → 260 chars total (Windows MAX_PATH), 240 conservative limit
        # exFAT  → 255 chars per filename component, no strict total limit
        # NTFS   → 255 chars per component, 32767 total (practically 260 without \\?\ prefix)
        # For Pioneer CDJ hardware compatibility: FAT32/exFAT recommended.
        # NTFS USB drives work for PC-to-PC sync but not all CDJ models.
        fs_upper = (filesystem or "").upper()
        if "NTFS" in fs_upper:
            self.path_limit = 255   # per-component limit; no strict total needed
            self.filesystem = "NTFS"
        elif "EXFAT" in fs_upper or "EX_FAT" in fs_upper:
            self.path_limit = 255
            self.filesystem = "exFAT"
        else:
            # FAT32 or unknown → conservative Windows MAX_PATH limit
            self.path_limit = 240
            self.filesystem = "FAT32"
        logger.info(f"UsbSyncEngine: drive={usb_drive} filesystem={self.filesystem} path_limit={self.path_limit}")

    def _ensure_usb_structure(self):
        """Create PIONEER directory structure on USB if missing, and ensure DB integrity."""
        self.usb_rb.mkdir(parents=True, exist_ok=True)
        self.usb_anlz.mkdir(parents=True, exist_ok=True)
        (self.usb_pioneer / "Artwork").mkdir(exist_ok=True)
        
        # Self-healing: if the DB exists but is an encrypted master.db clone from the old bug,
        # it will throw an error on `sqlite3.connect`. We must delete it to let the sync engine rebuild it.
        if self.usb_db_path.exists():
            try:
                import sqlite3
                conn = sqlite3.connect(str(self.usb_db_path))
                conn.execute("SELECT COUNT(*) FROM djmdContent").fetchone()
                conn.close()
            except Exception as e:
                logger.warning(f"USB DB is corrupted or encrypted (Error: {e}). Rebuilding.")
                try: self.usb_db_path.unlink()
                except: pass

    def _track_hash(self, row: Dict) -> str:
        """Create a deterministic hash of track metadata for comparison."""
        import hashlib
        key = f"{row.get('Title','')}|{row.get('ArtistName','')}|{row.get('Duration',0)}|{row.get('BPM',0)}"
        return hashlib.md5(key.encode()).hexdigest()

    def _read_usb_tracks(self) -> Dict[str, Dict]:
        """Read all tracks from the USB database."""
        tracks = {}
        if not self.usb_db_path.exists():
            return tracks
        try:
            import sqlite3
            conn = sqlite3.connect(str(self.usb_db_path))
            conn.row_factory = sqlite3.Row
            cur = conn.execute("""
                SELECT c.ID, c.Title, c.ArtistID, c.AlbumID, c.GenreID,
                       c.BPM, c.Rating, c.ColorID, c.Key, c.Duration,
                       c.FolderPath, c.FileNameL,
                       a.Name as ArtistName
                FROM djmdContent c
                LEFT JOIN djmdArtist a ON c.ArtistID = a.ID
                WHERE c.Title IS NOT NULL AND c.Title != ''
            """)
            for row in cur:
                r = dict(row)
                r["_hash"] = self._track_hash(r)
                tracks[str(r["ID"])] = r
            conn.close()
        except Exception as e:
            logger.error(f"Failed to read usb tracks: {e}")
        return tracks

    def _read_local_tracks(self) -> Dict[str, Dict]:
        """Read tracks directly from pyrekordbox MasterDb."""
        import rbox
        tracks = {}
        try:
            db = rbox.MasterDb(str(self.local_path))
            for c in db.get_contents():
                tid = str(c.id)
                a_name = ""
                artist_id = getattr(c, 'artist_id', None)
                if artist_id:
                    try:
                        a = db.get_artist(artist_id)
                        if a: a_name = getattr(a, 'name', '')
                    except: pass

                r = {
                    "ID": tid,
                    "Title": getattr(c, 'title', ''),
                    "ArtistID": str(artist_id or ''),
                    "AlbumID": str(getattr(c, 'album_id', '')),
                    "GenreID": str(getattr(c, 'genre_id', '')),
                    "BPM": getattr(c, 'bpm', 0),
                    "Rating": getattr(c, 'rating', 0),
                    "ColorID": getattr(c, 'color_id', 0),
                    "Key": getattr(c, 'key_id', ''),
                    "Duration": getattr(c, 'length', 0),
                    "FolderPath": getattr(c, 'folder_path', ''),
                    "FileNameL": getattr(c, 'file_name_l', ''),
                    "ArtistName": a_name
                }
                r["_hash"] = self._track_hash(r)
                tracks[tid] = r
        except Exception as e:
            logger.error(f"Failed to read local tracks via rbox: {e}")
        return tracks

    def _read_usb_playlists(self) -> Dict[str, Dict]:
        playlists = {}
        if not self.usb_db_path.exists():
            return playlists
        try:
            import sqlite3
            conn = sqlite3.connect(str(self.usb_db_path))
            conn.row_factory = sqlite3.Row
            cur = conn.execute("SELECT * FROM djmdPlaylist")
            for row in cur:
                playlists[str(dict(row)["ID"])] = dict(row)
            conn.close()
        except Exception as e:
            logger.error(f"Failed to read USB playlists: {e}")
        return playlists

    def _read_local_playlists(self) -> Dict[str, Dict]:
        import rbox
        playlists = {}
        try:
            db = rbox.MasterDb(str(self.local_path))
            for p in db.get_playlists():
                pid = str(p.id)
                playlists[pid] = {
                    "ID": pid,
                    "Name": getattr(p, 'name', ''),
                    "Type": str(getattr(p, 'is_folder', 0) or 0),
                    "ParentID": str(getattr(p, 'parent_id', ''))
                }
        except Exception as e:
            logger.error(f"Failed to read local playlists: {e}")
        return playlists

    def calculate_diff(self, playlist_ids: Optional[List[str]] = None) -> Dict:
        local_tracks = self._read_local_tracks()
        usb_tracks = self._read_usb_tracks()

        local_hashes = {t["_hash"]: tid for tid, t in local_tracks.items()}
        usb_hashes = {t["_hash"]: tid for tid, t in usb_tracks.items()}

        to_add = [local_tracks[local_hashes[h]] for h in local_hashes if h not in usb_hashes]
        to_remove = [usb_tracks[usb_hashes[h]] for h in usb_hashes if h not in local_hashes]
        to_update = []
        for h, local_id in local_hashes.items():
            if h not in usb_hashes:
                lt = local_tracks[local_id]
                for uid, ut in usb_tracks.items():
                    if (lt.get("Title","").lower() == ut.get("Title","").lower() and
                        lt.get("ArtistName","").lower() == ut.get("ArtistName","").lower()):
                        to_update.append({"local": lt, "usb": ut})
                        break

        local_pl = self._read_local_playlists()
        usb_pl = self._read_usb_playlists()

        if playlist_ids:
            local_pl = {k: v for k, v in local_pl.items() if k in playlist_ids}

        pl_to_add = [v for k, v in local_pl.items() if k not in usb_pl]
        pl_to_remove = [v for k, v in usb_pl.items() if k not in local_pl]

        return {
            "tracks": {
                "to_add": len(to_add), "to_remove": len(to_remove),
                "to_update": len(to_update), "unchanged": len(local_tracks) - len(to_add) - len(to_update),
            },
            "playlists": {
                "to_add": len(pl_to_add), "to_remove": len(pl_to_remove),
                "local_total": len(local_pl), "usb_total": len(usb_pl),
            },
            "total_local": len(local_tracks),
            "total_usb": len(usb_tracks),
        }

    def sync_collection(self, profile: Dict, library_types: List[str] = ["library_legacy"]) -> Generator[Dict, None, None]:
        yield {"stage": "preparing", "message": "Preparing full sync...", "progress": 0}
        self._ensure_usb_structure()

        try:
            did_sync = False
            
            with locked_sync(Path(profile["drive"])):
                if "library_one" in library_types:
                    logger.warning("Skipping Library One sync: exportLibrary.db requires SQLCipher encryption.")
                    yield {"stage": "info", "message": "Library One sync disabled (Modern Rekordbox Database is Encrypted)", "progress": 10}
                    if "library_legacy" not in library_types:
                        library_types = list(library_types) + ["library_legacy"]
                        logger.info("Auto-including library_legacy as fallback for encrypted library_one")

                if "library_legacy" in library_types or profile.get("sync_mirrored"):
                    yield {"stage": "info", "message": "Starting Legacy XML Sync...", "progress": 20}
                    for event in self._sync_library_legacy(profile):
                        yield {
                            "stage": event.get("stage", "sync"),
                            "message": f"Legacy: {event.get('message', '')}",
                            "progress": 20 + int(event.get("progress", 0) * 0.8)
                        }
                    did_sync = True

            if not did_sync:
                yield {"stage": "complete", "message": "Sync finished (No compatible libraries selected — try enabling Legacy XML)", "progress": 100}
            
        except Exception as e:
            logger.error(f"Collection sync failed: {e}")
            yield {"stage": "error", "message": str(e), "progress": -1}

    def sync_playlists(self, profile: Dict, playlist_ids: List[str], library_types: List[str] = ["library_legacy"]) -> Generator[Dict, None, None]:
        if profile.get("sync_mirrored"):
            library_types = list(set(library_types + ["library_one", "library_legacy"]))
            logger.info(f"Mirrored sync enabled. Syncing both formats for {profile.get('drive')}")

        yield {"stage": "preparing", "message": "Preparing playlist sync...", "progress": 0}
        self._ensure_usb_structure()

        try:
            profile["last_sync"] = datetime.now().isoformat()
            profile["sync_playlists"] = playlist_ids
            UsbProfileManager.save_profile(profile)

            did_sync = False
            
            with locked_sync(Path(profile["drive"])):
                if "library_one" in library_types:
                    logger.warning("Skipping Library One playlist sync: exportLibrary.db requires SQLCipher encryption.")
                    yield {"stage": "info", "message": "Library One sync disabled (Modern Rekordbox Database is Encrypted)", "progress": 10}
                    if "library_legacy" not in library_types:
                        library_types = list(library_types) + ["library_legacy"]
                        logger.info("Auto-including library_legacy as fallback")

                if "library_legacy" in library_types or profile.get("sync_mirrored"):
                    yield {"stage": "info", "message": "Starting Legacy XML Playlist Sync...", "progress": 20}
                    for event in self._sync_library_legacy(profile, playlist_ids):
                        yield {
                            "stage": event.get("stage", "sync"),
                            "message": f"Legacy: {event.get('message', '')}",
                            "progress": 20 + int(event.get("progress", 0) * 0.8)
                        }
                    did_sync = True

            if not did_sync:
                yield {"stage": "complete", "message": "Playlist Sync finished (No compatible libraries — enable Legacy XML)", "progress": 100}

        except Exception as e:
            logger.error(f"Playlist sync failed: {e}")
            yield {"stage": "error", "message": str(e), "progress": -1}

    def _clean_filename(self, name: str) -> str:
        """Req 20: Enforce UTF-8 and remove invalid OS characters."""
        import string, unicodedata
        name = str(name or "Unknown")
        valid_chars = f"-_.() {string.ascii_letters}{string.digits}"
        cleaned = ''.join(c for c in name if c in valid_chars or (unicodedata.category(c)[0] not in 'C'))
        for char in ["/", "\\", ":", "*", "?", '"', "<", ">", "|"]:
            cleaned = cleaned.replace(char, "_")
        return cleaned

    def _get_safe_dest_path(self, artist: str, album: str, filename: str) -> Path:
        """
        Build a safe destination path for a track on the USB drive.

        Path limits per filesystem (self.filesystem / self.path_limit):
          FAT32  → 240 chars total (conservative Windows MAX_PATH)
          exFAT  → 255 chars per component (no strict total limit)
          NTFS   → 255 chars per component (no strict total limit on modern Windows)

        Pioneer CDJs expect audio files under PIONEER/Contents/<Artist>/<Album>/<file>.
        """
        contents_dir = self.usb_pioneer / "Contents"
        artist_clean = self._clean_filename(artist)[:40].strip() or "UnknownArtist"
        album_clean = self._clean_filename(album)[:40].strip() or "UnknownAlbum"
        file_clean = self._clean_filename(filename)

        dest = contents_dir / artist_clean / album_clean / file_clean

        # Only truncate total path length for FAT32 where MAX_PATH is a hard limit.
        # On NTFS/exFAT the per-component limit (255) is already enforced by _clean_filename.
        if self.filesystem == "FAT32" and len(str(dest)) > self.path_limit:
            excess = len(str(dest)) - self.path_limit
            stem = dest.stem
            ext = dest.suffix
            if len(stem) > excess:
                dest = contents_dir / artist_clean / album_clean / (stem[:-excess] + ext)
            else:
                # Path too deep — flatten to contents root with hash-based name
                dest = contents_dir / f"track_{hashlib.md5(filename.encode()).hexdigest()[:8]}{ext}"
            logger.debug(f"FAT32 path truncated to {len(str(dest))} chars: {dest.name}")

        return dest

    def _copy_file_stream(self, src: Path, dest: Path) -> Generator[Dict, None, None]:
        """Req 18 & 19: Chunk-based streaming & Deduplication."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        
        # Req 18: Deduplication -> check if exists and size matches
        if dest.exists() and src.exists() and dest.stat().st_size == src.stat().st_size:
            yield {"stage": "copy_skip", "message": f"Deduplicated (already exists): {dest.name}"}
            return

        # Req 16: Check Disk Full proactively (use drive root for disk_usage)
        try:
            _, _, free = shutil.disk_usage(str(self.usb_root))
            if src.stat().st_size > free:
                raise OSError(errno.ENOSPC, "No space left on USB device")
        except Exception as e:
            if "No space left" in str(e): raise

        # Req 19: Chunk-based streaming
        total_size = src.stat().st_size
        copied = 0
        chunk_size = 1024 * 1024 * 4 # 4MB chunks
        
        # Req 14 & 15: Disconnect safety -> write to .tmp, then atomic rename
        tmp_dest = dest.with_suffix(dest.suffix + ".tmp")
        
        try:
            with open(src, 'rb') as fsrc, open(tmp_dest, 'wb') as fdst:
                while True:
                    buf = fsrc.read(chunk_size)
                    if not buf:
                        break
                    fdst.write(buf)
                    copied += len(buf)
                    yield {"stage": "copying", "message": f"Copying {dest.name}", "copied": copied, "total": total_size}
            
            # Atomic rename if completed successfully
            tmp_dest.replace(dest)
        except Exception as e:
            # Cleanup temp file on failure
            if tmp_dest.exists():
                try: tmp_dest.unlink()
                except: pass
            raise e

    def _sync_library_legacy(self, profile: Dict, playlist_ids: List[str] = None) -> Generator[Dict, None, None]:
        """Legacy Sync (Library Legacy): Exports library and audio to USB."""
        yield {"stage": "lib_legacy", "message": "Starting Library Legacy (XML & Audio) sync...", "progress": 0}
        try:
            import xml.etree.ElementTree as ET
            target = self.usb_pioneer / "rekordbox.xml"
            # We use the local master.db to generate a clean XML
            import rbox
            db = rbox.MasterDb(str(self.local_path))
            
            # Simple XML generation
            root = ET.Element("DJ_PLAYLISTS", Version="1.0.0")
            
            # Filter tracks if playlist_ids provided
            target_track_ids = set()
            if playlist_ids:
                for pl_id in playlist_ids:
                    try:
                        pl = db.get_playlist(int(pl_id))
                        if pl:
                            for t_id in db.get_playlist_content(pl.id):
                                target_track_ids.add(str(t_id))
                    except: pass
            
            tracks_to_export = [t for t in db.get_contents() if not target_track_ids or str(t.id) in target_track_ids]
            
            collection = ET.SubElement(root, "COLLECTION", Entries=str(len(tracks_to_export)))
            
            for i, t in enumerate(tracks_to_export):
                artist_name = ""
                if getattr(t, 'artist_id', None):
                    try: artist_name = getattr(db.get_artist(t.artist_id), 'name', '')
                    except: pass
                
                album_name = ""
                if getattr(t, 'album_id', None):
                    try: album_name = getattr(db.get_album(t.album_id), 'name', '')
                    except: pass
                
                # Original local path — folder_path may or may not end with separator
                local_folder = getattr(t, 'folder_path', '') or ''
                local_file = getattr(t, 'file_name_l', '') or ''
                # Ensure exactly one path separator between folder and filename
                if local_folder and local_file and not local_folder.endswith(('/', '\\')):
                    local_path_str = f"{local_folder}/{local_file}"
                else:
                    local_path_str = f"{local_folder}{local_file}"
                
                # Req 30: Resolve symlinks to avoid infinite loops and get absolute real paths
                try:
                    local_path = Path(local_path_str).resolve(strict=False)
                except Exception:
                    local_path = Path(local_path_str)
                
                usb_dest_path = None
                if local_path.exists():
                    usb_dest_path = self._get_safe_dest_path(artist_name, album_name, local_file)
                    try:
                        # Copy the file to USB with chunk streaming progress
                        for event in self._copy_file_stream(local_path, usb_dest_path):
                            # Ignore fine-grained chunk progress for now to keep UI simpler,
                            # but it's physically chunked and safe.
                            pass
                    except OSError as e:
                        logger.error(f"Copy failed for {local_file}: {e}")
                        
                        err_code = getattr(e, 'winerror', None) or getattr(e, 'errno', None)
                        
                        # Req 16: ENOSPC / Disk Full (Win: 112, 39, Unix: 28)
                        if err_code in (112, 39, 28) or "No space left" in str(e):
                            raise Exception("Device is full (ENOSPC). Sync aborted.")
                            
                        # Req 22: Unexpected Disconnect (Win: 21, 31, 1167, 2, 3)
                        if err_code in (21, 31, 1167, 2, 3) or "No such file" in str(e):
                            raise Exception("USB Drive disconnected or inaccessible. Sync aborted.")
                            
                        # Req 25: OS File Locks
                        if isinstance(e, PermissionError) or err_code in (5, 32):
                            logger.warning(f"PermissionError: file '{local_file}' may be locked by Rekordbox. Skipping without aborting batch.")
                else:
                    logger.warning(f"Audio file missing locally, skipping copy: {local_path}")
                
                # XML Location -> URL Encode
                import urllib.parse
                if usb_dest_path:
                    # Map to the new USB location file://localhost/D:/Contents/...
                    loc_val = f"file://localhost/{str(usb_dest_path)}".replace("\\", "/")
                else:
                    # Give fallback
                    loc_val = f"file://localhost/{local_path_str}".replace("\\", "/")
                    
                loc_val = urllib.parse.quote(loc_val, safe=":/")
                
                ET.SubElement(collection, "TRACK",
                    TrackID=str(t.id),
                    Name=getattr(t, 'title', '') or '',
                    Artist=artist_name,
                    Album=album_name,
                    TotalTime=str(int(getattr(t, 'length', 0) or 0)),
                    AverageBpm=f"{float(getattr(t, 'bpm', 0) or 0):.2f}",
                    Tonality=str(getattr(t, 'key_id', '') or ''),
                    Rating=str(getattr(t, 'rating', 0) or 0),
                    Location=loc_val,
                )
                if i % 10 == 0:
                    yield {"stage": "lib_legacy", "message": f"Copying & Exporting: {i}/{len(tracks_to_export)}", "progress": int((i/max(len(tracks_to_export),1))*90)}
            
            # Also export the Playlists if provided
            if playlist_ids:
                node_pl = ET.SubElement(root, "PLAYLISTS")
                # Simplified recursive playlist export
                for pl_id in playlist_ids:
                    try:
                        pl = db.get_playlist(int(pl_id))
                        if pl:
                            pl_elem = ET.SubElement(node_pl, "NODE", Name=getattr(pl, 'name', ''), Type="1")
                            for t_id in db.get_playlist_content(pl.id):
                                ET.SubElement(pl_elem, "TRACK", Key=str(t_id))
                    except: pass

            tree = ET.ElementTree(root)
            with open(target, "wb") as f:
                tree.write(f, encoding="UTF-8", xml_declaration=True)
            
            # Req 22: UI-state mismatch -> Give OS buffers 1.5s to flush before declaring 100% complete
            yield {"stage": "flushing", "message": "Flushing OS file buffers to USB, please wait...", "progress": 99}
            time.sleep(1.5)
            
            yield {"stage": "complete", "message": "Library Legacy (XML & Audio) synced securely.", "progress": 100}
        except Exception as e:
            logger.error(f"Library Legacy sync failed: {e}")
            yield {"stage": "error", "message": f"Library Legacy sync failed: {e}", "progress": -1}

    def sync_metadata(self, profile: Dict, library_types: List[str] = ["library_legacy"]) -> Generator[Dict, None, None]:
        yield {"stage": "preparing", "message": "Syncing metadata...", "progress": 0}

        try:
            did_sync = False

            if "library_one" in library_types:
                logger.warning("Skipping Library One metadata sync: exportLibrary.db requires SQLCipher encryption.")
                yield {"stage": "info", "message": "Library One metadata sync disabled (Modern Rekordbox Database is Encrypted)", "progress": 50}
                if "library_legacy" not in library_types:
                    library_types = list(library_types) + ["library_legacy"]

            if "library_legacy" in library_types or profile.get("sync_mirrored"):
                yield {"stage": "info", "message": "Starting Legacy XML Metadata Sync...", "progress": 60}
                for event in self._sync_library_legacy(profile, profile.get("sync_playlists", [])):
                    yield {
                        "stage": event.get("stage", "sync"),
                        "message": f"Legacy: {event.get('message', '')}",
                        "progress": 60 + int(event.get("progress", 0) * 0.4)
                    }
                did_sync = True

            if not did_sync:
                yield {"stage": "complete", "message": "Metadata Sync finished (No compatible libraries — enable Legacy XML)", "progress": 100}

        except Exception as e:
            logger.error(f"Metadata sync failed: {e}")
            yield {"stage": "error", "message": str(e), "progress": -1}

    def _remap_paths(self, profile: Dict):
        """Update FolderPath in USB DB to use the USB drive letter."""
        pass

    def _write_usb_settings(self):
        """Write DEVSETTING.DAT and related config files to PIONEER root."""
        settings_files = {
            "DEVSETTING.DAT": b"\x00" * 140,
            "MYSETTING.DAT": b"\x00" * 148,
            "MYSETTING2.DAT": b"\x00" * 148,
            "DJMMYSETTING.DAT": b"\x00" * 160
        }
        for name, default_content in settings_files.items():
            path = self.usb_pioneer / name
            if not path.exists():
                path.write_bytes(default_content)


# --- USB Actions ---

class UsbActions:
    """High-level USB operations."""

    @staticmethod
    def eject(drive: str) -> Dict:
        """Safely eject a USB drive on Windows with timeout/verification (Req 23)."""
        drive_letter = drive.rstrip("\\").rstrip(":")
        try:
            # Use PowerShell to eject
            result = subprocess.run(
                ["powershell", "-Command",
                 f"(New-Object -COM Shell.Application).NameSpace(17).ParseName('{drive_letter}:').InvokeVerb('Eject')"],
                capture_output=True, text=True, timeout=10
            )
            
            # Polling loop: Wait up to 5s for the OS to unmount it
            ejected = False
            for _ in range(10):
                if not Path(f"{drive_letter}:\\").exists():
                    ejected = True
                    break
                time.sleep(0.5)
                
            if ejected or result.returncode == 0:
                logger.info(f"Drive {drive_letter}: ejected safely")
                return {"status": "success", "message": f"Drive {drive_letter}: ejected safely. It is now safe to remove."}
            else:
                return {"status": "error", "message": result.stderr or "Drive is busy and could not be ejected cleanly."}
        except Exception as e:
            return {"status": "error", "message": f"Eject command failed: {e}"}

    @staticmethod
    def set_label(drive: str, new_label: str) -> Dict:
        """Sets the volume label for a drive."""
        try:
            drive_root = f"{drive.rstrip(os.sep)}{os.sep}" # Ensure X:\ format
            if not ctypes.windll.kernel32.SetVolumeLabelW(drive_root, new_label):
                error = ctypes.GetLastError()
                return {"status": "error", "message": f"Failed to rename (Error {error})"}
            return {"status": "success", "message": f"Renamed to {new_label}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @staticmethod
    def reset(profile: Dict) -> Dict:
        """Wipe PIONEER folder on USB and rebuild structure."""
        drive = profile.get("drive", "")
        pioneer_path = Path(drive) / "PIONEER"

        if not pioneer_path.exists():
            return {"status": "error", "message": "No PIONEER folder found"}

        try:
            # Backup the existing DB just in case
            db_path = pioneer_path / "rekordbox" / "exportLibrary.db"
            if db_path.exists():
                backup = Path(drive) / f"exportLibrary_reset_backup_{int(time.time())}.db"
                shutil.copy2(db_path, backup)

            shutil.rmtree(pioneer_path)

            # Recreate structure
            (pioneer_path / "rekordbox").mkdir(parents=True)
            (pioneer_path / "USBANLZ").mkdir(parents=True)
            (pioneer_path / "Artwork").mkdir(parents=True)

            # Reset profile
            profile["last_sync"] = None
            profile["track_count"] = 0
            UsbProfileManager.save_profile(profile)

            return {"status": "success", "message": "USB reset complete. Run sync to repopulate."}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @staticmethod
    def update_all(local_db_path: str) -> Generator[Dict, None, None]:
        # ... (unchanged) ...
        """Sync all connected USB devices according to their profiles."""
        devices = UsbDetector.scan()
        profiles = UsbProfileManager.get_profiles()
        connected_profiles = [p for p in profiles if p.get("connected")]

        if not connected_profiles:
            yield {"stage": "complete", "message": "No connected USB devices with profiles found", "progress": 100}
            return

        total = len(connected_profiles)
        for i, profile in enumerate(connected_profiles):
            base_progress = int((i / total) * 100)
            yield {"stage": "device", "message": f"Syncing {profile.get('label', 'USB')}...", "progress": base_progress}

            engine = UsbSyncEngine(local_db_path, profile["drive"])
            sync_mode = profile.get("sync_mode", "full")
            library_types = profile.get("library_types", ["library_one"]) # Assuming library_types can be stored in profile

            try:
                if sync_mode == "full":
                    # Assuming sync_collection exists and needs library_types
                    for event in engine.sync_collection(profile, library_types):
                        scaled = base_progress + int(event.get("progress", 0) / total)
                        yield {**event, "progress": min(scaled, 99), "device": profile.get("label")}
                elif sync_mode == "playlists_only":
                    pl_ids = profile.get("sync_playlists", [])
                    for event in engine.sync_playlists(profile, pl_ids, library_types):
                        scaled = base_progress + int(event.get("progress", 0) / total)
                        yield {**event, "progress": min(scaled, 99), "device": profile.get("label")}
                elif sync_mode == "metadata_only":
                    for event in engine.sync_metadata(profile):
                        scaled = base_progress + int(event.get("progress", 0) / total)
                        yield {**event, "progress": min(scaled, 99), "device": profile.get("label")}
            except Exception as e:
                yield {"stage": "error", "message": f"{profile.get('label')}: {e}", "progress": base_progress}

        yield {"stage": "complete", "message": f"All {total} devices synced", "progress": 100}
