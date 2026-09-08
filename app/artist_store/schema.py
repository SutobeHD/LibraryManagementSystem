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
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from platformdirs import user_data_dir

logger = logging.getLogger("ARTIST_STORE")

_APP_DIRNAME = "MusicLibraryManager"
_DB_FILENAME = "artists.db"

SCHEMA_VERSION = 2

KIND_ARTIST = "artist"

#: Roles a fetched track can hold for ONE artist (``track_identity.role`` and
#: ``user_override``). Defined here, not in ``identity.py``, because the store must
#: refuse a value the classifier does not know — and ``identity`` imports this module.
ROLE_PRIMARY = "primary"
ROLE_REMIXER = "remixer"
ROLE_REMIXED_BY_OTHER = "remixed_by_other"
ROLE_FEATURED = "featured"
ROLE_UNCERTAIN = "uncertain"
IDENTITY_ROLES = frozenset(
    {ROLE_PRIMARY, ROLE_REMIXER, ROLE_REMIXED_BY_OTHER, ROLE_FEATURED, ROLE_UNCERTAIN}
)

CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"
IDENTITY_CONFIDENCES = frozenset({CONFIDENCE_HIGH, CONFIDENCE_MEDIUM, CONFIDENCE_LOW})

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


# v2: the owner's "local file with artist id + universal track id". One row per
# (collection, SoundCloud track): the role the classifier gave the track FOR THAT
# artist, and the role the user pinned over it. ``isrc`` is the universal id when the
# upload carries one; ``sc_urn`` is the fallback key. The key is composite on purpose:
# "Bangarang (Boys Noize Remix)" is ``remixer`` for Boys Noize and ``remixed_by_other``
# for Skrillex, and a per-track primary key could hold only one of those verdicts.
_DDL_V2_TRACK_IDENTITY = """
CREATE TABLE IF NOT EXISTS track_identity (
    sc_urn        TEXT NOT NULL,                  -- soundcloud:tracks:<id>
    collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    isrc          TEXT,                           -- normalised (upper, no dashes) or NULL
    title         TEXT,
    uploader_urn  TEXT,
    role          TEXT NOT NULL,                  -- classifier verdict, see IDENTITY_ROLES
    confidence    TEXT NOT NULL,                  -- high|medium|low
    first_seen    TEXT NOT NULL,
    last_seen     TEXT NOT NULL,
    user_override TEXT,                           -- pinned role; wins over `role`
    PRIMARY KEY (collection_id, sc_urn)
);
CREATE INDEX IF NOT EXISTS ix_track_identity_collection ON track_identity(collection_id);
CREATE INDEX IF NOT EXISTS ix_track_identity_isrc ON track_identity(isrc);
"""


def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
    conn.executescript(_DDL_V2_TRACK_IDENTITY)


# vN -> vN+1 steps. Additive only — the base DDL above is frozen (users already hold a
# v1 file), so every later table arrives through a step here.
_MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {1: _migrate_v1_to_v2}


def migrate(conn: sqlite3.Connection) -> int:
    """Bring ``conn`` to ``SCHEMA_VERSION``. Idempotent. Returns the resulting version.

    A fresh DB gets the v1 tables, is stamped v1 and then walks the same
    ``_MIGRATIONS`` steps an existing file would — one code path for both, so a step
    cannot be forgotten on the fresh side. A DB newer than the code is left alone
    (logged) so a downgrade cannot silently corrupt rows.
    """
    conn.executescript(_DDL_V1)
    current = _schema_version(conn)

    if current == 0:
        current = 1
        _set_schema_version(conn, current)
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


# --------------------------------------------------------------------------- store meta

#: Owned by the migration runner — not writable through ``set_meta``.
_RESERVED_META_KEYS = frozenset({"schema_version"})


def set_meta(key: str, value: str) -> None:
    """Store one process-wide scalar (e.g. the projection's root-folder id)."""
    if key in _RESERVED_META_KEYS:
        raise ValueError(f"{key!r} is owned by the migration runner")
    conn = _ensure_schema()
    with _write_lock:
        conn.execute(
            "INSERT OR REPLACE INTO store_meta (key, value) VALUES (?, ?)", (key, str(value))
        )
        conn.commit()


def get_meta(key: str) -> str | None:
    conn = _ensure_schema()
    row = conn.execute("SELECT value FROM store_meta WHERE key = ?", (key,)).fetchone()
    return str(row[0]) if row is not None else None


def delete_meta(key: str) -> bool:
    if key in _RESERVED_META_KEYS:
        raise ValueError(f"{key!r} is owned by the migration runner")
    conn = _ensure_schema()
    with _write_lock:
        cur = conn.execute("DELETE FROM store_meta WHERE key = ?", (key,))
        conn.commit()
    return cur.rowcount > 0


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


# --------------------------------------------------------------------------- track identity


def _check_role(role: str, *, field_name: str = "role") -> str:
    if role not in IDENTITY_ROLES:
        raise ValueError(f"unknown {field_name} {role!r}; expected one of {sorted(IDENTITY_ROLES)}")
    return role


