"""
SoundCloud Downloader — Legal, dedup-aware download pipeline.

LEGAL COMPLIANCE
================
Only tracks explicitly marked 'downloadable: true' by their creator are eligible
for download. Non-downloadable tracks are rejected before any network request is
made. This matches SoundCloud's Terms of Service:
  "You may only download Content if a download button or link is displayed
   by SoundCloud for that Content."

Downloads use the official SoundCloud API endpoint:
  GET https://api.soundcloud.com/tracks/{id}/download
  Authorization: OAuth {token}

This is the same mechanism used by the SoundCloud web player download button.
No third-party ripping tools (scdl, yt-dlp) are used.

DEDUPLICATION
=============
Two-layer dedup is applied before every download:
  1. SoundCloud track ID → O(1) SQLite indexed query
  2. SHA-256 content hash after download → catches re-uploads with new IDs

FILE ORGANIZATION
=================
  {MUSIC_DIR}/SoundCloud/{sanitized_artist}/{sanitized_title}.{ext}

POST-DOWNLOAD PIPELINE
======================
  1. SHA-256 hash → content-based dedup check
  2. Registry update (status = downloaded)
  3. Background: BPM/key analysis → registry update (status = analyzed)
  4. Background: Auto-import into library + auto-sort into matching SC playlist
"""

import logging
import re
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable, Dict, Optional

import requests

from .config import MUSIC_DIR
from . import download_registry as registry

logger = logging.getLogger(__name__)

# Allowed audio extensions from official SC downloads
_ALLOWED_EXTS = frozenset({".mp3", ".wav", ".flac", ".aiff", ".aif", ".ogg", ".opus", ".m4a", ".aac"})

# Maximum per-component filename length (Windows MAX_PATH-safe)
_MAX_NAME_LEN = 80

# Network timeouts
_API_TIMEOUT = 15       # seconds — URL resolution / redirect
_DOWNLOAD_TIMEOUT = 180  # seconds — actual file download (large files up to ~500 MB)

# Content-Type → extension mapping
_CT_MAP: Dict[str, str] = {
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/flac": ".flac",
    "audio/x-flac": ".flac",
    "audio/aiff": ".aiff",
    "audio/x-aiff": ".aiff",
    "audio/ogg": ".ogg",
    "audio/opus": ".opus",
    "audio/aac": ".aac",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
}


# ── Filename helpers ───────────────────────────────────────────────────────────

def _sanitize_name(name: str) -> str:
    """
    Convert an artist/title string to a safe filesystem component.
    Strips Windows/Unix path-illegal characters, collapses whitespace, limits length.
    """
    if not name or not name.strip():
        return "Unknown"
    # Replace illegal chars (Windows: < > : " / \ | ? * and control chars)
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    safe = re.sub(r'\s+', " ", safe).strip(" ._")
    if len(safe) > _MAX_NAME_LEN:
        safe = safe[:_MAX_NAME_LEN].rstrip(" ._")
    return safe or "Unknown"


def _build_save_path(artist: str, title: str, ext: str) -> Path:
    """
    Canonical path for a downloaded track:
      {MUSIC_DIR}/SoundCloud/{sanitized_artist}/{sanitized_title}.{ext}

    Handles filename collisions by appending a numeric suffix.
    Creates the artist subdirectory if it doesn't exist.
    """
    artist_dir = MUSIC_DIR / "SoundCloud" / _sanitize_name(artist)
    artist_dir.mkdir(parents=True, exist_ok=True)
    stem = _sanitize_name(title)
    candidate = artist_dir / f"{stem}{ext}"
    counter = 1
    while candidate.exists():
        candidate = artist_dir / f"{stem} ({counter}){ext}"
        counter += 1
    return candidate


def _guess_extension(content_type: str, url: str) -> str:
    """Determine file extension from Content-Type header, falling back to URL path."""
    ct_lower = content_type.lower()
    for mime, ext in _CT_MAP.items():
        if mime in ct_lower:
            return ext
    # Fall back: extract from URL path before the query string
    url_stem = url.split("?")[0]
    suffix = Path(url_stem).suffix.lower()
    return suffix if suffix in _ALLOWED_EXTS else ".mp3"


