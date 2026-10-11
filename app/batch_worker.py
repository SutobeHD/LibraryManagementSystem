"""Batch comment edits over the live library (``POST /api/tools/batch-comment``).

Runs inside the sidecar on the live library's own rbox connection. It used to be a CLI
the route launched as ``[sys.executable, batch_worker.py, ...]``; in the PyInstaller
build ``sys.executable`` is the sidecar exe, which ignores argv, so every run booted a
second backend instead of this script.
"""

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class UnknownPlaylistError(LookupError):
    """The batch's ``source_id`` names no playlist in master.db."""


def compute_new_comment(action: str, original: str, find_text: str, replace_text: str) -> str:
    """Pure comment transform for one track — mirrors the four batch actions.

    Returns the new comment string (equal to ``original`` when the action is a
    no-op or unknown). Extracted so the action semantics are unit-testable
    without rbox / a real master.db.
    """
    original = original or ""
    if action == "set":
        return replace_text
    if action == "append":
        if replace_text and replace_text not in original:
            return f"{original} {replace_text}".strip()
        return original
    if action == "remove":
        if find_text:
            return original.replace(find_text, "").strip()
        return original
    if action == "replace":
        if find_text:
            return original.replace(find_text, replace_text).strip()
        return original
    return original


def apply_batch_comment(
    master_db: Any,
    source_id: str,
    action: str,
    find_text: str,
    replace_text: str,
    on_changed: Callable[[str, str], None] | None = None,
) -> int:
    """Apply one comment action to every track of ``LIB`` or one playlist.

    Each track's re-read and write sit inside ``db_lock``: ``update_content`` writes the
    whole row, so a row read outside the lock clobbers a concurrent rating / artist /
    analysis edit. The lock is taken per track, not around the loop, so a library-wide
    run never pins every other ``master.db`` writer for its whole duration.

    Args:
        master_db: The live library's open ``rbox.MasterDb`` (this thread's connection).
        source_id: ``"LIB"`` for the whole library, else a playlist id.
        on_changed: Called as ``(track_id, new_comment)`` under the lock after each
            write, so the caller can refresh its in-memory track cache.

    Returns:
        How many tracks' comments changed.

    Raises:
        UnknownPlaylistError: ``source_id`` is neither ``LIB`` nor a playlist id. Used
            to read as an empty playlist and answer "0 updated" as a success.
    """
    from .database import db_lock

    if source_id == "LIB":
        target_ids = [str(c.id) for c in master_db.get_contents()]
    else:
        if master_db.get_playlist_by_id(source_id) is None:
            raise UnknownPlaylistError(source_id)
        target_ids = [str(c.id) for c in master_db.get_playlist_contents(source_id)]
    logger.info("batch comment: %d target tracks", len(target_ids))

    count = 0
    for tid in target_ids:
        try:
            with db_lock():
                # str, not int: rbox's MasterDb.get_content_by_id takes the id as a string.
                item = master_db.get_content_by_id(tid)
                if not item:
                    continue
                original = getattr(item, "commnt", "") or ""
                new_comment = compute_new_comment(action, original, find_text, replace_text)
                if new_comment == original:
                    continue
                item.commnt = new_comment
                master_db.update_content(item)
                if on_changed is not None:
                    on_changed(tid, new_comment)
            count += 1
        except Exception as e:
            logger.warning("batch comment: track %s not updated: %s", tid, e)
    logger.info("batch comment: updated %d tracks", count)
    return count
