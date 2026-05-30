"""variant_detector — title-only variant classifier + clusterer (M1).

Classifies each track's variant label (radio/extended/remix/...) and links tracks
that are versions of the same work, persisting track-to-track edges in the
``variants.db`` sidecar. Consumes the shared parsing API from
``app.external_track_match`` (``parse_version_tag`` / ``extract_title_stem``) — does
NOT fork it.

M1 is title-only (no network, no new dep, <5s for 30k tracks). Reads already-loaded
``master.db`` rows passed in by the caller (no rbox interaction); writes only the
sidecar, guarded by a module-private ``_variants_db_write_lock`` (NOT the global
``master.db`` lock). M2 adds the Rust-fingerprint cluster pass; M3 adds AcoustID/MB.

Scoring (analysis-remix-detector OQ2/OQ3 + Findings 2026-05-15):
- classify: ``parse_version_tag`` label; untagged → ``original`` (recall floor).
- cluster: shared ``normalised_root``; same artist → confidence ``0.75`` (auto-group),
  artist mismatch (cross-artist remix) → ``0.55`` (suggestion).
- canonical picker: +0.3 original/unsuffixed, +0.2 earliest release, +0.1 shortest
  title; user-pinned ``is_canonical`` overrides; tiebreak lowest track id.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app import external_track_match as etm
from app import variant_schema

logger = logging.getLogger(__name__)

#: Auto-group floor: same (root, artist). 0.5-0.74 = suggestion, <0.5 hidden.
CONFIDENCE_SAME_ARTIST = 0.75
CONFIDENCE_ROOT_ONLY = 0.55
SOURCE_TITLE = "title-regex"

_variants_db_write_lock = threading.RLock()
_DB_PATH: Path | None = None


def _db_path(db_path: Path | None = None) -> Path:
    """Resolve the sidecar path. Explicit arg wins (tests); else lazy MUSIC_DIR."""
    global _DB_PATH
    if db_path is not None:
        return db_path
    if _DB_PATH is None:
        from app.config import MUSIC_DIR

        MUSIC_DIR.mkdir(parents=True, exist_ok=True)
        _DB_PATH = MUSIC_DIR / "variants.db"
    return _DB_PATH


def _conn(db_path: Path | None = None) -> sqlite3.Connection:
    c = sqlite3.connect(str(_db_path(db_path)), check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    return c


def init(db_path: Path | None = None) -> None:
    """Create/migrate the sidecar schema. Safe to call repeatedly."""
    with _variants_db_write_lock, _conn(db_path) as c:
        variant_schema.migrate(c)


# ── Classification (pure, title-only) ──────────────────────────────────────────


def _primary_artist(artist: str) -> str:
    """Normalised primary-artist key for clustering (collab markers preserved)."""
    return etm.normalize_title(artist or "", nfd_fold=True)


def classify_track(track: dict[str, Any]) -> dict[str, Any]:
    """Classify one track row → a ``track_variants``-shaped dict (not yet persisted).

    ``track`` needs ``ID``/``Title``/``Artist`` (Rekordbox shape). Untagged titles
    classify as ``original`` (recall floor) with ``remixer=None``.
    """
    title = track.get("Title") or ""
    tag = etm.parse_version_tag(title)
    label = tag.label if tag is not None else "original"
    remixer = tag.remixer if tag is not None else None
    return {
        "track_id": track.get("ID"),
        "variant_label": label,
        "normalised_root": etm.extract_title_stem(title),
        "remixer": remixer,
        "primary_artist": _primary_artist(track.get("Artist") or ""),
    }


# ── Canonical picker (OQ2) ──────────────────────────────────────────────────────


def _release_year(track: dict[str, Any]) -> int | None:
    raw = track.get("ReleaseDate") or track.get("Year")
    if raw is None:
        return None
    try:
        return int(str(raw)[:4])
    except (ValueError, TypeError):
        return None


def pick_canonical(members: list[dict[str, Any]]) -> int | None:
    """Return the ``track_id`` of the cluster's canonical original (OQ2 order).

    ``members`` are raw track dicts (need ``ID``; optionally ``Title``/``ReleaseDate``/
    ``is_canonical``). User-pinned ``is_canonical`` wins; else weighted score; tiebreak
    lowest id. Returns ``None`` only for an empty cluster.
    """
    if not members:
        return None
    pinned = [m for m in members if m.get("is_canonical")]
    if pinned:
        return min(pinned, key=lambda m: m.get("ID", 0)).get("ID")

    years = [y for m in members if (y := _release_year(m)) is not None]
    earliest = min(years) if years else None
    shortest_len = min(len(etm.extract_title_stem(m.get("Title") or "")) for m in members)

    def score(m: dict[str, Any]) -> tuple[float, int]:
        s = 0.0
        tag = etm.parse_version_tag(m.get("Title") or "")
        if tag is None or tag.label == "original":
            s += 0.3
        if earliest is not None and _release_year(m) == earliest:
            s += 0.2
        if len(etm.extract_title_stem(m.get("Title") or "")) == shortest_len:
            s += 0.1
        # Negate id so that, at equal score, max() prefers the lowest id (tiebreak).
        return (s, -int(m.get("ID", 0)))

    return max(members, key=score).get("ID")


# ── Clustering ──────────────────────────────────────────────────────────────────


def cluster_by_root(tracks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group tracks sharing a ``normalised_root`` → variant-edge rows.

    Each cluster picks one canonical; every other member becomes a row pointing at
    it. Confidence ``0.75`` when the member shares the canonical's primary artist,
    ``0.55`` for a cross-artist match (same root, different artist). Singletons and
    the canonical itself produce no edge. Returns ``track_variants``-shaped dicts
    ready for :func:`upsert_variant`.
    """
    classified = {t.get("ID"): classify_track(t) for t in tracks}
    by_id = {t.get("ID"): t for t in tracks}

    groups: dict[str, list[Any]] = defaultdict(list)
    for tid, c in classified.items():
        if c["normalised_root"]:
            groups[c["normalised_root"]].append(tid)

    now = datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []
    for _root, ids in groups.items():
        if len(ids) < 2:
            continue
        canonical_id = pick_canonical([by_id[i] for i in ids])
        canonical_artist = classified[canonical_id]["primary_artist"]
        for tid in ids:
            if tid == canonical_id:
                continue
            c = classified[tid]
            same_artist = c["primary_artist"] == canonical_artist
            rows.append(
                {
                    "track_id": tid,
                    "variant_label": c["variant_label"],
                    "normalised_root": c["normalised_root"],
                    "remixer": c["remixer"],
                    "parent_track_id": canonical_id,
                    "confidence": CONFIDENCE_SAME_ARTIST if same_artist else CONFIDENCE_ROOT_ONLY,
                    "source": SOURCE_TITLE,
                    "computed_at": now,
                }
            )
    return rows


