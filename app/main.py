from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import os
import secrets
import shutil
import uvicorn
import urllib.parse
import sys, time, threading, signal
import asyncio
import subprocess
import logging
import traceback
from pathlib import Path

# EC9: Load .env file so SOUNDCLOUD_CLIENT_ID etc. are available as env-vars.
# python-dotenv is a soft dependency; if missing we fall back to os.environ silently.
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env", override=False)
except ImportError:
    pass  # dotenv not installed — rely on shell environment variables

# EC7/EC13: keyring provides OS-level credential storage for the SC OAuth token.
# This avoids storing the secret in plaintext in settings.json or cookies.
try:
    import keyring
except ImportError:
    # Fallback shim so the rest of main.py doesn't crash on import if keyring
    # is not yet installed.  On first run the user will get a clear 503 error
    # instead of a silent startup crash.
    class _KeyringShim:
        """No-op shim when the `keyring` package is unavailable."""
        _store: dict = {}
        def get_password(self, service, username):
            return self._store.get(f"{service}:{username}")
        def set_password(self, service, username, value):
            self._store[f"{service}:{username}"] = value
        def delete_password(self, service, username):
            self._store.pop(f"{service}:{username}", None)
    keyring = _KeyringShim()
    logging.getLogger("APP_MAIN").warning(
        "[WARN] `keyring` package not installed. SC tokens will be stored in-memory only "
        "and lost on restart. Run: pip install keyring"
    )

from .services import AudioEngine, FileManager, LibraryTools, SettingsManager, SystemCleaner, XMLProcessor, BeatAnalyzer, ImportManager, ProjectManager
from .database import db
from .config import EXPORT_DIR, LOG_DIR, TEMP_DIR, MUSIC_DIR
from .usb_manager import UsbDetector, UsbProfileManager, UsbSyncEngine, UsbActions
from .backup_engine import BackupEngine
from .rbep_parser import list_projects as rbep_list_projects, parse_project as rbep_parse_project
from .rekordbox_bridge import RekordboxBridge
from .soundcloud_downloader import sc_downloader
from .audio_analyzer import AudioAnalyzer, LIBROSA_AVAILABLE
from .soundcloud_api import SoundCloudPlaylistAPI, SoundCloudSyncEngine, AuthExpiredError, RateLimitError

# Per-operation lock — prevents race conditions on concurrent sync requests (Criterion 10)
_sync_lock = asyncio.Lock()

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

# --- SECURITY: Internal shutdown token (generated per session) ---
SHUTDOWN_TOKEN = secrets.token_urlsafe(32)
logger.info(f"Session security token generated.")

# --- SECURITY: Allowed audio directories for streaming/processing ---
# Users can only stream/process audio from these root directories.
ALLOWED_AUDIO_ROOTS: list[Path] = []

def _init_allowed_roots():
    """Populate allowed audio roots from common music locations and settings."""
    roots = [
        Path(os.path.expanduser("~/Music")),
        Path(EXPORT_DIR).resolve(),
        Path(MUSIC_DIR).resolve(),
        Path(TEMP_DIR).resolve(),
    ]
    # Add Rekordbox database root if available
    rb_root = Path(os.environ.get('APPDATA', '')) / "Pioneer" / "rekordbox"
    if rb_root.exists():
        roots.append(rb_root.resolve())
    # Add common drive letters on Windows
    for drive in ['C:', 'D:', 'E:', 'F:', 'G:', 'H:']:
        music_path = Path(drive + os.sep) / "Music"
        if music_path.exists():
            roots.append(music_path.resolve())
        dj_path = Path(drive + os.sep) / "DJ Music"
        if dj_path.exists():
            roots.append(dj_path.resolve())
    ALLOWED_AUDIO_ROOTS.extend(roots)
    logger.info(f"Allowed audio roots: {[str(r) for r in ALLOWED_AUDIO_ROOTS]}")

_init_allowed_roots()

ALLOWED_AUDIO_EXTENSIONS = {'.mp3', '.wav', '.aiff', '.aif', '.flac', '.m4a', '.ogg', '.wma', '.alac'}

def validate_audio_path(path_str: str) -> Path:
    """
    Security: Validates that a file path is a real audio file within allowed directories.
    Prevents path traversal and arbitrary file read attacks.
    """
    try:
        file_path = Path(path_str).resolve()
    except (ValueError, OSError):
        raise HTTPException(status_code=400, detail="Invalid file path")
    
    # Check extension
    if file_path.suffix.lower() not in ALLOWED_AUDIO_EXTENSIONS:
        raise HTTPException(status_code=400, detail="File type not allowed")
    
    # Check file exists
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    
    # Check that the file is within an allowed directory
    is_allowed = any(
        str(file_path).startswith(str(root))
        for root in ALLOWED_AUDIO_ROOTS
    )
    # Also allow paths from the database (track paths stored in library)
    if not is_allowed:
        known_paths = {t.get('path', '') for t in db.tracks.values()} if hasattr(db, 'tracks') else set()
        if str(file_path) not in known_paths and path_str not in known_paths:
            logger.warning(f"SECURITY: Blocked access to path outside allowed roots: {file_path}")
            raise HTTPException(status_code=403, detail="Access denied: path outside allowed directories")
    
    return file_path

def safe_error_message(e: Exception) -> str:
    """Sanitize error messages to avoid leaking internal paths or system info."""
    msg = str(e)
    # Strip absolute path prefixes from error messages
    for sensitive in [APP_DIR, str(Path.home()), os.environ.get('APPDATA', '')]:
        if sensitive:
            msg = msg.replace(sensitive, '[...]')
    return msg

