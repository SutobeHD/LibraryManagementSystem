"""metadata_fixer.schema — sidecar undo-log DB for the metadata fixer (T4).

The fixer mutates Rekordbox ``master.db`` rows + audio-file tags. Every mutation
is journalled to a SEPARATE sidecar DB (``metadata_fixer_log.db`` beside the
session-token, NOT inside ``master.db``) so a run can be reverted without going
through ``master.db``'s write path, and a leaked log exposes only metadata
snapshots — no tokens, no audio.

Two tables:

  * ``runs``      — one row per Apply batch (status + rule set + counts).
  * ``mutations`` — one row per journalled change; carries the full pre-image
                    (``DjmdContent`` row JSON + audio-file SHA-1) the applier
                    needs to revert the change byte-for-byte.

Since v2 a ``mutations`` row is not necessarily a per-track field edit: with
``entity_kind`` / ``entity_id`` / ``after_json`` it also journals whole-entity
mutations (an artist merge deleting a ``DjmdArtist`` row), which is why
``rule_id`` — a metadata-fixer concept — is nullable there.

Mirrors ``app/auth_db.py``: ``platformdirs`` user-data dir, WAL +
``synchronous=NORMAL``, per-thread connection, dedicated writer ``Lock``,
``MainProcess``-guarded init; schema evolution mirrors
``app/variant_schema.py``'s step-walking runner. Deliberately route-free —
``applier.py`` (T5) and the routes (T6) drive it.
"""

from __future__ import annotations

import json
import logging
import multiprocessing as _mp
import sqlite3
import threading
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from platformdirs import user_data_dir

logger = logging.getLogger("METADATA_FIXER_DB")

_APP_DIRNAME = "MusicLibraryManager"
_DB_FILENAME = "metadata_fixer_log.db"

#: Bumped whenever ``_MIGRATIONS`` grows a step.
SCHEMA_VERSION = 2

#: Run lifecycle states.
RUN_IN_PROGRESS = "in_progress"
RUN_COMPLETED = "completed"
RUN_REVERTED = "reverted"
RUN_REVERT_PARTIAL = "revert_partial"
RUN_FAILED = "failed"

#: ``mutations.entity_kind`` values. ``content`` = per-track field edit (the
#: metadata fixer's own shape, and the default every pre-v2 row migrates to).
ENTITY_CONTENT = "content"
ENTITY_ARTIST = "artist"

_local = threading.local()
_write_lock = threading.Lock()


def _db_path() -> Path:
    base = Path(user_data_dir(_APP_DIRNAME, appauthor=False, roaming=False))
    return base / _DB_FILENAME


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    conn.execute("PRAGMA foreign_keys=ON")
    _local.conn = conn
    return conn


# v1 base DDL — frozen. Shipped installs were created with exactly this; column
# changes belong in _MIGRATIONS so their rows keep reverting.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id         TEXT PRIMARY KEY,
    created_at     TEXT NOT NULL,
    status         TEXT NOT NULL,
    rule_ids       TEXT NOT NULL,            -- JSON array of active rule ids
    note           TEXT NOT NULL DEFAULT '',
    mutation_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS mutations (
    mutation_id  TEXT PRIMARY KEY,
    run_id       TEXT NOT NULL REFERENCES runs(run_id),
    content_id   TEXT NOT NULL,              -- Rekordbox DjmdContent id
    rule_id      INTEGER NOT NULL,
    field        TEXT NOT NULL,              -- which field changed (title/artist/...)
    before_value TEXT,
    after_value  TEXT,
    before_json  TEXT NOT NULL,              -- full DjmdContent row pre-image (revert)
    before_sha1  TEXT,                       -- audio-file hash before tag write
    after_sha1   TEXT,
    file_path    TEXT,
    reverted     INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mutations_run ON mutations(run_id);
"""

_META_DDL = """
CREATE TABLE IF NOT EXISTS fixer_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# v2 shape of `mutations`: entity-aware, rule_id nullable.
_MUTATIONS_V2_DDL = """
CREATE TABLE mutations_v2 (
    mutation_id  TEXT PRIMARY KEY,
    run_id       TEXT NOT NULL REFERENCES runs(run_id),
    content_id   TEXT,                       -- DjmdContent id; NULL only for entity rows
    entity_kind  TEXT NOT NULL DEFAULT 'content',
    entity_id    TEXT,                       -- NULL for content rows (they carry content_id)
    rule_id      INTEGER,                    -- fixer rule; NULL for entity mutations
    field        TEXT NOT NULL,
    before_value TEXT,
    after_value  TEXT,
    before_json  TEXT NOT NULL,              -- full row pre-image (revert)
    after_json   TEXT,                       -- post-image; lets a DELETE be re-INSERTed
    before_sha1  TEXT,
    after_sha1   TEXT,
    file_path    TEXT,
    reverted     INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL,
    CHECK (entity_kind <> 'content' OR content_id IS NOT NULL)
);
"""


def _schema_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT value FROM fixer_meta WHERE key = 'schema_version'").fetchone()
    if row is None:
        return 0
    return int(row[0])


def _set_schema_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO fixer_meta (key, value) VALUES ('schema_version', ?)",
        (str(version),),
    )


