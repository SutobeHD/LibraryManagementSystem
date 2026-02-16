from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import os
import shutil
import uvicorn
import urllib.parse
import sys, time, threading, signal
import subprocess
import logging
import traceback
from pathlib import Path
from .services import AudioEngine, FileManager, LibraryTools, SettingsManager, SystemCleaner, XMLProcessor, BeatAnalyzer, ImportManager, ProjectManager
from .database import db
from .config import EXPORT_DIR, LOG_DIR, TEMP_DIR, MUSIC_DIR

# CONFIG LOGGING
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / "app.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("APP_MAIN")

APP_DIR = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(title="Rekordbox Editor Pro")

# --- AUTO-SHUTDOWN MONITOR ---
last_heartbeat = time.time() + 20 # 20s grace period

def monitor_heartbeat():
    global last_heartbeat
    while True:
        time.sleep(2)
        if time.time() - last_heartbeat > 6: # 6s timeout (frontend sends every 2s)
            print("Heartbeat timeout. Shutting down...")
            os.kill(os.getpid(), signal.SIGTERM)

@app.on_event("startup")
def start_monitor():
    threading.Thread(target=monitor_heartbeat, daemon=True).start()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

app.mount("/exports", StaticFiles(directory=EXPORT_DIR), name="exports")

# Artwork Mount
COVERS_DIR = Path(APP_DIR).parent / "app" / "data" / "covers"
COVERS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/api/artwork", StaticFiles(directory=COVERS_DIR), name="artwork")

# --- DATA MODELS ---
class ExportRequest(BaseModel):
    source_path: str
    filename: str
    cuts: List[dict]
    output_name: str
    fade_in: bool = False
    fade_out: bool = False

class BatchReq(BaseModel):
    track_ids: List[str]
    updates: Dict[str, Any]

class TrackUpdateReq(BaseModel):
    Rating: Optional[int] = None
    ColorID: Optional[int] = None
    Comment: Optional[str] = None
    Genre: Optional[str] = None

class MoveReq(BaseModel):
    track_ids: List[str]
    target_folder: str

class RenameReq(BaseModel):
    track_ids: List[str]
    pattern: str

class ScReq(BaseModel):
    artist_name: str
    link: str

class CueReq(BaseModel):
    track_id: str
    cues: List[dict]

class GridReq(BaseModel):
    track_id: str
    beat_grid: List[dict]

class SetReq(BaseModel):
    backup_retention_days: int
    default_export_format: str
    theme: str
    auto_snap: bool
    db_path: str = ""
    artist_view_threshold: int = 0
    waveform_visual_mode: str = "blue"
    hide_streaming: bool = False
    remember_lib_mode: bool = False
    last_lib_mode: str = "xml"

class SmartPlReq(BaseModel):
    artist_threshold: int = 3
    label_threshold: int = 3

class PlCreateReq(BaseModel):
    name: str
    parent_id: str = "ROOT"
    type: str = "1" # 0=folder, 1=playlist

class PlRenameReq(BaseModel):
    pid: str
    name: str

class PlDeleteReq(BaseModel):
    pid: str

class PlMoveReq(BaseModel):
    pid: str
    parent_id: str = "ROOT"
    target_id: Optional[str] = None
    position: Optional[str] = "inside"

class PlRemoveTrackReq(BaseModel):
    pid: str
    track_id: str

class CleanTitlesReq(BaseModel):
    track_ids: List[str]

class DeleteTrackReq(BaseModel):
    track_id: str

class CreatePlReq(BaseModel):
    name: str
    parent_id: str = "ROOT"
    type: str = "1" # 1=Playlist, 0=Folder
    track_ids: List[str] = []

class RenamePlReq(BaseModel):
    pid: str
    name: str

class MovePlReq(BaseModel):
    pid: str
    parent_id: str
    target_id: Optional[str] = None
    position: Optional[str] = "inside"

class DeletePlReq(BaseModel):
    pid: str

class TrackPlReq(BaseModel):
    pid: str
    track_id: str


class MergeReq(BaseModel):
    category: str # "artists", "labels", "albums"
    source_name: str
    target_name: str

class PlCreateReq(BaseModel):
    name: str
    parent_id: str = "ROOT"
    type: str = "1" # 0=Folder, 1=Playlist

class PlRenameReq(BaseModel):
    pid: str
    name: str

