"""auth_db — sidecar-local store for per-device paired tokens (Phase-2 auth).

Phase-1 ships a single boot-time ``SESSION_TOKEN`` (``app/auth.py``) that rotates
on sidecar restart and cannot be handed to a phone. Phase-2 (mobile companion)
needs long-lived, per-device, individually-revocable bearer tokens. This module
owns that store.

Design (Option A — see docs/research/implement/accepted_security-mobile-paired-tokens-phase2.md):

  * ``auth.db`` lives next to ``.session-token`` (``platformdirs`` user-data dir),
    NOT inside Rekordbox ``master.db`` — so it never contends with the
    ``_db_write_lock`` and a leaked DB exposes only SHA-256 hashes.
  * Device tokens are stored **hashed** (``sha256``); the plaintext is returned to
    the phone exactly once at pairing and never persisted.
  * WAL + ``synchronous=NORMAL`` and a per-thread connection so authed reads do
    not serialise on the writer lock; ``last_seen_at`` writes are throttled
    (only when stale > ``_LAST_SEEN_THROTTLE_S``) to keep the auth read path cheap.
  * Revocation is a flag (``UPDATE``), never a row delete — keeps an audit trail.

This module is deliberately route-free; ``app/main.py`` wires the pairing routes
and ``app/auth.py`` calls ``paired_token_valid`` from ``require_session`` (later tasks).
"""

from __future__ import annotations

import hashlib
import logging
import multiprocessing as _mp
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from platformdirs import user_data_dir

logger = logging.getLogger("AUTH_DB")

_APP_DIRNAME = "MusicLibraryManager"
_DB_FILENAME = "auth.db"

#: Only rewrite last_seen_at when the stored value is older than this (seconds).
#: Turns the common "authed GET" path from a write into a read (contention fix).
_LAST_SEEN_THROTTLE_S = 60

_local = threading.local()
_write_lock = threading.Lock()


def _db_path() -> Path:
    base = Path(user_data_dir(_APP_DIRNAME, appauthor=False, roaming=False))
    return base / _DB_FILENAME


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _connect() -> sqlite3.Connection:
    """Per-thread connection. WAL + NORMAL so reads don't block on the writer."""
    conn: sqlite3.Connection | None = getattr(_local, "conn", None)
    if conn is not None:
        return conn
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    _local.conn = conn
    return conn


_SCHEMA = """
CREATE TABLE IF NOT EXISTS paired_devices (
    device_id    TEXT PRIMARY KEY,
    token_hash   TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    last_seen_at TEXT,
    revoked      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_paired_token_hash ON paired_devices(token_hash);
"""


def init_db() -> None:
    """Idempotent schema create. Safe to call repeatedly; main-process only."""
    if _mp.current_process().name != "MainProcess":
        return
    with _write_lock:
        conn = _connect()
        conn.executescript(_SCHEMA)
        conn.commit()


def create_device(token: str, display_name: str) -> str:
    """Register a freshly-issued device token. Stores only its hash.

    Returns the generated ``device_id`` (surfaced in the revoke route).
    """
    if not token:
        raise ValueError("token must be non-empty")
    device_id = uuid.uuid4().hex
    with _write_lock:
        conn = _connect()
        conn.execute(
            "INSERT INTO paired_devices "
            "(device_id, token_hash, display_name, created_at, last_seen_at, revoked) "
            "VALUES (?, ?, ?, ?, NULL, 0)",
            (device_id, _hash_token(token), display_name or "Unknown device", _now_iso()),
        )
        conn.commit()
    return device_id


def _maybe_touch_last_seen(conn: sqlite3.Connection, token_hash: str, prev: str | None) -> None:
    """Throttled best-effort last_seen update. Never raises into the auth path."""
    now = time.time()
    if prev is not None:
        try:
            last = datetime.fromisoformat(prev).timestamp()
            if now - last < _LAST_SEEN_THROTTLE_S:
                return
        except (ValueError, OSError):
            pass  # unparseable -> fall through and refresh it
    try:
        with _write_lock:
            conn.execute(
                "UPDATE paired_devices SET last_seen_at=? WHERE token_hash=?",
                (_now_iso(), token_hash),
            )
            conn.commit()
    except sqlite3.Error as e:
        logger.warning("auth_db last_seen update failed: %s", e)


def paired_token_valid(candidate: str) -> bool:
    """True iff ``candidate`` matches a non-revoked paired device token.

    Constant-ish hot path: one indexed hash lookup; the last_seen write is
    throttled so most authed requests stay read-only.
    """
    if not candidate:
        return False
    token_hash = _hash_token(candidate)
    try:
        conn = _connect()
        row = conn.execute(
            "SELECT last_seen_at FROM paired_devices WHERE token_hash=? AND revoked=0",
            (token_hash,),
        ).fetchone()
    except sqlite3.Error as e:
        logger.warning("auth_db lookup failed: %s", e)
        return False
    if row is None:
        return False
    _maybe_touch_last_seen(conn, token_hash, row["last_seen_at"])
    return True


def list_devices() -> list[dict[str, object]]:
    """All devices (incl. revoked) for the Settings 'Paired Devices' view."""
    conn = _connect()
    rows = conn.execute(
        "SELECT device_id, display_name, created_at, last_seen_at, revoked "
        "FROM paired_devices ORDER BY created_at DESC"
    ).fetchall()
    return [
        {
            "device_id": r["device_id"],
            "display_name": r["display_name"],
            "created_at": r["created_at"],
            "last_seen_at": r["last_seen_at"],
            "revoked": bool(r["revoked"]),
        }
        for r in rows
    ]


def revoke_device(device_id: str) -> bool:
    """Revoke a device (UPDATE flag, not DELETE). True if a row was affected."""
    with _write_lock:
        conn = _connect()
        cur = conn.execute(
            "UPDATE paired_devices SET revoked=1 WHERE device_id=? AND revoked=0",
            (device_id,),
        )
        conn.commit()
        return cur.rowcount > 0