# ── Network helpers ────────────────────────────────────────────────────────────

def _resolve_official_download_url(
    sc_track_id: str,
    auth_token: Optional[str],
) -> Optional[str]:
    """
    Resolve the official download URL for a downloadable SC track.

    Flow:
      GET /tracks/{id}/download  →  follow redirect(s)  →  return final URL

    The final URL points to the CDN (typically AWS S3). We stream from there.
    Returns None on any network or HTTP error; caller decides what to do.
    """
    from .soundcloud_api import SC_API_BASE, get_sc_client_id

    headers: Dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }
    if auth_token:
        headers["Authorization"] = f"OAuth {auth_token}"

    params: Dict[str, str] = {} if auth_token else {"client_id": get_sc_client_id()}
    url = f"{SC_API_BASE}/tracks/{sc_track_id}/download"
    logger.info("[SC-DL] Resolving official download URL: sc_id=%s", sc_track_id)

    try:
        resp = requests.get(
            url,
            headers=headers,
            params=params,
            allow_redirects=True,   # follow the 302 chain to the CDN
            timeout=_API_TIMEOUT,
            stream=True,            # avoid buffering the body here
        )
        resp.raise_for_status()
        logger.info("[SC-DL] Resolved to: %s", resp.url[:120])
        return resp.url

    except requests.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else "?"
        logger.error(
            "[SC-DL] HTTP %s resolving download URL for sc_id=%s: %s",
            code, sc_track_id, exc,
        )
        return None
    except requests.RequestException as exc:
        logger.error("[SC-DL] Network error resolving download URL (sc_id=%s): %s", sc_track_id, exc)
        return None


def _stream_file_to_temp(
    download_url: str,
    auth_token: Optional[str],
) -> Optional[Path]:
    """
    Stream the audio file from `download_url` into a secure named temp file.

    Returns the temp file path on success.
    Returns None on any network error.
    The caller is responsible for deleting the temp file on failure.
    """
    headers: Dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }
    if auth_token:
        headers["Authorization"] = f"OAuth {auth_token}"

    try:
        resp = requests.get(
            download_url,
            headers=headers,
            stream=True,
            timeout=_DOWNLOAD_TIMEOUT,
        )
        resp.raise_for_status()

        content_type = resp.headers.get("Content-Type", "")
        ext = _guess_extension(content_type, download_url)

        with tempfile.NamedTemporaryFile(
            prefix="rbpro_sc_", suffix=ext, delete=False
        ) as tf:
            tmp_path = Path(tf.name)
            total = 0
            for chunk in resp.iter_content(chunk_size=65_536):
                if chunk:
                    tf.write(chunk)
                    total += len(chunk)

        logger.info("[SC-DL] Streamed %d bytes to temp=%s", total, tmp_path.name)
        return tmp_path

    except requests.RequestException as exc:
        logger.error("[SC-DL] Streaming failed from %s: %s", download_url[:80], exc)
        return None


# ── Downloader ─────────────────────────────────────────────────────────────────

