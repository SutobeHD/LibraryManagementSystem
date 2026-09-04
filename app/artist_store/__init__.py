"""artist_store — Artist-Hub sidecar package (``artists.db``).

Holds what Rekordbox cannot: favourite collections, alias groups, provider links,
per-collection sync state, the Rekordbox playlist id-map and the catalogue cache.
``schema`` owns the DDL + migration runner; ``registry`` maps the library's artist
names onto it and serves the hub; ``merge`` / ``projection`` land in later tasks.
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

__all__ = [
    "DEFAULT_BACKLOG_LIMIT",
    "KIND_ARTIST",
    "PROVIDER_SOUNDCLOUD",
    "SCHEMA_VERSION",
    "SYNC_AUTO",
    "SYNC_MODES",
    "SYNC_OFF",
    "SYNC_REVIEW",
    "add_favourite_artist",
    "backlog",
    "collection_id_for",
    "favourite_artist_by_name",
    "hub",
    "init_db",
    "library_artist_counts",
    "list_favourite_artists",
    "migrate",
    "remove_favourite_artist",
    "resolve_library_artists",
]
