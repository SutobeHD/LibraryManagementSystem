"""metadata_fixer.applier — atomic apply + revert for the metadata fixer (T5).

M1 mutation engine. For each requested fix it runs the plan's 6-step order:

  1. ``before_sha1`` = SHA-1 of the audio file bytes,
  2. snapshot the current ``DjmdContent`` row (pre-image) to the sidecar,
  3. under ``db_lock()``: write ``master.db`` (``update_tracks_metadata``),
  4. best-effort mirror the change into the audio file's tags,
  5. ``after_sha1`` = SHA-1 of the file after the tag write,
  6. journal one undo-log row (``schema.record_mutation``).

Steps 1 and 5 are skipped entirely when ``write_tags=False``: no file is touched,
so hashing it twice would only read the whole library off disk for nothing.

:func:`revert_run` replays a run's mutations in reverse, restoring each
pre-image field value in ``master.db`` (+ tags) so the whole run is undone. A
mutation journalled against a whole entity (``entity_kind != 'content'``, e.g. a
``DjmdArtist`` row an artist merge deleted) is instead re-INSERTed through the
injected DB's ``restore_entity``.

Every ``master.db`` write holds ``db_lock()`` — the M1 own-writers half of the
invariant. The systemic retrofit of the other 85 unguarded writers is a parked
topic (see the research doc Risks section); this module does not own that fix.

The DB handle is injected (not imported) so tests drive a fake. ``db_lock`` and
``audio_tags`` are reached through the thin :func:`_db_lock` / :func:`_write_tags`
indirections — lazily imported so importing this module doesn't pull the heavy
``app.database`` → ``rbox``/``anlz_safe`` chain, and so tests can monkeypatch the
lock and tag-write in isolation.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.metadata_fixer import schema

logger = logging.getLogger("METADATA_FIXER_APPLIER")


def _db_lock() -> AbstractContextManager[None]:
    """Acquire the global master.db write lock (lazy import; monkeypatch target)."""
    from app.database import db_lock

    return db_lock()


def _write_tags(src: str, updates: dict[str, Any]) -> None:
    """Best-effort audio-file tag mirror (lazy import; monkeypatch target)."""
    from app import audio_tags

    audio_tags.write_tags(src, updates)


@dataclass(frozen=True)
class FixRequest:
    """One requested change: set ``content_id``'s ``field`` to ``after_value``.

    ``field`` is the ``master.db`` column key forwarded to
    ``update_tracks_metadata`` (e.g. ``"Title"`` / ``"ArtistName"``). Mapping a
    detector ``Match`` to a ``FixRequest`` is the route's job (T6), not the
    applier's — this keeps the engine independent of the detector's shape.
    """

    content_id: str
    rule_id: int
    field: str
    after_value: str


class _DB(Protocol):
    """Minimal slice of ``RekordboxDB`` the applier needs (injected).

    ``restore_entity(entity_kind, entity_id, row) -> bool`` is optional: only a
    DB that journals whole-entity mutations (the artist merge) has to provide
    it, and :func:`revert_run` probes for it instead of requiring it.
    """

    def get_track_details(self, tid: str) -> dict[str, Any] | None: ...

    def update_tracks_metadata(self, track_ids: list[str], updates: dict[str, Any]) -> bool: ...


def _file_sha1(path: str | None) -> str | None:
    """SHA-1 of a file's bytes, or ``None`` if absent/unreadable (best-effort)."""
    if not path:
        return None
    p = Path(path)
    if not p.is_file():
        return None
    h = hashlib.sha1()  # integrity marker, not a security primitive
    try:
        with p.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    except OSError as exc:
        logger.warning("metadata_fixer: sha1 read failed for %s: %s", path, exc)
        return None
    return h.hexdigest()


def _write_one(db: _DB, content_id: str, updates: dict[str, Any]) -> bool:
    """Single locked ``master.db`` write. Returns the DB's success flag."""
    with _db_lock():
        return db.update_tracks_metadata([content_id], updates)


