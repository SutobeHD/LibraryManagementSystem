"""
Download Registry — SQLite-based deduplication & analysis history log.

Architecture:
  - sc_track_id (TEXT, UNIQUE): Primary dedup key. O(1) B-tree index lookup.
  - sha256_hash (TEXT, INDEXED): Content-based dedup catches re-uploads with new IDs.
  - device_id (TEXT): Stable UUID per machine — enables multi-device history aggregation.
  - status flow: downloading → downloaded → analyzing → analyzed | failed

Legal note:
  This registry only records tracks that were explicitly marked 'downloadable: true'
  by their creator on the SoundCloud API. Downloads of non-downloadable tracks are
  rejected before any network request is made. All downloads use the official SC API
  download endpoint, which matches SoundCloud's Terms of Service:
    "You may only download Content if a download button or link is displayed
     by SoundCloud for that Content."
"""

import hashlib
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Lazy-initialized — resolved after config module is loaded
_REGISTRY_DB: Optional[Path] = None


def _registry_path() -> Path:
    global _REGISTRY_DB
    if _REGISTRY_DB is None:
        from .config import MUSIC_DIR
        MUSIC_DIR.mkdir(parents=True, exist_ok=True)
        _REGISTRY_DB = MUSIC_DIR / "download_registry.db"
    return _REGISTRY_DB