class PlDeleteReq(BaseModel):
    pid: str

class PlMoveReq(BaseModel):
    pid: str
    parent_id: str
    target_id: Optional[str] = None
    position: str = "inside"

class PlReorderReq(BaseModel):
    pid: str
    track_id: str
    target_index: int

class PlRemoveTrackReq(BaseModel):
    pid: str
    track_id: str

class ProjectReq(BaseModel):
    name: str
    data: Dict[str, Any]

class DBModeReq(BaseModel):
    mode: str # "xml" or "live"

@app.on_event("startup")
async def startup_check():
    # Auto-load library on startup
    logger.info(f"Auto-loading library in {db.mode} mode...")
    db.load_library()

# --- ENDPOINTS ---

from fastapi import Request

@app.get("/api/stream")
async def stream_audio(path: str, request: Request):
    """Streams audio file from absolute path with RANGE SUPPORT"""
    logger.info(f"Stream request for: {path}")
    # logger.info(f"Headers: {dict(request.headers)}")
    
    file_path = Path(path)
    if not file_path.exists() or not file_path.is_file():
        logger.warning(f"File not found for streaming: {path}")
        raise HTTPException(status_code=404, detail="File not found")
    
    # Basic security check - ensure it looks like an audio file
    ext = file_path.suffix.lower()
    mime_types = {
        '.mp3': 'audio/mpeg',
        '.wav': 'audio/wav',
        '.aiff': 'audio/aiff',
        '.flac': 'audio/flac',
        '.m4a': 'audio/mp4'
    }
    if ext not in mime_types:
        logger.warning(f"Invalid file type for streaming: {ext}")
        raise HTTPException(status_code=400, detail="Invalid file type")

    return FileResponse(
        file_path, 
        media_type=mime_types[ext],
        filename=file_path.name,
        content_disposition_type="inline"
    )

@app.post("/api/xml/clean")
async def clean_xml(
    file: UploadFile = File(...),
    artist_folder: str = Form("_AUTO_ARTISTS"),
    label_folder: str = Form("_AUTO_LABELS")
):
    try:
        # User requested NO auto-optimization. Just save as main XML.
        # But we should keep the uploaded filename or standardize?
        # Let's save to rekordbox.xml in root so it persists.

        target_path = Path("rekordbox.xml")
        with open(target_path, "wb") as f:
             shutil.copyfileobj(file.file, f)
        
        # Reload DB
        db.load_xml(str(target_path))
        
        return {
            "status": "success",
            "message": "XML Uploaded and Scanned",
            "tracks": len(db.tracks),
            "playlists": len(db.playlists)
        } 
    except Exception as e:
        logger.error(f"XML Error: {e}")
        raise HTTPException(400, str(e))

@app.get("/api/genres")
def get_genres(): return db.get_all_genres()

@app.get("/api/library/tracks")
def get_library_tracks():
    try:
        tracks = db.get_all_tracks()
        logger.info(f"Returning {len(tracks)} tracks for library view")
        return tracks
    except Exception as e:
        logger.error(f"Failed to fetch library tracks: {e}")
        return []

@app.get("/api/insights/low_quality")
def get_low_quality_tracks():
    threshold = 320
    try:
        from .services import SettingsManager
        settings = SettingsManager.load()
        threshold = int(settings.get("insights_bitrate_threshold", 320))
    except: pass

    tracks = []
    source = db.tracks.values()
    
    for t in source:
        try:
            # Check Bitrate (Live DB uses 'Bitrate' standardized, previous XML might use 'BitRate')
            br = t.get("Bitrate", t.get("BitRate", 0))
            if int(br) < threshold and int(br) > 0: 
               tracks.append(t)
        except: pass
        
    return tracks

@app.get("/api/insights/no_artwork")
def get_no_artwork_tracks():
    try:
        return db.get_tracks_missing_artwork()
    except Exception as e:
        logger.error(f"Error fetching no-artwork tracks: {e}")
        return []

@app.get("/api/insights/lost")
def get_lost_tracks():
    logger.info("Fetching lost tracks (low play count)...")
    
    threshold = 0
    try:
        from .services import SettingsManager
        settings = SettingsManager.load()
        threshold = int(settings.get("insights_playcount_threshold", 0))
    except: pass
    
    tracks = []
    for t in db.tracks.values():
        try:
            pc = int(t.get("PlayCount", 0))
            if pc <= threshold:
                tracks.append(t)
        except: pass
    return tracks

