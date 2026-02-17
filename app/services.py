import shutil
import wave
import psutil
import datetime
import subprocess
import os
import gc
import json
import time
import re
import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from collections import defaultdict
from .config import REKORDBOX_ROOT, DB_FILENAME, BACKUP_DIR, FFMPEG_BIN, EXPORT_DIR, MUSIC_DIR
from .xml_generator import RekordboxXML
from .database import db
import mutagen
from mutagen.id3 import ID3, APIC
from mutagen.flac import FLAC, Picture

logger = logging.getLogger(__name__)

class XMLProcessor:
    REMOVE_STRINGS = ["(Original Mix)", "(Extended Mix)", "Original Mix"]
    MIN_TRACKS_THRESHOLD = 5
    MISSING_ARTIST_NAME = "!!SERVICE!!"
    MISSING_ARTIST_COLOR_ID = "8"

    @staticmethod
    def clean_tag(text: str) -> str:
        if not text: return ""
        cleaned = text.strip()
        for bad_str in XMLProcessor.REMOVE_STRINGS:
            if bad_str in cleaned:
                cleaned = cleaned.replace(bad_str, "")
        return " ".join(cleaned.split())

    @staticmethod
    def create_node(parent, name, type_id="0"):
        node = ET.SubElement(parent, "NODE")
        node.set("Name", name)
        node.set("Type", type_id)
        node.set("Count", "0")
        if type_id == "1":
            node.set("KeyType", "0")
            node.set("Entries", "0")
        return node

    @staticmethod
    def get_or_create_path(root_node, path_str):
        current_node = root_node
        parts = [p for p in path_str.replace("\\", "/").split("/") if p]
        for part in parts:
            found = None
            for child in current_node.findall("NODE"):
                if child.get("Name") == part and child.get("Type") == "0":
                    found = child
                    break
            if found: current_node = found
            else: current_node = XMLProcessor.create_node(current_node, part, "0")
        return current_node

    @staticmethod
    def process(input_path, output_path, artist_folder, label_folder):
        tree = ET.parse(input_path)
        root = tree.getroot()
        if root.tag != "DJ_PLAYLISTS": raise ValueError("Invalid Rekordbox XML")
        
        collection = root.find("COLLECTION")
        playlists_root = root.find("PLAYLISTS")
        if collection is None or playlists_root is None: raise ValueError("Invalid XML Structure")

        tracks = list(collection.findall("TRACK"))
        artist_map = defaultdict(list)
        label_map = defaultdict(list)
        
        for track in tracks:
            tid = track.get("TrackID")
            
            # Cleaning
            for attr in ["Name", "Artist", "Album", "Label"]:
                track.set(attr, XMLProcessor.clean_tag(track.get(attr, "")))

            # Service Check
            artist_val = track.get("Artist", "").strip()
            if not artist_val:
                track.set("Artist", XMLProcessor.MISSING_ARTIST_NAME)
                track.set("ColorID", XMLProcessor.MISSING_ARTIST_COLOR_ID)
                artist_val = XMLProcessor.MISSING_ARTIST_NAME
            
            if artist_val: artist_map[artist_val].append(tid)
            label_val = track.get("Label", "").strip()
            if label_val: label_map[label_val].append(tid)

        # Playlist Gen
        root_node = playlists_root.find("NODE")
        if root_node is None: root_node = XMLProcessor.create_node(playlists_root, "ROOT", "0")

        # Artists
        target_art = XMLProcessor.get_or_create_path(root_node, artist_folder)
        for art, tids in artist_map.items():
            if len(tids) >= XMLProcessor.MIN_TRACKS_THRESHOLD:
                pl = XMLProcessor.create_node(target_art, art, "1")
                pl.set("Entries", str(len(tids)))
                for t in tids: ET.SubElement(pl, "TRACK").set("Key", t)

        # Labels
        target_lbl = XMLProcessor.get_or_create_path(root_node, label_folder)
        for lbl, tids in label_map.items():
            if len(tids) >= XMLProcessor.MIN_TRACKS_THRESHOLD:
                pl = XMLProcessor.create_node(target_lbl, lbl, "1")
                pl.set("Entries", str(len(tids)))
                for t in tids: ET.SubElement(pl, "TRACK").set("Key", t)

        tree.write(output_path, encoding="utf-8", xml_declaration=True)
        return output_path

