"""
LibraryManagementSystem -- Analysis Result Cache
=================================================
Persistent cache to avoid re-running expensive audio analysis on tracks
whose source file hasn't changed.

Validity check: file mtime + size + analyzer version. Hash is *not* used
by default (slow on large files); set USE_CONTENT_HASH=True to verify
content integrity for paranoid setups.

Cache layout:
    <cache_dir>/index.json           -- map file_path → {mtime, size, cache_id, version, depth}
    <cache_dir>/<cache_id>.json.gz   -- per-file analysis result (gzipped)

Depth: every entry records the analysis depth that produced it ("rekordbox" <
"high"). A lookup asks for a minimum depth and only a deeper-or-equal entry
counts as a hit; a shallower result never overwrites a still-valid deeper one.
"""

from __future__ import annotations

import contextlib
import gzip
import hashlib
import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# Bump when output schema changes — invalidates all stale cache entries.
# 4: depth-aware entries (rekordbox / high); mood, genre_hint, stereo nullable; extras added.
ANALYSIS_VERSION = 4

USE_CONTENT_HASH = False  # opt-in: also compare a quick xxhash/md5 sample

ANALYSIS_DEPTHS: tuple[str, ...] = ("rekordbox", "high")
DEFAULT_DEPTH = "rekordbox"
DEPTH_RANK: dict[str, int] = {"rekordbox": 0, "high": 1}


def validate_depth(depth: str) -> str:
    """Return ``depth`` unchanged or raise ``ValueError`` for anything outside ANALYSIS_DEPTHS."""
    if not isinstance(depth, str) or depth not in DEPTH_RANK:
        raise ValueError(f"unknown analysis depth {depth!r}; expected one of {ANALYSIS_DEPTHS}")
    return depth


def _depth_rank(value: Any) -> int | None:
    """Rank of a depth read from disk (index entry / payload); None for anything unknown."""
    if not isinstance(value, str):
        return None
    return DEPTH_RANK.get(value)