@app.get("/api/labels")
def get_labels(): return db.get_all_labels()

@app.get("/api/albums")
def get_albums(): return db.get_all_albums()

@app.post("/api/metadata/merge")
def merge_metadata(r: MergeReq):
    try:
        from .services import MetadataManager
        MetadataManager.add_mapping(r.category, r.source_name, r.target_name)
        db.refresh_metadata()
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get("/api/artists")
def get_artists():
    # artists = db.get_all_artists()
    # For XML mode, this might come from cached XML data
    return db.get_all_artists()

@app.get("/api/artist/{aid}/tracks")
def get_artist_tracks(aid: str): return db.get_tracks_by_artist(aid)

@app.get("/api/label/{aid}/tracks")
def get_label_tracks(aid: str): return db.get_tracks_by_label(aid)

@app.get("/api/album/{aid}/tracks")
def get_album_tracks(aid: str): return db.get_tracks_by_album(aid)

@app.get("/api/track/{tid}")
def get_track(tid: str):
    track = db.get_track_details(tid)
    if not track: raise HTTPException(404, "Track not found")
    # Synthesis ArtistName
    res = dict(track)
    res['ArtistName'] = res.get('Artist') or 'Unknown Artist'
    return res

@app.get("/api/track/{tid}/cues")
def get_cues(tid: str): return db.get_track_cues(tid)

@app.get("/api/track/{tid}/beatgrid")
def get_beatgrid(tid: str): return db.get_track_beatgrid(tid)

@app.post("/api/track/{tid}/analyze")
async def analyze_track(tid: str):
    """Analyzes a track to detect BPM and beat grid if missing from XML"""
    track = db.get_track_details(tid)
    if not track:
        raise HTTPException(404, "Track not found")
    
    path = track.get("path")
    if not path or not os.path.exists(path):
        raise HTTPException(404, f"Audio file not found")
    
    try:
        # Perform analysis
        result = BeatAnalyzer.analyze(path)
        
        # PERSIST TO DATABASE IN-MEMORY
        track["BPM"] = result["bpm"]
        track["beatGrid"] = result["beats"]
        track["TotalTime"] = result["totalTime"]
        track["dropTime"] = result["dropTime"]
        
        # Add a "DROP" position mark if not already present
        marks = track.get("positionMarks", [])
        if not any(m.get("name") == "DROP" for m in marks):
            marks.append({
                "name": "DROP",
                "type": 0,
                "start": result["dropTime"],
                "num": -1, # Not a hot cue
                "red": 255, "green": 0, "blue": 0
            })
            track["positionMarks"] = marks
        
        db.save_xml() # Save to XML so it's permanent
        return result
    except Exception as e:
        logger.error(f"Analysis error: {e}")
        raise HTTPException(500, str(e))

@app.post("/api/track/cues/save")
def save_cues(r: CueReq): return {"status": "success" if db.save_track_cues(r.track_id, r.cues) else "error"}

@app.post("/api/track/grid/save")
def save_grid(r: GridReq): return {"status": "success" if db.save_track_beatgrid(r.track_id, r.beat_grid) else "error"}

@app.post("/api/track/{tid}")
def update_track(tid: str, r: TrackUpdateReq):
    updates = {k: v for k, v in r.dict().items() if v is not None}
    if not updates: return {"status": "no_change"}
    try:
        if db.update_tracks_metadata([tid], updates): 
            return {"status": "success"}
        raise HTTPException(500, "Update returned False (unknown error)")
    except Exception as e:
        logger.error(f"Update failed for {tid}: {e}")
        raise HTTPException(500, f"Update failed: {str(e)}")

@app.patch("/api/tracks/batch")
def batch_up(r: BatchReq): return {"status": "success" if db.update_tracks_metadata(r.track_ids, r.updates) else "error"}

@app.post("/api/system/heartbeat")
def system_heartbeat():
    global last_heartbeat
    last_heartbeat = time.time()
    return {"status": "alive"}

@app.post("/api/system/shutdown")
def system_shutdown():
    os.kill(os.getpid(), signal.SIGTERM)
    return {"status": "shutdown"}

@app.post("/api/track/delete")
def del_trk(r: DeleteTrackReq): return {"status": "success" if db.delete_track(r.track_id) else "error"}