class SystemGuard:
    @staticmethod
    def is_rekordbox_running() -> bool:
        for proc in psutil.process_iter(['name']):
            try:
                if "rekordbox" in proc.info['name'].lower(): return True
            except: pass
        return False
    @staticmethod
    def create_backup():
        source = REKORDBOX_ROOT / DB_FILENAME
        if not source.exists(): return None
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = BACKUP_DIR / f"{DB_FILENAME}.backup_{timestamp}"
        try: shutil.copy2(source, dest); return str(dest)
        except: return None

class AudioEngine:
    @staticmethod
    def check_ffmpeg():
        try:
            subprocess.run([FFMPEG_BIN, "-version"], capture_output=True, check=True)
            return True
        except:
            logger.error("FFmpeg not found in PATH")
            return False

    @staticmethod
    def render_segment(source_path: str, cuts: list, output_filename: str, fade_in=False, fade_out=False):
        if not AudioEngine.check_ffmpeg():
             raise RuntimeError("FFmpeg not installed or not found in system PATH. Please install FFmpeg.")
        if not os.path.exists(source_path): raise FileNotFoundError(f"File not found: {source_path}")
        temp_files = []
        try:
            for i, cut in enumerate(cuts):
                start, end = cut['start'], cut['end']
                duration = end - start
                
                # Skip zero-duration segments which cause FFmpeg to fail
                if duration <= 0:
                    logger.warning(f"Skipping zero-duration segment at index {i} ({start} - {end})")
                    continue

                cut_src = cut.get('src', source_path)
                logger.info(f"[Segment {i}] Checking source: {cut_src}")
                if not cut_src or not os.path.exists(cut_src):
                    logger.warning(f"Segment source not found: {cut_src}, falling back to master source")
                    cut_src = source_path

                # Use unique filename with microsecond precision
                unique_id = f"{int(time.time() * 1000)}_{i}"
                temp = EXPORT_DIR / f"temp_{unique_id}.wav"
                
                filters = []
                if fade_in and i == 0: filters.append("afade=t=in:st=0:d=1.0")
                if fade_out and i == len(cuts)-1: filters.append(f"afade=t=out:st={max(0, duration-1)}:d=1.0")
                f_arg = ["-af", ",".join(filters)] if filters else []
                
                cmd = [FFMPEG_BIN, "-y", "-ss", str(max(0, start)), "-t", str(duration), "-i", cut_src] + f_arg + ["-vn", "-map", "0:a", "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", str(temp)]
                logger.info(f"[Segment {i}] FFmpeg command: {' '.join(cmd)}")
                logger.info(f"[Segment {i}] Cut details - start: {start}s, end: {end}s, duration: {duration}s")
                logger.info(f"[Segment {i}] Source file: {cut_src}")
                logger.info(f"[Segment {i}] Source exists: {os.path.exists(cut_src)}")
                logger.info(f"[Segment {i}] Output file: {temp}")
                
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode != 0:
                    logger.error(f"[Segment {i}] FFmpeg FAILED")
                    logger.error(f"[Segment {i}] Return code: {result.returncode}")
                    logger.error(f"[Segment {i}] STDERR: {result.stderr}")
                    logger.error(f"[Segment {i}] STDOUT: {result.stdout}")
                    raise RuntimeError(f"FFmpeg failed for segment {i}: {result.stderr}")
                
                logger.info(f"[Segment {i}] Successfully created temp file: {temp}")
                temp_files.append(temp)

            if not temp_files:
                raise ValueError("No valid segments to render")

            # Final output file path
            final_path = EXPORT_DIR / output_filename

            # Use Python's wave module to concatenate the standardized WAV files
            with wave.open(str(final_path), 'wb') as outfile:
                with wave.open(str(temp_files[0]), 'rb') as infile:
                    outfile.setparams(infile.getparams())
                
                for tf in temp_files:
                    with wave.open(str(tf), 'rb') as infile:
                        outfile.writeframes(infile.readframes(infile.getnframes()))
            
            logger.info(f"Successfully exported track to {final_path} using python wave module")

            # Generate Track Metadata for DB
            new_tid = f"R_{int(time.time())}"
            orig_track = None
            for t in db.tracks.values():
                if t.get('path') == source_path:
                    orig_track = t
                    break

            track_data = {
                "TrackID": new_tid,
                "Name": output_filename.rsplit('.', 1)[0],
                "Artist": orig_track.get('Artist', 'RB Editor') if orig_track else "RB Editor",
                "Album": "Edits",
                "Genre": orig_track.get('Genre', '') if orig_track else "",
                "Kind": "WAV File",
                "Size": str(final_path.stat().st_size),
                "TotalTime": str(int(duration)),
                "DateAdded": datetime.datetime.now().strftime("%Y-%m-%d"),
                "Bitrate": "2304",
                "SampleRate": "48000",
                "path": str(final_path),
            }
            
            # Recalculate total time from segments
            total_duration = sum([c['end'] - c['start'] for c in cuts])
            track_data["TotalTime"] = str(int(total_duration))

            db.add_track(track_data)
            db.save_xml()
            
            return new_tid
        except Exception as e: 
            logger.error(f"Render failed: {e}")
            raise RuntimeError(f"Render failed: {e}")
        finally:
            # STABILITY: Always clean up temp files, even on error
            for tf in temp_files:
                try:
                    if os.path.exists(str(tf)):
                        os.remove(str(tf))
                except OSError as cleanup_err:
                    logger.warning(f"Could not remove temp file {tf}: {cleanup_err}")

    @staticmethod
    def slice_audio(source_path: str, start: float, end: float):
        if not AudioEngine.check_ffmpeg():
             raise RuntimeError("FFmpeg not found")
        
        if not os.path.exists(source_path): raise FileNotFoundError(f"Source not found: {source_path}")

        duration = end - start
        if duration <= 0: raise ValueError("Invalid duration")
        
        unique_id = f"slice_{int(time.time()*1000)}"
        temp_path = EXPORT_DIR / f"{unique_id}.wav"
        
        # Standardize to WAV PCM for frontend compatibility
        cmd = [
            FFMPEG_BIN, "-y", 
            "-ss", str(float(start)), 
            "-t", str(float(duration)), 
            "-i", source_path,
            "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le",
            str(temp_path)
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                logger.error(f"FFmpeg slice failed: {result.stderr}")
                raise RuntimeError(f"FFmpeg slice failed: {result.stderr}")
            return str(temp_path)
        except Exception as e:
            logger.error(f"Slice error: {e}")
            raise e

class FileManager:
    @staticmethod
    def move_track(current, target_folder):
        src, dst_dir = Path(current), Path(target_folder)
        if not src.exists(): raise FileNotFoundError()
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / src.name
        counter = 1
        while dst.exists():
            if src.resolve() == dst.resolve(): return str(dst)
            dst = dst_dir / f"{src.stem}_{counter}{src.suffix}"
            counter += 1
        shutil.move(str(src), str(dst))
        return str(dst)

class LibraryTools:
    @staticmethod
    def find_duplicates():
        if not db.tracks: return []
        # Basic duplicate detection by Name and Artist
        counts = defaultdict(list)
        for tid, track in db.tracks.items():
            key = (track.get("Title", "").lower(), track.get("Artist", "").lower())
            counts[key].append(tid)
        
        duplicates = []
        for key, ids in counts.items():
            if len(ids) > 1:
                duplicates.append({
                    "Title": db.tracks[ids[0]].get("Title"),
                    "Artist": db.tracks[ids[0]].get("Artist"),
                    "count": len(ids),
                    "ids": ids
                })
        return duplicates

    @staticmethod
    def clean_track_titles(track_ids):
        """Removes artist name from track title if redundant."""
        results = {"success": [], "errors": []}
        for tid in track_ids:
            track = db.get_track_details(tid)
            if not track: continue
            
            title = track.get("Title", "")
            artist = track.get("Artist", "")
            if not title or not artist: continue

            # Pattern 1: "Artist - Title"
            # Pattern 2: "Title (feat. Artist)" - maybe keep this? 
            # User specifically mentioned "Artist in title field".
            
            new_title = title
            # Try some common delimiters
            for sep in [" - ", " – ", " — ", " | "]:
                if sep in title:
                    parts = title.split(sep)
                    # If the first part matches the artist (ignore case)
                    if parts[0].strip().lower() == artist.lower():
                        new_title = sep.join(parts[1:]).strip()
                        break
                    # Or second part matches
                    elif parts[-1].strip().lower() == artist.lower():
                        new_title = sep.join(parts[:-1]).strip()
                        break
            
            if new_title != title:
                db.update_track_title(tid, new_title)
                results["success"].append({"id": tid, "old": title, "new": new_title})
        return results

    @staticmethod
    def generate_smart_playlists(artist_threshold=5, label_threshold=5):
        """Generates intelligent playlists for Artists and Labels meeting the threshold."""
        # Note: XMLProcessor already does something similar, but this is for dynamic calling
        artist_map = defaultdict(list)
        label_map = defaultdict(list)
        
        for tid, track in db.tracks.items():
            artist = track.get("Artist")
            label = track.get("Label")
            if artist: artist_map[artist].append(tid)
            if label: label_map[label].append(tid)

        # 1. Ensure "Auto Playlists" folder
        auto_folder_node = next((p for p in db.playlists if p['Name'] == "Auto Playlists" and p['Type'] == "0"), None)
        if not auto_folder_node:
            auto_folder_node = db.create_playlist("Auto Playlists", parent_id="ROOT", is_folder=True)
        
        if not auto_folder_node: return False
        auto_folder_id = auto_folder_node['ID']

        # 2. Artists Folder
        art_folder_node = next((p for p in db.playlists if p['Name'] == "By Artist" and p['ParentID'] == auto_folder_id), None)
        if not art_folder_node:
            art_folder_node = db.create_playlist("By Artist", parent_id=auto_folder_id, is_folder=True)
        
        if art_folder_node:
            art_folder_id = art_folder_node['ID']
            for art, tids in artist_map.items():
                if len(tids) >= artist_threshold:
                    db.create_playlist(art, parent_id=art_folder_id, tracks=tids)

        # 3. Labels Folder
        lbl_folder_node = next((p for p in db.playlists if p['Name'] == "By Label" and p['ParentID'] == auto_folder_id), None)
        if not lbl_folder_node:
            lbl_folder_node = db.create_playlist("By Label", parent_id=auto_folder_id, is_folder=True)
            
        if lbl_folder_node:
            lbl_folder_id = lbl_folder_node['ID']
            for lbl, tids in label_map.items():
                if len(tids) >= label_threshold:
                    db.create_playlist(lbl, parent_id=lbl_folder_id, tracks=tids)

        db.save()
        return True

    @staticmethod
    def smart_rename(track_ids, pattern):
        results = {"success": [], "errors": []}
        for tid in track_ids:
            track = db.get_track_details(tid)
            if not track: continue
            new_name = pattern.replace("%Artist%", track.get('Artist','')).replace("%Title%", track.get('Title','')).replace("%BPM%", str(round(track.get('BPM',0)))).replace("%Key%", track.get('Key',''))
            new_name = re.sub(r'[<>:"/\\|?*]', '', new_name).strip()
            src = Path(track['path'])
            target = src.parent / (new_name + src.suffix)
            try:
                if target.exists() and target != src: target = src.parent / (f"{new_name}_1{src.suffix}")
                os.rename(src, target)
                db.update_track_path(tid, str(target))
                results["success"].append({"id": tid})
            except Exception as e: results["errors"].append(str(e))
        return results

class SettingsManager:
    CONFIG = Path("settings.json")
    DEFAULT = {
        "backup_retention_days": 30, 
        "default_export_format": "wav", 
        "theme": "dark", 
        "auto_snap": True, 
        "db_path": "", 
        "artist_view_threshold": 0,
        "ranking_filter_mode": "all", # all, unrated, untagged
        "archive_frequency": "daily", # off, daily, weekly, monthly
        "last_archive_date": "",
        "insights_playcount_threshold": 0,
        "insights_bitrate_threshold": 320,
        "hide_streaming": False,
        "remember_lib_mode": False,
        "last_lib_mode": "xml"
    }
    @classmethod
    def load(cls):
        try: return {**cls.DEFAULT, **json.load(open(cls.CONFIG))}
        except: return cls.DEFAULT
    @classmethod
    def save(cls, cfg): json.dump(cfg, open(cls.CONFIG, "w"), indent=2)

class MetadataManager:
    MAPPINGS_FILE = Path("metadata_mappings.json")

    @classmethod
    def load(cls):
        if not cls.MAPPINGS_FILE.exists():
            return {"artists": {}, "labels": {}, "albums": {}}
        try:
            with open(cls.MAPPINGS_FILE, "r", encoding='utf-8') as f:
                return json.load(f)
        except:
            return {"artists": {}, "labels": {}, "albums": {}}

    @classmethod
    def save(cls, data):
        with open(cls.MAPPINGS_FILE, "w", encoding='utf-8') as f:
            json.dump(data, f, indent=2)

    @classmethod
    def add_mapping(cls, category, source_name, target_name):
        data = cls.load()
        if category not in data: data[category] = {}
        data[category][source_name] = target_name
        cls.save(data)

    @classmethod
    def get_mapped_name(cls, category, name):
        data = cls.load()
        return data.get(category, {}).get(name, name)

class SystemCleaner:
    @staticmethod
    def cleanup_old_backups():
        days = SettingsManager.load().get("backup_retention_days", 30)
        cutoff = time.time() - (days * 86400)
        count = 0
        for b in BACKUP_DIR.glob("master.db.backup_*"):
            if b.stat().st_mtime < cutoff: 
                try: os.remove(b); count += 1
                except: pass
        return count

class BeatAnalyzer:
    @staticmethod
    def analyze(path: str):
        """Analyzes audio file with advanced 'Drop Detection' and spectral novelty analysis."""
        logger.info(f"Starting advanced spectral analysis for: {path}")
        if not os.path.exists(path):
            logger.error(f"Analysis aborted: File not found at {path}")
            raise FileNotFoundError(f"Audio file not found: {path}")
        
        try:
            import librosa
            import numpy as np
            from scipy.ndimage import gaussian_filter1d
        except ImportError:
            logger.error("CRITICAL: Dependencies missing. Please run 'pip install librosa scipy numba'")
            raise RuntimeError("Audio analysis engine missing dependencies.")
        
        try:
            # 1. Load Audio (Load full for better accuracy, but process in chunks if needed)
            logger.info("Loading audio data...")
            y, sr = librosa.load(path, sr=None)
            duration = librosa.get_duration(y=y, sr=sr)
            logger.info(f"Audio loaded. Duration: {duration:.2f}s, SR: {sr}")
            
            # 2. Detect BPM (Full track for robustness)
            logger.info("Detecting global BPM...")
            onset_env = librosa.onset.onset_strength(y=y, sr=sr)
            tempo, beats = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr)
            bpm = float(tempo)
            logger.info(f"Detected BPM: {bpm:.2f}")
            
            # 3. ADVANCED DROP DETECTION
            # Search window: 10s to 90s (most drops happen in this range)
            # Favor the highest energy transition after a buildup.
            logger.info("Searching for musical 'drop' (Spectral Novelty)...")
            limit_sr_start = int(sr * 10) # Skip first 10s (usually silence/simple beat)
            limit_sr_end = min(len(y), int(sr * 90)) # Up to 90s
            
            if limit_sr_end <= limit_sr_start:
                # Track too short, analyze full length instead
                y_analysis = y
                offset_frames = 0
            else:
                y_analysis = y[limit_sr_start:limit_sr_end]
                offset_frames = int(limit_sr_start / 512) # Based on hop_length=512
            
            # Calculate spectral novelty (sudden changes in frequency content)
            S = np.abs(librosa.stft(y_analysis))
            spectral_novelty = librosa.onset.onset_strength(S=librosa.amplitude_to_db(S, ref=np.max), sr=sr)
            
            # Smooth the novelty curve to find broad structural changes
            # Large window (2.5 seconds) to identify structural parts rather than hits
            hop_length = 512
            window_size_sec = 2.5
            window_size_frames = int((window_size_sec * sr) / hop_length)
            smoothed_novelty = gaussian_filter1d(spectral_novelty, sigma=window_size_frames/4)
            
            # Find the point of maximum GRADIENT (start of the drop/buildup)
            novelty_diff = np.diff(smoothed_novelty)
            
            # Give a slight weight to transitions further into the track to avoid picking up the first kick
            weights = np.linspace(1.0, 1.2, len(novelty_diff))
            weighted_diff = novelty_diff * weights
            
            drop_frame = np.argmax(weighted_diff) + offset_frames
            drop_time = librosa.frames_to_time(drop_frame, sr=sr, hop_length=hop_length)
            
            logger.info(f"Probable Drop/Big Transition detected at: {drop_time:.4f}s")
            
            # 4. ALIGN DOWNBEAT TO DROP
            # We find the nearest beat to this drop and treat it as the "Anchor" (Beat 1)
            beat_times = librosa.frames_to_time(beats, sr=sr)
            # Find the beat closest to the detected drop
            anchor_idx = np.argmin(np.abs(beat_times - drop_time))
            anchor_time = beat_times[anchor_idx]
            
            logger.info(f"Aligning grid anchor to drop-adjacent beat at: {anchor_time:.4f}s")
            
            # 5. GENERATE GRID (Backwards and Forwards from Anchor)
            beat_duration = 60.0 / bpm
            grid = []
            
            # Start from anchor and go backwards to find the "start" of the track grid
            start_time = anchor_time
            while start_time > 0:
                start_time -= beat_duration
            start_time += beat_duration # Correction to stay > 0
            
            current_time = start_time
            while current_time < duration:
                # We want the anchor_time to be mapped to a 'Beat 1' (Downbeat)
                # Calculate beat number relative to anchor
                beats_from_anchor = round((current_time - anchor_time) / beat_duration)
                beat_num = (beats_from_anchor % 4) + 1
                
                grid.append({
                    "time": round(float(current_time), 4),
                    "bpm": bpm,
                    "beat": int(beat_num),
                    "metro": "4/4"
                })
                current_time += beat_duration
            
            logger.info(f"Analysis complete for {path}: {len(grid)} beats aligned to drop.")
            return {
                "bpm": round(bpm, 2),
                "beats": grid,
                "totalTime": duration,
                "dropTime": round(float(drop_time), 4)
            }
        except Exception as e:
            logger.error(f"Professional analysis failed for {path}: {str(e)}", exc_info=True)
            raise RuntimeError(f"Audio analysis failed: {str(e)}")

