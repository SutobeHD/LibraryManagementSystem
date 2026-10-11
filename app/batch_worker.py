"""Batch comment edits over the live library (``POST /api/tools/batch-comment``).

Runs inside the sidecar on the live library's own rbox connection. It used to be a CLI
the route launched as ``[sys.executable, batch_worker.py, ...]``; in the PyInstaller
build ``sys.executable`` is the sidecar exe, which ignores argv, so every run booted a
second backend instead of this script.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


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
    master_db: Any, source_id: str, action: str, find_text: str, replace_text: str
) -> int:
    """Apply one comment action to every track of ``LIB`` or one playlist.

    Args:
        master_db: The live library's open ``rbox.MasterDb`` (this thread's connection).
        source_id: ``"LIB"`` for the whole library, else a playlist id.

    Returns:
        How many tracks' comments changed.
    """
    if source_id == "LIB":
        target_ids = [str(c.id) for c in master_db.get_contents()]
    else:
        target_ids = [str(c.id) for c in master_db.get_playlist_contents(source_id)]
    logger.info("batch comment: %d target tracks", len(target_ids))

    count = 0
    for tid in target_ids:
        try:
            # str, not int: rbox's MasterDb.get_content_by_id takes the id as a string.
            item = master_db.get_content_by_id(tid)
            if not item:
                continue
            original = getattr(item, "commnt", "") or ""
            new_comment = compute_new_comment(action, original, find_text, replace_text)
            if new_comment != original:
                item.commnt = new_comment
                master_db.update_content(item)
                count += 1
        except Exception as e:
            logger.warning("batch comment: track %s not updated: %s", tid, e)
    logger.info("batch comment: updated %d tracks", count)
    return count
