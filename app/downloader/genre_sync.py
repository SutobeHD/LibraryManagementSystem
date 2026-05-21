"""Genre normalisation + canonical-vocabulary mapping (D5).

Incoming genre strings from Spotify / Tidal / Qobuz / Amazon are messy and
inconsistent (``"deep-house"``, ``"Deep_House"``, ``"DEEP HOUSE"``). This
module collapses them onto a single canonical vocabulary so the file's
genre tag — and therefore the CDJ-3000 display — stays consistent.

Mapping strategy (``map_genre``):

1. **Exact cached mapping** — a prior decision for this normalised string.
2. **Exact canonical match** — the normalised string already names a
   canonical genre; the mapping is cached as ``auto_exact``.
3. **Fuzzy match >= 0.90** — closest canonical via ``difflib.SequenceMatcher``;
   cached as ``auto_fuzzy_<score>``. (``coding-rules.md`` mandates difflib,
   not rapidfuzz, for matchers — consistent with ``external_track_match``.)
4. **Owner escalation** — a novel genre is handed to ``owner_callback`` (the
   3-button UI dialog: add-new / map-to-existing / skip). With no callback
   the genre is silently skipped.

The ``canonical_genres`` + ``genre_mappings`` tables are created by
``download_registry.init_registry`` (Phase 0). This module only reads/writes
rows — it never owns the schema.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from difflib import SequenceMatcher

from ..download_registry import _conn
from ._genre_starter import GENRE_STARTER

logger = logging.getLogger("DOWNLOADER_GENRE_SYNC")

#: Fuzzy-match threshold for auto-mapping an incoming genre to a canonical
#: one. Below this, the genre is treated as novel and escalated to the owner.
FUZZY_THRESHOLD = 0.90

#: Callback shape for novel-genre escalation: given the *raw* incoming genre,
#: return the canonical name to map it to (existing or freshly added), or
#: ``None`` to skip the genre entirely.
OwnerCallback = Callable[[str], str | None]


def normalise_genre(s: str) -> str:
    """Lower-case, swap ``_`` / ``-`` for spaces, collapse whitespace.

    The canonical normal form used as the lookup key for both the
    ``genre_mappings`` cache and the exact-canonical comparison. Returns an
    empty string for empty / whitespace-only input.
    """
    if not s:
        return ""
    return " ".join(s.lower().replace("_", " ").replace("-", " ").split())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _persist_mapping(db: sqlite3.Connection, incoming: str, canonical: str, source: str) -> None:
    """Cache an incoming→canonical decision so the next occurrence is instant.

    ``incoming`` is the *normalised* form (the lookup key). ``source`` is a
    short machine-readable trace: ``auto_exact``, ``auto_fuzzy_0.93``,
    ``owner_add``, ``owner_map``.
    """
    db.execute(
        "INSERT OR REPLACE INTO genre_mappings"
        "(incoming, canonical, decision_made_at, decision_source) VALUES (?,?,?,?)",
        (incoming, canonical, _now(), source),
    )


def _add_canonical(db: sqlite3.Connection, name: str, *, seeded: bool) -> None:
    """Insert a canonical genre if absent (idempotent — ``INSERT OR IGNORE``)."""
    db.execute(
        "INSERT OR IGNORE INTO canonical_genres(name, added_at, seeded) VALUES (?,?,?)",
        (name, _now(), 1 if seeded else 0),
    )


def seed_starter_genres(starter_list: Iterable[str] | None = None) -> int:
    """Seed the canonical vocabulary from the D5 starter list (first-run).

    Idempotent — ``INSERT OR IGNORE`` means an already-seeded table is left
    untouched and user-added genres are never clobbered. Defaults to the
    curated :data:`._genre_starter.GENRE_STARTER` tuple. Returns the number
    of canonical genres present after seeding.
    """
    genres = tuple(starter_list) if starter_list is not None else GENRE_STARTER
    try:
        with _conn() as db:
            for g in genres:
                if g and g.strip():
                    _add_canonical(db, g.strip(), seeded=True)
            count = int(db.execute("SELECT COUNT(*) FROM canonical_genres").fetchone()[0])
        logger.info("[GenreSync] Seeded starter genres — %d canonical total", count)
        return count
    except sqlite3.Error as exc:
        logger.error("[GenreSync] seed_starter_genres failed: %s", exc)
        return 0


def map_genre(incoming: str, *, owner_callback: OwnerCallback | None = None) -> str | None:
    """Map a raw incoming genre string onto a canonical genre.

    Returns the canonical genre name, or ``None`` when the genre is empty,
    is novel and the owner skipped it (or no callback was supplied), or a DB
    error occurred. See the module docstring for the four-step strategy.

    When ``owner_callback`` adds a brand-new canonical genre, that genre is
    persisted to ``canonical_genres`` (``seeded=0``) so it is reusable, and
    the incoming→canonical decision is cached.
    """
    norm = normalise_genre(incoming)
    if not norm:
        return None

    try:
        with _conn() as db:
            # 1. Exact cached mapping?
            row = db.execute(
                "SELECT canonical FROM genre_mappings WHERE incoming = ?", (norm,)
            ).fetchone()
            if row:
                return str(row["canonical"])

            # 2. Exact canonical match (case-insensitive)?
            row = db.execute(
                "SELECT name FROM canonical_genres WHERE LOWER(name) = ?", (norm,)
            ).fetchone()
            if row:
                _persist_mapping(db, norm, row["name"], "auto_exact")
                return str(row["name"])

            # 3. Fuzzy match >= FUZZY_THRESHOLD against all canonical genres.
            canonicals = [
                r["name"] for r in db.execute("SELECT name FROM canonical_genres").fetchall()
            ]
            best: str | None = None
            best_score = 0.0
            for c in canonicals:
                score = SequenceMatcher(None, norm, c.lower()).ratio()
                if score > best_score:
                    best, best_score = c, score
            if best is not None and best_score >= FUZZY_THRESHOLD:
                _persist_mapping(db, norm, best, f"auto_fuzzy_{best_score:.2f}")
                logger.info(
                    "[GenreSync] Fuzzy-mapped %r -> %r (score=%.2f)",
                    incoming,
                    best,
                    best_score,
                )
                return best

            # 4. Novel genre — escalate to the owner.
            if owner_callback is None:
                logger.debug("[GenreSync] Novel genre skipped (no callback): %r", incoming)
                return None
            decision = owner_callback(incoming)
            if decision is None or not decision.strip():
                logger.info("[GenreSync] Owner skipped novel genre: %r", incoming)
                return None
            chosen = decision.strip()
            # The owner may have named an existing canonical or a new one;
            # INSERT OR IGNORE makes both cases safe.
            existing = {c.lower() for c in canonicals}
            source = "owner_map" if chosen.lower() in existing else "owner_add"
            if source == "owner_add":
                _add_canonical(db, chosen, seeded=False)
                logger.info("[GenreSync] Owner added new canonical genre: %r", chosen)
            _persist_mapping(db, norm, chosen, source)
            return chosen
    except sqlite3.Error as exc:
        logger.error("[GenreSync] map_genre failed for %r: %s", incoming, exc)
        return None


__all__ = ["FUZZY_THRESHOLD", "map_genre", "normalise_genre", "seed_starter_genres"]