class ImportManager:
    @staticmethod
    def process_import(file_path: Path):
        """Orchestrates analysis and library insertion for a new file."""
        logger.info(f"Processing new import: {file_path}")
        try:
            # 1. Analyze
            analysis = BeatAnalyzer.analyze(str(file_path))

            # 1.5 Extract Cover Art
            artwork_path = ""
            try:
                # Ensure covers dir exists
                COVERS_DIR = Path(REKORDBOX_ROOT).parent / "app" / "data" / "covers"
                COVERS_DIR.mkdir(parents=True, exist_ok=True)
                
                # Check for existing cover to avoid re-extraction logic if hash match (TODO) - for now simple extraction
                has_art = False
                art_data = None
                
                if file_path.suffix.lower() == ".mp3":
                    try:
                        audio = ID3(file_path)
                        for tag in audio.values():
                            if isinstance(tag, APIC):
                                art_data = tag.data
                                break
                    except: pass
                elif file_path.suffix.lower() == ".flac":
                    try:
                        audio = FLAC(file_path)
                        if audio.pictures:
                            art_data = audio.pictures[0].data
                    except: pass
                
                if art_data:
                    # Save with unique name based on file stem
                    bg_name = f"{file_path.stem}_{int(time.time())}.jpg"
                    bg_path = COVERS_DIR / bg_name
                    with open(bg_path, "wb") as f:
                        f.write(art_data)
                    artwork_path = str(bg_path.relative_to(Path(REKORDBOX_ROOT).parent_path if hasattr(Path(REKORDBOX_ROOT), "parent_path") else Path(REKORDBOX_ROOT).parent))
                    # Fix path for frontend: absolute or relative strictly?
                    # Let's use absolute path for internally managed, but relative for portability?
                    # Rekordbox uses absolute. Let's stick to absolute for now to be safe with serving.
                    artwork_path = str(bg_path.resolve())
                    logger.info(f"Extracted artwork to {artwork_path}")
            except Exception as e:
                logger.warning(f"Failed to extract artwork: {e}")
            
            # 2. Prepare track data
            track_data = {
                "Title": file_path.stem,
                "Artist": "New Import",
                "Album": "Imported",
                "BPM": analysis["bpm"],
                "path": str(file_path.absolute()),
                "TotalTime": analysis["totalTime"],
                "beatGrid": analysis["beats"],
                "Artwork": artwork_path,
                "positionMarks": []
            }
            
            # 3. Add to Collection
            tid = db.add_track(track_data)
            logger.info(f"Import successful! Track ID: {tid}")
            
            # 4. Add to "Import" Playlist
            # Case-insensitive search
            import_playlists = [p for p in db.playlists if p['Name'].lower() == "import"]
            
            if not import_playlists:
                logger.info("Creating 'Import' playlist...")
                target_pl = db.create_playlist("Import")
            else:
                # If multiple found, use the first one (or arguably the one with most tracks, but first is stable)
                if len(import_playlists) > 1:
                    logger.warning(f"Found {len(import_playlists)} 'Import' playlists. Using the first one.")
                    # Optional: We could consolidate here, but that might be a heavy operation for an import.
                    # For now, just pick one.
                target_pl = import_playlists[0]
            
            if target_pl:
                pid = target_pl['ID']
                # Check if track is already in playlist to avoid duplicates
                current_tracks = db.get_playlist_tracks(pid)
                if not any(str(t.get('ID') or t.get('id')) == str(tid) for t in current_tracks):
                     if db.add_track_to_playlist(pid, tid):
                         logger.info(f"Added track {tid} to 'Import' playlist ({pid})")
                else:
                     logger.info(f"Track {tid} already in 'Import' playlist.")

            return tid, analysis
        except Exception as e:
            logger.error(f"Import manager failed for {file_path}: {e}", exc_info=True)
            raise

class ProjectManager:
    PROJECTS_DIR = Path("PRJ")

    @staticmethod
    def ensure_dir():
        ProjectManager.PROJECTS_DIR.mkdir(exist_ok=True)

    @staticmethod
    def save_project(name, data):
        ProjectManager.ensure_dir()
        filename = ProjectManager.PROJECTS_DIR / f"{name}.prj"
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            return True
        except Exception as e:
            logger.error(f"Failed to save project {name}: {e}")
            raise e

    @staticmethod
    def load_project(name):
        filename = ProjectManager.PROJECTS_DIR / f"{name}.prj"
        if not filename.exists():
             # Try without extension if passed
             filename = ProjectManager.PROJECTS_DIR / name
             if not filename.exists(): raise FileNotFoundError("Project not found")
        
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load project {name}: {e}")
            raise e

    @staticmethod
    def list_projects():
        ProjectManager.ensure_dir()
        projects = []
        for f in ProjectManager.PROJECTS_DIR.glob("*.prj"):
            projects.append({
                "name": f.stem,
                "updated": os.path.getmtime(f)
            })
        # Sort by newest
        projects.sort(key=lambda x: x['updated'], reverse=True)
        return projects