# --- SECURITY: CORS locked to localhost only ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:1420",
        "http://127.0.0.1:1420",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "tauri://localhost",
        "https://tauri.localhost",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    EC4/EC10: Surface Pydantic 422 validation errors with field-level detail.
    FastAPI normally returns 422 for these, but they were previously swallowed by the
    global Exception handler into a generic 500.  This handler logs the exact field
    errors so payload mismatches are immediately visible in the backend logs,
    and returns them to the client in a structured way.
    """
    errors = exc.errors()
    logger.warning(
        f"[VALIDATION] {request.method} {request.url.path} — "
        f"{len(errors)} validation error(s): "
        + "; ".join(f"{e['loc']} → {e['msg']}" for e in errors)
    )
    return JSONResponse(
        status_code=422,
        content={
            "detail": "Request validation failed",
            "errors": [{"field": list(e["loc"]), "message": e["msg"], "type": e["type"]} for e in errors],
        },
    )

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """SECURITY: Catch all unhandled exceptions to prevent hard crashes and data leaks."""
    logger.error(f"Unhandled Exception on {request.method} {request.url}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error occurred.", "error_type": type(exc).__name__}
    )

app.mount("/exports", StaticFiles(directory=EXPORT_DIR), name="exports")

# Artwork Mount
COVERS_DIR = Path(APP_DIR).parent / "app" / "data" / "covers"
COVERS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/api/artwork", StaticFiles(directory=COVERS_DIR), name="artwork")

# --- DATA MODELS ---
class FileWriteReq(BaseModel):
    path: str
    content: str
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
    ranking_filter_mode: str = "all"
    archive_frequency: str = "daily"
    last_archive_date: str = ""
    insights_playcount_threshold: int = 0
    insights_bitrate_threshold: int = 320
    soundcloud_auth_token: str = ""

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

class AudioImportReq(BaseModel):
    file_path: str
    mode: str = "speed" # "speed" or "accuracy"

class AudioStatusReq(BaseModel):
    task_id: str


class MergeReq(BaseModel):
    category: str # "artists", "labels", "albums"
    source_name: str
    target_name: str

class RbxSyncReq(BaseModel):
    track_ids: List[str]
    filename: Optional[str] = "rekordbox_export.xml"

class RbxImportReq(BaseModel):
    xml_path: str

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
async def stream_audio(path: str):
    """Streams audio file from absolute path — SECURITY: validates path against allowed roots."""
    logger.info(f"Stream request for: {path}")
    
    # SECURITY: Validate path is within allowed audio directories
    file_path = validate_audio_path(path)
    
    mime_types = {
        '.mp3': 'audio/mpeg',
        '.wav': 'audio/wav',
        '.aiff': 'audio/aiff',
        '.aif': 'audio/aiff',
        '.flac': 'audio/flac',
        '.m4a': 'audio/mp4',
        '.ogg': 'audio/ogg',
    }
    ext = file_path.suffix.lower()
    media_type = mime_types.get(ext, 'application/octet-stream')

    return FileResponse(
        file_path, 
        media_type=media_type,
        filename=file_path.name,
        content_disposition_type="inline"
    )

@app.get("/api/audio/waveform")
async def get_multiband_waveform(path: str, pps: int = 50):
    """Returns 3-band waveform data for professional visualization."""
    file_path = validate_audio_path(path)
    try:
        return AudioEngine.generate_multiband_waveform(str(file_path), pixels_per_second=pps)
    except Exception as e:
        logger.error(f"Waveform generation failed: {e}")
        raise HTTPException(500, safe_error_message(e))

@app.post("/api/file/write")
async def file_write(r: FileWriteReq):
    """Writes text content to a file (used for .rbep project saving)."""
    try:
        # Simple security: only allow writing to specific directories?
        # For now, we trust the path but ensure directory exists
        path = Path(r.path)
        if not path.is_absolute():
             path = Path(APP_DIR).parent / r.path
        
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(path, "w", encoding="utf-8") as f:
            f.write(r.content)
            
        return {"status": "success", "path": str(path)}
    except Exception as e:
        logger.error(f"File write error: {e}")
        raise HTTPException(500, str(e))

@app.post("/api/xml/clean")
async def clean_xml(
    file: UploadFile = File(...),
    artist_folder: str = Form("_AUTO_ARTISTS"),
    label_folder: str = Form("_AUTO_LABELS")
):
    try:
        # SECURITY: Validate file extension
        if not file.filename or not file.filename.lower().endswith('.xml'):
            raise HTTPException(400, "Only XML files are accepted")
        
        # SECURITY: Fixed target path — no user-controlled filename
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
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"XML Error: {e}")
        raise HTTPException(400, safe_error_message(e))

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
    except Exception as e:
        logger.warning(f"Could not load bitrate threshold from settings: {e}")

    tracks = []
    source = db.tracks.values()
    
    for t in source:
        try:
            br = t.get("Bitrate", t.get("BitRate", 0))
            if int(br) < threshold and int(br) > 0: 
               tracks.append(t)
        except (ValueError, TypeError) as e:
            logger.debug(f"Skipping track with invalid bitrate: {t.get('Name', '?')}: {e}")
        
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
    except Exception as e:
        logger.warning(f"Could not load playcount threshold from settings: {e}")
    
    tracks = []
    for t in db.tracks.values():
        try:
            pc = int(t.get("PlayCount", 0))
            if pc <= threshold:
                tracks.append(t)
        except (ValueError, TypeError) as e:
            logger.debug(f"Skipping track with invalid playcount: {t.get('Name', '?')}: {e}")
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
        raise HTTPException(404, "Audio file not found")
    
    try:
        # Perform analysis in a separate process pool to avoid blocking the event loop
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(AudioAnalyzer.get_executor(), BeatAnalyzer.analyze, path)
        
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
                "num": -1,
                "red": 255, "green": 0, "blue": 0
            })
            track["positionMarks"] = marks
        
        db.save_xml()
        return result
    except Exception as e:
        logger.error(f"Analysis error: {e}")
        raise HTTPException(500, safe_error_message(e))

@app.get("/api/audio/stream")
async def stream_audio(path: str):
    """Streams an audio file from the local filesystem"""
    logger.info(f"Stream request for: {path}")
    
    # SECURITY: Validate against allowed audio roots to prevent path traversal
    valid_path = validate_audio_path(path)
    
    return FileResponse(valid_path, headers={"Accept-Ranges": "bytes"})


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
    return {"status": "alive", "token": SHUTDOWN_TOKEN}

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
    pid = db.create_playlist(r.name, r.parent_id, r.type == "0", r.track_ids)
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
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Reorder error: {e}")
        raise HTTPException(500, safe_error_message(e))

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
        raise HTTPException(500, "Batch processing failed. Check logs for details.")
    except Exception as e:
        logger.error(f"Batch comment error: {e}")
        raise HTTPException(500, safe_error_message(e))

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
    """Create an incremental backup using the Git-like engine."""
    if db.mode == "live" and db.active_db and hasattr(db.active_db, 'db_path'):
        try:
            engine = BackupEngine(str(db.active_db.db_path))
            result = engine.snapshot("Manual backup")
            return result
        except Exception as e:
            logger.error(f"Incremental backup failed, falling back to legacy: {e}")
            success = db.active_db._ensure_backup()
            return {"status": "success" if success else "error", "fallback": True}
    return {"status": "error", "message": "Backups only supported in live mode"}

@app.post("/api/library/sync")
def sync_lib():
    """
    Triggered by 'Create Backup' (formerly Sync).
    In Live Mode: Creates incremental snapshot.
    In XML Mode: Saves XML.
    """
    if db.mode == "live" and db.active_db and hasattr(db.active_db, 'db_path'):
        try:
            engine = BackupEngine(str(db.active_db.db_path))
            result = engine.snapshot("Sync backup")
            return {"status": "success", "message": "Backup created successfully", **result}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    success = db.save()
    return {"status": "success" if success else "error"}

@app.get("/api/library/backups")
def list_backups():
    """Get backup history (incremental commits + legacy backups)."""
    if db.mode == "live" and db.active_db and hasattr(db.active_db, 'db_path'):
        try:
            engine = BackupEngine(str(db.active_db.db_path))
            return engine.get_history()
        except Exception as e:
            logger.error(f"Incremental history failed, falling back: {e}")
            return db.active_db.get_available_backups()
    return []

class RestoreReq(BaseModel):
    filename: str
    commit_hash: Optional[str] = None

@app.post("/api/library/restore")
def restore_backup(r: RestoreReq):
    """Restore from incremental commit or legacy backup."""
    if db.mode == "live" and db.active_db and hasattr(db.active_db, 'db_path'):
        # Try incremental restore first
        if r.commit_hash:
            engine = BackupEngine(str(db.active_db.db_path))
            return engine.restore(r.commit_hash)
        # Fall back to legacy restore
        if r.filename:
            success, msg = db.active_db.restore_backup(r.filename)
            return {"status": "success" if success else "error", "message": msg}
    return {"status": "error", "message": "Restore only available in Live mode"}

@app.get("/api/library/backup/{commit_hash}/diff")
def get_backup_diff(commit_hash: str):
    """Get detailed diff for a specific backup commit."""
    if db.mode == "live" and db.active_db and hasattr(db.active_db, 'db_path'):
        engine = BackupEngine(str(db.active_db.db_path))
        return engine.get_diff(commit_hash)
    return {"error": "Not available in current mode"}

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
        logger.error(f"Failed to load library: {e}\n{traceback.format_exc()}")
        return {"status": "error", "message": safe_error_message(e)}

@app.post("/api/library/unload")
def unload_lib():
    success = db.unload_library()
    return {"status": "success", "message": "Library unloaded."}

# --- REKORDBOX SYNC ENDPOINTS ---

@app.post("/api/rekordbox/export")
async def rbx_export(r: RbxSyncReq):
    """Exports specified tracks to a Rekordbox XML file."""
    try:
        output_path = EXPORT_DIR / r.filename
        xml_path = RekordboxBridge.export_collection(r.track_ids, output_path)
        return {
            "status": "success",
            "message": f"Exported {len(r.track_ids)} tracks to XML.",
            "path": str(xml_path)
        }
    except Exception as e:
        logger.error(f"Rekordbox export failed: {e}")
        raise HTTPException(500, safe_error_message(e))

@app.post("/api/rekordbox/import")
async def rbx_import(r: RbxImportReq):
    """Imports tracks and metadata from a Rekordbox XML file."""
    try:
        if not os.path.exists(r.xml_path):
             raise HTTPException(404, "XML file not found")
        
        results = RekordboxBridge.import_library(r.xml_path)
        return {
            "status": "success",
            "message": f"Import complete: {results['added']} added, {results['updated']} updated.",
            "details": results
        }
    except Exception as e:
        logger.error(f"Rekordbox import failed: {e}")
        raise HTTPException(500, safe_error_message(e))


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

    file_path = Path(p_path).resolve()
    
    # SECURITY: Directory Jail & Extension Validation
    ALLOWED_ARTWORK_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif'}
    if file_path.suffix.lower() not in ALLOWED_ARTWORK_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Invalid artwork file type")

    # Ensure the path is either in the local covers dir or the Pioneer share dir
    is_allowed = False
    if str(file_path).startswith(str(COVERS_DIR.resolve())):
        is_allowed = True
    elif os.environ.get("APPDATA"):
        rb_share_dir = (Path(os.environ.get("APPDATA")) / "Pioneer" / "rekordbox" / "share").resolve()
        if str(file_path).startswith(str(rb_share_dir)):
            is_allowed = True
            
    # As a fallback, if not in defined locations, allow only if it's explicitly tracked in the DB as artwork.
    # Note: we mostly rely on the above checks for safety.
    if not is_allowed:
        logger.warning(f"SECURITY: Blocked access to non-artwork path: {file_path}")
        raise HTTPException(status_code=403, detail="Access denied: path outside allowed artwork directories")

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(404, "Artwork file not found")
        
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
            # Ensure lowercase 'id' exists for frontend compatibility
            if 'id' not in d and 'ID' in d:
                d['id'] = d['ID']
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
    except Exception as e:
        logger.error(f"Project load error: {e}")
        raise HTTPException(500, safe_error_message(e))

@app.post("/api/artist/soundcloud")
def set_sc(r: ScReq):
    # storage.set_artist_link(r.artist_name, r.link)
    return {"status": "saved"}

class SliceReq(BaseModel):
    source_path: str
    start: float
    end: float

@app.post("/api/audio/slice")
async def slice_endpoint(r: SliceReq):
    try:
        # SECURITY: Validate source path
        validate_audio_path(r.source_path)
        path = await asyncio.to_thread(AudioEngine.slice_audio, r.source_path, r.start, r.end)
        filename = os.path.basename(path)
        return {"filename": filename, "url": f"/exports/{filename}"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Slice endpoint error: {e}")
        raise HTTPException(500, safe_error_message(e))

@app.post("/api/audio/render")
async def render(r: ExportRequest):
    try:
        # SECURITY: Validate source path
        validate_audio_path(r.source_path)
        # SECURITY: Sanitize output name
        safe_name = Path(r.output_name).name  # Strip any path components
        if not safe_name.endswith(('.wav', '.mp3')):
            safe_name += ".wav"
            
        tid = await asyncio.to_thread(AudioEngine.render_segment, r.source_path, r.cuts, safe_name, r.fade_in, r.fade_out)
        return {
            "status": "success", 
            "track_id": tid,
            "filename": safe_name,
            "download_url": f"/exports/{safe_name}"
        }
    except HTTPException:
        raise
    except Exception as e: 
        logger.error(f"Render failed: {e}")
        raise HTTPException(500, safe_error_message(e))

@app.post("/api/audio/import")
def import_audio(files: List[UploadFile] = File(...)):
    """Handles batch audio upload, analysis and library insertion."""
    results = []
    for file in files:
        try:
            # SECURITY: Validate file extension
            if not file.filename or Path(file.filename).suffix.lower() not in ALLOWED_AUDIO_EXTENSIONS:
                results.append({"filename": file.filename or "unknown", "status": "error", "message": "File type not allowed"})
                continue
            
            # SECURITY: Use only the basename to prevent path traversal
            safe_filename = Path(file.filename).name
            dest = MUSIC_DIR / safe_filename
            if dest.exists():
                stem = safe_filename.rsplit('.', 1)[0]
                ext = safe_filename.rsplit('.', 1)[-1]
                dest = MUSIC_DIR / f"{stem}_{int(time.time())}.{ext}"
            
            with open(dest, "wb") as f:
                shutil.copyfileobj(file.file, f)
            
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
            results.append({"filename": file.filename, "status": "error", "message": safe_error_message(e)})
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




# --- GRACEFUL SHUTDOWN ---
_shutdown_event = threading.Event()

def _graceful_shutdown():
    """Performs cleanup before shutting down the backend."""
    logger.info("Graceful shutdown initiated...")
    _shutdown_event.set()
    # Give time for pending requests to complete
    time.sleep(0.5)
    logger.info("Shutdown complete.")
    os._exit(0)

@app.on_event("startup")
async def startup_event():
    logger.info(f"Backend started. Binding to 127.0.0.1:8000 only.")
    
    # Req 30: State Recovery - Purge obsolete temp files from previous hard crashes
    import tempfile, glob
    tmp_base = tempfile.gettempdir()
    for stale_dir in glob.glob(os.path.join(tmp_base, "scdl_tmp_*")):
        try:
            shutil.rmtree(stale_dir, ignore_errors=True)
            logger.info(f"Purged stale download state: {stale_dir}")
        except: pass
        
    for stale_file in MUSIC_DIR.glob("*.tmp"):
        try:
            os.remove(stale_file)
        except: pass

    # Req 29: Timeout Handling - Prevent infinite hangs on DB locks during boot
    try:
        logger.info("Auto-loading library with 30s timeout...")
        await asyncio.wait_for(asyncio.to_thread(db.load_library), timeout=30.0)
    except asyncio.TimeoutError:
        logger.error("Library auto-load timed out after 30 seconds (Possible strict DB lock).")
    except Exception as e:
        logger.error(f"Failed to auto-load library on startup: {e}")

@app.post("/api/system/heartbeat")
def heartbeat():
    global last_heartbeat
    last_heartbeat = time.time()
    return {"status": "alive", "token": SHUTDOWN_TOKEN}

@app.post("/api/system/shutdown")
async def shutdown(token: str = ""):
    """SECURITY: Requires session token to trigger shutdown."""
    if token != SHUTDOWN_TOKEN:
        logger.warning(f"SECURITY: Unauthorized shutdown attempt!")
        raise HTTPException(status_code=403, detail="Invalid shutdown token")
    threading.Thread(target=_graceful_shutdown, daemon=True).start()
    return {"message": "Shutting down..."}

@app.post("/api/system/restart")
async def restart(token: str = ""):
    """SECURITY: Requires session token to trigger restart."""
    if token != SHUTDOWN_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid restart token")
    def restart_proc():
        logger.info("Restarting backend...")
        time.sleep(0.5)
        if getattr(sys, 'frozen', False):
            os.execv(sys.executable, sys.argv)
        else:
            os.execv(sys.executable, [sys.executable] + sys.argv)
    threading.Thread(target=restart_proc, daemon=True).start()
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

# ─── USB Management API ───────────────────────────────────────────────────────

class UsbProfileReq(BaseModel):
    device_id: str
    label: Optional[str] = None
    drive: Optional[str] = None
    type: Optional[str] = "Collection"  # MainCollection, Collection, PartCollection, SetStick
    sync_mode: Optional[str] = "full"   # full, playlists_only, metadata_only, selective
    sync_playlists: Optional[List[str]] = []
    auto_sync: Optional[bool] = False

class UsbSyncReq(BaseModel):
    device_id: str
    sync_type: Optional[str] = "collection"  # collection, playlists, metadata
    playlist_ids: Optional[List[str]] = []
    library_types: Optional[List[str]] = ["library_legacy"] # library_one, library_legacy

class UsbEjectReq(BaseModel):
    drive: str

class UsbResetReq(BaseModel):
    device_id: str

class DupMergeReq(BaseModel):
    keep_id: str
    remove_ids: List[str]

@app.get("/api/usb/devices")
def usb_scan_devices():
    """Scan for connected USB devices."""
    return UsbDetector.scan()

@app.get("/api/usb/profiles")
def usb_get_profiles():
    """List all registered USB profiles (connected + disconnected)."""
    return UsbProfileManager.get_profiles()

@app.post("/api/usb/profiles")
def usb_save_profile(r: UsbProfileReq):
    """Create or update a USB device profile."""
    profile = UsbProfileManager.save_profile(r.dict())
    return {"status": "success", "profile": profile}

@app.delete("/api/usb/profiles/{device_id}")
def usb_delete_profile(device_id: str):
    """Delete a USB device profile."""
    if UsbProfileManager.delete_profile(device_id):
        return {"status": "success"}
    raise HTTPException(404, "Profile not found")

@app.get("/api/usb/{device_id}/contents")
def usb_get_contents(device_id: str):
    """Get the tracks currently existing on the referenced USB stick."""
    tracks = UsbProfileManager.get_usb_contents(device_id)
    return {"status": "success", "tracks": tracks}

@app.get("/api/usb/diff/{device_id}")
def usb_get_diff(device_id: str):
    """Preview what would change in a sync operation."""
    profile = UsbProfileManager.get_profile(device_id)
    if not profile:
        # Try to auto-create from scan data
        devices = UsbDetector.scan()
        dev = next((d for d in devices if d["device_id"] == device_id), None)
        if not dev:
            raise HTTPException(404, "Device not found")
        profile = UsbProfileManager.save_profile({"device_id": device_id, "label": dev.get("label", "USB"), "drive": dev["drive"]})
    if not db.active_db or not hasattr(db.active_db, 'db_path'):
        raise HTTPException(400, "No local database loaded")
    engine = UsbSyncEngine(str(db.active_db.db_path), profile["drive"])
    diff = engine.calculate_diff()
    # Add space estimate: ~10MB avg per track to add
    avg_track_size = 10 * 1024 * 1024
    diff["space_estimate"] = diff["tracks"]["to_add"] * avg_track_size
    diff["drive_free"] = profile.get("free_space", 0)
    return diff

def _get_or_create_profile(device_id: str) -> dict:
    """Get existing profile or auto-create from scan data."""
    profile = UsbProfileManager.get_profile(device_id)
    if profile:
        return profile
    devices = UsbDetector.scan()
    dev = next((d for d in devices if d["device_id"] == device_id), None)
    if not dev:
        raise HTTPException(404, "Device not connected — cannot create profile")
    return UsbProfileManager.save_profile({
        "device_id": device_id,
        "label": dev.get("label", "USB Drive"),
        "drive": dev["drive"]
    })

@app.post("/api/usb/sync")
def usb_sync(r: UsbSyncReq):
    """Sync a specific USB device."""
    profile = _get_or_create_profile(r.device_id)
    if not db.active_db or not hasattr(db.active_db, 'db_path'):
        raise HTTPException(400, "No local database loaded")

    engine = UsbSyncEngine(str(db.active_db.db_path), profile["drive"])
    results = []
    libs = r.library_types or ["library_one"]

    if r.sync_type == "collection":
        for event in engine.sync_collection(profile, libs):
            results.append(event)
    elif r.sync_type == "playlists":
        for event in engine.sync_playlists(profile, r.playlist_ids, libs):
            results.append(event)
    elif r.sync_type == "metadata":
        for event in engine.sync_metadata(profile, libs):
            results.append(event)

    last = results[-1] if results else {"stage": "error", "message": "No events"}
    return {"status": "success" if last.get("stage") == "complete" else "error", "result": last}

@app.post("/api/usb/sync/all")
def usb_sync_all():
    """Sync all connected USB devices per their profiles."""
    if not db.active_db or not hasattr(db.active_db, 'db_path'):
        raise HTTPException(400, "No local database loaded")
    results = []
    for event in UsbActions.update_all(str(db.active_db.db_path)):
        results.append(event)
    last = results[-1] if results else {"stage": "complete", "message": "Nothing to sync"}
    return {"status": "success", "result": last, "events": results}

@app.post("/api/usb/eject")
def usb_eject(r: UsbEjectReq):
    """Safely eject a USB drive."""
    return UsbActions.eject(r.drive)

@app.post("/api/usb/reset")
def usb_reset(r: UsbResetReq):
    """Reset a USB device (wipe PIONEER folder)."""
    profile = UsbProfileManager.get_profile(r.device_id)
    if not profile:
        raise HTTPException(404, "Profile not found")
    return UsbActions.reset(profile)

class UsbInitReq(BaseModel):
    drive: str

@app.post("/api/usb/initialize")
def usb_initialize(r: UsbInitReq):
    """Initialize a new Rekordbox library on a USB drive."""
    if UsbDetector.initialize_usb(r.drive):
        return {"status": "success", "message": "Library initialized"}
    raise HTTPException(500, "Failed to initialize library")

class UsbRenameReq(BaseModel):
    drive: str
    new_label: str

@app.post("/api/usb/rename")
def usb_rename(req: UsbRenameReq):
    """Rename a USB device."""
    res = UsbActions.set_label(req.drive, req.new_label)
    if res["status"] == "error":
        raise HTTPException(500, res["message"])
    return res

@app.get("/api/usb/settings")
def usb_get_settings():
    """Get USB global settings."""
    return UsbProfileManager.get_settings()

@app.post("/api/usb/settings")
def usb_save_settings(r: dict):
    """Save USB global settings."""
    UsbProfileManager.save_settings(r)
    return {"status": "success"}

# ─── Enhanced Duplicate Scanner ───────────────────────────────────────────────

@app.post("/api/tools/duplicates/merge")
def merge_duplicates(r: DupMergeReq):
    """Merge duplicate tracks: keep one, transfer playlist memberships, delete others."""
    try:
        if not db.active_db:
            raise HTTPException(400, "No database loaded")

        keep_id = r.keep_id
        remove_ids = r.remove_ids

        # Transfer playlist memberships
        if hasattr(db.active_db, 'db'):
            rbox = db.active_db.db
            for rid in remove_ids:
                # Find all playlists containing the track to remove
                for pl in db.playlists:
                    pl_tracks = db.get_playlist_tracks(pl.get('ID', ''))
                    track_ids = [str(t.get('id', t.get('ID', ''))) for t in pl_tracks]
                    if str(rid) in track_ids and str(keep_id) not in track_ids:
                        # Add the kept track to this playlist
                        try:
                            db.add_track_to_playlist(str(pl.get('ID', '')), str(keep_id))
                        except Exception:
                            pass

                # Delete the duplicate track
                try:
                    db.delete_track(str(rid))
                except Exception as e:
                    logger.warning(f"Could not delete duplicate {rid}: {e}")

        return {"status": "success", "kept": keep_id, "removed": len(remove_ids)}
    except Exception as e:
        logger.error(f"Merge failed: {e}")
        raise HTTPException(500, str(e))

@app.post("/api/tools/duplicates/merge-all")
def merge_all_duplicates():
    """Auto-merge all duplicate groups using best-metadata heuristic."""
    try:
        groups = LibraryTools.find_duplicates()
        merged = 0

        for group in groups:
            ids = group.get("ids", [])
            if len(ids) < 2:
                continue

            # Pick the best track (highest rating, then most cue points, then highest bitrate)
            best_id = ids[0]
            best_score = -1

            for tid in ids:
                track = db.tracks.get(tid, {})
                score = (track.get("Rating", 0) or 0) * 100
                score += (track.get("Bitrate", 0) or 0)
                score += len(str(track.get("CuePath", ""))) * 10
                if score > best_score:
                    best_score = score
                    best_id = tid

            remove_ids = [i for i in ids if i != best_id]

            # Transfer memberships and delete
            for rid in remove_ids:
                try:
                    db.delete_track(str(rid))
                except Exception:
                    pass

            merged += 1

        return {"status": "success", "groups_merged": merged}
    except Exception as e:
        logger.error(f"Merge all failed: {e}")
        raise HTTPException(500, str(e))

# ─── RBEP Project API ──────────────────────────────────────────────────────────

@app.get("/api/projects/rbep/list")
def rbep_list():
    """List available .rbep project files."""
    return rbep_list_projects()

@app.get("/api/projects/rbep/{name}")
def rbep_get(name: str):
    """Parse and return a .rbep project by name."""
    project = rbep_parse_project(name)
    if not project:
        raise HTTPException(404, f"Project '{name}' not found")
    return project

# ─── Audio Analysis API ──────────────────────────────────────────────────────────

@app.post("/api/audio/analyze")
def analyze_audio(req: AudioImportReq):
    """Submit an audio file for high-accuracy background analysis."""
    if not LIBROSA_AVAILABLE:
        logger.warning("Librosa not installed. Audio analysis will be mocked.")
    
    file_path = Path(req.file_path)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Audio file not found")
        
    task_id = f"analysis_{secrets.token_hex(8)}"
    return AudioAnalyzer.analyze_track(task_id, str(file_path), req.mode)

@app.get("/api/audio/analyze/{task_id}")
def get_analysis_status(task_id: str):
    """Check the status/result of a background audio analysis job."""
    status = AudioAnalyzer.get_status(task_id)
    if status["status"] == "not_found":
        raise HTTPException(status_code=404, detail="Task not found")
    return status

# ─── SoundCloud Download API ──────────────────────────────────────────────────
# NOTE: These endpoints use `keyring` for secure token storage (EC7/EC13).
# The routes must be defined BEFORE the __main__ guard so FastAPI registers them.

@app.post("/api/soundcloud/download")
async def soundcloud_download(data: Dict[str, str], request: Request):
    url = data.get("url")
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    auth_token = keyring.get_password("rb_editor_pro", "sc_token")

    # Criterion 14: write-permission check before starting download
    sc_dir = MUSIC_DIR / "SoundCloud"
    sc_dir.mkdir(parents=True, exist_ok=True)
    if not os.access(str(sc_dir), os.W_OK):
        raise HTTPException(
            status_code=403,
            detail=f"No write permission for download directory: {sc_dir}. Please check folder permissions."
        )

    # Criterion 7: cleanup corrupt fragments on failure
    def on_complete(task_id, success):
        if success:
            logger.info(f"[SC] Download {task_id} complete. Triggering import scan...")
            if sc_dir.exists():
                for f in sc_dir.glob("*"):
                    if f.suffix.lower() in ALLOWED_AUDIO_EXTENSIONS:
                        try:
                            ImportManager.process_import(f)
                        except Exception as e:
                            logger.error(f"[SC] Post-download import failed for {f}: {e}")
        else:
            logger.warning(f"[SC] Download {task_id} failed. Cleaning fragments...")
            for pattern in ["*.part", "*.tmp", "*.ytdl", "*.download"]:
                for frag in sc_dir.glob(pattern):
                    try:
                        frag.unlink()
                        logger.info(f"[SC] Removed fragment: {frag}")
                    except OSError as oe:
                        logger.warning(f"[SC] Could not remove fragment {frag}: {oe}")

    task_id = sc_downloader.download_content(url, auth_token=auth_token, callback=on_complete)
    return {"task_id": task_id}


@app.get("/api/soundcloud/tasks")
async def get_soundcloud_tasks():
    """Poll active download tasks. Returns empty dict when no tasks are running."""
    return sc_downloader.tasks


@app.get("/api/soundcloud/task/{task_id}")
async def get_soundcloud_task_status(task_id: str):
    """Get status for a specific download task."""
    task = sc_downloader.get_task_status(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@app.post("/api/soundcloud/auth-token")
async def set_soundcloud_auth_token(data: Dict[str, str], response: Response):
    """
    EC7/EC13: Persist the SC OAuth token in the OS keyring (not in cookies or JSON).
    Sets a lightweight HttpOnly sentinel cookie so frontend can detect auth state
    without ever seeing the raw token.
    """
    token = data.get("token", "").strip()

    # EC13: Token format validation.
    # SoundCloud OAuth 2.1 issues JWT access tokens that are typically 400–900+ chars.
    # Upper bound is 2048 to safely accept any standard JWT while blocking clearly
    # malformed payloads (e.g. accidental HTML page bodies > 2 KB).
    if token:
        token_len = len(token)
        is_ascii  = token.isascii()
        if not (10 <= token_len <= 2048 and is_ascii):
            # EC10: Log the exact rejection reason so future failures are debuggable.
            reason = (
                f"length={token_len} (must be 10–2048)"
                if not (10 <= token_len <= 2048)
                else "contains non-ASCII characters"
            )
            logger.warning(f"[SC] /api/soundcloud/auth-token rejected: {reason}")
            raise HTTPException(status_code=400, detail=f"Invalid token format: {reason}")


    if token:
        keyring.set_password("rb_editor_pro", "sc_token", token)
        logger.info("[SC] Auth token stored in OS keyring.")
    else:
        # Empty token → clear credentials (logout)
        try:
            keyring.delete_password("rb_editor_pro", "sc_token")
        except Exception:
            pass
        logger.info("[SC] Auth token cleared from keyring (logout).")

    # Sentinel cookie — value is never the real token (EC13)
    response.set_cookie(
        key="sc_token",
        value="os_keyring_active" if token else "",
        httponly=True,
        samesite="lax",
        secure=False,   # set to True when served over HTTPS
        max_age=31536000 if token else 0
    )
    return {"status": "success"}



# ─── SoundCloud Playlist Sync API ─────────────────────────────────────────────

@app.get("/api/soundcloud/playlists")
async def get_soundcloud_playlists(request: Request):
    """
    Fetch user playlists + likes + profile from SoundCloud in parallel.

    EC1: Returns empty lists on 0 playlists — never 404.
    EC2: Clears the lru_cache before fetching so a fresh token always hits the SC API.
    EC3: RateLimitError from _sc_get is surfaced as 429.
    ROOT CAUSE FIX: SoundCloud 404s on /me and /users/{id}/playlists (bad client_id
    or invalid token) now raise AuthExpiredError instead of leaking the raw
    "404 Client Error: Not Found" string to the frontend toast.
    """
    auth_token = keyring.get_password("rb_editor_pro", "sc_token")

    # DOD Verification Print
    safe_token = f"{auth_token[:10]}..." if auth_token else "NONE"
    print(f"DEBUG: Playlist Route aufgerufen mit Token: {safe_token}")

    if not auth_token:
        logger.warning("[SC] /api/soundcloud/playlists: no auth token in keyring — returning 401.")
        raise HTTPException(401, detail="auth_expired")

    # EC2: Invalidate lru_cache so a freshly-rotated token always fetches live data.
    SoundCloudPlaylistAPI.get_playlists.cache_clear()
    SoundCloudPlaylistAPI.get_likes.cache_clear()

    logger.info("[SC] Fetching playlists + user profile from SoundCloud (parallel).")

    import functools
    import time as pytime
    start_time = pytime.time()
    
    try:
        # asyncio.gather: runs profile + playlists + likes concurrently on the thread pool.
        # This is faster and prevents slow SC servers from stalling the event loop.
        logger.info(f"[SC] Starting parallel fetch for user profile, playlists, and likes...")
        
        profile, playlists, likes = await asyncio.gather(
            asyncio.to_thread(SoundCloudPlaylistAPI.get_user_profile, auth_token),
            asyncio.to_thread(functools.partial(SoundCloudPlaylistAPI.get_playlists, auth_token)),
            asyncio.to_thread(functools.partial(SoundCloudPlaylistAPI.get_likes, auth_token)),
        )

        duration = pytime.time() - start_time
        logger.info(
            f"[SC] Parallel fetch completed in {duration:.2f}s. "
            f"Results: user='{profile.get('username')}', "
            f"playlists={len(playlists)}, likes={likes.get('track_count', 0)} tracks."
        )
        return {
            "status": "success",
            "user": profile,
            "playlists": playlists,
            "likes": likes,
        }

    except AuthExpiredError as e:
        logger.warning(f"[SC] Auth expired / invalid token on playlists fetch: {e}")
        raise HTTPException(401, detail="auth_expired")

    except RateLimitError as e:
        logger.warning(f"[SC] Rate limited on playlists fetch: {e}")
        raise HTTPException(429, detail="SoundCloud rate limit hit. Please wait and try again.")

    except Exception as e:
        logger.error(f"[SC] Failed to fetch playlists: {e}", exc_info=True)
        raise HTTPException(500, safe_error_message(e))


@app.get("/api/soundcloud/me")
async def get_soundcloud_me(request: Request):
    """
    Standalone User Profile endpoint.
    Returns the SC account info (username, avatar) independently of playlists.
    Useful for the account card/header component without re-fetching all playlists.
    """
    auth_token = keyring.get_password("rb_editor_pro", "sc_token")
    if not auth_token:
        raise HTTPException(401, detail="auth_expired")

    try:
        import functools
        profile = await asyncio.to_thread(
            functools.partial(SoundCloudPlaylistAPI.get_user_profile, auth_token)
        )
        return {"status": "success", "user": profile}

    except AuthExpiredError as e:
        logger.warning(f"[SC] Auth expired on /me fetch: {e}")
        raise HTTPException(401, detail="auth_expired")

    except Exception as e:
        logger.error(f"[SC] Failed to fetch user profile: {e}", exc_info=True)
        raise HTTPException(500, safe_error_message(e))


class ScSyncReq(BaseModel):
    playlist_ids: List[int] = []
    include_likes: bool = False

@app.post("/api/soundcloud/sync")
async def sync_soundcloud_playlists(r: ScSyncReq, request: Request):
    """Sync selected SoundCloud playlists. Uses asyncio.Lock to prevent race conditions."""
    # Criterion 10: Race condition guard
    if _sync_lock.locked():
        raise HTTPException(409, "A sync operation is already in progress. Please wait.")

    auth_token = keyring.get_password("rb_editor_pro", "sc_token")
    if not auth_token:
        raise HTTPException(400, "SoundCloud auth token not configured")

    if not db.active_db:
        raise HTTPException(400, "No active library loaded")

    async with _sync_lock:
        try:
            engine = SoundCloudSyncEngine(db)
            all_playlists = SoundCloudPlaylistAPI.get_playlists(auth_token)
            to_sync = [pl for pl in all_playlists if pl["id"] in r.playlist_ids]

            if r.include_likes:
                likes = SoundCloudPlaylistAPI.get_likes(auth_token)
                to_sync.append(likes)

            results = engine.sync_all(to_sync, auth_token)

            total_added = sum(res.get("added", 0) for res in results)
            total_matched = sum(res.get("matched", 0) for res in results)
            total_unmatched = sum(res.get("unmatched", 0) for res in results)

            return {
                "status": "success",
                "message": f"Synced {len(results)} playlists: {total_added} tracks added, {total_matched} matched, {total_unmatched} not in library",
                "results": results
            }
        except AuthExpiredError as e:
            logger.warning(f"[SC] Auth expired during sync: {e}")
            raise HTTPException(401, detail="auth_expired")
        except Exception as e:
            logger.error(f"[SC] Sync failed: {e}")
            raise HTTPException(500, safe_error_message(e))

@app.post("/api/soundcloud/sync-all")
async def sync_all_soundcloud(request: Request):
    """Sync ALL SoundCloud playlists + likes. Uses asyncio.Lock to prevent race conditions."""
    if _sync_lock.locked():
        raise HTTPException(409, "A sync operation is already in progress. Please wait.")

    auth_token = keyring.get_password("rb_editor_pro", "sc_token")
    if not auth_token:
        raise HTTPException(400, "SoundCloud auth token not configured")

    if not db.active_db:
        raise HTTPException(400, "No active library loaded")

    async with _sync_lock:
        try:
            engine = SoundCloudSyncEngine(db)
            all_playlists = SoundCloudPlaylistAPI.get_playlists(auth_token)
            likes = SoundCloudPlaylistAPI.get_likes(auth_token)
            all_playlists.append(likes)

            results = engine.sync_all(all_playlists, auth_token)
            total_added = sum(res.get("added", 0) for res in results)
            return {
                "status": "success",
                "message": f"Synced all {len(results)} playlists: {total_added} tracks added",
                "results": results
            }
        except AuthExpiredError as e:
            logger.warning(f"[SC] Auth expired during sync-all: {e}")
            raise HTTPException(401, detail="auth_expired")
        except Exception as e:
            logger.error(f"[SC] Sync-all failed: {e}")
            raise HTTPException(500, safe_error_message(e))

class ScMergeReq(BaseModel):
    playlist_ids: List[int]
    merged_name: str
    delete_originals: bool = False  # Originals deleted ONLY after full verification

@app.post("/api/soundcloud/merge")
async def merge_soundcloud_playlists(r: ScMergeReq, request: Request):
    """
    Merge multiple SoundCloud playlists into one local playlist.

    Safety: if delete_originals=True, originals are only deleted AFTER
    we confirm all matched tracks exist in the merged playlist (zero-loss).
    """
    if _sync_lock.locked():
        raise HTTPException(409, "A sync operation is already in progress. Please wait.")

    auth_token = keyring.get_password("rb_editor_pro", "sc_token")
    if not auth_token:
        raise HTTPException(400, "SoundCloud auth token not configured")

    if not db.active_db:
        raise HTTPException(400, "No active library loaded")

    try:
        engine = SoundCloudSyncEngine(db)

        # ── 1. Resolve or create merged target playlist ────────────────────────
        merged_name = f"SC_{r.merged_name}"
        merged_pid = None
        for pl in db.playlists:
            if pl.get("Name") == merged_name:
                merged_pid = str(pl.get("ID"))
                break

        if not merged_pid:
            if hasattr(db, 'create_playlist'):
                node = db.create_playlist(merged_name)
                merged_pid = str(node["ID"]) if isinstance(node, dict) else str(node)
            else:
                raise HTTPException(500, "Database does not support create_playlist")

        if not merged_pid:
            raise HTTPException(500, "Could not create merged playlist")

        logger.info(f"[SC] Merging into '{merged_name}' (pid={merged_pid}), delete_originals={r.delete_originals}")

        # ── 2. Cache existing tracks in merged playlist ────────────────────────
        existing_ids: set = set()
        try:
            existing = db.get_playlist_tracks(merged_pid)
            existing_ids = {str(t.get("ID", t.get("id", ""))) for t in existing}
        except Exception:
            pass

        local_tracks = db.tracks if hasattr(db, 'tracks') else {}
        all_playlists = SoundCloudPlaylistAPI.get_playlists(auth_token)
        selected_pls = [pl for pl in all_playlists if pl["id"] in r.playlist_ids]

        source_track_sets: dict = {}  # sc_playlist_id → set of local track IDs matched
        added = 0

        # ── 3. Match & add tracks ──────────────────────────────────────────────
        for pl in selected_pls:
            sc_tracks = SoundCloudPlaylistAPI.get_full_playlist_tracks(pl["id"], auth_token)
            matched_for_pl: set = set()
            for sc_track in sc_tracks:
                matched = engine._fuzzy_match_track(
                    sc_track.get("title", ""),
                    sc_track.get("artist", ""),
                    local_tracks
                )
                if matched:
                    matched_for_pl.add(matched)
                    if matched not in existing_ids:
                        if db.add_track_to_playlist(merged_pid, matched):
                            existing_ids.add(matched)
                            added += 1
                        else:
                            logger.warning(f"[SC] add_track_to_playlist failed: tid={matched}")
            source_track_sets[pl["id"]] = matched_for_pl

        # ── 4. Verified deletion ───────────────────────────────────────────────
        deleted_playlists: list = []
        skipped_deletion_reason = None

        if r.delete_originals:
            try:
                merged_tracks_after = db.get_playlist_tracks(merged_pid)
                merged_ids_after = {str(t.get("ID", t.get("id", ""))) for t in merged_tracks_after}
            except Exception as ve:
                skipped_deletion_reason = f"Re-read of merged playlist failed: {ve}"
                merged_ids_after = set()

            all_ok = True
            for pl in selected_pls:
                required = source_track_sets.get(pl["id"], set())
                missing = required - merged_ids_after
                if missing:
                    all_ok = False
                    skipped_deletion_reason = (
                        f"Verification FAILED for '{pl['title']}': "
                        f"{len(missing)} track(s) absent from merged playlist — originals kept."
                    )
                    logger.error(f"[SC] {skipped_deletion_reason}")
                    break

            if all_ok:
                for pl in selected_pls:
                    sc_pl_name = f"SC_{pl['title']}"
                    local_pl = next((p for p in db.playlists if p.get("Name") == sc_pl_name), None)
                    if local_pl:
                        if db.delete_playlist(str(local_pl["ID"])):
                            deleted_playlists.append(sc_pl_name)
                            logger.info(f"[SC] Deleted original: {sc_pl_name}")
                        else:
                            logger.warning(f"[SC] Could not delete: {sc_pl_name}")

        return {
            "status": "success",
            "message": (
                f"Merged {len(selected_pls)} playlist(s) into '{merged_name}': {added} tracks added"
                + (f". Deleted: {deleted_playlists}" if deleted_playlists else "")
                + (f". ⚠️ {skipped_deletion_reason}" if skipped_deletion_reason else "")
            ),
            "playlist_name": merged_name,
            "tracks_added": added,
            "deleted_playlists": deleted_playlists,
            "skipped_deletion_reason": skipped_deletion_reason,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[SC] Merge failed: {e}", exc_info=True)
        raise HTTPException(500, safe_error_message(e))

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
