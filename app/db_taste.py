"""db_taste — sidecar store for per-user taste vectors (recommender-taste-llm M1, T1).

The taste recommender ranks tracks by cosine distance to a user's *taste vector*
— a recency-weighted centroid (and, later, mood-cluster centroids) of the tracks
they like. This module owns the persistence of those vectors.

Storage: a ``user_taste_vectors`` **sibling** table inside the sister doc's
``app_data/track_vectors.db`` (``recommender-similar-tracks`` owns the
``track_vectors`` table + the file shape; this module only adds its own table).
It is a sidecar SQLite file — NOT Rekordbox ``master.db`` — so it needs no
``_db_write_lock`` and a leaked file exposes only opaque vector blobs.

Vectors are stored as opaque ``BLOB`` bytes; serialisation (``np.ndarray`` →
bytes) is the caller's job (``taste_profile.py``, T2), keeping this module
dependency-free (stdlib ``sqlite3`` only, mirroring ``app/download_registry.py``).

Writes are atomic single-statement ``INSERT OR REPLACE`` keyed on
``(profile_id, kind)`` — refreshing a profile overwrites in place.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Taste-vector kinds. ``centroid`` ships in M1; the cluster kinds are reserved
#: for M2 mood-cluster centroids (schema accepts them now, no consumer yet).
VALID_KINDS: frozenset[str] = frozenset({"centroid", "cluster_0", "cluster_1", "cluster_2"})

#: Lazy-resolved; shares the sister doc's vector DB file.
_TASTE_DB: Path | None = None


def _db_path() -> Path:
    global _TASTE_DB
    if _TASTE_DB is None:
        base = Path("app_data")
        base.mkdir(parents=True, exist_ok=True)
        _TASTE_DB = base / "track_vectors.db"
    return _TASTE_DB


def _conn() -> sqlite3.Connection:
    """Open a WAL-mode connection with Row factory (per-call, like download_registry)."""
    c = sqlite3.connect(str(_db_path()), check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")  # concurrent reads while writing
    c.execute("PRAGMA synchronous=NORMAL")  # durability/speed balance for a sidecar
    return c


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_taste_db() -> None:
    """Create the ``user_taste_vectors`` table if absent. Idempotent; call at startup."""
    with _conn() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS user_taste_vectors (
                profile_id      TEXT      NOT NULL,
                kind            TEXT      NOT NULL,
                vector_blob     BLOB      NOT NULL,
                n_source_tracks INTEGER   NOT NULL,
                computed_at     TIMESTAMP NOT NULL,
                PRIMARY KEY (profile_id, kind)
            )
            """
        )


def upsert_taste_vector(
    profile_id: str,
    kind: str,
    vector_blob: bytes,
    n_source_tracks: int,
) -> None:
    """Atomically write (or overwrite) one taste vector.

    ``vector_blob`` is opaque bytes (caller serialises). ``kind`` must be one of
    :data:`VALID_KINDS`. ``computed_at`` is stamped here (UTC ISO-8601).
    """
    if kind not in VALID_KINDS:
        raise ValueError(f"unknown taste-vector kind: {kind!r} (allowed: {sorted(VALID_KINDS)})")
    if not profile_id:
        raise ValueError("profile_id must be non-empty")
    with _conn() as db:
        db.execute(
            "INSERT OR REPLACE INTO user_taste_vectors "
            "(profile_id, kind, vector_blob, n_source_tracks, computed_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (profile_id, kind, sqlite3.Binary(vector_blob), int(n_source_tracks), _now_iso()),
        )


def _row_to_dict(r: sqlite3.Row) -> dict[str, Any]:
    return {
        "profile_id": r["profile_id"],
        "kind": r["kind"],
        "vector_blob": bytes(r["vector_blob"]),
        "n_source_tracks": r["n_source_tracks"],
        "computed_at": r["computed_at"],
    }


def get_taste_vector(profile_id: str, kind: str = "centroid") -> dict[str, Any] | None:
    """Fetch one stored taste vector, or ``None`` if absent."""
    with _conn() as db:
        row = db.execute(
            "SELECT * FROM user_taste_vectors WHERE profile_id = ? AND kind = ?",
            (profile_id, kind),
        ).fetchone()
    return _row_to_dict(row) if row is not None else None


def list_taste_vectors(profile_id: str) -> list[dict[str, Any]]:
    """All stored vectors for a profile (e.g. centroid + cluster kinds)."""
    with _conn() as db:
        rows = db.execute(
            "SELECT * FROM user_taste_vectors WHERE profile_id = ? ORDER BY kind",
            (profile_id,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def delete_profile(profile_id: str) -> int:
    """Drop all vectors for a profile. Returns rows deleted (rollback/reset helper)."""
    with _conn() as db:
        cur = db.execute("DELETE FROM user_taste_vectors WHERE profile_id = ?", (profile_id,))
        return cur.rowcount
