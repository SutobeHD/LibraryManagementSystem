"""artist_store.registry — library artists into the store, favourites, Tier-1 backlog (T-4).

Bridges the library's per-track artist strings to the sidecar's stable collection ids.
The UI's ``art_{i}`` ids are positions in a list that is rebuilt on every library load
(``app/live_database.py:_finalize_ui_metadata``), so nothing here keys on them: the
bridge is the NAME, folded into ``schema.collection_id_for``.

Splitting and normalising are NOT redone here. ``_split_artists`` /
``_normalize_artist_name`` already ran at library load and their output *is*
``db.artists`` — one row per distinct artist with its owned track count and artwork.
This module consumes that list; a second normaliser would drift from the first.

Only ``resolve_library_artists`` and the favourite mutators write. ``hub`` / ``backlog``
/ ``list_favourite_artists`` are pure reads so ``GET /api/artists/hub`` stays a read,
and the Tier-1 backlog makes zero network calls — the counts are already in memory.
"""

from __future__ import annotations

import logging
from typing import Any, NamedTuple

from app.artist_store import schema
from app.artist_store.schema import KIND_ARTIST

logger = logging.getLogger("ARTIST_STORE")

PROVIDER_SOUNDCLOUD = "soundcloud"

#: ``source`` stamped on alias rows minted from a library scan.
ALIAS_SOURCE_LIBRARY = "library"

DEFAULT_BACKLOG_LIMIT = 25


class _StoreIndex(NamedTuple):
    """One-pass snapshot of the store, so a whole-library scan stays O(collections).

    ``schema.resolve_alias`` falls back to a full alias scan on a miss; calling it once
    per library artist is O(names x aliases). This is read once and reused instead.
    """

    collections: dict[str, dict[str, Any]]
    by_alias: dict[str, str]
    by_fold: dict[str, str]


def _store_index(kind: str) -> _StoreIndex:
    collections: dict[str, dict[str, Any]] = {}
    by_alias: dict[str, str] = {}
    by_fold: dict[str, str] = {}
    for collection in schema.list_collections(kind):
        cid = str(collection["id"])
        collections[cid] = collection
        for alias_row in schema.list_aliases(cid):
            alias = str(alias_row["alias"]).strip()
            if not alias:
                continue
            by_alias.setdefault(alias, cid)
            by_fold.setdefault(schema.collection_id_for(alias, kind), cid)
    return _StoreIndex(collections, by_alias, by_fold)


def _resolve_id(name: str, kind: str, store: _StoreIndex) -> str:
    """Collection a raw library name belongs to. Never writes; derives the id on a miss."""
    known = store.by_alias.get(name)
    if known is not None:
        return known
    own = schema.collection_id_for(name, kind)
    return store.by_fold.get(own, own)


