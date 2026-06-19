"""Tests for app/analysis_cache.py — persistent analysis-result cache.

Covers the put/get validity round-trip (mtime+size+version) and the
regression where an index entry missing 'cache_id' (legacy/hand-edited
index.json) crashed invalidate()/clear()/get() with KeyError.
"""

from __future__ import annotations

import json
import os
import sys

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
    # inject a legacy/corrupt entry directly, persist, reload
    c._index["/music/legacy.wav"] = {"mtime": 1.0, "size": 10, "version": 3}
    c._save_index()
    c2 = AnalysisCache(str(tmp_path / "cache"))
    assert c2.get("/music/legacy.wav") is None  # no KeyError
    c2.invalidate("/music/legacy.wav")  # no KeyError
    # re-add another bad entry and clear()
    c2._index["/music/legacy2.wav"] = {"mtime": 1.0, "size": 10, "version": 3}
    assert c2.clear() == 1  # counts + survives missing cache_id


def test_unreadable_index_starts_fresh(tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True)
    (cache_dir / "index.json").write_text("{not valid json")
    c = AnalysisCache(str(cache_dir))
    assert c._index == {}


def test_json_default_handles_numpy():
    np = __import__("numpy")
    assert _json_default(np.int64(5)) == 5
    assert _json_default(np.float32(1.5)) == 1.5
    assert _json_default(np.array([1, 2])) == [1, 2]
    # round-trips through json.dumps with the default hook
    assert json.dumps({"a": np.int64(7)}, default=_json_default) == '{"a": 7}'