def _conn() -> sqlite3.Connection:
    """Open a WAL-mode connection with Row factory enabled."""
    c = sqlite3.connect(str(_registry_path()), check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")    # safe concurrent reads while writing
    c.execute("PRAGMA synchronous=NORMAL")  # balance durability vs. speed
    return c


# ── Schema ────────────────────────────────────────────────────────────────────

def init_registry() -> None:
    """Create DB schema if it doesn't exist. Safe to call multiple times on startup."""
    try:
        with _conn() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS download_history (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    sc_track_id         TEXT    NOT NULL,
                    sha256_hash         TEXT,
                    title               TEXT    NOT NULL DEFAULT '',
                    artist              TEXT    NOT NULL DEFAULT '',
                    duration_ms         INTEGER DEFAULT 0,
                    sc_permalink_url    TEXT    DEFAULT '',
                    sc_playlist_title   TEXT,
                    file_path           TEXT,
                    file_format         TEXT,
                    file_size_bytes     INTEGER,
                    bpm                 REAL,
                    key_str             TEXT,
                    analysis_confidence REAL,
                    downloaded_at       TEXT    NOT NULL,
                    analyzed_at         TEXT,
                    status              TEXT    NOT NULL DEFAULT 'downloading',
                    error_message       TEXT,
                    device_id           TEXT    NOT NULL DEFAULT '',
                    local_track_id      TEXT,
                    UNIQUE(sc_track_id)
                );

                -- Primary dedup index: O(1) lookup by SC track ID
                CREATE INDEX IF NOT EXISTS idx_reg_sc_id
                    ON download_history(sc_track_id);

                -- Content dedup: catch re-uploads under new IDs
                CREATE INDEX IF NOT EXISTS idx_reg_sha256
                    ON download_history(sha256_hash)
                    WHERE sha256_hash IS NOT NULL;

                -- Dashboard queries
                CREATE INDEX IF NOT EXISTS idx_reg_status
                    ON download_history(status);
                CREATE INDEX IF NOT EXISTS idx_reg_dl_at
                    ON download_history(downloaded_at DESC);
                CREATE INDEX IF NOT EXISTS idx_reg_device
                    ON download_history(device_id);
            """)
        logger.info("[Registry] Initialized at %s", _registry_path())
    except sqlite3.Error as exc:
        logger.error("[Registry] Schema init failed: %s", exc)


# ── Device ID ─────────────────────────────────────────────────────────────────

def _device_id() -> str:
    """
    Stable per-device UUID. Persisted as a plaintext file next to the registry DB.
    NOT tied to hardware (avoids permission/privacy issues on shared Windows machines).
    Generated once, then reused across all sessions.
    """
    id_file = _registry_path().parent / ".rb_device_id"
    if id_file.exists():
        try:
            did = id_file.read_text(encoding="utf-8").strip()
            if did:
                return did
        except OSError:
            pass
    new_id = str(uuid.uuid4())
    try:
        id_file.write_text(new_id, encoding="utf-8")
        logger.info("[Registry] New device_id generated: %s", new_id)
    except OSError as exc:
        logger.warning("[Registry] Could not persist device_id to %s: %s", id_file, exc)
    return new_id


def get_current_device_id() -> str:
    """Expose device ID so the frontend can filter history to this device."""
    return _device_id()


# ── Deduplication ─────────────────────────────────────────────────────────────

def is_already_downloaded(sc_track_id: str) -> bool:
    """
    O(1) dedup check by SoundCloud track ID.

    Returns True if the track was already successfully downloaded or is
    currently being downloaded (status not 'failed').
    Always returns False on DB errors (fail-open: better to retry than block).
    """
    if not sc_track_id:
        return False
    try:
        with _conn() as db:
            row = db.execute(
                "SELECT status FROM download_history WHERE sc_track_id = ? LIMIT 1",
                (str(sc_track_id),)
            ).fetchone()
        if row and row["status"] not in ("failed",):
            logger.debug("[Registry] Dedup hit: sc_id=%s (status=%s)", sc_track_id, row["status"])
            return True
    except sqlite3.Error as exc:
        logger.error("[Registry] is_already_downloaded query failed: %s", exc)
    return False


def find_by_hash(sha256: str) -> Optional[Dict]:
    """
    Content-based dedup. Returns the existing record dict if a file with the
    same SHA-256 hash already exists — even if it has a different sc_track_id
    (handles artist re-uploads under new track IDs).
    Returns None if not found or on DB error.
    """
    if not sha256:
        return None
    try:
        with _conn() as db:
            row = db.execute(
                "SELECT * FROM download_history WHERE sha256_hash = ? LIMIT 1",
                (sha256,)
            ).fetchone()
        return dict(row) if row else None
    except sqlite3.Error as exc:
        logger.error("[Registry] find_by_hash query failed: %s", exc)
    return None


# ── Write operations ───────────────────────────────────────────────────────────

def register_download(
    *,
    sc_track_id: str,
    title: str,
    artist: str,
    duration_ms: int = 0,
    sc_permalink_url: str = "",
    sc_playlist_title: Optional[str] = None,
    file_path: Optional[Path] = None,
    file_format: Optional[str] = None,
    file_size_bytes: Optional[int] = None,
    sha256_hash: Optional[str] = None,
    status: str = "downloaded",
    error_message: Optional[str] = None,
) -> bool:
    """
    Insert or update a download record. Idempotent (UPSERT on sc_track_id).

    Status lifecycle:
      'downloading'  → download in progress (registered immediately to block parallel duplicates)
      'downloaded'   → file on disk, not yet analyzed
      'analyzing'    → BPM/key analysis in progress
      'analyzed'     → full pipeline complete
      'failed'       → permanent failure (track can be retried by deleting this record)
    """
    now = datetime.now(timezone.utc).isoformat()
    try:
        with _conn() as db:
            db.execute(
                """
                INSERT INTO download_history
                    (sc_track_id, title, artist, duration_ms, sc_permalink_url,
                     sc_playlist_title, file_path, file_format, file_size_bytes,
                     sha256_hash, downloaded_at, status, error_message, device_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(sc_track_id) DO UPDATE SET
                    file_path        = COALESCE(excluded.file_path,        file_path),
                    file_size_bytes  = COALESCE(excluded.file_size_bytes,  file_size_bytes),
                    sha256_hash      = COALESCE(excluded.sha256_hash,      sha256_hash),
                    status           = excluded.status,
                    error_message    = excluded.error_message
                """,
                (
                    str(sc_track_id), title, artist, duration_ms, sc_permalink_url,
                    sc_playlist_title,
                    str(file_path) if file_path else None,
                    file_format, file_size_bytes, sha256_hash,
                    now, status, error_message, _device_id(),
                )
            )
        logger.info("[Registry] Registered: sc_id=%s status=%s", sc_track_id, status)
        return True
    except sqlite3.Error as exc:
        logger.error("[Registry] register_download failed (sc_id=%s): %s", sc_track_id, exc)
        return False


def update_analysis(
    *,
    sc_track_id: str,
    bpm: Optional[float] = None,
    key_str: Optional[str] = None,
    confidence: Optional[float] = None,
    local_track_id: Optional[str] = None,
) -> bool:
    """Store DSP analysis results and mark the record as 'analyzed'."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        with _conn() as db:
            db.execute(
                """
                UPDATE download_history
                SET bpm=?, key_str=?, analysis_confidence=?, analyzed_at=?,
                    status='analyzed', local_track_id=?
                WHERE sc_track_id=?
                """,
                (bpm, key_str, confidence, now, local_track_id, str(sc_track_id))
            )
        logger.info(
            "[Registry] Analysis saved: sc_id=%s bpm=%.1f key=%s",
            sc_track_id, bpm or 0, key_str or "?"
        )
        return True
    except sqlite3.Error as exc:
        logger.error("[Registry] update_analysis failed (sc_id=%s): %s", sc_track_id, exc)
        return False


def mark_failed(sc_track_id: str, error: str) -> None:
    """Mark a download as permanently failed."""
    try:
        with _conn() as db:
            db.execute(
                "UPDATE download_history SET status='failed', error_message=? WHERE sc_track_id=?",
                (error[:500], str(sc_track_id))
            )
        logger.warning("[Registry] Marked failed: sc_id=%s error=%s", sc_track_id, error[:120])
    except sqlite3.Error as exc:
        logger.error("[Registry] mark_failed query failed: %s", exc)


def delete_entry(sc_track_id: str) -> bool:
    """
    Remove a registry entry (e.g. to allow re-download of a failed track).
    Does NOT delete the file from disk.
    """
    try:
        with _conn() as db:
            db.execute(
                "DELETE FROM download_history WHERE sc_track_id=?",
                (str(sc_track_id),)
            )
        logger.info("[Registry] Deleted entry: sc_id=%s", sc_track_id)
        return True
    except sqlite3.Error as exc:
        logger.error("[Registry] delete_entry failed (sc_id=%s): %s", sc_track_id, exc)
        return False


# ── Query operations ───────────────────────────────────────────────────────────

def get_history(
    *,
    limit: int = 100,
    offset: int = 0,
    status: Optional[str] = None,
    device_id: Optional[str] = None,
    search: Optional[str] = None,
) -> List[Dict]:
    """
    Paginated history log, newest-first.

    Filters:
      status     — exact match ('analyzed', 'downloaded', 'failed', etc.)
      device_id  — filter to a specific device (pass get_current_device_id() for this device)
      search     — substring match on title or artist (case-insensitive)
    """
    clauses: List[str] = []
    params: List[Any] = []

    if status:
        clauses.append("status = ?")
        params.append(status)
    if device_id:
        clauses.append("device_id = ?")
        params.append(device_id)
    if search:
        like = f"%{search}%"
        clauses.append("(title LIKE ? OR artist LIKE ?)")
        params.extend([like, like])

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    try:
        with _conn() as db:
            rows = db.execute(
                f"""
                SELECT * FROM download_history
                {where}
                ORDER BY downloaded_at DESC
                LIMIT ? OFFSET ?
                """,
                (*params, limit, offset)
            ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.Error as exc:
        logger.error("[Registry] get_history failed: %s", exc)
        return []


def get_stats() -> Dict:
    """Aggregate statistics for the history dashboard widget."""
    try:
        with _conn() as db:
            row = db.execute("""
                SELECT
                    COUNT(*)                                              AS total,
                    SUM(CASE WHEN status='analyzed'   THEN 1 ELSE 0 END) AS analyzed,
                    SUM(CASE WHEN status='downloaded' THEN 1 ELSE 0 END) AS downloaded_only,
                    SUM(CASE WHEN status='analyzing'  THEN 1 ELSE 0 END) AS analyzing,
                    SUM(CASE WHEN status='failed'     THEN 1 ELSE 0 END) AS failed,
                    COUNT(DISTINCT device_id)                             AS devices,
                    MIN(downloaded_at)                                    AS first_download,
                    MAX(downloaded_at)                                    AS last_download
                FROM download_history
            """).fetchone()
        return dict(row) if row else {}
    except sqlite3.Error as exc:
        logger.error("[Registry] get_stats failed: %s", exc)
        return {}


# ── File hashing ──────────────────────────────────────────────────────────────

def compute_sha256(path: Path, chunk_size: int = 65_536) -> Optional[str]:
    """
    Stream-hash a file with SHA-256. Returns hex digest or None on I/O error.
    chunk_size=65536 balances memory use and speed for audio files (30–500 MB).
    """
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            while chunk := fh.read(chunk_size):
                h.update(chunk)
        return h.hexdigest()
    except OSError as exc:
        logger.error("[Registry] compute_sha256 failed for %s: %s", path, exc)
        return None
