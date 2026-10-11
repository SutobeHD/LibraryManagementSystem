"""Tests for app/batch_worker.py — the comment transform and the batch loop.

The batch loop runs against a stub of the rbox.MasterDb slice it uses; nothing
opens a real master.db.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.batch_worker import apply_batch_comment, compute_new_comment  # noqa: E402


def test_set_overwrites():
    assert compute_new_comment("set", "old", "", "brand new") == "brand new"
    assert compute_new_comment("set", "old", "", "") == ""  # set to empty


def test_append_adds_when_absent_and_skips_when_present():
    assert compute_new_comment("append", "intro", "", "fire") == "intro fire"
    # already present → no-op (no duplicate)
    assert compute_new_comment("append", "intro fire", "", "fire") == "intro fire"
    # appending to empty original → trimmed
    assert compute_new_comment("append", "", "", "tag") == "tag"
    # empty replace → no-op
    assert compute_new_comment("append", "intro", "", "") == "intro"


def test_remove_strips_substring():
    assert compute_new_comment("remove", "hot banger track", "banger ", "") == "hot track"
    # find_text absent in comment → unchanged (after strip)
    assert compute_new_comment("remove", "clean", "xyz", "") == "clean"
    # empty find → no-op
    assert compute_new_comment("remove", "clean", "", "") == "clean"


def test_replace_swaps_substring():
    assert compute_new_comment("replace", "key Am", "Am", "8A") == "key 8A"
    assert compute_new_comment("replace", "no match", "zzz", "8A") == "no match"
    # empty find → no-op
    assert compute_new_comment("replace", "x", "", "y") == "x"


def test_unknown_action_and_none_original():
    assert compute_new_comment("bogus", "keep me", "a", "b") == "keep me"
    # None original treated as empty string, never raises
    assert compute_new_comment("set", None, "", "v") == "v"  # type: ignore[arg-type]
    assert compute_new_comment("append", None, "", "v") == "v"  # type: ignore[arg-type]


class _Content:
    def __init__(self, cid, commnt):
        self.id = cid
        self.commnt = commnt


class _MasterDb:
    def __init__(self):
        self.rows = {"1": _Content(1, "a"), "2": _Content(2, "b"), "3": _Content(3, "b")}
        self.updated = []

    def get_contents(self):
        return list(self.rows.values())

    def get_content_by_id(self, tid):
        if not isinstance(tid, str):
            raise TypeError("argument 'id': 'int' object cannot be converted to 'PyString'")
        if tid == "2":
            raise RuntimeError("row locked")
        return self.rows.get(tid)

    def update_content(self, item):
        self.updated.append((str(item.id), item.commnt))


def test_batch_passes_string_ids_and_survives_a_failing_row():
    """rbox declares MasterDb.get_content_by_id(id: str) (_rbox.pyi); the old CLI passed int."""
    master = _MasterDb()

    assert apply_batch_comment(master, "LIB", "set", "", "z") == 2
    assert master.updated == [("1", "z"), ("3", "z")]


def test_batch_skips_rows_whose_comment_does_not_change():
    master = _MasterDb()

    assert apply_batch_comment(master, "LIB", "remove", "zzz", "") == 0
    assert master.updated == []