def _restore_entity(db: _DB, mutation: dict[str, Any]) -> bool:
    """Re-INSERT a journalled entity row (the undo of a merge's ``delete_artist``).

    Pre-image first, ``after_json`` as the fallback for callers that journal the
    removed row as the post-image. Returns False — never raises — when the row
    or the injected DB cannot support it, so the caller can report a partial
    revert instead of a complete one.
    """
    entity_kind = str(mutation.get("entity_kind") or "")
    entity_id = mutation.get("entity_id")
    before = mutation.get("before_json")
    after = mutation.get("after_json")
    row = before if isinstance(before, dict) and before else after
    restore = getattr(db, "restore_entity", None)
    if restore is None or not entity_id or not isinstance(row, dict) or not row:
        logger.warning(
            "metadata_fixer: cannot revert %s entity %s (restore_entity=%s, row=%s)",
            entity_kind or "?",
            entity_id,
            restore is not None,
            bool(row),
        )
        return False
    with _db_lock():
        return bool(restore(entity_kind, str(entity_id), row))


def apply_fixes(
    db: _DB,
    fixes: Iterable[FixRequest],
    *,
    rule_ids: Sequence[int],
    write_tags: bool = True,
) -> tuple[str, int]:
    """Apply ``fixes`` in one journalled run. Returns ``(run_id, applied_count)``."""
    run_id = schema.create_run(list(rule_ids))
    applied = 0
    for fix in fixes:
        track = db.get_track_details(fix.content_id) or {}
        src = track.get("path")
        # No tag write => the file is never touched, so hashing it is pure I/O
        # burn (two full reads per row; ~630 GiB over a 5000-AIFF run).
        before_sha1 = _file_sha1(src) if write_tags else None
        before_value = track.get(fix.field)
        updates = {fix.field: fix.after_value}

        if not _write_one(db, fix.content_id, updates):
            logger.warning("metadata_fixer: db update failed for %s; skipping", fix.content_id)
            continue
        if write_tags and src:
            _write_tags(src, updates)

        schema.record_mutation(
            run_id,
            fix.content_id,
            fix.rule_id,
            fix.field,
            before_value=before_value,
            after_value=fix.after_value,
            before_json=track,
            before_sha1=before_sha1,
            after_sha1=_file_sha1(src) if write_tags else None,
            file_path=src,
        )
        applied += 1

    schema.set_run_status(run_id, schema.RUN_COMPLETED)
    return run_id, applied


def revert_run(db: _DB, run_id: str, *, write_tags: bool = True) -> int:
    """Undo a run in reverse order. Returns the number of restored mutations.

    Content rows get their pre-image field value back; entity rows are
    re-INSERTed. Rows that fail leave the run in ``RUN_REVERT_PARTIAL`` — the
    run is only ``RUN_REVERTED`` when nothing was left behind.
    """
    reverted = 0
    failed = 0
    for m in schema.get_mutations(run_id, reverse=True):
        if m["reverted"]:
            continue
        kind = str(m.get("entity_kind") or schema.ENTITY_CONTENT)

        if kind != schema.ENTITY_CONTENT:
            if not _restore_entity(db, m):
                failed += 1
                continue
        else:
            content_id = str(m["content_id"])
            updates = {str(m["field"]): m["before_value"]}
            src = m["file_path"]

            if not _write_one(db, content_id, updates):
                logger.warning("metadata_fixer: revert db update failed for %s", content_id)
                failed += 1
                continue
            if write_tags and src:
                _write_tags(str(src), updates)

        schema.mark_mutation_reverted(str(m["mutation_id"]))
        reverted += 1

    if failed:
        logger.warning(
            "metadata_fixer: run %s partially reverted (%d restored, %d left)",
            run_id,
            reverted,
            failed,
        )
    schema.set_run_status(run_id, schema.RUN_REVERT_PARTIAL if failed else schema.RUN_REVERTED)
    return reverted
