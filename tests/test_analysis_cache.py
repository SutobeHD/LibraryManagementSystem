"""Tests for app/analysis_cache.py — persistent analysis-result cache.

Covers the put/get validity round-trip (mtime+size+version) and the
regression where an index entry missing 'cache_id' (legacy/hand-edited
index.json) crashed invalidate()/clear()/get() with KeyError.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.analysis_cache import AnalysisCache, _json_default  # noqa: E402


def _make(tmp_path):
    return AnalysisCache(str(tmp_path / "cache"))


def test_put_get_roundtrip(tmp_path):
    src = tmp_path / "song.wav"
    src.write_bytes(b"\x00" * 2048)
    c = _make(tmp_path)
    assert c.get(str(src)) is None  # cold miss
    c.put(str(src), {"bpm": 128.0, "key": "8A"})
    hit = c.get(str(src))
    assert hit == {"bpm": 128.0, "key": "8A"}


def test_get_miss_after_file_changes(tmp_path):
    src = tmp_path / "song.wav"
    src.write_bytes(b"\x00" * 1024)
    c = _make(tmp_path)
    c.put(str(src), {"bpm": 100})
    src.write_bytes(b"\x01" * 4096)  # size changes → stale
    assert c.get(str(src)) is None


def test_corrupt_index_entry_does_not_crash(tmp_path):
    """Regression: an entry without 'cache_id' must not KeyError."""
    c = _make(tmp_path)
    # Index keys must be what os.path.abspath() produces, or get()/invalidate()
    # look up a different key than the one injected here and the assertions pass
    # for the wrong reason. A POSIX literal like "/music/legacy.wav" becomes
    # "C:\\music\\legacy.wav" under abspath on Windows, so invalidate() missed
    # and clear() counted 2 — build the keys the way the cache does instead.
    legacy = os.path.abspath(str(tmp_path / "legacy.wav"))
    legacy2 = os.path.abspath(str(tmp_path / "legacy2.wav"))
    # inject a legacy/corrupt entry directly, persist, reload
    c._index[legacy] = {"mtime": 1.0, "size": 10, "version": 3}
    c._save_index()
    c2 = AnalysisCache(str(tmp_path / "cache"))
    assert c2.get(legacy) is None  # no KeyError
    c2.invalidate(legacy)  # no KeyError — and actually removes the entry
    # re-add another bad entry and clear()
    c2._index[legacy2] = {"mtime": 1.0, "size": 10, "version": 3}
    assert c2.clear() == 1  # counts + survives missing cache_id


def test_unreadable_index_starts_fresh(tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True)
    (cache_dir / "index.json").write_text("{not valid json")
    c = AnalysisCache(str(cache_dir))
    assert c._index == {}


def test_stats_reports_entries_and_bytes(tmp_path):
    src = tmp_path / "s.wav"
    src.write_bytes(b"\x00" * 1024)
    c = _make(tmp_path)
    c.put(str(src), {"bpm": 120})
    st = c.stats()
    assert st["entries"] == 1
    assert st["bytes"] > 0
    assert st["version"] == c.stats()["version"]


def test_stats_tolerates_file_vanishing_mid_scan(tmp_path, monkeypatch):
    """Regression: a *.json.gz that stat() can't read — standing in for a file
    unlinked by a concurrent clear/invalidate between glob and stat — must be
    skipped, not raise FileNotFoundError out of stats()."""
    src = tmp_path / "s.wav"
    src.write_bytes(b"\x00" * 1024)
    c = _make(tmp_path)
    c.put(str(src), {"bpm": 120})  # one real cache file
    # Make stat() fail rather than making the filesystem fail. The previous
    # version created a dangling symlink, which needs SeCreateSymbolicLinkPrivilege
    # — absent on a stock Windows box without Developer Mode, so the test errored
    # in setup instead of skipping, and a local "pytest is red" became
    # indistinguishable from a real regression.
    broken = c.cache_dir / "broken.json.gz"
    broken.write_bytes(b"x")
    real_stat = Path.stat

    def vanishing_stat(self, *args, **kwargs):
        if self.name == "broken.json.gz":
            raise FileNotFoundError(2, "unlinked between glob and stat", str(self))
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", vanishing_stat)

    st = c.stats()  # must not raise
    assert st["bytes"] > 0  # the real file still counted
    assert st["entries"] == 1  # index count taken under the lock


def test_json_default_handles_numpy():
    np = __import__("numpy")
    assert _json_default(np.int64(5)) == 5
    assert _json_default(np.float32(1.5)) == 1.5
    assert _json_default(np.array([1, 2])) == [1, 2]
    # round-trips through json.dumps with the default hook
    assert json.dumps({"a": np.int64(7)}, default=_json_default) == '{"a": 7}'
