"""artist_store — Artist-Hub sidecar package (``artists.db``).

Holds what Rekordbox cannot: favourite collections, alias groups, provider links,
per-collection sync state, the Rekordbox playlist id-map and the catalogue cache.
``schema`` owns the DDL + migration runner; ``registry`` maps the library's artist
names onto it and serves the hub; ``projection`` mirrors the favourites into Rekordbox
as the ``Artists`` folder; ``merge`` groups duplicate artist spellings, costs a merge,
performs it and takes it back (``merge.apply`` / ``merge.revert`` — reached through the
module, their verbs are too generic for this namespace).

``projection``, ``catalogue`` and ``identity`` are imported as modules (``from
app.artist_store import projection``) — their ``sync`` / ``status`` / ``classify`` /
``diff`` / ``catalogue`` / ``classify_roles`` verbs are too generic to hoist into this
namespace. ``identity`` is the name-based, remix-aware role layer (owner decision
2026-09-08) plus the ``track_identity`` table. The provider-link helpers are not: they
are already artist-specific, and the routes bind through them.
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
    artist_names,
    backlog,
    favourite_artist_by_name,
    get_provider_link,
    hub,
    library_artist_counts,
    link_confidence,
    list_favourite_artists,
    migrate_legacy_artist_links,
    remove_favourite_artist,
    remove_provider_link,
    resolve_library_artists,
    set_provider_link,
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
    "artist_names",
    "backlog",
    "candidates",
    "collection_id_for",
    "favourite_artist_by_name",
    "fold_key",
    "get_provider_link",
    "hub",
    "init_db",
    "library_artist_counts",
    "link_confidence",
    "list_favourite_artists",
    "migrate",
    "migrate_legacy_artist_links",
    "preview",
    "remove_favourite_artist",
    "remove_provider_link",
    "resolve_library_artists",
    "set_provider_link",
    "suggest_canonical",
]
