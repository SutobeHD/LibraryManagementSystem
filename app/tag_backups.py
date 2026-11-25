"""tag_backups — exact copy of an audio file before the app first rewrites its tags.

The tag writers (``app/audio_tags.py``) saved in place, and every tag revert (artist
merge, metadata fixer) restores only the tag string it journalled, never the bytes. A
crash or a full disk mid-save could truncate the file, and nothing held the file as
it was before the app touched it. Two pieces close that:

* :func:`ensure_backup` copies the file byte for byte into the backup store the first
  time its tags are written. Later writes find the entry and copy nothing, so the
  copy stays the file as it was before the app's first write. A file that changed
  outside the app since (size or mtime is neither the copy's nor the app's own last
  write) gets a new generation instead of being treated as already covered.
* :func:`atomic_rewrite` runs the tag writer on a temp copy beside the file and
  ``os.replace``s it over the original. The original is never opened for writing, so
  a crash at any point before the rename leaves it untouched, and the rename itself
  is atomic on one volume.

The store is capped at :data:`TAG_BACKUP_CAP_BYTES`; the oldest generations are pruned
first, the one just taken never. A pruned file gets a new copy (of its state then) on
its next write.

Layout, one directory per file, keyed by the sha1 of its normalised resolved path::

    %APPDATA%/MusicLibraryManager/tag-write-backups/<key>/<stamp><suffix>  exact copy
    %APPDATA%/MusicLibraryManager/tag-write-backups/<key>/<stamp>.json     manifest

The manifest holds the original path, size, mtime_ns and sha256, plus the size and
mtime of the app's last write. :func:`restore` puts a generation back atomically after
checking its sha256; no route or UI calls it.

Log lines carry the key and the suffix, never the path: music folders sit outside the
prefixes ``app/logging_utils.py`` redacts.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import secrets
import shutil
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("TAG_BACKUPS")

#: Total bytes of copies kept. ~100 WAV/AIFF or ~500 MP3 originals; oldest go first.
TAG_BACKUP_CAP_BYTES = 5 * 1024**3

_DIRNAME = "tag-write-backups"
_MANIFEST_VERSION = 1
_TMP_PREFIX = ".lmstag-"
_TMP_SUFFIX = ".tmp"
_PART_SUFFIX = ".part"
_CHUNK = 1024 * 1024

#: ``os.replace`` onto a file another process holds open without FILE_SHARE_DELETE
#: (a player, a scanner) fails on Windows; short-lived handles are retried this often.
_REPLACE_ATTEMPTS = 5
_REPLACE_BACKOFF_S = 0.05

# One store, one process: copy, manifest update and prune never interleave. Callers
# take the per-file tag lock first (audio_tags), this one second — never the reverse.
_store_lock = threading.Lock()


@dataclass(frozen=True)
class BackupEntry:
    """One generation: the exact copy and its manifest."""

    key: str
    stamp: str
    copy: Path
    manifest: Path


def backup_root() -> Path:
    """``%APPDATA%/MusicLibraryManager/tag-write-backups`` (format-swap's convention)."""
    base = Path(os.environ.get("APPDATA", str(Path.home() / ".local" / "share")))
    return base / "MusicLibraryManager" / _DIRNAME


def _real(path: str | Path) -> Path:
    """The file a write lands in — a symlink is followed, never replaced."""
    try:
        return Path(path).resolve()
    except (OSError, RuntimeError):
        return Path(os.path.abspath(path))


def file_key(path: str | Path) -> str:
    """Store key of one audio file: stable across spellings of the same path."""
    normalised = os.path.normcase(str(_real(path)))
    return hashlib.sha1(normalised.encode("utf-8"), usedforsecurity=False).hexdigest()[:20]


def _fingerprint(path: Path) -> tuple[int, int]:
    st = os.stat(path)
    return st.st_size, st.st_mtime_ns


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_name(f"{path.name}{_PART_SUFFIX}")
    tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        logger.warning("op=tag_backup_manifest status=unreadable err=%s", type(e).__name__)
        return None
    return payload if isinstance(payload, dict) else None


def _entry(key_dir: Path, manifest: Path, payload: dict[str, Any]) -> BackupEntry:
    stamp = manifest.stem
    return BackupEntry(
        key=key_dir.name,
        stamp=stamp,
        copy=key_dir / f"{stamp}{payload.get('suffix', '')}",
        manifest=manifest,
    )


def generations(path: str | Path) -> list[tuple[BackupEntry, dict[str, Any]]]:
    """Every intact generation of one file, oldest first."""
    key_dir = backup_root() / file_key(path)
    out: list[tuple[BackupEntry, dict[str, Any]]] = []
    if not key_dir.is_dir():
        return out
    for manifest in sorted(key_dir.glob("*.json")):
        payload = _read_json(manifest)
        if payload is None:
            continue
        entry = _entry(key_dir, manifest, payload)
        if entry.copy.is_file():
            out.append((entry, payload))
    return out


def _unique_stamp(key_dir: Path) -> str:
    """Sortable UTC stamp no generation in ``key_dir`` uses (the clock ticks ~16 ms)."""
    now = datetime.now(timezone.utc)
    while any(key_dir.glob(f"{now:%Y%m%d-%H%M%S-%f}*")):
        now += timedelta(microseconds=1)
    return f"{now:%Y%m%d-%H%M%S-%f}"


def _covers(payload: dict[str, Any], current: tuple[int, int]) -> bool:
    """Whether this generation already holds the file's pre-app state."""
    original = (payload.get("size"), payload.get("mtime_ns"))
    written = payload.get("written") or {}
    last_write = (written.get("size"), written.get("mtime_ns"))
    return current in (original, last_write)


def _take_copy(real: Path, key: str, current: tuple[int, int]) -> BackupEntry:
    key_dir = backup_root() / key
    key_dir.mkdir(parents=True, exist_ok=True)
    stamp = _unique_stamp(key_dir)
    suffix = real.suffix.lower()
    part = key_dir / f"{stamp}{suffix}{_PART_SUFFIX}"
    copy = key_dir / f"{stamp}{suffix}"
    manifest = key_dir / f"{stamp}.json"
    digest = hashlib.sha256()
    size = 0
    try:
        with open(real, "rb") as src, open(part, "xb") as dst:
            while chunk := src.read(_CHUNK):
                digest.update(chunk)
                dst.write(chunk)
                size += len(chunk)
            dst.flush()
            os.fsync(dst.fileno())
        if size != current[0] or _fingerprint(real) != current:
            raise OSError(f"file changed while it was copied (key={key})")
        st = os.stat(real)
        os.utime(part, ns=(st.st_atime_ns, st.st_mtime_ns))
        os.replace(part, copy)
        _write_json(
            manifest,
            {
                "version": _MANIFEST_VERSION,
                "path": str(real),
                "name": real.name,
                "suffix": suffix,
                "size": size,
                "mtime_ns": current[1],
                "sha256": digest.hexdigest(),
                "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "written": None,
            },
        )
    except BaseException:
        for leftover in (part, copy, manifest):
            leftover.unlink(missing_ok=True)
        raise
    return BackupEntry(key=key, stamp=stamp, copy=copy, manifest=manifest)


def ensure_backup(path: str | Path) -> BackupEntry:
    """The generation holding this file's state before the app's writes; copy if none.

    Call it with the file's tag-write lock held (``audio_tags.write_tags`` does), right
    before the write. Raises ``OSError`` when the copy cannot be made — the caller must
    not write then.
    """
    real = _real(path)
    key = file_key(real)
    with _store_lock:
        current = _fingerprint(real)
        existing = generations(real)
        # Newest first: after a restore the file matches an older generation again.
        for found, payload in reversed(existing):
            if _covers(payload, current):
                return found
        entry = _take_copy(real, key, current)
        logger.info(
            "op=tag_backup status=created key=%s ext=%s bytes=%d generation=%d",
            key,
            real.suffix.lower(),
            current[0],
            len(existing) + 1,
        )
        _prune(keep=entry)
        return entry


def record_written(entry: BackupEntry, path: str | Path) -> None:
    """Remember the app's own write, so the next one is not mistaken for a foreign edit."""
    with _store_lock:
        payload = _read_json(entry.manifest) if entry.manifest.is_file() else None
        if payload is None:
            return  # pruned in between: the next write takes a fresh copy
        size, mtime_ns = _fingerprint(_real(path))
        payload["written"] = {"size": size, "mtime_ns": mtime_ns}
        _write_json(entry.manifest, payload)


def _store_entries(root: Path) -> list[tuple[str, BackupEntry, int]]:
    """``(stamp, entry, bytes)`` for every intact generation; drops crash leftovers.

    Leftovers are a ``.part`` file, a copy whose manifest never landed (the copy was
    taken, the write never happened) and a manifest whose copy is gone. The store lock
    is held, so no copy is in flight. A manifest that cannot be parsed keeps its copy:
    nothing is deleted on a guess.
    """
    entries: list[tuple[str, BackupEntry, int]] = []
    if not root.is_dir():
        return entries
    for key_dir in root.iterdir():
        if not key_dir.is_dir():
            continue
        stamps: set[str] = set()
        for manifest in key_dir.glob("*.json"):
            stamps.add(manifest.stem)
            payload = _read_json(manifest)
            if payload is None:
                continue
            entry = _entry(key_dir, manifest, payload)
            if not entry.copy.is_file():
                manifest.unlink(missing_ok=True)
                continue
            entries.append((entry.stamp, entry, entry.copy.stat().st_size))
        for stray in key_dir.iterdir():
            if not stray.is_file() or stray.suffix == ".json":
                continue
            if stray.name.endswith(_PART_SUFFIX) or stray.name.split(".", 1)[0] not in stamps:
                stray.unlink(missing_ok=True)
        with contextlib.suppress(OSError):
            key_dir.rmdir()  # only succeeds when empty
    return entries


def _prune(keep: BackupEntry) -> None:
    """Drop the oldest generations until the store fits the cap; ``keep`` always stays."""
    cap = int(TAG_BACKUP_CAP_BYTES)
    entries = sorted(_store_entries(backup_root()), key=lambda e: (e[0], e[1].key))
    total = sum(size for _stamp, _entry, size in entries)
    removed = freed = 0
    for _stamp, entry, size in entries:
        if total <= cap:
            break
        if entry.copy == keep.copy:
            continue
        try:
            entry.copy.unlink()
            entry.manifest.unlink(missing_ok=True)
        except OSError as e:
            logger.warning("op=tag_backup_prune key=%s err=%s", entry.key, e.strerror)
            continue
        with contextlib.suppress(OSError):
            entry.copy.parent.rmdir()
        total -= size
        freed += size
        removed += 1
    if removed:
        logger.info(
            "op=tag_backup_prune removed=%d freed=%d total=%d cap=%d", removed, freed, total, cap
        )
    if total > cap:
        logger.warning("op=tag_backup_prune status=over_cap total=%d cap=%d", total, cap)


def _fsync(path: Path) -> None:
    with open(path, "rb+") as fh:
        os.fsync(fh.fileno())


def _replace(src: Path, dst: Path) -> None:
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == _REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(_REPLACE_BACKOFF_S * 2**attempt)


def atomic_rewrite(path: str | Path, mutate: Callable[[Path], bool]) -> bool:
    """Run ``mutate`` on a temp copy beside ``path``, then swap it in with ``os.replace``.

    ``mutate`` gets the temp path and returns True when it saved. The original is
    read, never written: on False, an exception or a crash the temp copy is all that
    changed (and is removed unless the process died). Returns False, original
    untouched, when ``mutate`` fails or the file changed while the copy was edited.
    Raises ``PermissionError`` when the file stays held by another process.
    """
    real = _real(path)
    if not os.access(real, os.W_OK):
        logger.warning("op=tag_write status=read_only ext=%s", real.suffix.lower())
        return False
    tmp = real.with_name(f"{_TMP_PREFIX}{secrets.token_hex(6)}{_TMP_SUFFIX}")
    try:
        before = _fingerprint(real)
        shutil.copyfile(real, tmp)
        shutil.copymode(real, tmp)
        if not mutate(tmp):
            return False
        _fsync(tmp)
        if _fingerprint(real) != before:
            logger.warning(
                "op=tag_write status=changed_underneath ext=%s — not replaced",
                real.suffix.lower(),
            )
            return False
        _replace(tmp, real)
        return True
    finally:
        _drop_tmp(tmp)


def _drop_tmp(tmp: Path) -> None:
    try:
        tmp.unlink(missing_ok=True)
    except OSError as e:
        logger.warning("op=tag_write status=temp_left err=%s", e.strerror)


def restore(path: str | Path, entry: BackupEntry | None = None) -> bool:
    """Put a generation (default: the newest) back over ``path``, byte for byte.

    Hold the file's tag-write lock (``audio_tags.FileWriteLocks``) around the call.
    The copy's sha256 is checked against its manifest first; a mismatch raises
    ``ValueError`` and touches nothing. False when the file has no generation.
    """
    real = _real(path)
    with _store_lock:
        found = generations(real)
        if entry is not None:
            found = [(e, p) for e, p in found if e == entry]
        if not found:
            return False
        chosen, payload = found[-1]
        digest = hashlib.sha256()
        with open(chosen.copy, "rb") as fh:
            while chunk := fh.read(_CHUNK):
                digest.update(chunk)
        if digest.hexdigest() != payload.get("sha256"):
            raise ValueError(f"backup copy damaged (key={chosen.key} stamp={chosen.stamp})")
        tmp = real.with_name(f"{_TMP_PREFIX}{secrets.token_hex(6)}{_TMP_SUFFIX}")
        try:
            shutil.copyfile(chosen.copy, tmp)
            st = os.stat(chosen.copy)
            os.utime(tmp, ns=(st.st_atime_ns, st.st_mtime_ns))
            _fsync(tmp)
            _replace(tmp, real)
        finally:
            _drop_tmp(tmp)
    logger.info("op=tag_backup_restore key=%s stamp=%s", chosen.key, chosen.stamp)
    return True


__all__ = [
    "TAG_BACKUP_CAP_BYTES",
    "BackupEntry",
    "atomic_rewrite",
    "backup_root",
    "ensure_backup",
    "file_key",
    "generations",
    "record_written",
    "restore",
]
