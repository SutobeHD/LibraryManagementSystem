"""Legacy ``app_data.json`` store — READ-ONLY, kept only for a one-shot import.

Superseded by the artist-store sidecar (``app/artist_store/schema.py``, table ``links``).
This file keyed a SoundCloud URL on the artist **name**, which a merge rewrites, so the
binding was orphaned the moment two spellings were collapsed. Its only writer route
(``POST /api/artist/soundcloud``) had the storage call commented out and returned a fake
success, so no production data depends on the write path.

``app/artist_store/registry.py:migrate_legacy_artist_links`` reads ``data["artists"]``
once, writes the rows into ``links`` keyed on the store's stable ``collection_id``, and
stamps a ``store_meta`` marker. The setter is deliberately gone: nothing may write here
again, or the two stores diverge.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_FILE = Path("app_data.json")


class SidecarStorage:
    def __init__(self):
        self.data = self._load()

    def _load(self):
        if not DATA_FILE.exists():
            return {"artists": {}}
        try:
            with open(DATA_FILE, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(
                "sidecar: failed to load %s — returning empty data (%s)",
                DATA_FILE,
                e,
            )
            return {"artists": {}}

    def get_artist_link(self, artist_name: str):
        """Legacy read. Only the migration should call this."""
        return self.data.get("artists", {}).get(artist_name, {}).get("soundcloud", "")


storage = SidecarStorage()
