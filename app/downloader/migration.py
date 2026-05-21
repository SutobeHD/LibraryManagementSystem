"""One-shot folder migration: per-source layout -> unified layout (D7).

Before the unified downloader, SoundCloud downloads landed under
``MUSIC_DIR/SoundCloud/<artist>/``. The unified layout drops the per-source
directory: every source now files into ``MUSIC_DIR/<artist>/``.

:func:`migrate_per_source_to_unified` moves the legacy files and rewrites the
matching ``download_history.file_path`` rows. It is **idempotent** — once a
file has moved, the legacy path no longer exists, so a second run finds
nothing to do and reports ``moved: 0``. A name collision in the destination
is left in place (``skipped``) rather than overwritten, so a partially-run
migration is safe to resume.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from ..config import MUSIC_DIR
from ..download_registry import _conn

logger = logging.getLogger("DOWNLOADER_MIGRATION")

#: The legacy per-source subdirectory migrated away from.
_LEGACY_SOURCE_DIRNAME = "SoundCloud"


def _update_path_row(db: sqlite3.Connection, old_path: Path, new_path: Path) -> None:
    """Re-point any ``download_history`` row from ``old_path`` to ``new_path``.

    Also backfills ``source = 'soundcloud'`` for the legacy SC-only rows that
    predate the unified ``source`` column (``COALESCE`` leaves an already-set
    source untouched). No-op if no row matches the old path.
    """
    db.execute(
        "UPDATE download_history "
        "SET file_path = ?, source = COALESCE(source, 'soundcloud') "
        "WHERE file_path = ?",
        (str(new_path), str(old_path)),
    )


def migrate_per_source_to_unified() -> dict[str, object]:
    """Move ``MUSIC_DIR/SoundCloud/<artist>/*`` into ``MUSIC_DIR/<artist>/*``.

    Returns a result dict::

        {"moved": int, "skipped": int}                    # ran
        {"moved": 0, "skipped": 0, "reason": "<why>"}      # nothing to do

    ``skipped`` counts files whose destination already existed (collision —
    left untouched). The DB row is rewritten for every successful move so the
    registry's ``file_path`` always reflects the on-disk location.

    Idempotent: safe to call on every startup. A finished migration re-runs
    as a pure no-op.
    """
    moved = 0
    skipped = 0
    src_root = MUSIC_DIR / _LEGACY_SOURCE_DIRNAME

    if not src_root.is_dir():
        logger.info("[Migration] No %s/ folder — nothing to migrate", _LEGACY_SOURCE_DIRNAME)
        return {"moved": 0, "skipped": 0, "reason": "no SoundCloud/ folder"}

    try:
        with _conn() as db:
            for artist_dir in src_root.iterdir():
                if not artist_dir.is_dir():
                    continue
                dst_dir = MUSIC_DIR / artist_dir.name
                dst_dir.mkdir(parents=True, exist_ok=True)
                for f in artist_dir.iterdir():
                    if not f.is_file():
                        continue
                    dst = dst_dir / f.name
                    if dst.exists():
                        logger.warning("[Migration] Destination exists — skipping: %s", dst)
                        skipped += 1
                        continue
                    try:
                        f.rename(dst)
                    except OSError as exc:
                        logger.error("[Migration] Move failed for %s: %s", f, exc)
                        skipped += 1
                        continue
                    _update_path_row(db, f, dst)
                    moved += 1
    except sqlite3.Error as exc:
        logger.error("[Migration] DB update failed: %s", exc)
        return {"moved": moved, "skipped": skipped, "reason": f"db error: {exc}"}

    logger.info("[Migration] Done — moved=%d skipped=%d", moved, skipped)
    return {"moved": moved, "skipped": skipped}


__all__ = ["migrate_per_source_to_unified"]