class AnalysisCache:
    """File-based cache for AnalysisEngine results.

    Thread-safe within a single process (uses an instance lock for index writes).
    Cross-process safety: index is read on miss, written atomically via temp+rename.
    """

    def __init__(self, cache_dir: str | None = None):
        if cache_dir is None:
            cache_dir = str(Path.home() / ".cache" / "rb_editor_pro" / "analysis_cache")
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.index_file = self.cache_dir / "index.json"
        self._lock = threading.Lock()
        self._index = self._load_index()

    # ------------------------------------------------------------------
    @staticmethod
    def _entry_matches(entry: dict[str, Any], st: os.stat_result) -> bool:
        """Version + size + mtime (±1 s, FS rounding) still describe the file on disk."""
        if entry.get("version") != ANALYSIS_VERSION:
            return False
        if entry.get("size") != st.st_size:
            return False
        return abs(float(entry.get("mtime", 0)) - st.st_mtime) <= 1.0

    def get(self, file_path: str, min_depth: str = DEFAULT_DEPTH) -> dict[str, Any] | None:
        """Return the cached result if the file is unchanged and the entry is at least
        ``min_depth`` deep, else None. Entries without a known depth never hit."""
        min_rank = DEPTH_RANK[validate_depth(min_depth)]
        try:
            abs_path = os.path.abspath(file_path)
        except Exception:
            return None

        entry = self._index.get(abs_path)
        if not entry:
            return None

        entry_rank = _depth_rank(entry.get("depth"))
        if entry_rank is None or entry_rank < min_rank:
            return None

        try:
            st = os.stat(abs_path)
        except OSError:
            return None

        if not self._entry_matches(entry, st):
            return None

        if USE_CONTENT_HASH:
            current = _quick_content_hash(abs_path)
            if current != entry.get("hash"):
                return None

        cache_id = entry.get("cache_id")
        if not cache_id:
            return None
        cache_file = self.cache_dir / cache_id
        if not cache_file.exists():
            return None

        try:
            with gzip.open(cache_file, "rt", encoding="utf-8") as f:
                result = json.load(f)
        except Exception as e:
            logger.warning(f"Cache read failed for {abs_path}: {e}")
            return None
        # The payload is the authority: another process may have rewritten the
        # shared <cache_id>.json.gz at a shallower depth behind this index.
        payload_rank = _depth_rank(result.get("depth")) if isinstance(result, dict) else None
        if payload_rank is None or payload_rank < min_rank:
            logger.debug(f"Cache MISS (payload depth below {min_depth}): {abs_path}")
            return None
        logger.debug(f"Cache HIT: {abs_path}")
        return result

    # ------------------------------------------------------------------
    def put(self, file_path: str, result: dict[str, Any]) -> None:
        """Store an analysis result for its ``result["depth"]`` (missing → "rekordbox").

        Replaces a prior entry unless that entry is still valid for the file on
        disk and deeper than the new result: a rekordbox run never downgrades a
        cached high result.
        """
        try:
            abs_path = os.path.abspath(file_path)
            st = os.stat(abs_path)
        except Exception as e:
            logger.warning(f"Cannot stat for cache: {e}")
            return

        depth = result.get("depth") or DEFAULT_DEPTH
        if _depth_rank(depth) is None:
            logger.warning("op=cache_put path=%s err=unknown_depth depth=%r", abs_path, depth)
            return

        cache_id = hashlib.md5(abs_path.encode("utf-8")).hexdigest() + ".json.gz"
        cache_file = self.cache_dir / cache_id
        payload = dict(result)
        payload["depth"] = depth
        entry: dict[str, Any] = {
            "mtime": st.st_mtime,
            "size": st.st_size,
            "cache_id": cache_id,
            "version": ANALYSIS_VERSION,
            "depth": depth,
        }
        if USE_CONTENT_HASH:
            entry["hash"] = _quick_content_hash(abs_path)

        # Guard + gz write + index update under one lock: the guard's answer must
        # still hold when the file is replaced (same cache_id for every depth).
        with self._lock:
            existing = self._index.get(abs_path)
            if (
                existing is not None
                and self._entry_matches(existing, st)
                and (_depth_rank(existing.get("depth")) or -1) > DEPTH_RANK[depth]
            ):
                logger.debug(
                    "Cache PUT skipped (%s entry deeper than %s): %s",
                    existing.get("depth"),
                    depth,
                    abs_path,
                )
                return
            try:
                with gzip.open(cache_file, "wt", encoding="utf-8") as f:
                    json.dump(payload, f, default=_json_default)
            except Exception as e:
                logger.warning(f"Cache write failed: {e}")
                return
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
                cache_id = entry.get("cache_id")
                if cache_id:
                    with contextlib.suppress(OSError):
                        (self.cache_dir / cache_id).unlink()
                self._save_index()

    def clear(self) -> int:
        """Empty the entire cache. Returns number of removed entries."""
        with self._lock:
            count = len(self._index)
            for entry in self._index.values():
                cache_id = entry.get("cache_id")
                if not cache_id:
                    continue
                with contextlib.suppress(OSError):
                    (self.cache_dir / cache_id).unlink()
            self._index = {}
            self._save_index()
        return count

    def stats(self) -> dict[str, Any]:
        """Return cache size + entry count."""
        with self._lock:
            entries = len(self._index)
        # glob+stat outside the lock: a concurrent invalidate()/clear() can
        # unlink a file between glob and stat (is_file() is a TOCTOU), raising
        # FileNotFoundError. Tolerate it per-file instead of failing the call.
        total_bytes = 0
        for f in self.cache_dir.glob("*.json.gz"):
            try:
                total_bytes += f.stat().st_size
            except OSError:
                continue
        return {
            "entries": entries,
            "bytes": total_bytes,
            "version": ANALYSIS_VERSION,
            "dir": str(self.cache_dir),
        }

    # ------------------------------------------------------------------
    def _load_index(self) -> dict[str, Any]:
        if not self.index_file.exists():
            return {}
        try:
            with open(self.index_file, encoding="utf-8") as f:
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
            with contextlib.suppress(OSError):
                tmp.unlink()


# ---------------------------------------------------------------------------
# Waveform cache
# ---------------------------------------------------------------------------

# Bump when generate_multiband_waveform output changes.
WAVEFORM_CACHE_VERSION = 1
WAVEFORM_CACHE_MAX_ENTRIES = 200  # ~250 kB gzip per 6-min track at 50 pps
# Byte cap too: editor zoom requests up to pps 2000 (~3.5 MB gzip per track).
WAVEFORM_CACHE_MAX_BYTES = 256 * 1024 * 1024
_WAVEFORM_SUFFIX = ".wf.gz"
_STALE_TMP_SECONDS = 3600


