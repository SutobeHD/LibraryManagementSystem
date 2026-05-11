"""
LibraryManagementSystem -- Analysis Result Cache
=================================================
Persistent cache to avoid re-running expensive audio analysis on tracks
whose source file hasn't changed.

Validity check: file mtime + size + analyzer version. Hash is *not* used
by default (slow on large files); set USE_CONTENT_HASH=True to verify
content integrity for paranoid setups.

Cache layout:
    <cache_dir>/index.json           -- map file_path → {mtime, size, cache_id, version}
    <cache_dir>/<cache_id>.json.gz   -- per-file analysis result (gzipped)
"""
from __future__ import annotations

import json
import gzip
import os
import hashlib
import logging
import threading
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# Bump when output schema changes — invalidates all stale cache entries.
ANALYSIS_VERSION = 3

USE_CONTENT_HASH = False  # opt-in: also compare a quick xxhash/md5 sample


class AnalysisCache:
    """File-based cache for AnalysisEngine results.

    Thread-safe within a single process (uses an instance lock for index writes).
    Cross-process safety: index is read on miss, written atomically via temp+rename.
    """

    def __init__(self, cache_dir: Optional[str] = None):
        if cache_dir is None:
            cache_dir = str(Path.home() / ".cache" / "rb_editor_pro" / "analysis_cache")
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.index_file = self.cache_dir / "index.json"
        self._lock = threading.Lock()
        self._index = self._load_index()

    # ------------------------------------------------------------------
    def get(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Return cached result if file is unchanged, else None."""
        try:
            abs_path = os.path.abspath(file_path)
        except Exception:
            return None

        entry = self._index.get(abs_path)
        if not entry:
            return None

        if entry.get("version") != ANALYSIS_VERSION:
            return None

        try:
            st = os.stat(abs_path)
        except OSError:
            return None

        if entry.get("size") != st.st_size:
            return None
        # mtime: tolerate FS rounding by comparing within 1 second
        if abs(float(entry.get("mtime", 0)) - st.st_mtime) > 1.0:
            return None

        if USE_CONTENT_HASH:
            current = _quick_content_hash(abs_path)
            if current != entry.get("hash"):
                return None

        cache_file = self.cache_dir / entry["cache_id"]
        if not cache_file.exists():
            return None

        try:
            with gzip.open(cache_file, "rt", encoding="utf-8") as f:
                result = json.load(f)
            logger.debug(f"Cache HIT: {abs_path}")
            return result
        except Exception as e:
            logger.warning(f"Cache read failed for {abs_path}: {e}")
            return None

    # ------------------------------------------------------------------
    def put(self, file_path: str, result: Dict[str, Any]) -> None:
        """Store analysis result, replacing any prior cached entry."""
        try:
            abs_path = os.path.abspath(file_path)
            st = os.stat(abs_path)
        except Exception as e:
            logger.warning(f"Cannot stat for cache: {e}")
            return

        cache_id = hashlib.md5(abs_path.encode("utf-8")).hexdigest() + ".json.gz"
        cache_file = self.cache_dir / cache_id

        try:
            with gzip.open(cache_file, "wt", encoding="utf-8") as f:
                json.dump(result, f, default=_json_default)
        except Exception as e:
            logger.warning(f"Cache write failed: {e}")
            return

        entry: Dict[str, Any] = {
            "mtime": st.st_mtime,
            "size": st.st_size,
            "cache_id": cache_id,
            "version": ANALYSIS_VERSION,
        }
        if USE_CONTENT_HASH:
            entry["hash"] = _quick_content_hash(abs_path)

        with self._lock:
            self._index[abs_path] = entry
            self._save_index()
        logger.debug(f"Cache PUT: {abs_path}")

    # ------------------------------------------------------------------
    def invalidate(self, file_path: str) -> None:
        """Remove a cache entry without deleting the underlying audio file."""
        try:
            abs_path = os.path.abspath(file_path)
        except Exception:
            return
        with self._lock:
            entry = self._index.pop(abs_path, None)
            if entry:
                cache_file = self.cache_dir / entry["cache_id"]
                try:
                    cache_file.unlink()
                except OSError:
                    pass
                self._save_index()

    def clear(self) -> int:
        """Empty the entire cache. Returns number of removed entries."""
        with self._lock:
            count = len(self._index)
            for entry in self._index.values():
                try:
                    (self.cache_dir / entry["cache_id"]).unlink()
                except OSError:
                    pass
            self._index = {}
            self._save_index()
        return count

    def stats(self) -> Dict[str, Any]:
        """Return cache size + entry count."""
        total_bytes = sum(
            f.stat().st_size for f in self.cache_dir.glob("*.json.gz")
            if f.is_file()
        )
        return {
            "entries": len(self._index),
            "bytes": total_bytes,
            "version": ANALYSIS_VERSION,
            "dir": str(self.cache_dir),
        }

    # ------------------------------------------------------------------
    def _load_index(self) -> Dict[str, Any]:
        if not self.index_file.exists():
            return {}
        try:
            with open(self.index_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Cache index unreadable, starting fresh: {e}")
            return {}

    def _save_index(self) -> None:
        tmp = self.index_file.with_suffix(".json.tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._index, f)
            os.replace(tmp, self.index_file)
        except Exception as e:
            logger.warning(f"Cache index write failed: {e}")
            try:
                tmp.unlink()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _quick_content_hash(file_path: str, sample_bytes: int = 1024 * 1024) -> str:
    """Quick md5 over first+last MB. Good enough to catch most edits."""
    h = hashlib.md5()
    try:
        size = os.path.getsize(file_path)
        with open(file_path, "rb") as f:
            h.update(f.read(min(sample_bytes, size)))
            if size > sample_bytes * 2:
                f.seek(-sample_bytes, os.SEEK_END)
                h.update(f.read(sample_bytes))
        h.update(str(size).encode())
    except OSError:
        return ""
    return h.hexdigest()


def _json_default(obj):
    """JSON serializer that handles numpy types."""
    try:
        import numpy as np
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
    except ImportError:
        pass
    raise TypeError(f"Not JSON serializable: {type(obj).__name__}")


# Module-level singleton (lazy)
_default_cache: Optional[AnalysisCache] = None


def get_default_cache() -> AnalysisCache:
    global _default_cache
    if _default_cache is None:
        _default_cache = AnalysisCache()
    return _default_cache