@app.post("/api/tracks/move")
def move_t(r: MoveReq):
    # This might need adjustment for XML mode if we edit XML
    return {"moved": 0, "errors": ["Not supported in XML-only mode yet"]}

@app.post("/api/tools/rename")
def ren_t(r: RenameReq): return {"success": [], "errors": ["Not supported in XML-only mode yet"]}

@app.get("/api/playlists/tree")
def get_tree(): 
    tree = db.get_playlist_tree()
    logger.info(f"Fetched playlist tree. Root nodes: {len(tree)}")
    return tree

@app.post("/api/playlists/create")
def create_pl(r: CreatePlReq):
    pid = db.create_playlist(r.name, r.parent_id, r.track_ids, r.type)
    return {"status": "success", "id": pid}

@app.post("/api/playlists/rename")
def rename_pl(r: RenamePlReq): return {"status": "success" if db.rename_playlist(r.pid, r.name) else "error"}

@app.post("/api/playlists/move")
def move_pl(r: MovePlReq): return {"status": "success" if db.move_playlist(r.pid, r.parent_id, r.target_id, r.position) else "error"}

@app.post("/api/playlists/delete")
def delete_pl(r: DeletePlReq): return {"status": "success" if db.delete_playlist(r.pid) else "error"}

@app.post("/api/playlists/add-track")
def add_trk_pl(r: TrackPlReq): return {"status": "success" if db.add_track_to_playlist(r.pid, r.track_id) else "error"}

@app.post("/api/playlists/remove-track")
def remove_track_pl(r: PlRemoveTrackReq):
    try:
        db.remove_track_from_playlist(r.pid, r.track_id)
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Failed to remove track {r.track_id} from PL {r.pid}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/track/{tid}")
def delete_track(tid: str):
    logger.info(f"API Request: Delete track {tid}")
    if db.delete_track(tid):
        return {"status": "success", "tid": tid}
    raise HTTPException(status_code=404, detail="Track not found or could not be deleted")

@app.post("/api/playlists/reorder")
def reorder_pl_track(r: PlReorderReq):
    try:
        if db.reorder_playlist_track(r.pid, r.track_id, r.target_index):
            return {"status": "success"}
        else:
            raise HTTPException(500, "Failed to reorder")
    except Exception as e: raise HTTPException(500, str(e))

# --- RESTORED ENDPOINTS ---

@app.get("/api/tools/duplicates")
def get_dupes(): return LibraryTools.find_duplicates()

class BatchCommentReq(BaseModel):
    source_id: str  # "LIB" or playlist_id
    action: str     # remove, replace, append, set
    find: Optional[str] = ""
    replace: Optional[str] = ""

@app.post("/api/tools/batch-comment")
async def batch_comment(r: BatchCommentReq):
    try:
        import subprocess
        import sys
        import os
        from pathlib import Path
        
        # Manually resolve DB path to avoid touching the global 'db' object
        # which contains thread-unsafe Rust objects.
        live_db_path = Path(os.path.expandvars(r"%APPDATA%\Pioneer\rekordbox\master.db"))
        if not live_db_path.exists():
            live_db_path = Path(os.path.expandvars(r"%APPDATA%\Pioneer\rekordbox6\master.db"))
            
        if not live_db_path.exists():
             raise HTTPException(400, "Could not find Rekordbox master.db")
        
        # Call the worker script
        cmd = [
            sys.executable, 
            os.path.join(APP_DIR, "batch_worker.py"),
            "--db", str(live_db_path),
            "--source", r.source_id,
            "--action", r.action
        ]
        
        if r.find:
            cmd.extend(["--find", r.find])
        if r.replace:
            cmd.extend(["--replace", r.replace])
            
        logger.info(f"Running batch worker: {cmd}")
        
        # Run and capture output
        result = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)
        logger.info(f"Batch worker output: {result}")
        
        # Parse count
        count = 0
        for line in result.split("\n"):
            if line.startswith("COUNT:"):
                count = int(line.split(":")[1])
                
        return {"status": "success", "count": count}

    except subprocess.CalledProcessError as e:
        logger.error(f"Batch worker failed: {e.output}")
        raise HTTPException(500, f"Worker failed: {e.output}")
    except Exception as e:
        logger.error(f"Batch comment error: {e}")
        raise HTTPException(500, str(e))

@app.post("/api/library/clean-titles")
def clean_titles(r: CleanTitlesReq):
    return LibraryTools.clean_track_titles(r.track_ids)

