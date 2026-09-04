"""artist_store.schema — sidecar DB + migration runner for the Artist Hub (T-3).

``artists.db`` owns everything Rekordbox has no place for: favourite collections,
the alias groups a merge collapses, the SoundCloud binding, per-collection sync
state, the ``collection -> Rekordbox playlist`` id-map and the catalogue TTL cache.

Sidecar, NOT Rekordbox ``master.db``. Writes serialise on a module-private lock;
``app/database.py:_db_write_lock`` is never touched from here — that one belongs to
rbox alone. Feature rollback is ``rm artists.db``: no library data lives here.

``kind`` is generic on purpose. Only ``artist`` ships now; label / genre / setlist
are the same rows with a different ``kind``, so the follow-up doc is a projection
rule, not a schema rewrite. ``(kind, sort_key)`` is indexed for that reason.

Pattern mirrors ``app/auth_db.py`` (platformdirs path, per-thread connection, WAL +
``synchronous=NORMAL``) and ``app/variant_schema.py`` (``SCHEMA_VERSION`` +
step-walking ``migrate()`` with a downgrade guard). Deliberately route-free —
``registry.py`` / ``merge.py`` / ``projection.py`` drive it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import multiprocessing as _mp
import re
import sqlite3
import threading
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from platformdirs import user_data_dir

logger = logging.getLogger("ARTIST_STORE")

_APP_DIRNAME = "MusicLibraryManager"
_DB_FILENAME = "artists.db"

SCHEMA_VERSION = 1

KIND_ARTIST = "artist"

#: Per-collection sync behaviour (Settings: Auto / Review / Off).
SYNC_AUTO = "auto"
SYNC_REVIEW = "review"
SYNC_OFF = "off"
SYNC_MODES = frozenset({SYNC_AUTO, SYNC_REVIEW, SYNC_OFF})

#: Id prefix per kind. Deliberately NOT ``art_`` — that is the UI's unstable
#: list-index id (``app/live_database.py``) and the two must never look alike.
_KIND_PREFIX = {KIND_ARTIST: "a", "label": "l", "genre": "g", "setlist": "s"}

_WS_RUN = re.compile(r"\s+")

_local = threading.local()
_write_lock = threading.Lock()
_init_lock = threading.Lock()
_initialised = False


def _db_path() -> Path:
    base = Path(user_data_dir(_APP_DIRNAME, appauthor=False, roaming=False))
    return base / _DB_FILENAME


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fold(name: str) -> str:
    """Case- and whitespace-insensitive form used for ids, sort keys and lookups."""
    return _WS_RUN.sub(" ", name).strip().casefold()


def collection_id_for(canonical_name: str, kind: str = KIND_ARTIST) -> str:
    """Our own stable id for a collection, derived from ``kind`` + the folded name.

    Never key on the library's artist ids: ``art_{i}`` is a position in a sorted list
    that is rebuilt on every library load (``app/live_database.py``), so a store keyed
    on it silently repoints to a different artist after the next scan. Folding case and
    whitespace means re-casing a canonical name (``boys noize`` -> ``Boys Noize``) keeps
    the same id, so favourites, links and the Rekordbox id-map survive a merge.
    """
    folded = _fold(canonical_name)
    if not folded:
        raise ValueError("canonical_name must contain a non-space character")
    if not kind:
        raise ValueError("kind must be non-empty")
    digest = hashlib.sha256(f"{kind}\x00{folded}".encode()).hexdigest()[:12]
    return f"{_KIND_PREFIX.get(kind, kind[:1].casefold())}_{digest}"


def sort_key_for(canonical_name: str) -> str:
    """Default ordering key — folded name, so ``(kind, sort_key)`` sorts naturally."""
    return _fold(canonical_name)


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


_DDL_V1 = """
CREATE TABLE IF NOT EXISTS collections (
    id             TEXT PRIMARY KEY,              -- collection_id_for(), never art_{i}
    kind           TEXT NOT NULL DEFAULT 'artist',
    canonical_name TEXT NOT NULL,
    sort_key       TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_collections_kind_sort ON collections(kind, sort_key);
CREATE TABLE IF NOT EXISTS aliases (
    collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    alias         TEXT NOT NULL,                  -- raw library variant string
    source        TEXT,                           -- 'canonical'|'merge'|'import'|'user'
    PRIMARY KEY (collection_id, alias)
);
CREATE INDEX IF NOT EXISTS ix_aliases_alias ON aliases(alias);
CREATE TABLE IF NOT EXISTS links (
    collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    provider      TEXT NOT NULL,                  -- 'soundcloud'|...
    remote_id     TEXT,                           -- URN, e.g. soundcloud:users:1234567
    permalink     TEXT,
    confidence    REAL,
    PRIMARY KEY (collection_id, provider)
);
CREATE TABLE IF NOT EXISTS sync_state (
    collection_id TEXT PRIMARY KEY REFERENCES collections(id) ON DELETE CASCADE,
    mode          TEXT NOT NULL DEFAULT 'review',
    last_sync_at  TEXT,
    last_error    TEXT
);
CREATE TABLE IF NOT EXISTS projection (
    collection_id     TEXT PRIMARY KEY REFERENCES collections(id) ON DELETE CASCADE,
    rb_playlist_id    TEXT,                       -- verified per sync; RB has no uniqueness
    rb_uuid           TEXT,
    last_projected_at TEXT
);
CREATE TABLE IF NOT EXISTS catalogue_cache (
    collection_id TEXT PRIMARY KEY REFERENCES collections(id) ON DELETE CASCADE,
    payload_json  TEXT NOT NULL,
    fetched_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS favourites (
    collection_id TEXT PRIMARY KEY REFERENCES collections(id) ON DELETE CASCADE,
    added_at      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS store_meta (
    key TEXT PRIMARY KEY, value TEXT NOT NULL
);
"""


def _schema_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT value FROM store_meta WHERE key = 'schema_version'").fetchone()
    if row is None:
        return 0
    return int(row[0])


def _set_schema_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO store_meta (key, value) VALUES ('schema_version', ?)",
        (str(version),),
    )


# vN -> vN+1 steps. Empty at v1; register additive steps here as the feature grows.
_MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {}


def migrate(conn: sqlite3.Connection) -> int:
    """Bring ``conn`` to ``SCHEMA_VERSION``. Idempotent. Returns the resulting version.

    A fresh DB gets the current tables and is stamped directly. An existing DB walks
    ``_MIGRATIONS`` forward one step at a time. A DB newer than the code is left alone
    (logged) so a downgrade cannot silently corrupt rows.
    """
    conn.executescript(_DDL_V1)
    current = _schema_version(conn)

    if current == 0:
        _set_schema_version(conn, SCHEMA_VERSION)
        conn.commit()
        return SCHEMA_VERSION
    if current > SCHEMA_VERSION:
        logger.warning(
            "artists.db schema_version=%d newer than code SCHEMA_VERSION=%d; leaving as-is",
            current,
            SCHEMA_VERSION,
        )
        return current

    while current < SCHEMA_VERSION:
        step = _MIGRATIONS.get(current)
        if step is None:
            raise RuntimeError(f"no migration path from artist-store schema v{current}")
        step(conn)
        current += 1
        _set_schema_version(conn, current)
    conn.commit()
    return current


def _ensure_schema() -> sqlite3.Connection:
    """Connection whose file is at ``SCHEMA_VERSION``. Migrates once per process."""
    global _initialised
    conn = _connect()
    if _initialised:
        return conn
    with _init_lock:
        if not _initialised:
            with _write_lock:
                migrate(conn)
            _initialised = True
    return conn


def init_db() -> None:
    """Eager, idempotent schema create for sidecar boot. Main-process only.

    Workers (``SafeAnlzParser``'s pool) never own this DB; they would only race the
    boot migration. Lazy callers still get a migrated connection via ``_ensure_schema``.
    """
    if _mp.current_process().name != "MainProcess":
        return
    _ensure_schema()


# --------------------------------------------------------------------------- collections


def create_collection(
    canonical_name: str,
    kind: str = KIND_ARTIST,
    sort_key: str | None = None,
) -> str:
    """Create (or adopt) the collection for ``canonical_name``; returns its id.

    Idempotent: the id is derived, so a second call with a differently-cased name
    returns the same row. The canonical name is also stored as an alias — alias rows
    are what let several raw library strings resolve to one collection after a merge.
    """
    name = _WS_RUN.sub(" ", canonical_name).strip()
    cid = collection_id_for(name, kind)
    now = _now_iso()
    conn = _ensure_schema()
    with _write_lock:
        conn.execute(
            "INSERT OR IGNORE INTO collections "
            "(id, kind, canonical_name, sort_key, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (cid, kind, name, sort_key or sort_key_for(name), now, now),
        )
        conn.execute(
            "INSERT OR IGNORE INTO aliases (collection_id, alias, source) VALUES (?, ?, 'canonical')",
            (cid, name),
        )
        conn.commit()
    return cid


def get_collection(collection_id: str) -> dict[str, Any] | None:
    conn = _ensure_schema()
    row = conn.execute("SELECT * FROM collections WHERE id = ?", (collection_id,)).fetchone()
    return dict(row) if row is not None else None


def get_collection_by_name(canonical_name: str, kind: str = KIND_ARTIST) -> dict[str, Any] | None:
    """Lookup by derived id — case/whitespace-insensitive by construction."""
    return get_collection(collection_id_for(canonical_name, kind))


def list_collections(kind: str | None = KIND_ARTIST) -> list[dict[str, Any]]:
    conn = _ensure_schema()
    if kind is None:
        rows = conn.execute("SELECT * FROM collections ORDER BY kind, sort_key").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM collections WHERE kind = ? ORDER BY sort_key", (kind,)
        ).fetchall()
    return [dict(r) for r in rows]


def set_canonical_name(collection_id: str, canonical_name: str) -> bool:
    """Rename a collection in place, keeping its id and adding the old name as an alias.

    The id stays put deliberately: it is the key the Rekordbox id-map, the SC link and
    the favourites list hang off, so a rename must not mint a new one.
    """
    name = _WS_RUN.sub(" ", canonical_name).strip()
    if not name:
        raise ValueError("canonical_name must contain a non-space character")
    current = get_collection(collection_id)
    if current is None:
        return False
    conn = _ensure_schema()
    with _write_lock:
        conn.execute(
            "UPDATE collections SET canonical_name = ?, sort_key = ?, updated_at = ? WHERE id = ?",
            (name, sort_key_for(name), _now_iso(), collection_id),
        )
        conn.execute(
            "INSERT OR IGNORE INTO aliases (collection_id, alias, source) VALUES (?, ?, 'rename')",
            (collection_id, current["canonical_name"]),
        )
        conn.execute(
            "INSERT OR IGNORE INTO aliases (collection_id, alias, source) VALUES (?, ?, 'canonical')",
            (collection_id, name),
        )
        conn.commit()
    return True


def delete_collection(collection_id: str) -> bool:
    """Drop a collection and everything hanging off it (FK cascade)."""
    conn = _ensure_schema()
    with _write_lock:
        cur = conn.execute("DELETE FROM collections WHERE id = ?", (collection_id,))
        conn.commit()
    return cur.rowcount > 0


# --------------------------------------------------------------------------- aliases


def add_alias(collection_id: str, alias: str, source: str | None = None) -> bool:
    """Map a raw library artist string onto a collection. False if already mapped."""
    text = _WS_RUN.sub(" ", alias).strip()
    if not text:
        raise ValueError("alias must contain a non-space character")
    conn = _ensure_schema()
    with _write_lock:
        cur = conn.execute(
            "INSERT OR IGNORE INTO aliases (collection_id, alias, source) VALUES (?, ?, ?)",
            (collection_id, text, source),
        )
        conn.commit()
    return cur.rowcount > 0


def remove_alias(collection_id: str, alias: str) -> bool:
    conn = _ensure_schema()
    with _write_lock:
        cur = conn.execute(
            "DELETE FROM aliases WHERE collection_id = ? AND alias = ?",
            (collection_id, _WS_RUN.sub(" ", alias).strip()),
        )
        conn.commit()
    return cur.rowcount > 0


def list_aliases(collection_id: str) -> list[dict[str, Any]]:
    conn = _ensure_schema()
    rows = conn.execute(
        "SELECT collection_id, alias, source FROM aliases WHERE collection_id = ? ORDER BY alias",
        (collection_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def resolve_alias(alias: str, kind: str = KIND_ARTIST) -> dict[str, Any] | None:
    """Collection a raw library artist string belongs to, or None.

    Exact match first (index-backed), then a folded match — Rekordbox hands us the
    string as typed, and the whole point of the store is that ``BOYS NOIZE`` and
    ``boys noize`` land on the same collection.
    """
    text = _WS_RUN.sub(" ", alias).strip()
    if not text:
        return None
    conn = _ensure_schema()
    row = conn.execute(
        "SELECT c.* FROM aliases a JOIN collections c ON c.id = a.collection_id "
        "WHERE a.alias = ? AND c.kind = ?",
        (text, kind),
    ).fetchone()
    if row is not None:
        return dict(row)
    folded = _fold(text)
    for candidate in conn.execute(
        "SELECT c.*, a.alias AS _alias FROM aliases a JOIN collections c ON c.id = a.collection_id "
        "WHERE c.kind = ?",
        (kind,),
    ).fetchall():
        if _fold(candidate["_alias"]) == folded:
            row_dict = dict(candidate)
            row_dict.pop("_alias", None)
            return row_dict
    return None


# --------------------------------------------------------------------------- links


def set_link(
    collection_id: str,
    provider: str,
    remote_id: str | None = None,
    permalink: str | None = None,
    confidence: float | None = None,
) -> None:
    """Bind a collection to a provider account (SoundCloud today)."""
    conn = _ensure_schema()
    with _write_lock:
        conn.execute(
            "INSERT INTO links (collection_id, provider, remote_id, permalink, confidence) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(collection_id, provider) DO UPDATE SET "
            "remote_id = excluded.remote_id, permalink = excluded.permalink, "
            "confidence = excluded.confidence",
            (collection_id, provider, remote_id, permalink, confidence),
        )
        conn.commit()


def get_link(collection_id: str, provider: str) -> dict[str, Any] | None:
    conn = _ensure_schema()
    row = conn.execute(
        "SELECT * FROM links WHERE collection_id = ? AND provider = ?",
        (collection_id, provider),
    ).fetchone()
    return dict(row) if row is not None else None


def remove_link(collection_id: str, provider: str) -> bool:
    conn = _ensure_schema()
    with _write_lock:
        cur = conn.execute(
            "DELETE FROM links WHERE collection_id = ? AND provider = ?",
            (collection_id, provider),
        )
        conn.commit()
    return cur.rowcount > 0


# --------------------------------------------------------------------------- sync state


def set_sync_mode(collection_id: str, mode: str) -> None:
    if mode not in SYNC_MODES:
        raise ValueError(f"unknown sync mode {mode!r}; expected one of {sorted(SYNC_MODES)}")
    conn = _ensure_schema()
    with _write_lock:
        conn.execute(
            "INSERT INTO sync_state (collection_id, mode) VALUES (?, ?) "
            "ON CONFLICT(collection_id) DO UPDATE SET mode = excluded.mode",
            (collection_id, mode),
        )
        conn.commit()


def get_sync_mode(collection_id: str) -> str:
    """Sync mode, defaulting to ``review`` for a collection that has no row yet."""
    state = get_sync_state(collection_id)
    return SYNC_REVIEW if state is None else str(state["mode"])


def get_sync_state(collection_id: str) -> dict[str, Any] | None:
    conn = _ensure_schema()
    row = conn.execute(
        "SELECT * FROM sync_state WHERE collection_id = ?", (collection_id,)
    ).fetchone()
    return dict(row) if row is not None else None


def record_sync(collection_id: str, error: str | None = None) -> None:
    """Stamp a finished sync attempt. ``error=None`` clears the previous failure."""
    conn = _ensure_schema()
    with _write_lock:
        conn.execute(
            "INSERT INTO sync_state (collection_id, mode, last_sync_at, last_error) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(collection_id) DO UPDATE SET "
            "last_sync_at = excluded.last_sync_at, last_error = excluded.last_error",
            (collection_id, SYNC_REVIEW, _now_iso(), error),
        )
        conn.commit()


# --------------------------------------------------------------------------- projection


def set_projection(
    collection_id: str,
    rb_playlist_id: str | None,
    rb_uuid: str | None = None,
) -> None:
    """Remember which Rekordbox playlist represents this collection.

    Rekordbox enforces no uniqueness on playlist name/parent and ``get_playlist_by_path``
    silently returns the first duplicate, so this id-map — verified per sync — is the
    only reliable identity the projection engine has.
    """
    conn = _ensure_schema()
    with _write_lock:
        conn.execute(
            "INSERT INTO projection (collection_id, rb_playlist_id, rb_uuid, last_projected_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(collection_id) DO UPDATE SET "
            "rb_playlist_id = excluded.rb_playlist_id, rb_uuid = excluded.rb_uuid, "
            "last_projected_at = excluded.last_projected_at",
            (collection_id, rb_playlist_id, rb_uuid, _now_iso()),
        )
        conn.commit()


def get_projection(collection_id: str) -> dict[str, Any] | None:
    conn = _ensure_schema()
    row = conn.execute(
        "SELECT * FROM projection WHERE collection_id = ?", (collection_id,)
    ).fetchone()
    return dict(row) if row is not None else None


def clear_projection(collection_id: str) -> bool:
    conn = _ensure_schema()
    with _write_lock:
        cur = conn.execute("DELETE FROM projection WHERE collection_id = ?", (collection_id,))
        conn.commit()
    return cur.rowcount > 0


# --------------------------------------------------------------------------- favourites


def add_favourite(collection_id: str) -> bool:
    """Mark a collection as a favourite. False if it already was."""
    conn = _ensure_schema()
    with _write_lock:
        cur = conn.execute(
            "INSERT OR IGNORE INTO favourites (collection_id, added_at) VALUES (?, ?)",
            (collection_id, _now_iso()),
        )
        conn.commit()
    return cur.rowcount > 0


def remove_favourite(collection_id: str) -> bool:
    conn = _ensure_schema()
    with _write_lock:
        cur = conn.execute("DELETE FROM favourites WHERE collection_id = ?", (collection_id,))
        conn.commit()
    return cur.rowcount > 0


def is_favourite(collection_id: str) -> bool:
    conn = _ensure_schema()
    row = conn.execute(
        "SELECT 1 FROM favourites WHERE collection_id = ?", (collection_id,)
    ).fetchone()
    return row is not None


def list_favourites(kind: str | None = KIND_ARTIST) -> list[dict[str, Any]]:
    """Favourited collections with their ``added_at``, ordered like the artist list."""
    conn = _ensure_schema()
    base = "SELECT c.*, f.added_at FROM favourites f JOIN collections c ON c.id = f.collection_id "
    if kind is None:
        rows = conn.execute(base + "ORDER BY c.kind, c.sort_key").fetchall()
    else:
        rows = conn.execute(base + "WHERE c.kind = ? ORDER BY c.sort_key", (kind,)).fetchall()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------- catalogue cache


def set_catalogue_cache(collection_id: str, payload: Any) -> None:
    """Store a fetched provider catalogue. TTL cache, never a permanent mirror."""
    conn = _ensure_schema()
    with _write_lock:
        conn.execute(
            "INSERT INTO catalogue_cache (collection_id, payload_json, fetched_at) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(collection_id) DO UPDATE SET "
            "payload_json = excluded.payload_json, fetched_at = excluded.fetched_at",
            (collection_id, json.dumps(payload), _now_iso()),
        )
        conn.commit()


def get_catalogue_cache(collection_id: str, max_age_s: float | None = None) -> Any | None:
    """Cached catalogue payload, or None when absent, unparseable or older than the TTL."""
    conn = _ensure_schema()
    row = conn.execute(
        "SELECT payload_json, fetched_at FROM catalogue_cache WHERE collection_id = ?",
        (collection_id,),
    ).fetchone()
    if row is None:
        return None
    if max_age_s is not None:
        try:
            age = (
                datetime.now(timezone.utc) - datetime.fromisoformat(row["fetched_at"])
            ).total_seconds()
        except (TypeError, ValueError) as e:
            logger.warning(
                "artist_store cache timestamp unparseable id=%s err=%s", collection_id, e
            )
            return None
        if age > max_age_s:
            return None
    try:
        return json.loads(row["payload_json"])
    except (TypeError, json.JSONDecodeError) as e:
        logger.warning("artist_store cache payload unreadable id=%s err=%s", collection_id, e)
        return None