# ── Persistence ──────────────────────────────────────────────────────────────────


def upsert_variant(row: dict[str, Any], *, db_path: Path | None = None) -> None:
    """Insert or replace one variant-edge row (PK ``track_id, source, parent_track_id``)."""
    with _variants_db_write_lock, _conn(db_path) as c:
        c.execute(
            "INSERT OR REPLACE INTO track_variants "
            "(track_id, variant_label, normalised_root, remixer, parent_track_id, "
            "confidence, source, computed_at, is_canonical) "
            "VALUES (:track_id, :variant_label, :normalised_root, :remixer, "
            ":parent_track_id, :confidence, :source, :computed_at, :is_canonical)",
            {"is_canonical": 0, **row},
        )


def get_variants(track_id: int, *, db_path: Path | None = None) -> list[dict[str, Any]]:
    """All variant-edge rows for a track."""
    with _conn(db_path) as c:
        rows = c.execute(
            "SELECT * FROM track_variants WHERE track_id = ? ORDER BY confidence DESC",
            (track_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_cluster(root_key: str, *, db_path: Path | None = None) -> list[dict[str, Any]]:
    """All rows in a normalised-root cluster."""
    with _conn(db_path) as c:
        rows = c.execute(
            "SELECT * FROM track_variants WHERE normalised_root = ? ORDER BY confidence DESC",
            (root_key,),
        ).fetchall()
    return [dict(r) for r in rows]


def scan(tracks: list[dict[str, Any]], *, db_path: Path | None = None) -> int:
    """Classify + cluster + persist a track batch. Returns edge-row count written."""
    init(db_path)
    rows = cluster_by_root(tracks)
    for row in rows:
        upsert_variant(row, db_path=db_path)
    logger.info("variant.scan.done tracks=%d edges=%d", len(tracks), len(rows))
    return len(rows)