@app.get("/api/library/status")
def get_lib_status():
    return {
        "loaded": db.loaded,
        "mode": db.mode,
        "path": str(db.xml_path) if db.mode == "xml" else str(db.live_db_path),
        "tracks": len(db.active_db.tracks) if db.active_db else 0,
        "playlists": len(db.active_db.playlists) if db.active_db else 0,
        "loading_current_item": getattr(db.active_db, "loading_status", "Idle") if db.active_db else "Idle"
    }

@app.post("/api/library/mode")
def set_lib_mode(r: DBModeReq):
    logger.info(f"Setting library mode to: {r.mode}")
    success = db.set_mode(r.mode)
    if success:
        # Update settings if remember is on
        s = SettingsManager.load()
        if s.get("remember_lib_mode"):
            s["last_lib_mode"] = r.mode
            SettingsManager.save(s)
            
        db.load_library() # Reload in new mode
        logger.info(f"Library reloaded in {r.mode} mode. Tracks: {len(db.tracks)}")
    return {"status": "success" if success else "error", "mode": db.mode}

@app.post("/api/library/backup")
def trigger_backup():
    if db.mode == "live" and db.live_db:
        success = db.live_db._ensure_backup()
        return {"status": "success" if success else "error"}
    return {"status": "error", "message": "Backups only supported in live mode"}

@app.post("/api/library/sync")
def sync_lib():
    """
    Triggered by 'Create Backup' (formerly Sync).
    In Live Mode: Forces a session backup.
    In XML Mode: Saves XML.
    """
    if db.mode == "live" and db.active_db:
        # User explicitly requested a backup
        try:
            db.active_db._ensure_backup()
            return {"status": "success", "message": "Backup created successfully"}
        except Exception as e:
            return {"status": "error", "message": str(e)}
            
    success = db.save()
    return {"status": "success" if success else "error"}

@app.get("/api/library/backups")
def list_backups():
    if db.mode == "live" and db.active_db:
        return db.active_db.get_available_backups()
    return []

class RestoreReq(BaseModel):
    filename: str

@app.post("/api/library/restore")
def restore_backup(r: RestoreReq):
    if db.mode == "live" and db.active_db:
        success, msg = db.active_db.restore_backup(r.filename)
        return {"status": "success" if success else "error", "message": msg}
    return {"status": "error", "message": "Restore only available in Live mode"}

@app.post("/api/library/load")
def load_lib():
    try:
        # success = db.load_library() 
        # Inline logic to avoid potential AttributeError if db.load_library is missing in runtime
        if db.mode == "live":
            success = db.active_db.load()
        else:
            success = db.xml_db.load_xml("rekordbox.xml")
        return {
            "status": "success" if success else "error",
            "message": "Library loaded" if success else "Failed to load library",
            "tracks": len(db.tracks)
        }
    except Exception as e:
        logger.error(f"Failed to load library: {e}")
        with open("last_error.txt", "w") as f:
            f.write(traceback.format_exc())
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}

@app.post("/api/library/unload")
def unload_lib():
    success = db.unload_library()
    return {"status": "success", "message": "Library unloaded."}


@app.post("/api/library/smart-playlists")
def gen_smart(r: SmartPlReq):
    status = LibraryTools.generate_smart_playlists(r.artist_threshold, r.label_threshold)
    return {"status": "success" if status else "error"}

@app.get("/api/artwork")
async def get_artwork(path: str):
    """
    Serves artwork image from absolute path or Rekordbox relative path.
    """
    if not path:
        raise HTTPException(404, "No path provided")
    
    # Try resolving Rekordbox relative paths (e.g. /PIONEER/Artwork/...)
    p_path = path
    if path.startswith("/PIONEER/"):
        app_data = os.environ.get("APPDATA")
        if app_data:
            # Rekordbox 6/7 stores artwork in AppData/Roaming/Pioneer/rekordbox/share
            # The relative path starts with /PIONEER/ which matches inside the share folder.
            rel = path.lstrip("/") # Remove leading slash
            p_path = Path(app_data) / "Pioneer" / "rekordbox" / "share" / rel
            # logger.debug(f"Resolved PIONEER path: {p_path}")
        else:
            logger.warning("APPDATA not found, cannot resolve PIONEER artwork path")

    file_path = Path(p_path)
    if not file_path.exists() or not file_path.is_file():
        # logger.error(f"Artwork NOT found: {file_path}")
        raise HTTPException(404, f"Artwork file not found: {p_path}")
        
    return FileResponse(file_path)