def _check_confidence(confidence: str) -> str:
    if confidence not in IDENTITY_CONFIDENCES:
        raise ValueError(
            f"unknown confidence {confidence!r}; expected one of {sorted(IDENTITY_CONFIDENCES)}"
        )
    return confidence


def _identity_row(collection_id: str, entry: Mapping[str, Any], now: str) -> tuple[Any, ...] | None:
    sc_urn = str(entry.get("sc_urn") or entry.get("sc_id") or "").strip()
    if not sc_urn:
        return None
    role = _check_role(str(entry.get("role") or ""))
    confidence = _check_confidence(str(entry.get("confidence") or ""))
    isrc = str(entry.get("isrc") or "").strip() or None
    title = str(entry.get("title") or "").strip() or None
    uploader_urn = str(entry.get("uploader_urn") or "").strip() or None
    return (sc_urn, collection_id, isrc, title, uploader_urn, role, confidence, now, now)


_UPSERT_IDENTITY_SQL = (
    "INSERT INTO track_identity "
    "(sc_urn, collection_id, isrc, title, uploader_urn, role, confidence, first_seen, last_seen) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
    "ON CONFLICT(collection_id, sc_urn) DO UPDATE SET "
    "isrc = excluded.isrc, title = excluded.title, uploader_urn = excluded.uploader_urn, "
    "role = excluded.role, confidence = excluded.confidence, last_seen = excluded.last_seen"
)


def upsert_track_identities(collection_id: str, entries: Iterable[Mapping[str, Any]]) -> int:
    """Remember the classifier's verdict for each track of one collection.

    One transaction under the module lock. ``first_seen`` and ``user_override`` are
    never touched by an upsert — the first is history, the second is the user's
    decision and the classifier has no say over it. ``last_seen`` is refreshed.
    Rows without an ``sc_urn``/``sc_id`` are skipped. Returns the number of rows written.
    """
    now = _now_iso()
    rows = [r for r in (_identity_row(collection_id, e, now) for e in entries) if r is not None]
    if not rows:
        return 0
    conn = _ensure_schema()
    with _write_lock:
        conn.executemany(_UPSERT_IDENTITY_SQL, rows)
        conn.commit()
    return len(rows)


def upsert_track_identity(
    collection_id: str,
    sc_urn: str,
    *,
    role: str,
    confidence: str,
    isrc: str | None = None,
    title: str | None = None,
    uploader_urn: str | None = None,
) -> bool:
    """Single-row form of :func:`upsert_track_identities`. True when a row was written."""
    return (
        upsert_track_identities(
            collection_id,
            [
                {
                    "sc_urn": sc_urn,
                    "role": role,
                    "confidence": confidence,
                    "isrc": isrc,
                    "title": title,
                    "uploader_urn": uploader_urn,
                }
            ],
        )
        == 1
    )


def get_track_identity(collection_id: str, sc_urn: str) -> dict[str, Any] | None:
    conn = _ensure_schema()
    row = conn.execute(
        "SELECT * FROM track_identity WHERE collection_id = ? AND sc_urn = ?",
        (collection_id, sc_urn),
    ).fetchone()
    return dict(row) if row is not None else None


def list_track_identities(collection_id: str) -> list[dict[str, Any]]:
    conn = _ensure_schema()
    rows = conn.execute(
        "SELECT * FROM track_identity WHERE collection_id = ? ORDER BY last_seen DESC, sc_urn",
        (collection_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def find_track_identities_by_isrc(isrc: str) -> list[dict[str, Any]]:
    """Every remembered row carrying this ISRC, across collections (index-backed)."""
    text = str(isrc or "").strip()
    if not text:
        return []
    conn = _ensure_schema()
    rows = conn.execute(
        "SELECT * FROM track_identity WHERE isrc = ? ORDER BY collection_id, sc_urn", (text,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_identity_overrides(collection_id: str) -> dict[str, str]:
    """``sc_urn -> pinned role`` for one collection — what the classifier must yield to."""
    conn = _ensure_schema()
    rows = conn.execute(
        "SELECT sc_urn, user_override FROM track_identity "
        "WHERE collection_id = ? AND user_override IS NOT NULL",
        (collection_id,),
    ).fetchall()
    return {str(r["sc_urn"]): str(r["user_override"]) for r in rows}


def set_identity_override(collection_id: str, sc_urn: str, role: str | None) -> bool:
    """Pin (or with ``None`` unpin) the role of one track for one artist.

    This is what "manual" means for a wrongly-classified track. A pin on a track the
    store has never seen is refused (False) rather than inventing a row with a made-up
    classifier verdict — the row appears once the catalogue has been classified.
    """
    if role is not None:
        _check_role(role, field_name="override")
    conn = _ensure_schema()
    with _write_lock:
        cur = conn.execute(
            "UPDATE track_identity SET user_override = ? WHERE collection_id = ? AND sc_urn = ?",
            (role, collection_id, sc_urn),
        )
        conn.commit()
    return cur.rowcount > 0


def delete_track_identity(collection_id: str, sc_urn: str) -> bool:
    conn = _ensure_schema()
    with _write_lock:
        cur = conn.execute(
            "DELETE FROM track_identity WHERE collection_id = ? AND sc_urn = ?",
            (collection_id, sc_urn),
        )
        conn.commit()
    return cur.rowcount > 0