class SoundCloudDownloader:
    """
    Queue-based manager for SoundCloud downloads.
    Each download runs in its own daemon thread.

    Public API:
      download_track(...)    → task_id str  (returns immediately)
      get_task_status(id)    → dict | None
      cleanup_processes()    → atexit hook (no-op — no subprocesses to kill)
    """

    def __init__(self) -> None:
        self.tasks: Dict[str, Dict] = {}
        self._lock = threading.Lock()

    # ── Public entry point ─────────────────────────────────────────────────────

    def download_track(
        self,
        *,
        sc_track_id: str,
        sc_permalink_url: str,
        title: str,
        artist: str,
        duration_ms: int = 0,
        downloadable: bool,
        auth_token: Optional[str] = None,
        sc_playlist_title: Optional[str] = None,
        on_complete: Optional[Callable] = None,
    ) -> str:
        """
        Queue a track for download. Returns a task_id immediately.

        Legal compliance gate:
          - downloadable must be True (set by the creator on SoundCloud).
            Non-downloadable tracks are rejected without making any network request.

        Deduplication gate:
          - Checks registry by sc_track_id before starting.
          - After download, checks SHA-256 hash against registry.

        Args:
          sc_track_id       : SoundCloud numeric track ID (as string)
          sc_permalink_url  : SC track URL (for registry / logging)
          title, artist     : Track metadata for file naming + registry
          duration_ms       : Track duration in ms (from SC API)
          downloadable      : Must be True — from SC API 'downloadable' field
          auth_token        : OAuth access token (required for most downloads)
          sc_playlist_title : Optional source playlist name for auto-sort
          on_complete       : Optional callback(task_id: str, success: bool, file_path: Path | None)
        """
        task_id = f"sc_{sc_track_id}_{int(time.time())}"

        # ── Gate 1: Legal compliance — only downloadable tracks ────────────────
        if not downloadable:
            logger.warning(
                "[SC-DL] Rejected sc_id=%s '%s' — not marked downloadable by creator.",
                sc_track_id, title,
            )
            self._set_task(task_id, {
                "id": task_id, "sc_track_id": sc_track_id,
                "title": title, "artist": artist,
                "status": "Rejected", "progress": 0,
                "error": (
                    "Dieser Track ist nicht zum Download freigegeben. "
                    "Der Ersteller hat den Download-Button nicht aktiviert."
                ),
                "start_time": time.time(),
            })
            if on_complete:
                on_complete(task_id, False, None)
            return task_id

        # ── Gate 2: Deduplication — skip if already in registry ───────────────
        if registry.is_already_downloaded(sc_track_id):
            logger.info("[SC-DL] Skipped sc_id=%s '%s' — already in registry.", sc_track_id, title)
            self._set_task(task_id, {
                "id": task_id, "sc_track_id": sc_track_id,
                "title": title, "artist": artist,
                "status": "Skipped", "progress": 100,
                "duplicate": True, "error": None,
                "start_time": time.time(),
            })
            if on_complete:
                on_complete(task_id, True, None)
            return task_id

        # Register as 'downloading' immediately to block parallel duplicates
        registry.register_download(
            sc_track_id=sc_track_id, title=title, artist=artist,
            duration_ms=duration_ms, sc_permalink_url=sc_permalink_url,
            sc_playlist_title=sc_playlist_title, status="downloading",
        )

        self._set_task(task_id, {
            "id": task_id, "sc_track_id": sc_track_id,
            "title": title, "artist": artist,
            "status": "Starting", "progress": 0,
            "error": None, "start_time": time.time(),
        })

        def _run() -> None:
            try:
                self._do_download(
                    task_id=task_id, sc_track_id=sc_track_id,
                    sc_permalink_url=sc_permalink_url,
                    title=title, artist=artist, duration_ms=duration_ms,
                    auth_token=auth_token, sc_playlist_title=sc_playlist_title,
                    on_complete=on_complete,
                )
            except Exception as exc:
                logger.error(
                    "[SC-DL] Unhandled error in download thread (task=%s): %s",
                    task_id, exc, exc_info=True,
                )
                self._update_task(task_id, status="Error", error=str(exc))
                registry.mark_failed(sc_track_id, str(exc))
                if on_complete:
                    on_complete(task_id, False, None)

        thread = threading.Thread(
            target=_run, daemon=True, name=f"sc-dl-{sc_track_id}"
        )
        thread.start()
        return task_id

    # ── Core download logic ────────────────────────────────────────────────────

    def _do_download(
        self, *, task_id: str, sc_track_id: str, sc_permalink_url: str,
        title: str, artist: str, duration_ms: int,
        auth_token: Optional[str], sc_playlist_title: Optional[str],
        on_complete: Optional[Callable],
    ) -> None:
        """Full download + hash + registry pipeline. Runs in a background thread."""

        tmp_path: Optional[Path] = None

        try:
            # Step 1 — Resolve official download URL via SC API ────────────────
            self._update_task(task_id, status="Resolving", progress=5)
            logger.info("[SC-DL] Starting: sc_id=%s title='%s'", sc_track_id, title)

            download_url = _resolve_official_download_url(sc_track_id, auth_token)
            if not download_url:
                err = (
                    "Download-URL konnte nicht von SoundCloud abgerufen werden. "
                    "Möglicherweise ist der Track für dein Konto nicht zugänglich."
                )
                self._update_task(task_id, status="Failed", error=err)
                registry.mark_failed(sc_track_id, err)
                if on_complete:
                    on_complete(task_id, False, None)
                return

            # Step 2 — Stream file to temp directory ──────────────────────────
            self._update_task(task_id, status="Downloading", progress=15)
            tmp_path = _stream_file_to_temp(download_url, auth_token)
            if not tmp_path:
                err = "Datei-Download fehlgeschlagen (Netzwerkfehler)."
                self._update_task(task_id, status="Failed", error=err)
                registry.mark_failed(sc_track_id, err)
                if on_complete:
                    on_complete(task_id, False, None)
                return

            self._update_task(task_id, status="Processing", progress=80)

            # Step 3 — Move to organized final location ────────────────────────
            ext = tmp_path.suffix.lower() or ".mp3"
            final_path = _build_save_path(artist, title, ext)
            shutil.move(str(tmp_path), str(final_path))
            tmp_path = None  # moved, no longer needs cleanup
            file_size = final_path.stat().st_size
            logger.info("[SC-DL] Saved: %s (%d bytes)", final_path, file_size)

            # Step 4 — SHA-256: content-based duplicate check ──────────────────
            self._update_task(task_id, status="Hashing", progress=88)
            sha256 = registry.compute_sha256(final_path)

            if sha256:
                existing = registry.find_by_hash(sha256)
                if existing and existing["sc_track_id"] != sc_track_id:
                    # Same content under a different SC ID — remove the duplicate
                    logger.warning(
                        "[SC-DL] Content duplicate: sc_id=%s matches existing sc_id=%s. "
                        "Removing duplicate file.",
                        sc_track_id, existing["sc_track_id"],
                    )
                    final_path.unlink(missing_ok=True)
                    registry.mark_failed(
                        sc_track_id,
                        f"Duplicate content (matches sc_id={existing['sc_track_id']})"
                    )
                    self._update_task(
                        task_id, status="Duplicate", progress=100,
                        error=(
                            f"Dieser Track ist bereits vorhanden als "
                            f"'{existing.get('title', '?')}' von '{existing.get('artist', '?')}'."
                        )
                    )
                    if on_complete:
                        on_complete(task_id, False, None)
                    return

            # Step 5 — Register as downloaded ──────────────────────────────────
            registry.register_download(
                sc_track_id=sc_track_id, title=title, artist=artist,
                duration_ms=duration_ms, sc_permalink_url=sc_permalink_url,
                sc_playlist_title=sc_playlist_title,
                file_path=final_path, file_format=ext.lstrip("."),
                file_size_bytes=file_size, sha256_hash=sha256,
                status="downloaded",
            )

            self._update_task(task_id, status="Completed", progress=100)
            logger.info("[SC-DL] Completed: '%s' → %s", title, final_path)

            if on_complete:
                on_complete(task_id, True, final_path)

            # Step 6 — Trigger background analysis (must not raise) ────────────
            self._trigger_analysis_async(sc_track_id, final_path, sc_playlist_title)

        except Exception as exc:
            logger.error(
                "[SC-DL] Unexpected error in _do_download (sc_id=%s): %s",
                sc_track_id, exc, exc_info=True,
            )
            # Clean up temp file if the move hadn't happened yet
            if tmp_path and tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            err = f"Interner Fehler: {exc}"
            self._update_task(task_id, status="Error", error=err)
            registry.mark_failed(sc_track_id, err)
            if on_complete:
                on_complete(task_id, False, None)

    # ── Post-download pipeline ─────────────────────────────────────────────────

    def _trigger_analysis_async(
        self,
        sc_track_id: str,
        file_path: Path,
        sc_playlist_title: Optional[str],
    ) -> None:
        """
        Spawn a daemon thread to run BPM/key analysis and auto-import.
        Errors here must NOT bubble up — the download itself already succeeded.
        """
        def _analyze() -> None:
            local_track_id: Optional[str] = None
            try:
                # Mark as analyzing in registry
                registry.register_download(
                    sc_track_id=sc_track_id, title="", artist="",
                    status="analyzing",
                )

                from .analysis_engine import run_full_analysis
                logger.info("[SC-DL] Analyzing: %s", file_path.name)
                result = run_full_analysis(str(file_path))
                bpm = result.get("bpm")
                key = result.get("key")
                conf = result.get("confidence")

                # Auto-import into Rekordbox library
                local_track_id = self._auto_import(file_path)

                registry.update_analysis(
                    sc_track_id=sc_track_id, bpm=bpm,
                    key_str=key, confidence=conf,
                    local_track_id=local_track_id,
                )
                logger.info(
                    "[SC-DL] Analysis done: sc_id=%s bpm=%.1f key=%s local_id=%s",
                    sc_track_id, bpm or 0, key or "?", local_track_id,
                )

                # Auto-sort into SC playlist after import
                if sc_playlist_title and local_track_id:
                    self._auto_add_to_playlist(local_track_id, sc_playlist_title)

            except Exception as exc:
                logger.error(
                    "[SC-DL] Background analysis failed for sc_id=%s: %s",
                    sc_track_id, exc, exc_info=True,
                )

        thread = threading.Thread(
            target=_analyze, daemon=True, name=f"sc-analyze-{sc_track_id}"
        )
        thread.start()

    def _auto_import(self, file_path: Path) -> Optional[str]:
        """
        Import the downloaded track into the Rekordbox XML library.
        Returns the new local track_id string, or None on failure.
        """
        try:
            from .services import ImportManager
            track_id = ImportManager.process_import(file_path)
            if track_id:
                logger.info("[SC-DL] Imported into library: track_id=%s", track_id)
            else:
                logger.warning("[SC-DL] Import returned no track_id for %s", file_path)
            return str(track_id) if track_id else None
        except Exception as exc:
            logger.error("[SC-DL] Auto-import failed for %s: %s", file_path, exc)
            return None

    def _auto_add_to_playlist(self, local_track_id: str, sc_playlist_title: str) -> None:
        """
        Add the imported track to the matching local SC_ playlist.
        Creates the playlist if it doesn't exist (via SoundCloudSyncEngine).
        """
        try:
            from .database import db
            from .soundcloud_api import SoundCloudSyncEngine

            engine = SoundCloudSyncEngine(db)
            pid = engine.find_or_create_playlist(sc_playlist_title)
            if not pid:
                logger.warning(
                    "[SC-DL] Could not find/create playlist for '%s'", sc_playlist_title
                )
                return

            add_fn = (
                db.add_track_to_playlist
                if hasattr(db, "add_track_to_playlist")
                else (
                    db.active_db.add_track_to_playlist
                    if hasattr(db, "active_db")
                    else None
                )
            )
            if add_fn:
                add_fn(pid, local_track_id)
                logger.info(
                    "[SC-DL] Auto-sorted track %s into 'SC_%s' (pid=%s)",
                    local_track_id, sc_playlist_title, pid,
                )
            else:
                logger.warning("[SC-DL] DB has no add_track_to_playlist method.")

        except Exception as exc:
            logger.error(
                "[SC-DL] auto_add_to_playlist failed (playlist='%s'): %s",
                sc_playlist_title, exc,
            )

    # ── State helpers ──────────────────────────────────────────────────────────

    def _set_task(self, task_id: str, data: Dict) -> None:
        with self._lock:
            self.tasks[task_id] = data

    def _update_task(self, task_id: str, **kwargs) -> None:
        with self._lock:
            if task_id in self.tasks:
                self.tasks[task_id].update(kwargs)

    def get_task_status(self, task_id: str) -> Optional[Dict]:
        with self._lock:
            return self.tasks.get(task_id)

    def cleanup_processes(self) -> None:
        """No-op: kept for API compatibility. No subprocesses used."""
        logger.debug("[SC-DL] cleanup_processes called (no-op — HTTP-based downloader)")


# Module-level singleton used by main.py
sc_downloader = SoundCloudDownloader()