@app.get("/api/library/tracks")
def get_library_tracks():
    logger.info("Fetching all library tracks...")
    if not db.active_db:
        logger.warning("No active DB found for library tracks.")
        return []
    tracks = db.active_db.get_all_tracks()
    logger.info(f"Returning {len(tracks)} tracks from library.")
    return tracks

@app.get("/api/playlist/{pid}/tracks")
def get_ptracks(pid: str): 
    try:
        tracks = []
        raw_tracks = db.get_playlist_tracks(pid)
        logger.info(f"Fetching tracks for playlist {pid}. Found: {len(raw_tracks)}")
        for t in raw_tracks:
            d = dict(t)
            # Fix Artist field for frontend
            d['ArtistName'] = d.get('Artist') or 'Unknown Artist'
            p = Path(d.get('path', ''))
            d['filename'] = urllib.parse.quote(p.name)
            tracks.append(d)
        return tracks
    except Exception as e:
        logger.error(f"Failed to fetch tracks for playlist {pid}: {e}")
        return []

@app.get("/api/artist/{aid}/tracks")
def get_arttracks(aid: str):
    try:
        tracks = []
        raw_tracks = db.get_tracks_by_artist(aid)
        for t in raw_tracks:
            d = dict(t)
            d['ArtistName'] = d.get('Artist') or 'Unknown Artist'
            p = Path(d.get('path', ''))
            d['filename'] = urllib.parse.quote(p.name)
            tracks.append(d)
        return tracks
    except Exception as e:
        logger.error(f"Error fetching artist tracks: {e}")
        return []

@app.get("/api/label/{aid}/tracks")
def get_lbltracks(aid: str):
    try:
        tracks = []
        raw_tracks = db.get_tracks_by_label(aid)
        for t in raw_tracks:
            d = dict(t)
            d['ArtistName'] = d.get('Artist') or 'Unknown Artist'
            p = Path(d.get('path', ''))
            d['filename'] = urllib.parse.quote(p.name)
            tracks.append(d)
        return tracks
    except Exception as e:
        logger.error(f"Error fetching label tracks: {e}")
        return []

@app.get("/api/album/{aid}/tracks")
def get_albtracks(aid: str):
    try:
        tracks = []
        raw_tracks = db.get_tracks_by_album(aid)
        for t in raw_tracks:
            d = dict(t)
            d['ArtistName'] = d.get('Artist') or 'Unknown Artist'
            p = Path(d.get('path', ''))
            d['filename'] = urllib.parse.quote(p.name)
            tracks.append(d)
        return tracks
    except Exception as e:
        logger.error(f"Error fetching album tracks: {e}")
        return []

@app.get("/api/projects")
def list_projects():
    prj_dir = Path("PRJ")
    if not prj_dir.exists():
        return []
    projects = []
    for f in prj_dir.glob("*.prj"):
        projects.append({
            "name": f.stem,
            "path": str(f)
        })
    return projects

@app.post("/api/projects/save")
def save_project(r: ProjectReq):
    try:
        ProjectManager.save_project(r.name, r.data)
        return {"status": "success"}
    except Exception as e: raise HTTPException(500, str(e))

@app.get("/api/projects/{name}")
def load_project_endpoint(name: str):
    try:
        data = ProjectManager.load_project(name)
        return data
    except FileNotFoundError: raise HTTPException(404, "Project not found")
    except Exception as e: raise HTTPException(500, str(e))

@app.post("/api/artist/soundcloud")

@app.post("/api/artist/soundcloud")
def set_sc(r: ScReq): 
    # storage.set_artist_link(r.artist_name, r.link)
    return {"status":"saved"}

class SliceReq(BaseModel):
    source_path: str
    start: float
    end: float

@app.post("/api/audio/slice")
def slice_endpoint(r: SliceReq):
    try:
        # Use absolute path if needed, or ensure services handles it
        path = AudioEngine.slice_audio(r.source_path, r.start, r.end)
        filename = os.path.basename(path)
        return {"filename": filename, "url": f"/exports/{filename}"}
    except Exception as e:
        logger.error(f"Slice endpoint error: {e}")
        raise HTTPException(500, str(e))

