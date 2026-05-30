"""Popularity sidecar engine — SoundCloud-only at M1 (underground-mainstream T1-T3).

Estimates a track's cross-platform popularity (underground ↔ mainstream) and
caches it per (track_id, platform) in a sidecar SQLite DB, so a cold 30k-track
scan (hours-scale) runs once and later reads are O(1) until the TTL expires.

Storage: ``~/.cache/rb_editor_pro/popularity/popularity.sqlite`` (XDG-cache
convention, mirrors ``app/analysis_cache.py:44``). Sidecar — NOT Rekordbox
``master.db`` (Pioneer hardware rejects unknown columns silently), so no
``_db_write_lock`` and ``rm popularity.sqlite`` is a clean reset.

This module is the M1 store layer (T1 skeleton + T2 schema-version/migrate
framework + T3 CRUD). The normalisation math (ECDF / Spotify carve-out),
aggregator, SoundCloud payload read, and routes are later tasks — they pull
``app.database`` / ``app.main``, which this module deliberately does not import
(keeps it stdlib-only and unit-testable in isolation).
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
DEFAULT_TTL_SECONDS = 86_400  # 24h for SC; per-platform override at M2
Platform = Literal["soundcloud", "spotify", "lastfm"]


def _default_db_path() -> Path:
    p = Path.home() / ".cache" / "rb_editor_pro" / "popularity" / "popularity.sqlite"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


class PopularityStore:
    """Per-track per-platform popularity sidecar. SQLite WAL, threadsafe writes."""

    def __init__(self, db_path: Path | None = None):
        self._db_path = db_path or _default_db_path()
        self._lock = threading.Lock()
        self._init_schema()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Per-call WAL connection with Row factory; commits on clean exit."""
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ── Schema + migrate-on-open framework (T1 + T2) ──────────────────────────

    def _init_schema(self) -> None:
        """Create tables if absent, then migrate forward to ``SCHEMA_VERSION``.

        Migrate-on-open contract: read ``popularity_meta.schema_version`` and run
        ``_migrate_vN_to_vN+1`` until current. Each migration is an idempotent
        transaction. A fresh DB is stamped at the current version directly.
        """
        with self._connect() as c:
            c.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS popularity (
                  track_id TEXT NOT NULL, platform TEXT NOT NULL,
                  raw_count INTEGER, log_count REAL, percentile REAL,
                  fetched_at INTEGER NOT NULL,
                  match_method TEXT, match_confidence REAL,
                  PRIMARY KEY (track_id, platform)
                );
                CREATE INDEX IF NOT EXISTS ix_pop_fetched ON popularity(fetched_at);
                CREATE TABLE IF NOT EXISTS popularity_meta (
                  key TEXT PRIMARY KEY, value TEXT NOT NULL
                );
                """
            )
            row = c.execute(
                "SELECT value FROM popularity_meta WHERE key = 'schema_version'"
            ).fetchone()
            current = int(row["value"]) if row is not None else 0

        if current == 0:
            # Fresh DB (tables just created at the current shape) — stamp directly.
            self._set_schema_version(SCHEMA_VERSION)
            return
        if current < SCHEMA_VERSION:
            self._migrate(current)
        elif current > SCHEMA_VERSION:
            logger.warning(
                "popularity DB schema_version=%d newer than code SCHEMA_VERSION=%d",
                current,
                SCHEMA_VERSION,
            )

    def _set_schema_version(self, version: int) -> None:
        with self._connect() as c:
            c.execute(
                "INSERT OR REPLACE INTO popularity_meta (key, value) VALUES ('schema_version', ?)",
                (str(version),),
            )

    def _migrate(self, from_version: int) -> None:
        """Apply ordered migrations ``from_version`` → ``SCHEMA_VERSION``.

        v2 (M2) will add ``genre_at_fetch`` / ``ecdf_basis``; v3 (M3)
        ``weight_profile_at_fetch``. No migrations defined yet at v1.
        """
        version = from_version
        while version < SCHEMA_VERSION:
            migrator = getattr(self, f"_migrate_v{version}_to_v{version + 1}", None)
            if migrator is None:
                raise RuntimeError(
                    f"no migration path from popularity schema v{version} to v{version + 1}"
                )
            migrator()
            version += 1
            self._set_schema_version(version)

    def schema_version(self) -> int:
        """Stored schema version (0 if unstamped — should not happen post-init)."""
        with self._connect() as c:
            row = c.execute(
                "SELECT value FROM popularity_meta WHERE key = 'schema_version'"
            ).fetchone()
        return int(row["value"]) if row is not None else 0

    # ── CRUD (T3) ─────────────────────────────────────────────────────────────

    def upsert(
        self,
        track_id: str,
        platform: Platform | str,
        *,
        raw_count: int | None,
        log_count: float | None = None,
        percentile: float | None = None,
        match_method: str | None = None,
        match_confidence: float | None = None,
        fetched_at: int | None = None,
    ) -> None:
        """Insert or replace one (track_id, platform) popularity row.

        ``fetched_at`` defaults to now (epoch seconds); pass an explicit value to
        backdate a row (used by tests + TTL sweeps).
        """
        if not track_id:
            raise ValueError("track_id must be non-empty")
        if not platform:
            raise ValueError("platform must be non-empty")
        ts = int(fetched_at if fetched_at is not None else time.time())
        with self._lock, self._connect() as c:
            c.execute(
                "INSERT OR REPLACE INTO popularity "
                "(track_id, platform, raw_count, log_count, percentile, fetched_at, "
                "match_method, match_confidence) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    track_id,
                    platform,
                    raw_count,
                    log_count,
                    percentile,
                    ts,
                    match_method,
                    match_confidence,
                ),
            )

    def get(self, track_id: str, platform: Platform | str) -> dict[str, Any] | None:
        """Fetch one row, or ``None``."""
        with self._connect() as c:
            row = c.execute(
                "SELECT * FROM popularity WHERE track_id = ? AND platform = ?",
                (track_id, platform),
            ).fetchone()
        return dict(row) if row is not None else None

    def get_all(self, track_id: str) -> list[dict[str, Any]]:
        """All platform rows for a track (the per-track breakdown panel)."""
        with self._connect() as c:
            rows = c.execute(
                "SELECT * FROM popularity WHERE track_id = ? ORDER BY platform",
                (track_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_stale(
        self, ttl_seconds: int = DEFAULT_TTL_SECONDS, *, now: int | None = None
    ) -> list[dict[str, Any]]:
        """Rows whose ``fetched_at`` is older than ``ttl_seconds`` (refresh queue)."""
        cutoff = int(now if now is not None else time.time()) - ttl_seconds
        with self._connect() as c:
            rows = c.execute(
                "SELECT * FROM popularity WHERE fetched_at < ? ORDER BY fetched_at",
                (cutoff,),
            ).fetchall()
        return [dict(r) for r in rows]

    def delete(self, track_id: str, platform: Platform | str | None = None) -> int:
        """Drop one platform row (or all rows for a track). Returns rows deleted."""
        with self._lock, self._connect() as c:
            if platform is None:
                cur = c.execute("DELETE FROM popularity WHERE track_id = ?", (track_id,))
            else:
                cur = c.execute(
                    "DELETE FROM popularity WHERE track_id = ? AND platform = ?",
                    (track_id, platform),
                )
            return cur.rowcount
