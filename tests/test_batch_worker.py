"""Tests for app/batch_worker.py — pure comment-transform logic.

run_batch_update itself needs rbox + a real master.db, so only the extracted
pure transform (the actual set/append/remove/replace semantics applied to
every track) is locked here.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.batch_worker import compute_new_comment  # noqa: E402


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
