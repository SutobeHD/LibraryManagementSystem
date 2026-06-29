"""Tests for app/import_tracker.py — live import-progress tracker.

Thread-safe module singleton. Locks: _basename path handling, task lifecycle
(register/update/get), stage-history dedup, clear_finished, and the prune
policy (drops oldest finished first; keeps in-flight tasks even past the cap).
"""

from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import import_tracker as it  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_tasks():
    it._TASKS.clear()
    yield
    it._TASKS.clear()


# --- _basename (pure) ------------------------------------------------------


def test_basename_unix_windows_and_bare():
    assert it._basename("/home/u/song.mp3") == "song.mp3"
    assert it._basename("C:\\Music\\track.flac") == "track.flac"
    assert it._basename("C:/Music/mix.wav") == "mix.wav"
    assert it._basename("noslash.aiff") == "noslash.aiff"


# --- register / get --------------------------------------------------------


def test_register_creates_queued_task():
    tid = it.register("/m/a.mp3", source="folder")
    assert len(tid) == 12
    t = it.get(tid)
    assert t["status"] == "Queued"
    assert t["title"] == "a.mp3"
    assert t["source"] == "folder"
    assert t["progress"] == 0
    assert t["stage_history"][0]["stage"] == "Queued"


def test_get_returns_copy_not_reference():
    tid = it.register("/m/a.mp3")
    t = it.get(tid)
    t["status"] = "MUTATED"
    assert it.get(tid)["status"] == "Queued"  # store untouched


def test_get_all_returns_copies():
    tid = it.register("/m/a.mp3")
    allt = it.get_all()
    allt[tid]["status"] = "MUTATED"
    assert it.get(tid)["status"] == "Queued"


def test_get_unknown_returns_none():
    assert it.get("nope") is None


# --- update ----------------------------------------------------------------


def test_update_appends_stage_history_on_change():
    tid = it.register("/m/a.mp3")
    it.update(tid, status="Analyzing")
    it.update(tid, status="Analyzing")  # same stage → no dup
    it.update(tid, status="Completed", bpm=128.0)
    t = it.get(tid)
    stages = [h["stage"] for h in t["stage_history"]]
    assert stages == ["Queued", "Analyzing", "Completed"]
    assert t["bpm"] == 128.0


def test_update_unknown_or_empty_is_noop():
    it.update("", status="X")  # no crash
    it.update("ghost", status="X")  # no crash
    assert it.get_all() == {}


# --- clear_finished --------------------------------------------------------


def test_clear_finished_removes_only_terminal():
    a = it.register("/m/a.mp3")
    b = it.register("/m/b.mp3")
    it.update(a, status="Completed")
    it.update(b, status="Analyzing")
    removed = it.clear_finished()
    assert removed == 1
    assert it.get(a) is None
    assert it.get(b) is not None


# --- prune policy ----------------------------------------------------------


def test_prune_drops_oldest_finished_first(monkeypatch):
    monkeypatch.setattr(it, "_MAX_KEEP", 3)
    ids = [it.register(f"/m/{i}.mp3") for i in range(3)]
    for i, tid in enumerate(ids):
        it.update(tid, status="Completed")
        it._TASKS[tid]["start_time"] = float(i)  # deterministic age ordering
    # registering a 4th pushes over the cap → oldest finished (start_time=0) pruned
    it.register("/m/new.mp3")
    assert it.get(ids[0]) is None
    assert it.get(ids[1]) is not None
    assert len(it._TASKS) == 3


def test_prune_keeps_inflight_over_cap(monkeypatch):
    """Soft cap by design: active (non-terminal) tasks are never dropped, even
    when the table exceeds _MAX_KEEP."""
    monkeypatch.setattr(it, "_MAX_KEEP", 3)
    for i in range(5):
        it.register(f"/m/{i}.mp3")  # all stay 'Queued'
    assert len(it._TASKS) == 5  # nothing finished → nothing to prune