def _library_artists(db: Any) -> list[dict[str, Any]]:
    """``db.artists`` as ``{name, track_count, artwork}``, hostile input tolerated.

    Accepts ``LiveRekordboxDB``, ``RekordboxXMLDB`` and the ``RekordboxDB`` facade —
    all three expose the same list. The XML backend omits ``Artwork``.
    """
    rows = getattr(db, "artists", None)
    if not rows and hasattr(db, "get_all_artists"):
        try:
            rows = db.get_all_artists()
        except (AttributeError, TypeError) as e:
            logger.warning("artist registry: get_all_artists failed err=%s", e)
            rows = None
    out: list[dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        try:
            count = int(row.get("track_count") or 0)
        except (TypeError, ValueError):
            count = 0
        out.append({"name": name, "track_count": count, "artwork": row.get("Artwork") or ""})
    return out


def _local_rows(db: Any, kind: str, store: _StoreIndex) -> dict[str, dict[str, Any]]:
    """``collection_id`` -> owned-track summary, alias variants folded together.

    Several raw library strings can share one collection (a merge, or plain re-casing),
    so counts are summed. Display name and artwork come from the store's canonical name
    when it has one, else from the busiest variant.
    """
    rows: dict[str, dict[str, Any]] = {}
    ordered = sorted(_library_artists(db), key=lambda r: (-r["track_count"], r["name"]))
    for entry in ordered:
        cid = _resolve_id(entry["name"], kind, store)
        existing = rows.get(cid)
        if existing is not None:
            existing["track_count"] += entry["track_count"]
            existing["library_names"].append(entry["name"])
            if not existing["artwork"]:
                existing["artwork"] = entry["artwork"]
            continue
        collection = store.collections.get(cid)
        name = str(collection["canonical_name"]) if collection is not None else entry["name"]
        rows[cid] = {
            "collection_id": cid,
            "name": name,
            "sort_key": schema.sort_key_for(name),
            "track_count": entry["track_count"],
            "artwork": entry["artwork"],
            "library_names": [entry["name"]],
        }
    return rows


# --------------------------------------------------------------------------- resolve


def resolve_library_artists(db: Any, kind: str = KIND_ARTIST) -> dict[str, Any]:
    """Give every distinct library artist name a stable collection in the store.

    Idempotent: the id is derived from the folded name and both inserts are
    ``INSERT OR IGNORE``, so a second run over an unchanged library creates nothing.
    A name already mapped as an alias of another collection (a merge happened) keeps
    that collection — resolving must never split a merged artist back apart.

    Returns ``{scanned, created, aliases_added, by_name}``.
    """
    store = _store_index(kind)
    created = 0
    aliases_added = 0
    by_name: dict[str, str] = {}

    for entry in _library_artists(db):
        name = entry["name"]
        cid = _resolve_id(name, kind, store)
        if cid not in store.collections:
            cid = schema.create_collection(name, kind)
            collection = schema.get_collection(cid)
            if collection is not None:
                store.collections[cid] = collection
            store.by_fold.setdefault(schema.collection_id_for(name, kind), cid)
            created += 1
        if schema.add_alias(cid, name, source=ALIAS_SOURCE_LIBRARY):
            aliases_added += 1
        store.by_alias.setdefault(name, cid)
        by_name[name] = cid

    logger.info(
        "op=artist_resolve scanned=%d created=%d aliases=%d",
        len(by_name),
        created,
        aliases_added,
    )
    return {
        "scanned": len(by_name),
        "created": created,
        "aliases_added": aliases_added,
        "by_name": by_name,
    }


def library_artist_counts(db: Any, kind: str = KIND_ARTIST) -> dict[str, int]:
    """``collection_id`` -> owned track count, alias variants summed. Read-only."""
    store = _store_index(kind)
    return {cid: row["track_count"] for cid, row in _local_rows(db, kind, store).items()}


# --------------------------------------------------------------------------- favourites


def add_favourite_artist(collection_id: str) -> bool:
    """Favourite an existing collection. False if it already was. KeyError if unknown."""
    if schema.get_collection(collection_id) is None:
        raise KeyError(f"unknown collection {collection_id!r}")
    return schema.add_favourite(collection_id)


def remove_favourite_artist(collection_id: str) -> bool:
    """Un-favourite. The collection, its aliases and its links survive."""
    return schema.remove_favourite(collection_id)


def favourite_artist_by_name(name: str, kind: str = KIND_ARTIST) -> str:
    """Favourite an artist the UI knows only by name (a backlog row); returns its id.

    Creates the collection when the store has not seen the name yet, so favouriting
    works before a full ``resolve_library_artists`` pass has run.
    """
    text = str(name or "").strip()
    if not text:
        raise ValueError("artist name must contain a non-space character")
    existing = schema.resolve_alias(text, kind)
    cid = str(existing["id"]) if existing is not None else schema.create_collection(text, kind)
    schema.add_alias(cid, text, source=ALIAS_SOURCE_LIBRARY)
    schema.add_favourite(cid)
    return cid


def _favourite_row(row: dict[str, Any], local: dict[str, dict[str, Any]]) -> dict[str, Any]:
    cid = str(row["id"])
    entry = local.get(cid)
    link = schema.get_link(cid, PROVIDER_SOUNDCLOUD)
    return {
        "collection_id": cid,
        "kind": row["kind"],
        "name": row["canonical_name"],
        "sort_key": row["sort_key"],
        "track_count": entry["track_count"] if entry is not None else 0,
        "artwork": entry["artwork"] if entry is not None else "",
        "library_names": list(entry["library_names"]) if entry is not None else [],
        "sync_mode": schema.get_sync_mode(cid),
        "sc_linked": link is not None,
        "sc_permalink": link.get("permalink") if link is not None else None,
        "added_at": row["added_at"],
        "favourite": True,
    }


def list_favourite_artists(db: Any = None, kind: str = KIND_ARTIST) -> list[dict[str, Any]]:
    """Favourites enriched with local track count, sync mode and SC-link state.

    ``db`` is optional: without a loaded library the rows still come back, with a
    ``track_count`` of 0, so the hub renders before the library finishes loading.
    """
    store = _store_index(kind)
    local = _local_rows(db, kind, store) if db is not None else {}
    return [_favourite_row(row, local) for row in schema.list_favourites(kind)]


# --------------------------------------------------------------------------- Tier-1 backlog


def _backlog_rows(
    local: dict[str, dict[str, Any]],
    favourite_ids: set[str],
    limit: int | None,
    query: str = "",
) -> tuple[list[dict[str, Any]], int]:
    """Ranked backlog plus the total that matched BEFORE truncation.

    The caller needs the pre-truncation count: a UI that filters only the rows it
    already holds silently finds nothing for an artist ranked below the limit.
    """
    rows = [
        {**row, "library_names": list(row["library_names"])}
        for cid, row in local.items()
        if cid not in favourite_ids and row["track_count"] > 0
    ]
    needle = query.strip().casefold()
    if needle:
        rows = [
            row
            for row in rows
            if needle in str(row["name"]).casefold()
            or any(needle in str(name).casefold() for name in row["library_names"])
        ]
    rows.sort(key=lambda r: (-r["track_count"], r["sort_key"]))
    total = len(rows)
    if limit is not None:
        rows = rows[:limit]
    return rows, total


def backlog(
    db: Any,
    limit: int | None = DEFAULT_BACKLOG_LIMIT,
    kind: str = KIND_ARTIST,
    query: str = "",
) -> list[dict[str, Any]]:
    """Tier-1 suggestions: artists you already own, most tracks first, favourites out.

    Zero network calls — the counts fall out of the library load. ``limit=None`` returns
    the whole tail.
    """
    if limit is not None and limit <= 0:
        return []
    store = _store_index(kind)
    local = _local_rows(db, kind, store)
    favourite_ids = {str(row["id"]) for row in schema.list_favourites(kind)}
    rows, _total = _backlog_rows(local, favourite_ids, limit, query)
    return rows


def hub(
    db: Any,
    backlog_limit: int | None = DEFAULT_BACKLOG_LIMIT,
    kind: str = KIND_ARTIST,
    query: str = "",
) -> dict[str, Any]:
    """Payload for ``GET /api/artists/hub``: favourites + Tier-1 backlog, one pass, no writes."""
    store = _store_index(kind)
    local = _local_rows(db, kind, store) if db is not None else {}
    favourite_rows = schema.list_favourites(kind)
    favourite_ids = {str(row["id"]) for row in favourite_rows}
    limit = backlog_limit
    if limit is not None and limit <= 0:
        suggestions: list[dict[str, Any]] = []
        total = 0
    else:
        suggestions, total = _backlog_rows(local, favourite_ids, limit, query)
    return {
        "favourites": [_favourite_row(row, local) for row in favourite_rows],
        "backlog": suggestions,
        "backlog_total": total,
        "backlog_query": query.strip(),
    }