def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
    """Entity-aware ``mutations``: +entity_kind/entity_id/after_json, rule_id NULLable.

    SQLite cannot drop ``NOT NULL`` in place, so this is the documented 12-step
    table rebuild. Every v1 row is carried over as ``entity_kind='content'`` —
    runs journalled by the shipped name-fixer stay revertable.
    """
    conn.commit()
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(_MUTATIONS_V2_DDL)
        conn.execute(
            "INSERT INTO mutations_v2 (mutation_id, run_id, content_id, entity_kind, entity_id, "
            "rule_id, field, before_value, after_value, before_json, after_json, before_sha1, "
            "after_sha1, file_path, reverted, created_at) "
            "SELECT mutation_id, run_id, content_id, ?, NULL, rule_id, field, before_value, "
            "after_value, before_json, NULL, before_sha1, after_sha1, file_path, reverted, "
            "created_at FROM mutations",
            (ENTITY_CONTENT,),
        )
        conn.execute("DROP TABLE mutations")
        conn.execute("ALTER TABLE mutations_v2 RENAME TO mutations")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mutations_run ON mutations(run_id)")
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise sqlite3.IntegrityError(
                f"metadata_fixer_log.db v2 rebuild left {len(violations)} FK violations"
            )
        conn.commit()
    except sqlite3.Error:
        conn.rollback()
        raise
    finally:
        conn.execute("PRAGMA foreign_keys=ON")


# vN -> vN+1 steps, walked in order by migrate().
_MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {1: _migrate_v1_to_v2}


def migrate(conn: sqlite3.Connection) -> int:
    """Bring ``conn`` to ``SCHEMA_VERSION``. Idempotent; returns the resulting version.

    A DB without a version stamp is v1 — either freshly created from ``_SCHEMA``
    or an install that predates versioning; both walk the same steps. A DB newer
    than the code is left alone (logged) so a downgrade can't corrupt rows.

    Caller holds ``_write_lock`` (it is a plain ``Lock``, so this must not take it).
    """
    conn.executescript(_META_DDL)
    current = _schema_version(conn)

    if current == 0:
        current = 1
        _set_schema_version(conn, current)
        conn.commit()
    if current > SCHEMA_VERSION:
        logger.warning(
            "metadata_fixer_log.db schema_version=%d newer than code SCHEMA_VERSION=%d; "
            "leaving as-is",
            current,
            SCHEMA_VERSION,
        )
        return current

    while current < SCHEMA_VERSION:
        step = _MIGRATIONS.get(current)
        if step is None:
            raise RuntimeError(f"no migration path from metadata-fixer schema v{current}")
        step(conn)
        current += 1
        _set_schema_version(conn, current)
        conn.commit()
    return current


def init_db() -> None:
    """Idempotent schema create + migrate. Safe to call repeatedly; main-process only."""
    if _mp.current_process().name != "MainProcess":
        return
    with _write_lock:
        conn = _connect()
        conn.executescript(_SCHEMA)
        conn.commit()
        migrate(conn)


def create_run(rule_ids: list[int], note: str = "") -> str:
    """Open a new fix run; returns its ``run_id``. Status starts in-progress."""
    run_id = uuid.uuid4().hex
    with _write_lock:
        conn = _connect()
        conn.execute(
            "INSERT INTO runs (run_id, created_at, status, rule_ids, note, mutation_count) "
            "VALUES (?, ?, ?, ?, ?, 0)",
            (run_id, _now_iso(), RUN_IN_PROGRESS, json.dumps(sorted(rule_ids)), note),
        )
        conn.commit()
    return run_id


