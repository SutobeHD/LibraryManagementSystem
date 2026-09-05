"""artist_store — Artist-Hub sidecar package (``artists.db``).

Holds what Rekordbox cannot: favourite collections, alias groups, provider links,
per-collection sync state, the Rekordbox playlist id-map and the catalogue cache.
``schema`` owns the DDL + migration runner; ``registry`` maps the library's artist
names onto it and serves the hub; ``projection`` mirrors the favourites into Rekordbox
as the ``Artists`` folder; ``merge`` groups duplicate artist spellings, costs a merge,
performs it and takes it back (``merge.apply`` / ``merge.revert`` — reached through the
module, their verbs are too generic for this namespace).

``projection`` is imported as a module (``from app.artist_store import projection``) —
its ``sync`` / ``status`` are too generic to hoist into this namespace.
"""

from __future__ import annotations

from app.artist_store.schema import (
    KIND_ARTIST,
    SCHEMA_VERSION,
    SYNC_AUTO,
    SYNC_MODES,
    SYNC_OFF,
    SYNC_REVIEW,
    collection_id_for,
    init_db,
    migrate,
)

from app.artist_store.registry import (  # isort: skip — must follow schema
    DEFAULT_BACKLOG_LIMIT,
    PROVIDER_SOUNDCLOUD,
    add_favourite_artist,
    backlog,
    favourite_artist_by_name,
    hub,
    library_artist_counts,
    list_favourite_artists,
    remove_favourite_artist,
    resolve_library_artists,
)

from app.artist_store.merge import (  # isort: skip — must follow registry
    ORPHAN_WARNING,
    MergeApplyResult,
    MergeCandidate,
    MergeError,
    MergePreview,
    MergeRevertResult,
    MergeVariant,
    candidates,
    fold_key,
    preview,
    suggest_canonical,
)

__all__ = [
    "DEFAULT_BACKLOG_LIMIT",
    "KIND_ARTIST",
    "ORPHAN_WARNING",
    "PROVIDER_SOUNDCLOUD",
    "SCHEMA_VERSION",
    "SYNC_AUTO",
    "SYNC_MODES",
    "SYNC_OFF",
    "SYNC_REVIEW",
    "MergeApplyResult",
    "MergeCandidate",
    "MergeError",
    "MergePreview",
    "MergeRevertResult",
    "MergeVariant",
    "add_favourite_artist",
    "backlog",
    "candidates",
    "collection_id_for",
    "favourite_artist_by_name",
    "fold_key",
    "hub",
    "init_db",
    "library_artist_counts",
    "list_favourite_artists",
    "migrate",
    "preview",
    "remove_favourite_artist",
    "resolve_library_artists",
    "suggest_canonical",
]