class WaveformCache:
    """Disk cache for /api/audio/waveform response bodies.

    One gzip file per (normalised abs path, pps). File = one JSON header line
    ``{"v", "mtime_ns", "size", "pps"}`` + the serialized response body, so a
    hit returns the bytes without a JSON parse. No shared index: entries are
    independent, written temp+rename. Bounded to ``max_entries`` files and
    ``max_bytes`` total; the least recently used (file mtime, touched on hit)
    are pruned first.
    """

    def __init__(
        self,
        cache_dir: str | Path | None = None,
        max_entries: int = WAVEFORM_CACHE_MAX_ENTRIES,
        max_bytes: int = WAVEFORM_CACHE_MAX_BYTES,
    ):
        if cache_dir is None:
            cache_dir = Path.home() / ".cache" / "rb_editor_pro" / "waveform_cache"
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_entries = max(1, int(max_entries))
        self.max_bytes = max(1, int(max_bytes))
        self._prune_lock = threading.Lock()

    @staticmethod
    def key(file_path: str, pps: int) -> str:
        norm = os.path.normcase(os.path.abspath(file_path))
        raw = f"{WAVEFORM_CACHE_VERSION}|{int(pps)}|{norm}"
        return hashlib.md5(raw.encode("utf-8"), usedforsecurity=False).hexdigest()

    def _entry_path(self, file_path: str, pps: int) -> Path:
        return self.cache_dir / (self.key(file_path, pps) + _WAVEFORM_SUFFIX)

    def get(self, file_path: str, pps: int, st: os.stat_result) -> bytes | None:
        """Cached body if the source file still has the stat ``st``, else None."""
        entry = self._entry_path(file_path, pps)
        try:
            with gzip.open(entry, "rb") as f:
                header = json.loads(f.readline())
                if (
                    header.get("v") != WAVEFORM_CACHE_VERSION
                    or header.get("pps") != int(pps)
                    or header.get("size") != st.st_size
                    or header.get("mtime_ns") != st.st_mtime_ns
                ):
                    return None
                body = f.read()
        except FileNotFoundError:
            return None
        except (OSError, EOFError, ValueError) as e:
            logger.warning("op=waveform_cache_get entry=%s err=%s", entry.name, e)
            return None
        with contextlib.suppress(OSError):
            os.utime(entry)
        return body

    def put(self, file_path: str, pps: int, st: os.stat_result, body: bytes) -> None:
        """Store ``body`` for the source stat ``st`` (taken before computing)."""
        entry = self._entry_path(file_path, pps)
        header = {
            "v": WAVEFORM_CACHE_VERSION,
            "mtime_ns": st.st_mtime_ns,
            "size": st.st_size,
            "pps": int(pps),
        }
        tmp: Path | None = None
        try:
            fd, tmp_name = tempfile.mkstemp(dir=self.cache_dir, suffix=".tmp")
            tmp = Path(tmp_name)
            with (
                os.fdopen(fd, "wb") as raw,
                gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=5) as f,
            ):
                f.write(json.dumps(header).encode("utf-8") + b"\n")
                f.write(body)
            # Windows: PermissionError while a reader holds the target open.
            os.replace(tmp, entry)
        except OSError as e:
            logger.warning("op=waveform_cache_put entry=%s err=%s", entry.name, e)
            if tmp is not None:
                with contextlib.suppress(OSError):
                    tmp.unlink()
            return
        self._prune()

    def _prune(self) -> None:
        with self._prune_lock:
            entries: list[tuple[float, int, Path]] = []
            for p in self.cache_dir.glob("*" + _WAVEFORM_SUFFIX):
                try:
                    st = p.stat()
                except OSError:
                    continue
                entries.append((st.st_mtime, st.st_size, p))
            count = len(entries)
            total = sum(e[1] for e in entries)
            entries.sort(key=lambda e: e[0])
            for _, size, p in entries:
                if count <= self.max_entries and total <= self.max_bytes:
                    break
                with contextlib.suppress(OSError):
                    p.unlink()
                    count -= 1
                    total -= size
            # Leftovers of a process killed mid-write.
            cutoff = time.time() - _STALE_TMP_SECONDS
            for p in self.cache_dir.glob("*.tmp"):
                with contextlib.suppress(OSError):
                    if p.stat().st_mtime < cutoff:
                        p.unlink()

    def clear(self) -> int:
        """Delete every entry. Returns number removed."""
        removed = 0
        with self._prune_lock:
            for p in self.cache_dir.glob("*" + _WAVEFORM_SUFFIX):
                with contextlib.suppress(OSError):
                    p.unlink()
                    removed += 1
        return removed


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
_default_cache: AnalysisCache | None = None


def get_default_cache() -> AnalysisCache:
    global _default_cache
    if _default_cache is None:
        _default_cache = AnalysisCache()
    return _default_cache


_default_waveform_cache: WaveformCache | None = None
_waveform_cache_lock = threading.Lock()


def get_waveform_cache() -> WaveformCache:
    global _default_waveform_cache
    if _default_waveform_cache is None:
        with _waveform_cache_lock:
            if _default_waveform_cache is None:
                _default_waveform_cache = WaveformCache()
    return _default_waveform_cache