def record_mutation(
    run_id: str,
    content_id: str | None,
    rule_id: int | None,
    field: str,
    *,
    before_value: str | None,
    after_value: str | None,
    before_json: dict[str, object],
    after_json: dict[str, object] | None = None,
    entity_kind: str = ENTITY_CONTENT,
    entity_id: str | None = None,
    before_sha1: str | None = None,
    after_sha1: str | None = None,
    file_path: str | None = None,
) -> str:
    """Journal one applied mutation with its full pre-image; bump the run count.

    ``entity_kind='content'`` (default) is a per-track field edit and needs
    ``content_id``. Any other kind is a whole-entity mutation keyed by
    ``entity_id``; journal the removed row in ``before_json`` (and/or
    ``after_json``) so :func:`applier.revert_run` can re-INSERT it.
    """
    mutation_id = uuid.uuid4().hex
    with _write_lock:
        conn = _connect()
        conn.execute(
            "INSERT INTO mutations (mutation_id, run_id, content_id, entity_kind, entity_id, "
            "rule_id, field, before_value, after_value, before_json, after_json, before_sha1, "
            "after_sha1, file_path, reverted, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)",
            (
                mutation_id,
                run_id,
                content_id,
                entity_kind,
                entity_id,
                rule_id,
                field,
                before_value,
                after_value,
                json.dumps(before_json),
                None if after_json is None else json.dumps(after_json),
                before_sha1,
                after_sha1,
                file_path,
                _now_iso(),
            ),
        )
        conn.execute(
            "UPDATE runs SET mutation_count = mutation_count + 1 WHERE run_id = ?",
            (run_id,),
        )
        conn.commit()
    return mutation_id


def set_run_status(run_id: str, status: str) -> None:
    """Transition a run (completed / reverted / failed)."""
    with _write_lock:
        conn = _connect()
        conn.execute("UPDATE runs SET status = ? WHERE run_id = ?", (status, run_id))
        conn.commit()


def mark_mutation_reverted(mutation_id: str) -> bool:
    """Flag one mutation reverted. True if a row flipped (not already reverted)."""
    with _write_lock:
        conn = _connect()
        cur = conn.execute(
            "UPDATE mutations SET reverted = 1 WHERE mutation_id = ? AND reverted = 0",
            (mutation_id,),
        )
        conn.commit()
        return cur.rowcount > 0


def _run_row(r: sqlite3.Row) -> dict[str, object]:
    return {
        "run_id": r["run_id"],
        "created_at": r["created_at"],
        "status": r["status"],
        "rule_ids": json.loads(r["rule_ids"]),
        "note": r["note"],
        "mutation_count": r["mutation_count"],
    }


def get_run(run_id: str) -> dict[str, object] | None:
    """Fetch one run, or ``None``."""
    conn = _connect()
    row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    return _run_row(row) if row is not None else None


def list_runs() -> list[dict[str, object]]:
    """All runs, newest first (the ``GET /runs`` surface)."""
    conn = _connect()
    rows = conn.execute("SELECT * FROM runs ORDER BY created_at DESC, rowid DESC").fetchall()
    return [_run_row(r) for r in rows]


def get_mutations(run_id: str, *, reverse: bool = False) -> list[dict[str, object]]:
    """Mutations of a run; ``reverse=True`` orders newest-first for undo replay."""
    conn = _connect()
    order = "DESC" if reverse else "ASC"
    rows = conn.execute(
        f"SELECT * FROM mutations WHERE run_id = ? ORDER BY created_at {order}, rowid {order}",
        (run_id,),
    ).fetchall()
    return [
        {
            "mutation_id": r["mutation_id"],
            "run_id": r["run_id"],
            "content_id": r["content_id"],
            "entity_kind": r["entity_kind"],
            "entity_id": r["entity_id"],
            "rule_id": r["rule_id"],
            "field": r["field"],
            "before_value": r["before_value"],
            "after_value": r["after_value"],
            "before_json": json.loads(r["before_json"]),
            "after_json": None if r["after_json"] is None else json.loads(r["after_json"]),
            "before_sha1": r["before_sha1"],
            "after_sha1": r["after_sha1"],
            "file_path": r["file_path"],
            "reverted": bool(r["reverted"]),
            "created_at": r["created_at"],
        }
        for r in rows
    ]
