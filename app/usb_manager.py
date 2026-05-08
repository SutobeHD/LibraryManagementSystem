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

# Playlist names that should NEVER be propagated to a USB stick.
# Lowercased + matched case-insensitively. The "Import" playlist is auto-
# created by ImportManager for every locally imported file — it's a working-
# memory bucket and would just clutter the CDJ playlist menu.
EXCLUDED_USB_PLAYLISTS: frozenset = frozenset({"import"})


def _is_excluded_playlist(name: str) -> bool:
    return (name or "").strip().lower() in EXCLUDED_USB_PLAYLISTS


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

    # 32-byte device-identification blob accepted by CDJ-2000NXS2 / CDJ-3000.
    # Some firmware revisions check for this file before mounting the stick as
    # a Rekordbox device. Format is "PIONEER DEVICE" + null padding to 32 bytes.
    DEVICE_PIONEER_MAGIC = b"PIONEER DEVICE"
    DEVICE_PIONEER_SIZE = 32

    @classmethod
    def _write_device_pioneer(cls, pioneer_path: Path) -> None:
        """Create /PIONEER/DEVICE.PIONEER if missing. Never overwrites."""
        target = pioneer_path / "DEVICE.PIONEER"
        if target.exists():
            return
        try:
            blob = cls.DEVICE_PIONEER_MAGIC + b"\x00" * (
                cls.DEVICE_PIONEER_SIZE - len(cls.DEVICE_PIONEER_MAGIC)
            )
            target.write_bytes(blob)
            logger.info(f"Wrote DEVICE.PIONEER marker at {target}")
        except Exception as e:
            logger.warning(f"Failed to write DEVICE.PIONEER at {target}: {e}")

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

    @staticmethod
    def _get_bus_types() -> Dict[str, str]:
        """Fetch Windows bus types (USB, NVMe, SATA) for each drive letter."""
        import subprocess, json
        try:
            CREATE_NO_WINDOW = 0x08000000
            ps_cmd = 'Get-Disk | Select-Object Number, BusType | ConvertTo-Json -Compress'
            output = subprocess.check_output(['powershell', '-NoProfile', '-Command', ps_cmd], text=True, creationflags=CREATE_NO_WINDOW)
            disks = json.loads(output)
            if isinstance(disks, dict): disks = [disks]
            
            ps_part = 'Get-Partition | Select-Object DiskNumber, DriveLetter | ConvertTo-Json -Compress'
            out_part = subprocess.check_output(['powershell', '-NoProfile', '-Command', ps_part], text=True, creationflags=CREATE_NO_WINDOW)
            parts = json.loads(out_part)
            if isinstance(parts, dict): parts = [parts]
            
            bus_map = {}
            disk_bus = {d['Number']: d['BusType'] for d in disks}
            for p in parts:
                dl = p.get('DriveLetter')
                if dl and str(dl).strip():
                    letter = f"{dl}:\\"
                    bus_map[letter] = disk_bus.get(p['DiskNumber'])
            return bus_map
        except Exception as e:
            logger.error(f"Failed to get bus types: {e}")
            return {}

    @classmethod
    def scan(cls) -> List[Dict]:
        """Scan all removable drives and return Rekordbox USB info."""
        devices = []
        bus_types = cls._get_bus_types()
        
        for drive in cls._get_removable_drives():
            drive_type = ctypes.windll.kernel32.GetDriveTypeW(drive)
            is_rb = cls.is_rekordbox_usb(drive)
            bus_type = bus_types.get(drive, "Unknown")

            # Strict filtering: if it's a fixed drive (type 3), it MUST be on a USB bus.
            # This prevents internal NVMe/SATA hard drives from being recognized as USB sticks,
            # even if they happen to contain a PIONEER directory.
            is_usb_bus = bus_type == "USB"
            
            if drive_type == 3 and not is_usb_bus:
                logger.debug(f"Skipping fixed internal drive {drive} (BusType: {bus_type})")
                continue

            # Fixed drives (type 3) that ARE USB: only include if they actually have Rekordbox data.
            if drive_type == 3 and not is_rb:
                logger.debug(f"Skipping fixed USB drive without Rekordbox structure: {drive}")
                continue
                
            logger.info(f"Scanning drive {drive}: type={drive_type}, bus={bus_type}, is_rb={is_rb}")

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

            # CDJ device-identification marker (some firmware needs this to mount
            # the stick as a Rekordbox device).
            cls._write_device_pioneer(pioneer_path)

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
        # Auto-prune obvious dupes on every read so the UI never shows
        # the long zombie list users get after several stick reformats.
        try:
            removed = cls.prune_duplicates()
            if removed:
                logger.info("[Profiles] auto-pruned %d duplicate(s)", removed)
        except Exception as exc:
            logger.warning("[Profiles] prune skipped: %s", exc)

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
    def prune_duplicates(cls) -> int:
        """Collapse duplicate profiles + migrate to current device IDs.

        Windows assigns a NEW volume serial every time a stick is
        reformatted, and our `device_id = md5(serial or drive)[:12]`
        therefore generates a fresh id per format. Two failure modes:

        1. After a reformat the OLD profile (with its sync_playlists,
           last_sync, etc.) gets orphaned — it's not in the scan and the
           connected device has no profile yet. UI renders the old
           profile as "offline" and the connected stick as "no profile".

        2. Repeated reformats grow the profile list unbounded — each old
           serial leaves a zombie entry.

        Two-step policy:
          A. **Migrate** — for each currently-connected device whose
             device_id has no profile, find an existing profile with the
             same (drive, label) and re-key it to the connected id.
             That preserves sync_playlists / last_sync across reformats.
          B. **Prune** — for each (drive, label) group, keep the
             currently-connected profile (post-migrate that's the
             freshly re-keyed one) or fall back to the newest by
             last_sync. Delete the rest, inheriting playlists from the
             newest deleted sibling if the keeper had none.

        Returns the number of profiles deleted.
        """
        data = cls._load_all()
        profiles = data.get("profiles", {})

        # Snapshot the live device list once
        try:
            scan_results = UsbDetector.scan()
        except Exception as e:
            logger.warning("[Profiles] scan failed during prune: %s", e)
            scan_results = []
        scanned_by_id = {d["device_id"]: d for d in scan_results}
        connected_ids = set(scanned_by_id.keys())

        # ── Step A: migrate each connected device with no matching profile
        # ── into the existing same-(drive,label) profile ───────────────
        migrated = 0
        for new_id, dev in list(scanned_by_id.items()):
            if new_id in profiles:
                continue   # device already has a profile — skip
            new_drive = dev.get("drive", "")
            new_label = dev.get("label", "")
            # Find existing profile that matches (drive, label) but has a
            # stale id. Prefer the most-recently-synced match.
            candidates = [
                did for did, p in profiles.items()
                if p.get("drive") == new_drive and p.get("label") == new_label
            ]
            if not candidates:
                continue
            old_id = max(candidates, key=lambda d: profiles[d].get("last_sync")
                                                  or profiles[d].get("created_at") or "")
            old_profile = profiles.pop(old_id)
            old_profile["device_id"] = new_id
            profiles[new_id] = old_profile
            migrated += 1
            logger.info(
                "[Profiles] migrated %s → %s (drive=%s label=%s, %d playlist(s) preserved)",
                old_id, new_id, new_drive, new_label,
                len(old_profile.get("sync_playlists") or []),
            )

        # Re-build groups after migration
        groups: Dict[tuple, List[str]] = {}
        for did, p in profiles.items():
            key = (p.get("drive", ""), p.get("label", ""))
            groups.setdefault(key, []).append(did)

        def _ts(did: str) -> str:
            p = profiles[did]
            return p.get("last_sync") or p.get("created_at") or ""

        # ── Step B: prune non-canonical siblings ───────────────────────
        removed = 0
        for key, dids in groups.items():
            if len(dids) <= 1:
                continue

            connected_in_group = [d for d in dids if d in connected_ids]
            keep_id = (
                connected_in_group[0]
                if connected_in_group
                else max(dids, key=_ts)
            )

            # Inherit playlists if keeper has none
            keeper = profiles[keep_id]
            if not keeper.get("sync_playlists"):
                for d in sorted(dids, key=_ts, reverse=True):
                    if d == keep_id:
                        continue
                    if profiles[d].get("sync_playlists"):
                        keeper["sync_playlists"] = profiles[d]["sync_playlists"]
                        logger.info(
                            "[Profiles] inherited %d playlist(s) from %s into %s",
                            len(keeper["sync_playlists"]), d, keep_id,
                        )
                        break

            for stale_id in dids:
                if stale_id == keep_id:
                    continue
                del profiles[stale_id]
                removed += 1
            logger.info(
                "[Profiles] kept %s, pruned %d sibling(s) (drive=%s label=%s)",
                keep_id, len(dids) - 1, key[0], key[1],
            )

        if migrated or removed:
            data["profiles"] = profiles
            cls._save_all(data)
            logger.info("[Profiles] prune summary: migrated=%d removed=%d", migrated, removed)
        return removed

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

        # --- Library One (modern OneLibrary, SQLCipher-encrypted) ---
        # Plain sqlite3 cannot open SQLCipher; use rbox.OneLibrary instead.
        # Reader output also gathers playlist tree so the UI can show what
        # was actually written (mirrors the legacy XML view).
        legacy_one_playlists: list = []
        if l1_path.exists():
            try:
                import rbox as _rbox
                onedb = _rbox.OneLibrary(str(l1_path))
                # Build artist + album lookup once so we don't N+1 each track
                artist_lookup = {a.id: a.name for a in onedb.get_artists() if a.name}
                album_lookup = {a.id: a.name for a in onedb.get_albums() if a.name}
                for c in onedb.get_contents():
                    artist_id = getattr(c, "artist_id", None)
                    album_id = getattr(c, "album_id", None)
                    results["library_one"].append({
                        "ID": str(c.id),
                        "Title": c.title or "",
                        "ArtistName": artist_lookup.get(artist_id, "") if artist_id else "",
                        "Album": album_lookup.get(album_id, "") if album_id else "",
                        "BPM": int((c.bpmx100 or 0)),  # already × 100
                        "Duration": int(c.length or 0),
                        "FolderPath": str(Path(c.path or "").parent).replace("\\", "/"),
                        "FileNameL": Path(c.path or "").name,
                        "TotalTime": int(c.length or 0),
                    })
                # Walk playlist tree (ordered by parent → seq)
                pls_by_id = {p.id: p for p in onedb.get_playlists()}
                children_by_parent = {}
                for p in pls_by_id.values():
                    pid = getattr(p, "parent_id", 0) or 0
                    children_by_parent.setdefault(pid, []).append(p)
                def _walk_one(parent_id, parent_name):
                    for child in sorted(children_by_parent.get(parent_id, []),
                                        key=lambda x: getattr(x, "seq", 0) or 0):
                        is_folder = getattr(child, "attribute", 0) == 1
                        track_keys = []
                        if not is_folder:
                            try:
                                contents = onedb.get_playlist_contents(int(child.id))
                                track_keys = [str(getattr(pc, "content_id", pc)) for pc in contents]
                            except Exception:
                                track_keys = []
                        legacy_one_playlists.append({
                            "name": child.name or "",
                            "type": "0" if is_folder else "1",
                            "parent": parent_name,
                            "track_keys": track_keys,
                        })
                        if is_folder:
                            _walk_one(child.id, child.name)
                _walk_one(0, "ROOT")
                statuses["library_one_status"] = "loaded"
                logger.info(
                    "Library One loaded for %s: %d tracks, %d playlists",
                    device_id, len(results["library_one"]), len(legacy_one_playlists),
                )
            except Exception as e:
                logger.warning(f"Library One read failed for {device_id} (will fall back to size estimate): {e}")
                statuses["library_one_status"] = "encrypted"
                try:
                    file_size = l1_path.stat().st_size
                    est_tracks = max(0, file_size // 50000)
                    results["library_one"].append({
                        "ID": "_status_encrypted",
                        "Title": f"Library One — ~{est_tracks} tracks (couldn't open: {type(e).__name__})",
                        "ArtistName": "rbox failed to open the DB on this stick",
                        "BPM": 0, "Duration": 0,
                        "FolderPath": str(l1_path), "FileNameL": "",
                        "_encrypted": True,
                    })
                except Exception:
                    pass

        # --- Library Legacy: Try XML first, then PDB ---
        legacy_playlists = []  # [{name, type, parent, track_keys: [...]}]
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
                            "Album": track.get("Album"),
                            "Genre": track.get("Genre"),
                            "Key": track.get("Tonality"),
                            "FolderPath": str(Path(path).parent).replace("\\", "/"),
                            "FileNameL": Path(path).name,
                            "BPM": int(float(track.get("AverageBpm", 0)) * 100),
                            "TotalTime": int(track.get("TotalTime") or 0),
                        })
                # Walk <PLAYLISTS> tree (Rekordbox-XML schema with optional ROOT wrapper)
                pls_root = root.find("PLAYLISTS")
                if pls_root is not None:
                    top_nodes = pls_root.findall("NODE")
                    walk_root = top_nodes[0] if (len(top_nodes) == 1 and top_nodes[0].get("Type") == "0") else pls_root
                    def _walk(n, parent):
                        for child in n.findall("NODE"):
                            ctype = child.get("Type", "1")
                            entry = {
                                "name": child.get("Name", ""),
                                "type": ctype,
                                "parent": parent,
                                "track_keys": [t.get("Key") for t in child.findall("TRACK")],
                            }
                            legacy_playlists.append(entry)
                            if ctype == "0":
                                _walk(child, entry["name"])
                    _walk(walk_root, "ROOT")
                statuses["library_legacy_status"] = "loaded"
                logger.info(
                    "Library Legacy (XML) loaded for %s: %d tracks, %d playlists",
                    device_id, len(results['library_legacy']), len(legacy_playlists),
                )
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
            # Filesystem-tree views (legacy UI)
            "library_one": build_tree(results["library_one"]),
            "library_legacy": build_tree(results["library_legacy"]),
            # Flat track + playlist views — what the new UI consumes to render
            # the stick like a normal library (sidebar + track table) instead
            # of as a folder tree of audio paths.
            "library_one_flat": results["library_one"],
            "library_legacy_flat": results["library_legacy"],
            "library_legacy_playlists": legacy_playlists,
            "library_one_playlists": legacy_one_playlists,
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
        # Normalize bare drive letters ("E:") to drive root ("E:\") so that
        # Path("E:") / "PIONEER" doesn't produce relative "E:PIONEER" instead
        # of the expected absolute "E:\PIONEER".
        if len(usb_drive) == 2 and usb_drive[1] == ':':
            usb_drive = usb_drive + '\\'
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
        # Ensure CDJ device-identification marker exists on already-prepared sticks.
        UsbDetector._write_device_pioneer(self.usb_pioneer)

        # Seed MYSETTING / MYSETTING2 / DJMMYSETTING with pyrekordbox factory
        # defaults if they're missing. The user can later overwrite these via
        # the USB Settings tab; this ensures every freshly-synced stick has
        # valid CDJ-readable settings out of the box.
        try:
            from . import usb_mysettings
            usb_mysettings.write_defaults(self.usb_root)
        except Exception as exc:
            logger.warning(f"[mysettings] default seed skipped: {exc}")
        
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

    def sync_collection(self, profile: Dict, library_types: List[str] = ["library_one", "library_legacy"]) -> Generator[Dict, None, None]:
        yield {"stage": "preparing", "message": "Preparing full sync...", "progress": 0}
        self._ensure_usb_structure()

        try:
            did_sync = False

            with locked_sync(Path(profile["drive"])):
                if "library_one" in library_types:
                    yield {"stage": "info", "message": "Writing OneLibrary (exportLibrary.db) — CDJ-3000 native format…", "progress": 10}
                    for event in self._sync_library_one(profile):
                        yield event
                    did_sync = True

                if "library_legacy" in library_types or profile.get("sync_mirrored"):
                    yield {"stage": "info", "message": "Writing Legacy XML (rekordbox.xml)…", "progress": 60}
                    for event in self._sync_library_legacy(profile):
                        yield {
                            "stage": event.get("stage", "sync"),
                            "message": f"Legacy: {event.get('message', '')}",
                            "progress": 60 + int(event.get("progress", 0) * 0.4),
                        }
                    did_sync = True

            if not did_sync:
                yield {"stage": "complete", "message": "Nothing synced — enable library_one or library_legacy", "progress": 100}

        except Exception as e:
            logger.error(f"Collection sync failed: {e}")
            yield {"stage": "error", "message": str(e), "progress": -1}

    def _sync_library_one(self, profile: Dict, playlist_ids: List[str] = None) -> Generator[Dict, None, None]:
        """Sync via rbox.OneLibrary → exportLibrary.db + ANLZ + audio copy.

        The OneLibrary writer reuses our `_get_safe_dest_path` resolver so
        audio files land in the SAME directory as the legacy XML writer.
        Without this both writers (when both library types are selected)
        would copy each track twice — once to <usb>/Contents and once to
        <usb>/PIONEER/Contents.
        """
        try:
            from .usb_one_library import OneLibraryUsbWriter
            from .library_source import from_db
            from .database import db as global_db

            source = from_db(global_db)
            writer = OneLibraryUsbWriter(
                profile["drive"],
                dest_resolver=self._get_safe_dest_path,
            )
            for ev in writer.sync(source, audio_copy=True, copy_anlz=True):
                yield ev
        except Exception as e:
            logger.error(f"OneLibrary sync failed: {e}", exc_info=True)
            yield {"stage": "error", "message": f"OneLibrary: {e}", "progress": -1}

    def sync_playlists(self, profile: Dict, playlist_ids: List[str], library_types: List[str] = ["library_one", "library_legacy"]) -> Generator[Dict, None, None]:
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
                    yield {"stage": "info", "message": "Writing OneLibrary playlist export…", "progress": 10}
                    for event in self._sync_library_one(profile, playlist_ids):
                        yield event

                if "library_legacy" in library_types or profile.get("sync_mirrored"):
                    yield {"stage": "info", "message": "Starting Legacy XML Playlist Sync...", "progress": 60}
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
        """Req 20: Enforce UTF-8 and remove invalid OS characters.

        Windows silently strips trailing dots and spaces when creating directories
        or files. That means mkdir("foo ..") actually creates "foo", and any
        subsequent write to "foo ..\\file" fails with ENOENT. We must strip them
        here so the path we *request* matches the path Windows actually creates.
        Same for leading dots/spaces (hidden / trim artifacts) and reserved names.
        """
        import string, unicodedata
        name = str(name or "Unknown")
        valid_chars = f"-_.() {string.ascii_letters}{string.digits}"
        cleaned = ''.join(c for c in name if c in valid_chars or (unicodedata.category(c)[0] not in 'C'))
        for char in ["/", "\\", ":", "*", "?", '"', "<", ">", "|"]:
            cleaned = cleaned.replace(char, "_")
        # Strip leading/trailing dots and whitespace — Windows silently drops
        # them and that mismatches the path we later try to write to.
        cleaned = cleaned.strip(" .")
        # Avoid Windows reserved device names (CON, PRN, AUX, NUL, COM1-9, LPT1-9)
        reserved = {"CON", "PRN", "AUX", "NUL",
                    *(f"COM{i}" for i in range(1, 10)),
                    *(f"LPT{i}" for i in range(1, 10))}
        if cleaned.upper() in reserved:
            cleaned = f"_{cleaned}"
        return cleaned or "Unknown"

    def _get_safe_dest_path(self, artist: str, title: str, filename: str) -> Path:
        """
        Build a safe destination path for a track on the USB drive.

        Path limits per filesystem (self.filesystem / self.path_limit):
          FAT32  → 240 chars total (conservative Windows MAX_PATH)
          exFAT  → 255 chars per component (no strict total limit)
          NTFS   → 255 chars per component (no strict total limit on modern Windows)

        Pioneer-canonical layout (matches what Rekordbox itself produces):
            <USB>/Contents/<Artist>/<Title>/<file>
        Note: NOT under PIONEER/ and segment 2 is the TRACK TITLE, not the
        album — verified against a real Rekordbox-exported stick. The earlier
        `PIONEER/Contents/<Artist>/<Album>/` layout was non-standard and
        mismatched the paths stored inside exportLibrary.db, which made
        Rekordbox treat tracks as missing on insert.
        """
        contents_dir = self.usb_root / "Contents"
        artist_clean = self._clean_filename(artist)[:40].strip() or "UnknownArtist"
        title_clean = self._clean_filename(title)[:40].strip() or "UnknownTitle"
        file_clean = self._clean_filename(filename)

        dest = contents_dir / artist_clean / title_clean / file_clean

        # Only truncate total path length for FAT32 where MAX_PATH is a hard limit.
        # On NTFS/exFAT the per-component limit (255) is already enforced by _clean_filename.
        if self.filesystem == "FAT32" and len(str(dest)) > self.path_limit:
            excess = len(str(dest)) - self.path_limit
            stem = dest.stem
            ext = dest.suffix
            if len(stem) > excess:
                dest = contents_dir / artist_clean / title_clean / (stem[:-excess] + ext)
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

    @staticmethod
    def _xml_safe(value: str) -> str:
        """Strip characters illegal in XML 1.0 attribute values.

        XML 1.0 only allows: #x9 | #xA | #xD | [#x20-#xD7FF] | [#xE000-#xFFFD]
        Track names from Rekordbox can contain ASCII control characters (e.g.
        \\x13 = DC3) which cause xml.etree.ElementTree to write values that it
        then refuses to parse — producing a RecordBox XML that Rekordbox itself
        cannot read.
        """
        import re
        # Remove everything below 0x20 except tab (0x09), LF (0x0A), CR (0x0D)
        return re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', str(value or ''))

    def _sync_library_legacy(self, profile: Dict, playlist_ids: List[str] = None) -> Generator[Dict, None, None]:
        """Legacy Sync (Library Legacy): Exports library and audio to USB."""
        yield {"stage": "lib_legacy", "message": "Starting Library Legacy (XML & Audio) sync...", "progress": 0}
        try:
            import xml.etree.ElementTree as ET
            target = self.usb_pioneer / "rekordbox.xml"

            # Mode-agnostic source: when the active library is a Standalone-XML
            # we cannot open it as SQLCipher-encrypted master.db. Fall back to
            # the in-memory LibrarySource which iterates xml_db.tracks.
            is_xml_source = str(self.local_path).lower().endswith(".xml")
            if is_xml_source:
                logger.info("[USB-Legacy] XML-mode source detected — using LibrarySource path")
                yield from self._sync_library_legacy_from_xml(playlist_ids, target)
                return

            # We use the local master.db to generate a clean XML
            import rbox
            db = rbox.MasterDb(str(self.local_path))
            
            # Simple XML generation
            root = ET.Element("DJ_PLAYLISTS", Version="1.0.0")
            
            # Filter tracks if playlist_ids provided.
            #
            # Historical bug: rbox.MasterDb has NO get_playlist() method (it's
            # get_playlist_by_id) and NO get_playlist_content() method (it's
            # get_playlist_contents — plural). Both raised AttributeError and were
            # swallowed by `except: pass`, leaving target_track_ids empty. The
            # subsequent filter then fell through to "copy all tracks", which in
            # practice silently skipped everything (SoundCloud streams, unresolved
            # paths) and reported success with zero files copied.
            target_track_ids = set()
            if playlist_ids:
                for pl_id in playlist_ids:
                    try:
                        # get_playlist_contents accepts a string ID and yields
                        # DjmdContent objects — extract .id from each.
                        contents = db.get_playlist_contents(str(pl_id))
                        count = 0
                        for content in contents:
                            target_track_ids.add(str(content.id))
                            count += 1
                        logger.info(f"Playlist {pl_id}: resolved {count} tracks for USB sync")
                    except Exception as e:
                        logger.warning(f"Failed to resolve playlist {pl_id}: {type(e).__name__}: {e}")

                # If the user asked for specific playlists but none resolved,
                # abort instead of silently copying the entire library.
                if not target_track_ids:
                    yield {"stage": "error", "message": "No tracks found in selected playlists (check playlist IDs)", "progress": -1}
                    return

            tracks_to_export = [t for t in db.get_contents() if not target_track_ids or str(t.id) in target_track_ids]
            logger.info(f"USB sync: {len(tracks_to_export)} tracks to process (filter={'playlists' if target_track_ids else 'full library'})")
            
            collection = ET.SubElement(root, "COLLECTION", Entries=str(len(tracks_to_export)))
            
            skipped_streaming = 0
            skipped_missing = 0
            copied_ok = 0

            for i, t in enumerate(tracks_to_export):
                # rbox API uses *_by_id suffix for single-entity lookups.
                # Previous code called db.get_artist / db.get_album which don't
                # exist — they raised AttributeError that got silently swallowed
                # by `except: pass`, producing empty artist/album folder names
                # on USB ("UnknownArtist/UnknownAlbum" for every track).
                artist_name = ""
                if getattr(t, 'artist_id', None):
                    try:
                        artist_name = getattr(db.get_artist_by_id(str(t.artist_id)), 'name', '') or ''
                    except Exception as e:
                        logger.debug(f"artist lookup failed for id={t.artist_id}: {e}")

                album_name = ""
                if getattr(t, 'album_id', None):
                    try:
                        album_name = getattr(db.get_album_by_id(str(t.album_id)), 'name', '') or ''
                    except Exception as e:
                        logger.debug(f"album lookup failed for id={t.album_id}: {e}")

                title = getattr(t, 'title', '') or ''

                # rbox's DjmdContent.folder_path is actually the FULL FILE PATH
                # (not a folder), e.g. '<user_dir>/Music/.../MTHN - Beginning.m4a'.
                # The old code did `folder_path + '/' + file_name_l` which doubled
                # the filename ('/MTHN - Beginning.m4a/MTHN - Beginning.m4a') and
                # silently failed for every single track — reporting "sync complete"
                # with zero files copied. See debug survey: 3322/3322 local tracks
                # have folder_path as a full file path, 0 have it as a real folder.
                local_path_str = getattr(t, 'folder_path', '') or ''
                local_file = getattr(t, 'file_name_l', '') or os.path.basename(local_path_str)

                # Skip streaming-service pseudo-tracks (SoundCloud, Spotify, etc.)
                # — they store a URI scheme in folder_path instead of a real path.
                if ':' in local_path_str[:12] and not local_path_str[1:3] == ':\\' and not local_path_str[1:3] == ':/':
                    # Matches soundcloud:tracks:123, spotify:track:abc, etc.
                    # but NOT Windows drive letters like "C:/" or "C:\"
                    if local_path_str.split(':', 1)[0].lower() in ('soundcloud', 'spotify', 'tidal', 'beatport', 'http', 'https'):
                        skipped_streaming += 1
                        continue

                # Req 30: Resolve symlinks to avoid infinite loops and get absolute real paths
                try:
                    local_path = Path(local_path_str).resolve(strict=False)
                except Exception:
                    local_path = Path(local_path_str)

                usb_dest_path = None
                if local_path.exists():
                    # Path is keyed on title (Pioneer-canonical), but we still
                    # surface album_name to the XML <Album> attribute below.
                    usb_dest_path = self._get_safe_dest_path(artist_name, title, local_file)
                    try:
                        # Copy the file to USB with chunk streaming progress
                        for event in self._copy_file_stream(local_path, usb_dest_path):
                            # Ignore fine-grained chunk progress for now to keep UI simpler,
                            # but it's physically chunked and safe.
                            pass
                        copied_ok += 1
                    except OSError as e:
                        logger.error(f"Copy failed for {local_file}: {e}")

                        err_code = getattr(e, 'winerror', None) or getattr(e, 'errno', None)

                        # Req 16: ENOSPC / Disk Full (Win: 112, 39, Unix: 28)
                        if err_code in (112, 39, 28) or "No space left" in str(e):
                            raise Exception("Device is full (ENOSPC). Sync aborted.")

                        # Req 22: Disconnect detection — ENOENT (errno 2) alone is
                        # ambiguous: it fires for illegal filenames (Windows strips
                        # trailing dots/spaces), missing sources, etc. A real USB
                        # disconnect means the drive ROOT no longer exists. Probe
                        # that before aborting the entire batch over one bad file.
                        disconnect_codes = (21, 31, 1167, 3)  # Win: dev not ready / disk removed / not accessible
                        drive_gone = False
                        try:
                            drive_gone = not self.usb_root.exists()
                        except Exception:
                            drive_gone = True
                        if err_code in disconnect_codes or drive_gone:
                            raise Exception("USB Drive disconnected or inaccessible. Sync aborted.")

                        # Req 25: OS File Locks
                        if isinstance(e, PermissionError) or err_code in (5, 32):
                            logger.warning(f"PermissionError: file '{local_file}' may be locked by Rekordbox. Skipping without aborting batch.")
                            continue

                        # ENOENT / ENOTDIR / invalid-name paths — skip the bad
                        # track, keep syncing the rest. Previous behavior treated
                        # ENOENT as disconnect and killed the whole batch.
                        logger.warning(f"Skipping '{local_file}' after OSError (err={err_code}): {e}")
                        continue
                else:
                    skipped_missing += 1
                    logger.warning(f"Audio file missing locally, skipping copy: {local_path}")
                
                # XML Location -> URL Encode
                import urllib.parse
                if usb_dest_path:
                    # Build absolute path string: Path("E:\\PIONEER\\...") → "E:/PIONEER/..."
                    # Use resolve() to guarantee an absolute path (drive letter + backslash root)
                    # before stringifying, so "E:PIONEER" never appears in the URL.
                    abs_dest = usb_dest_path.resolve()
                    loc_val = f"file://localhost/{str(abs_dest)}".replace("\\", "/")
                else:
                    loc_val = f"file://localhost/{local_path_str}".replace("\\", "/")

                # Percent-encode everything except already-safe URL chars.
                # safe=":/." keeps drive letters, slashes, and dots unencoded.
                loc_val = urllib.parse.quote(loc_val, safe=":/./-_~")

                # _xml_safe strips ASCII control characters (e.g. \x13 DC3) that
                # some Rekordbox track names contain — they make ElementTree write
                # invalid XML that nothing (including Rekordbox) can re-parse.
                ET.SubElement(collection, "TRACK",
                    TrackID=str(t.id),
                    Name=self._xml_safe(getattr(t, 'title', '') or ''),
                    Artist=self._xml_safe(artist_name),
                    Album=self._xml_safe(album_name),
                    TotalTime=str(int(getattr(t, 'length', 0) or 0)),
                    AverageBpm=f"{float(getattr(t, 'bpm', 0) or 0):.2f}",
                    Tonality=self._xml_safe(getattr(t, 'key_id', '') or ''),
                    Rating=str(getattr(t, 'rating', 0) or 0),
                    Location=loc_val,
                )
                if i % 10 == 0:
                    yield {"stage": "lib_legacy", "message": f"Copying & Exporting: {i}/{len(tracks_to_export)}", "progress": int((i/max(len(tracks_to_export),1))*90)}
            
            # Also export the Playlists if provided.
            # Same rbox method-name fix as above (get_playlist_by_id + get_playlist_contents).
            # System playlists like "Import" are filtered out — they're local
            # working-memory buckets and would just clutter the CDJ menu.
            if playlist_ids:
                node_pl = ET.SubElement(root, "PLAYLISTS")
                for pl_id in playlist_ids:
                    try:
                        pl = db.get_playlist_by_id(str(pl_id))
                        if not pl:
                            continue
                        pl_name = getattr(pl, 'name', '') or ''
                        if _is_excluded_playlist(pl_name):
                            logger.info(f"[USB-Legacy] Skipping excluded playlist '{pl_name}'")
                            continue
                        pl_elem = ET.SubElement(node_pl, "NODE",
                            Name=self._xml_safe(pl_name), Type="1")
                        for content in db.get_playlist_contents(str(pl_id)):
                            ET.SubElement(pl_elem, "TRACK", Key=str(content.id))
                    except Exception as e:
                        logger.warning(f"Failed to export playlist {pl_id} to XML: {type(e).__name__}: {e}")

            # Remove stale .corrupt leftover from a previous failed sync before
            # writing the new file — otherwise the reader sees the old bad file.
            corrupt_path = target.with_suffix(".xml.corrupt")
            if corrupt_path.exists():
                try:
                    corrupt_path.unlink()
                    logger.info(f"Removed stale corrupt XML: {corrupt_path}")
                except Exception as e:
                    logger.warning(f"Could not remove corrupt XML: {e}")

            tree = ET.ElementTree(root)
            with open(target, "wb") as f:
                tree.write(f, encoding="UTF-8", xml_declaration=True)
            
            # Req 22: UI-state mismatch -> Give OS buffers 1.5s to flush before declaring 100% complete
            yield {"stage": "flushing", "message": "Flushing OS file buffers to USB, please wait...", "progress": 99}
            time.sleep(1.5)

            summary = f"{copied_ok} copied, {skipped_missing} missing locally, {skipped_streaming} streaming (skipped)"
            logger.info(f"Legacy sync finished: {summary}")
            yield {
                "stage": "complete",
                "message": f"Synced: {summary}",
                "progress": 100,
                "copied": copied_ok,
                "skipped_missing": skipped_missing,
                "skipped_streaming": skipped_streaming,
            }
        except Exception as e:
            logger.error(f"Library Legacy sync failed: {e}")
            yield {"stage": "error", "message": f"Library Legacy sync failed: {e}", "progress": -1}

    def _sync_library_legacy_from_xml(
        self, playlist_ids: List[str], target: Path,
    ) -> Generator[Dict, None, None]:
        """Legacy XML sync sourced from RekordboxXMLDB (Standalone mode).
        Mirrors _sync_library_legacy's master.db path but pulls everything
        through LibrarySource so the operation works without rbox.MasterDb.
        """
        import xml.etree.ElementTree as ET
        import urllib.parse
        from .library_source import from_db
        from .database import db as global_db

        source = from_db(global_db)
        all_tracks = list(source.iter_tracks())

        # Filter by selected playlists
        target_track_ids: set = set()
        if playlist_ids:
            for pid in playlist_ids:
                target_track_ids.update(source.get_playlist_track_ids(pid))
            if not target_track_ids:
                yield {"stage": "error", "message": "No tracks in selected playlists", "progress": -1}
                return

        tracks_to_export = [t for t in all_tracks if not target_track_ids or t["id"] in target_track_ids]
        logger.info(f"[USB-Legacy-XML] {len(tracks_to_export)} tracks to process")

        root = ET.Element("DJ_PLAYLISTS", Version="1.0.0")
        collection = ET.SubElement(root, "COLLECTION", Entries=str(len(tracks_to_export)))

        skipped_missing = 0
        skipped_streaming = 0
        copied_ok = 0

        for i, t in enumerate(tracks_to_export):
            local_path_str = t.get("path") or ""
            if not local_path_str:
                skipped_missing += 1
                continue

            # Skip streaming pseudo-paths
            if ":" in local_path_str[:12] and not local_path_str[1:3] in (":\\", ":/"):
                if local_path_str.split(":", 1)[0].lower() in ("soundcloud", "spotify", "tidal", "beatport", "http", "https"):
                    skipped_streaming += 1
                    continue

            try:
                local_path = Path(local_path_str).resolve(strict=False)
            except Exception:
                local_path = Path(local_path_str)
            local_file = local_path.name

            usb_dest_path = None
            if local_path.exists():
                # Pioneer-canonical layout: <USB>/Contents/<Artist>/<Title>/<file>
                usb_dest_path = self._get_safe_dest_path(t.get("artist", ""), t.get("title", ""), local_file)
                try:
                    for _ in self._copy_file_stream(local_path, usb_dest_path):
                        pass
                    copied_ok += 1
                except OSError as e:
                    logger.warning(f"[USB-Legacy-XML] Copy failed for {local_file}: {e}")
                    err_code = getattr(e, "winerror", None) or getattr(e, "errno", None)
                    if err_code in (112, 39, 28) or "No space left" in str(e):
                        raise Exception("Device is full (ENOSPC). Sync aborted.")
                    if (err_code in (21, 31, 1167, 3)) or not self.usb_root.exists():
                        raise Exception("USB Drive disconnected. Sync aborted.")
                    continue
            else:
                skipped_missing += 1
                logger.warning(f"[USB-Legacy-XML] Missing locally: {local_path}")

            if usb_dest_path:
                abs_dest = usb_dest_path.resolve()
                loc_val = f"file://localhost/{str(abs_dest)}".replace("\\", "/")
            else:
                loc_val = f"file://localhost/{local_path_str}".replace("\\", "/")
            loc_val = urllib.parse.quote(loc_val, safe=":/./-_~")

            ET.SubElement(
                collection, "TRACK",
                TrackID=str(t["id"]),
                Name=self._xml_safe(t.get("title", "")),
                Artist=self._xml_safe(t.get("artist", "")),
                Album=self._xml_safe(t.get("album", "")),
                TotalTime=str(int((t.get("duration_ms", 0) or 0) / 1000)),
                AverageBpm=f"{float(t.get('bpm', 0) or 0):.2f}",
                Tonality=self._xml_safe(t.get("key", "")),
                Genre=self._xml_safe(t.get("genre", "")),
                Label=self._xml_safe(t.get("label", "")),
                Rating=str(t.get("rating", 0)),
                Comments=self._xml_safe(t.get("comment", "")),
                Location=loc_val,
            )
            if i % 10 == 0:
                yield {
                    "stage": "lib_legacy",
                    "message": f"Copying {i}/{len(tracks_to_export)}",
                    "progress": int((i / max(len(tracks_to_export), 1)) * 90),
                }

        # Playlist tree — filter out excluded playlists ("Import" etc.)
        all_playlists = [
            pl for pl in source.iter_playlists()
            if not _is_excluded_playlist(pl.get("name", ""))
        ]
        excluded_count = len(list(source.iter_playlists())) - len(all_playlists)
        if excluded_count:
            logger.info(f"[USB-Legacy-XML] Excluded {excluded_count} system playlist(s) from USB export")

        playlists_root = ET.SubElement(root, "PLAYLISTS")
        playlists_root_node = ET.SubElement(playlists_root, "NODE", Name="ROOT", Type="0",
                                            Count=str(len(all_playlists)))
        for pl in all_playlists:
            if playlist_ids and str(pl["id"]) not in playlist_ids:
                continue
            node = ET.SubElement(
                playlists_root_node, "NODE",
                Name=self._xml_safe(pl.get("name", "")),
                Type=pl.get("type", "1"),
            )
            if pl.get("type") in ("1", "4"):
                node.set("Entries", str(len(pl.get("track_ids", []))))
                for tid in pl.get("track_ids", []):
                    ET.SubElement(node, "TRACK", Key=str(tid))

        # Atomic write
        corrupt_path = target.with_suffix(".xml.corrupt")
        if corrupt_path.exists():
            try: corrupt_path.unlink()
            except Exception: pass
        tree = ET.ElementTree(root)
        with open(target, "wb") as f:
            tree.write(f, encoding="UTF-8", xml_declaration=True)

        yield {"stage": "flushing", "message": "Flushing OS buffers…", "progress": 99}
        time.sleep(1.0)

        summary = f"{copied_ok} copied, {skipped_missing} missing, {skipped_streaming} streaming (skipped)"
        logger.info(f"[USB-Legacy-XML] complete: {summary}")
        yield {
            "stage": "complete",
            "message": f"Synced (XML): {summary}",
            "progress": 100,
            "copied": copied_ok,
            "skipped_missing": skipped_missing,
            "skipped_streaming": skipped_streaming,
        }

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
    def format_drive(drive: str, label: str = "CDJ", filesystem: str = "FAT32") -> Dict:
        """
        Wipe and re-format a USB drive, then re-create the Pioneer skeleton.

        DESTRUCTIVE — all existing data on the drive is lost. Callers must
        gate this behind explicit double-confirmation in the UI; this method
        does not prompt.

        Supported filesystems: FAT32 (CDJ-2000NXS2 + CDJ-3000), exFAT (CDJ-3000
        only — needed for files >4GB).

        Platform support:
          * Windows: PowerShell `Format-Volume`
          * Linux:   `mkfs.vfat` / `mkfs.exfat` (drive must be a block device)
          * macOS:   `diskutil eraseDisk`
        """
        import platform, shlex, subprocess as sp

        fs = (filesystem or "FAT32").upper()
        if fs not in ("FAT32", "EXFAT"):
            return {"status": "error", "message": f"Unsupported filesystem: {fs}"}

        # Sanitise label — most filesystems impose limits.
        safe_label = "".join(c for c in (label or "CDJ") if c.isalnum() or c in " _-")[:11] or "CDJ"

        system = platform.system()
        try:
            if system == "Windows":
                drive_letter = drive.rstrip("\\").rstrip("/").rstrip(":")
                if not drive_letter:
                    return {"status": "error", "message": "Invalid drive."}
                ps_fs = "FAT32" if fs == "FAT32" else "exFAT"
                # -Confirm:$false suppresses interactive prompt; -Force overrides
                # the "drive contains data" guard.
                cmd = (
                    f"Format-Volume -DriveLetter {drive_letter} -FileSystem {ps_fs} "
                    f"-NewFileSystemLabel '{safe_label}' -Confirm:$false -Force"
                )
                proc = sp.run(
                    ["powershell", "-NoProfile", "-Command", cmd],
                    capture_output=True, text=True, timeout=600,
                )
                if proc.returncode != 0:
                    return {"status": "error", "message": (proc.stderr or proc.stdout or "Format failed").strip()}

                # Re-create PIONEER skeleton + DEVICE.PIONEER marker.
                drive_root = f"{drive_letter}:\\"
                UsbDetector.initialize_usb(drive_root)
                return {
                    "status": "success",
                    "message": f"Drive {drive_letter}: formatted as {ps_fs} '{safe_label}' and CDJ-prepared.",
                }

            elif system == "Linux":
                # On Linux `drive` must be a block device path (e.g. /dev/sdb1).
                if not drive or not drive.startswith("/dev/"):
                    return {"status": "error", "message": "Linux: pass a block device path like /dev/sdb1."}
                tool = "mkfs.vfat" if fs == "FAT32" else "mkfs.exfat"
                args = (
                    [tool, "-F", "32", "-n", safe_label, drive]
                    if fs == "FAT32"
                    else [tool, "-n", safe_label, drive]
                )
                proc = sp.run(args, capture_output=True, text=True, timeout=600)
                if proc.returncode != 0:
                    return {"status": "error", "message": (proc.stderr or proc.stdout).strip()}
                return {
                    "status": "success",
                    "message": f"Formatted {drive} as {fs}. Mount it, then run /api/usb/initialize.",
                }

            elif system == "Darwin":
                # macOS: drive should be a disk identifier like disk2 or /dev/disk2.
                ident = drive.replace("/dev/", "")
                fs_arg = "MS-DOS" if fs == "FAT32" else "ExFAT"
                proc = sp.run(
                    ["diskutil", "eraseDisk", fs_arg, safe_label, ident],
                    capture_output=True, text=True, timeout=600,
                )
                if proc.returncode != 0:
                    return {"status": "error", "message": (proc.stderr or proc.stdout).strip()}
                return {
                    "status": "success",
                    "message": f"Erased {ident} as {fs_arg} '{safe_label}'.",
                }
            else:
                return {"status": "error", "message": f"Unsupported platform: {system}"}
        except sp.TimeoutExpired:
            return {"status": "error", "message": "Format command timed out (>10 min). Drive may be unhealthy."}
        except FileNotFoundError as exc:
            return {"status": "error", "message": f"Format tool not found: {exc}"}
        except Exception as exc:
            logger.error("format_drive failed: %s", exc, exc_info=True)
            return {"status": "error", "message": str(exc)}

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
            # Always sync both formats — Rekordbox auto-detect (library_one)
            # AND legacy XML (library_legacy) — regardless of saved profile.
            library_types = sorted(set(
                (profile.get("library_types") or []) + ["library_one", "library_legacy"]
            ))

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