@app.post("/api/audio/render")
async def render(r: ExportRequest):
    try:
        # Ensure output name ends with .wav or .mp3
        if not r.output_name.endswith(('.wav', '.mp3')):
            r.output_name += ".wav"
            
        tid = AudioEngine.render_segment(r.source_path, r.cuts, r.output_name, r.fade_in, r.fade_out)
        return {
            "status": "success", 
            "track_id": tid,
            "filename": r.output_name,
            "download_url": f"/exports/{r.output_name}"
        }
    except Exception as e: 
        logger.error(f"Render failed: {e}")
        raise HTTPException(500, str(e))

@app.post("/api/audio/import")
async def import_audio(files: List[UploadFile] = File(...)):
    """Handles batch audio upload, analysis and library insertion."""
    results = []
    for file in files:
        try:
            # 1. Save to MUSIC_DIR
            dest = MUSIC_DIR / file.filename
            # Avoid overwriting if possible or handle conflict
            if dest.exists():
                dest = MUSIC_DIR / f"{file.filename.split('.')[0]}_{int(os.path.getmtime(dest))}.{file.filename.split('.')[-1]}"
            
            with open(dest, "wb") as f:
                shutil.copyfileobj(file.file, f)
            
            # 2. Process (Analyze + Add to DB)
            tid, analysis = ImportManager.process_import(dest)
            results.append({
                "filename": file.filename, 
                "status": "success", 
                "id": tid,
                "bpm": analysis.get("bpm"),
                "totalTime": analysis.get("totalTime")
            })
        except Exception as e:
            logger.error(f"Import failed for {file.filename}: {e}")
            results.append({"filename": file.filename, "status": "error", "message": str(e)})
    return results

@app.get("/api/settings")
def get_s(): 
    s = SettingsManager.load()
    s['active_db_path'] = "XML Mode"
    return s

@app.post("/api/settings")
def save_s(s: SetReq): 
    SettingsManager.save(s.dict())
    db.refresh_metadata()
    return {"status":"saved"}




# --- HEARTBEAT MONITOR ---
last_heartbeat = time.time()
HEARTBEAT_TIMEOUT = 30.0

def monitor_heartbeat():
    global last_heartbeat
    logger.info("Heartbeat monitor started.")
    while True:
        time.sleep(1)
        if time.time() - last_heartbeat > HEARTBEAT_TIMEOUT:
            logger.warning(f"Heartbeat lost (Last: {last_heartbeat}, Now: {time.time()}). Shutting down...")
            os.kill(os.getpid(), signal.SIGTERM)
            break

@app.on_event("startup")
async def startup_event():
    # Heartbeat monitor disabled - not needed for desktop app
    # Backend lifecycle is managed by Tauri (sidecar in prod, Ctrl+C in dev)
    # global last_heartbeat
    # last_heartbeat = time.time() + 60  # Large grace for dev mode (Rust compile is slow)
    # t = threading.Thread(target=monitor_heartbeat, daemon=True)
    # t.start()
    pass

@app.post("/api/system/heartbeat")
def heartbeat():
    global last_heartbeat
    last_heartbeat = time.time()
    return {"status": "alive"}

@app.post("/api/system/shutdown")
async def shutdown():
    import os, signal, threading
    def kill():
        os.kill(os.getpid(), signal.SIGTERM)
    threading.Timer(1.0, kill).start()
    return {"message": "Shutting down..."}

@app.post("/api/system/restart")
async def restart():
    import os, sys, threading
    def restart_proc():
        logger.info("Restarting backend...")
        # Check if running as script or frozen
        if getattr(sys, 'frozen', False):
            os.execv(sys.executable, sys.argv)
        else:
            # Re-execute the current script
            os.execv(sys.executable, [sys.executable] + sys.argv)
    threading.Timer(1.0, restart_proc).start()
    return {"message": "Restarting backend..."}

@app.post("/api/system/cleanup")
def cln(): return {"deleted_files": 0}

@app.post("/api/system/select_db")
def select_db_dialog():
    return {"path": "XML Mode"}

@app.post("/api/library/new")
def create_new_lib():
    db.create_new_library()
    return {"status": "success", "message": "New empty library created."}

@app.post("/api/debug/load_xml")
def debug_load_xml():
    db.load_xml("rekordbox.xml")
    return {"status": "loaded", "tracks": len(db.tracks), "playlists": len(db.playlists)}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
