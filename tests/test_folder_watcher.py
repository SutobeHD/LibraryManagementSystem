"""Tests for app/folder_watcher.py — auto-import folder watcher.

Focus on the file-stability guard (must NOT import a still-growing file) and
the stop()/add() lock interplay. The watchdog Observer + import callback are
not driven here; _wait_until_stable is a staticmethod fed a fake Path.
"""

from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import folder_watcher as fw  # noqa: E402
from app.folder_watcher import FolderWatcher, _is_audio  # noqa: E402


class _FakeStat:
    def __init__(self, size):
        self.st_size = size


class _FakePath:
    """Yields a scripted sequence of sizes from .stat(); an Exception value is
    raised instead (to simulate a vanished file)."""

    def __init__(self, sizes):
        self._sizes = list(sizes)
        self._i = 0

    def stat(self):
        s = self._sizes[min(self._i, len(self._sizes) - 1)]
        self._i += 1
        if isinstance(s, Exception):
            raise s
        return _FakeStat(s)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(fw.time, "sleep", lambda *_: None)


# --- _is_audio (pure) ------------------------------------------------------


def test_is_audio():
    from pathlib import Path

    assert _is_audio(Path("/m/x.MP3")) is True
    assert _is_audio(Path("/m/x.flac")) is True
    assert _is_audio(Path("/m/x.txt")) is False
    assert _is_audio(Path("/m/x")) is False


# --- _wait_until_stable ----------------------------------------------------


def test_stable_file_is_ready():
    assert FolderWatcher._wait_until_stable(_FakePath([100, 100]), attempts=6) is True


def test_growing_file_is_not_ready():
    """Regression: a file still being copied (size changes every read) must
    return False on timeout, not True — else a truncated file gets imported."""
    growing = _FakePath([100, 200, 300, 400, 500, 600])
    assert FolderWatcher._wait_until_stable(growing, attempts=6) is False


def test_empty_file_is_not_ready():
    assert FolderWatcher._wait_until_stable(_FakePath([0, 0, 0]), attempts=3) is False


def test_vanished_file_is_not_ready():
    gone = _FakePath([FileNotFoundError()])
    assert FolderWatcher._wait_until_stable(gone, attempts=6) is False


# --- stop() / add() lock interplay -----------------------------------------


def test_add_after_stop_returns_false():
    w = FolderWatcher(import_callback=lambda p: None, is_known_callback=lambda p: False)
    w.stop()
    # _stopped guard: add() must refuse and never touch the shut-down executor
    assert w.add(str(ROOT)) is False
    st = w.status()
    assert st["running"] is False
    assert st["folders"] == []


def test_normalize_resolves_to_absolute():
    out = FolderWatcher._normalize(ROOT)
    assert out and os.path.isabs(out)
    # idempotent: normalizing an already-resolved path yields the same value
    assert FolderWatcher._normalize(out) == out
