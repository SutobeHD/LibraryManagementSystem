"""
FolderWatcher — auto-import audio files from user-configured folders.

For each watched folder we run:
  1. an initial recursive scan (catches files added while the app was off)
  2. a watchdog Observer that fires on file create / move-into-folder

New files are debounced (so we don't import while the file is still being
written) and then handed to ImportManager.process_import on a small worker
pool. Path-based dedup keeps repeat events from re-importing the same file.

Public surface:
  FolderWatcher.start(folders)        -- begin watching, kicks initial scan
  FolderWatcher.stop()                -- stop everything (graceful shutdown)
  FolderWatcher.reconcile(folders)    -- diff against current set, add/remove
  FolderWatcher.add(folder)           -- watch one more folder
  FolderWatcher.remove(folder)        -- stop watching one folder
  FolderWatcher.status()              -- diagnostic snapshot for the UI
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

logger = logging.getLogger("FOLDER_WATCHER")

AUDIO_EXTENSIONS = {
    ".mp3", ".wav", ".flac", ".aiff", ".aif",
    ".ogg", ".opus", ".m4a", ".aac", ".wma", ".alac",
}

# Wait this long after the last filesystem event for a path before importing —
# protects against picking up a file that's still being copied.
DEBOUNCE_SECONDS = 2.5

# Stability check: file size must be unchanged across two reads this far apart.
STABILITY_INTERVAL = 0.75


def _is_audio(path: Path) -> bool:
    return path.suffix.lower() in AUDIO_EXTENSIONS


class _Handler(FileSystemEventHandler):
    """watchdog handler — forwards every audio file event to the watcher."""

    def __init__(self, watcher: FolderWatcher, root: Path):
        self.watcher = watcher
        self.root = root

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        self.watcher._enqueue(Path(event.src_path))

    def on_moved(self, event: FileSystemEvent) -> None:
        # File renamed or moved INTO the watched tree.
        if event.is_directory:
            return
        dest = getattr(event, "dest_path", None)
        if dest:
            self.watcher._enqueue(Path(dest))


class FolderWatcher:
    """
    Process-wide singleton. Wired up at FastAPI startup, torn down at shutdown.
    """

    def __init__(
        self,
        import_callback: Callable[[Path], object],
        is_known_callback: Callable[[Path], bool],
        max_workers: int = 2,
    ):
        self._import = import_callback
        self._is_known = is_known_callback
        self._observers: dict[str, Observer] = {}
        self._timers: dict[str, threading.Timer] = {}
        self._inflight: set[str] = set()
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="folder-watch-import"
        )
        self._stopped = False

    # ── lifecycle ──────────────────────────────────────────────────────────

    def start(self, folders: Iterable[str]) -> None:
        for f in folders:
            self.add(f)

    def stop(self) -> None:
        with self._lock:
            self._stopped = True
            for path, obs in list(self._observers.items()):
                try:
                    obs.stop()
                except Exception as exc:
                    logger.warning("Observer stop failed for %s: %s", path, exc)
            for obs in self._observers.values():
                try:
                    obs.join(timeout=2.0)
                except Exception:
                    pass
            self._observers.clear()
            for timer in self._timers.values():
                timer.cancel()
            self._timers.clear()
        self._executor.shutdown(wait=False, cancel_futures=True)
        logger.info("FolderWatcher stopped.")

    def reconcile(self, folders: Iterable[str]) -> None:
        """Bring observers in sync with the given desired list."""
        desired = {self._normalize(f) for f in folders if f}
        with self._lock:
            current = set(self._observers.keys())
        for gone in current - desired:
            self.remove(gone)
        for added in desired - current:
            self.add(added)

    # ── per-folder add/remove ──────────────────────────────────────────────

    def add(self, folder: str) -> bool:
        norm = self._normalize(folder)
        if not norm:
            return False
        path = Path(norm)
        if not path.exists() or not path.is_dir():
            logger.warning("Cannot watch missing folder: %s", folder)
            return False

        with self._lock:
            if self._stopped:
                return False
            if norm in self._observers:
                return True
            observer = Observer()
            handler = _Handler(self, path)
            observer.schedule(handler, str(path), recursive=True)
            try:
                observer.start()
            except Exception as exc:
                logger.error("Failed to start observer for %s: %s", path, exc)
                return False
            self._observers[norm] = observer
            logger.info("Watching folder: %s", path)

        # Initial scan on a worker thread so the API call returns instantly.
        self._executor.submit(self._initial_scan, path)
        return True

    def remove(self, folder: str) -> bool:
        norm = self._normalize(folder)
        with self._lock:
            obs = self._observers.pop(norm, None)
        if obs is None:
            return False
        try:
            obs.stop()
            obs.join(timeout=2.0)
        except Exception as exc:
            logger.warning("Observer teardown failed for %s: %s", norm, exc)
        logger.info("Stopped watching folder: %s", norm)
        return True

    # ── status ─────────────────────────────────────────────────────────────

    def status(self) -> dict:
        with self._lock:
            return {
                "running": not self._stopped,
                "folders": [
                    {"path": p, "alive": obs.is_alive()}
                    for p, obs in self._observers.items()
                ],
                "pending_imports": len(self._timers),
            }

    # ── internals ──────────────────────────────────────────────────────────

    @staticmethod
    def _normalize(folder: str) -> str:
        try:
            return str(Path(folder).expanduser().resolve())
        except Exception:
            return ""

    def _enqueue(self, file_path: Path) -> None:
        if not _is_audio(file_path):
            return
        try:
            key = str(file_path.resolve())
        except Exception:
            return
        with self._lock:
            if self._stopped:
                return
            existing = self._timers.pop(key, None)
            if existing is not None:
                existing.cancel()
            timer = threading.Timer(
                DEBOUNCE_SECONDS, self._submit_after_debounce, args=(key,)
            )
            timer.daemon = True
            self._timers[key] = timer
            timer.start()

    def _submit_after_debounce(self, key: str) -> None:
        with self._lock:
            self._timers.pop(key, None)
            if self._stopped or key in self._inflight:
                return
            self._inflight.add(key)
        self._executor.submit(self._run_import, key)

    def _run_import(self, key: str) -> None:
        path = Path(key)
        try:
            if not self._wait_until_stable(path):
                logger.info("Skipping unstable/missing file: %s", path)
                return
            if self._is_known(path):
                logger.debug("Skipping already-known file: %s", path)
                return
            logger.info("Auto-importing: %s", path)
            self._import(path)
        except Exception as exc:
            logger.error("Auto-import failed for %s: %s", path, exc, exc_info=True)
        finally:
            with self._lock:
                self._inflight.discard(key)

    @staticmethod
    def _wait_until_stable(path: Path, attempts: int = 6) -> bool:
        """Return True when the file size has been steady for one interval."""
        last = -1
        for _ in range(attempts):
            try:
                size = path.stat().st_size
            except FileNotFoundError:
                return False
            except OSError:
                return False
            if size == last and size > 0:
                return True
            last = size
            time.sleep(STABILITY_INTERVAL)
        return last > 0

    def _initial_scan(self, root: Path) -> None:
        imported = 0
        skipped = 0
        for entry in root.rglob("*"):
            try:
                if not entry.is_file() or not _is_audio(entry):
                    continue
                if self._is_known(entry):
                    skipped += 1
                    continue
                self._import(entry)
                imported += 1
            except Exception as exc:
                logger.warning("Initial scan skipped %s: %s", entry, exc)
                skipped += 1
        logger.info(
            "Initial scan complete: root=%s imported=%d skipped=%d",
            root, imported, skipped,
        )


# ── module-level singleton + helpers ──────────────────────────────────────

_instance: FolderWatcher | None = None
_instance_lock = threading.Lock()


def get_watcher() -> FolderWatcher | None:
    return _instance


def init_watcher(
    import_callback: Callable[[Path], object],
    is_known_callback: Callable[[Path], bool],
) -> FolderWatcher:
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = FolderWatcher(import_callback, is_known_callback)
    return _instance


def shutdown_watcher() -> None:
    global _instance
    with _instance_lock:
        if _instance is not None:
            _instance.stop()
            _instance = None
