"""variant_schema — DDL + idempotent migration runner for the variants sidecar.

Owns the schema of ``variants.db`` (the remix/variant-relation sidecar; see
analysis-remix-detector). Kept separate from ``variant_detector`` so the schema
can be migrated/tested without booting the classifier.

Sidecar, NOT Rekordbox ``master.db`` — relations live decoupled from rbox writes,
so no ``_db_write_lock`` and rollback is ``rm variants.db``. ``migrate(conn)`` is
idempotent: safe to call on every open. Future versions add tables additively
(v2 ``variants_fp_staging``, v3 ``acoustid_cache``).
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

_DDL_V1 = """
CREATE TABLE IF NOT EXISTS track_variants (
  track_id        INTEGER NOT NULL,        -- Rekordbox DjmdContent.ID
  variant_label   TEXT    NOT NULL,        -- VersionTag.label enum (12 members)
  normalised_root TEXT    NOT NULL,        -- post feat-strip + casefold grouping key
  remixer         TEXT,                    -- parsed from tail-parenthetical, nullable
  parent_track_id INTEGER,                 -- canonical original; NULL = is-canonical/unknown
  confidence      REAL    NOT NULL,        -- [0.0, 1.0]
  source          TEXT    NOT NULL,        -- 'title-regex'|'rust-fp-cluster'|'acoustid-cluster'|'mb-relation'
  computed_at     TEXT    NOT NULL,        -- ISO-8601
  is_canonical    INTEGER NOT NULL DEFAULT 0,  -- user-pinned override (OQ2)
  PRIMARY KEY (track_id, source, parent_track_id)
);
CREATE INDEX IF NOT EXISTS ix_variants_root ON track_variants(normalised_root);
CREATE INDEX IF NOT EXISTS ix_variants_parent ON track_variants(parent_track_id);
CREATE TABLE IF NOT EXISTS variant_meta (
  key TEXT PRIMARY KEY, value TEXT NOT NULL
);
"""


def _schema_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT value FROM variant_meta WHERE key = 'schema_version'").fetchone()
    if row is None:
        return 0
    return int(row[0])


def _set_schema_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO variant_meta (key, value) VALUES ('schema_version', ?)",
        (str(version),),
    )


def migrate(conn: sqlite3.Connection) -> int:
    """Bring ``conn`` to ``SCHEMA_VERSION``. Idempotent. Returns the resulting version.

    A fresh DB gets the current tables created and is stamped directly. An existing
    DB walks ``_migrate_vN`` steps forward. A DB newer than the code is left alone
    (logged) so a downgrade can't silently corrupt rows.
    """
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_DDL_V1)
    current = _schema_version(conn)

    if current == 0:
        _set_schema_version(conn, SCHEMA_VERSION)
        conn.commit()
        return SCHEMA_VERSION
    if current > SCHEMA_VERSION:
        logger.warning(
            "variants.db schema_version=%d newer than code SCHEMA_VERSION=%d; leaving as-is",
            current,
            SCHEMA_VERSION,
        )
        return current

    while current < SCHEMA_VERSION:
        step = _MIGRATIONS.get(current)
        if step is None:
            raise RuntimeError(f"no migration path from variants schema v{current}")
        step(conn)
        current += 1
        _set_schema_version(conn, current)
    conn.commit()
    return current


# vN -> vN+1 migration steps. Empty at v1; v2 adds variants_fp_staging,
# v3 adds acoustid_cache (both additive — register here when M2/M3 land).
_MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {}
