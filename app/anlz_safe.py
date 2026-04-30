"""
Safe wrapper around `rbox.Anlz` parsing.

Why this module exists
----------------------
The third-party `rbox` Rust crate (PyO3 binding) can hit unrecoverable
panics on malformed Rekordbox ANLZ files. Observed in the wild:

    thread '<unnamed>' panicked at rbox/src/masterdb/database.rs:1162:52:
    called `Option::unwrap()` on a `None` value

Because the crate is compiled with `panic = "abort"` (or the unwind
cannot cross the FFI boundary), the panic terminates the entire Python
process with Windows exit code 0xC0000409 (STATUS_STACK_BUFFER_OVERRUN).
A regular `try/except Exception` in Python does NOT catch this — the
backend just dies.

Defense in depth
----------------
1. **Header validation** — reject files that fail a quick sanity check
   (size + `PMAI` magic) before they ever reach `rbox.Anlz`. Cheap and
   catches most truncated / zero-byte / unrelated files.
2. **Subprocess isolation** — actual `rbox.Anlz` calls run in a
   `ProcessPoolExecutor` worker. If `rbox` panics, only the worker dies
   (`BrokenProcessPool`); the parent respawns it and continues.
3. **Bad-track cache** — once a track id has caused a panic / timeout /
   header failure, skip it on subsequent calls in the same session
   instead of crashing the worker again on every reload.

TODO: When rbox upstream fixes the unwrap (file an issue at
https://github.com/dylanljones/rbox referencing
`masterdb/database.rs:1162`), we can revisit whether subprocess
isolation is still needed.
"""
from __future__ import annotations

import logging
import os
from concurrent.futures import (
    BrokenExecutor,
    ProcessPoolExecutor,
    TimeoutError as FuturesTimeout,
)
from typing import Optional

logger = logging.getLogger(__name__)

# Magic bytes at the start of every Rekordbox ANLZ DAT file.
# Reference: https://djl-analysis.deepsymmetry.org/djl-analysis/anlz.html
ANLZ_MAGIC = b"PMAI"

# Smallest plausible ANLZ DAT: 4-byte magic + 4-byte len_header
# + 4-byte len_file = 12 bytes minimum, but real files always carry at
# least one tag (PQTZ/PCOB/...). 28 bytes is a conservative floor.
ANLZ_MIN_SIZE = 28

# Per-call timeout for the rbox subprocess. A healthy parse takes
# milliseconds; anything longer indicates the worker is stuck or the
# file is pathological.
PER_CALL_TIMEOUT_S = 5.0


def _validate_anlz_header(dat_path: str) -> bool:
    """Quick sanity check before handing the file to rbox.

    Catches truncated, zero-byte, or non-ANLZ files that would otherwise
    have a high chance of panicking inside the Rust parser.

    Returns:
        True if the file passes the minimum well-formed checks.
    """
    try:
        if not os.path.isfile(dat_path):
            return False
        size = os.path.getsize(dat_path)
        if size < ANLZ_MIN_SIZE:
            return False
        with open(dat_path, "rb") as f:
            magic = f.read(4)
        return magic == ANLZ_MAGIC
    except OSError as exc:
        logger.debug("ANLZ header check OSError on %s: %s", dat_path, exc)
        return False


def _parse_pqtz_in_worker(dat_path: str) -> Optional[list[dict]]:
    """Worker-side: parse PQTZ entries from an ANLZ DAT.

    Imported `rbox` lazily inside the worker so the parent process never
    imports it just for parsing — keeps the panic blast radius limited
    to the subprocess.
    """
    import rbox  # noqa: WPS433 — intentional in-worker import

    anlz = rbox.Anlz(dat_path)
    pqtz = getattr(anlz, "pqtz", None)
    if not pqtz or not pqtz.entries:
        return None
    return [
        {
            "time": float(entry.time) / 1000.0,
            "bpm": float(entry.bpm) / 100.0,
            "beat": 1,
        }
        for entry in pqtz.entries
    ]


class SafeAnlzParser:
    """Process-isolated `rbox.Anlz` PQTZ extractor.

    Usage:
        parser = SafeAnlzParser()
        for track_id, dat_path in tracks:
            entries = parser.parse_pqtz(track_id, dat_path)
            if entries is not None:
                ...
        parser.shutdown()
    """

    def __init__(self) -> None:
        self._executor: Optional[ProcessPoolExecutor] = None
        self._bad_ids: set[str] = set()
        self._panic_count: int = 0

    # ------------------------------------------------------------------
    # Executor lifecycle
    # ------------------------------------------------------------------
    def _ensure_executor(self) -> ProcessPoolExecutor:
        if self._executor is None:
            # max_workers=1 keeps memory low; calls are inherently
            # sequential in the current usage anyway.
            self._executor = ProcessPoolExecutor(max_workers=1)
            logger.debug("SafeAnlzParser: spawned worker process")
        return self._executor

    def _restart_executor(self) -> None:
        """Tear down the current executor (e.g. after a worker panic)."""
        if self._executor is not None:
            try:
                self._executor.shutdown(wait=False, cancel_futures=True)
            except Exception as exc:  # noqa: BLE001
                logger.debug("SafeAnlzParser: shutdown error (ignored): %s", exc)
            self._executor = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def parse_pqtz(
        self, track_id: str, dat_path: str
    ) -> Optional[list[dict]]:
        """Extract PQTZ beatgrid entries safely.

        Args:
            track_id: Logical id used for logging and bad-id caching.
            dat_path: Filesystem path to the ANLZ `.DAT` file.

        Returns:
            List of dicts ``{"time": float, "bpm": float, "beat": int}``
            on success, or ``None`` for any failure mode (invalid
            header, worker panic, timeout, missing PQTZ tag).
        """
        if not isinstance(track_id, str) or not track_id:
            logger.debug("SafeAnlzParser: invalid track_id=%r", track_id)
            return None
        if not isinstance(dat_path, str) or not dat_path:
            logger.debug("SafeAnlzParser: invalid dat_path=%r", dat_path)
            return None

        if track_id in self._bad_ids:
            return None

        if not _validate_anlz_header(dat_path):
            logger.debug(
                "SafeAnlzParser: header invalid for track=%s path=%s",
                track_id,
                dat_path,
            )
            self._bad_ids.add(track_id)
            return None

        executor = self._ensure_executor()
        try:
            future = executor.submit(_parse_pqtz_in_worker, dat_path)
            return future.result(timeout=PER_CALL_TIMEOUT_S)
        except BrokenExecutor:
            # The worker died — almost certainly a Rust panic in rbox.
            # Mark this track as bad so we never retry it this session,
            # log loudly, and respawn for the next call.
            self._panic_count += 1
            logger.warning(
                "SafeAnlzParser: rbox worker crashed on track=%s "
                "(panic #%d, file=%s) — likely rbox::masterdb panic. "
                "Skipping this track for the rest of the session.",
                track_id,
                self._panic_count,
                dat_path,
            )
            self._bad_ids.add(track_id)
            self._restart_executor()
            return None
        except FuturesTimeout:
            logger.warning(
                "SafeAnlzParser: rbox.Anlz timeout (>%ss) on track=%s file=%s",
                PER_CALL_TIMEOUT_S,
                track_id,
                dat_path,
            )
            self._bad_ids.add(track_id)
            # A hung worker is unsafe to reuse — kill it.
            self._restart_executor()
            return None
        except Exception as exc:  # noqa: BLE001
            # Normal Python-side errors (file I/O, attribute errors,
            # etc.) — these do bubble through PyO3 correctly. Don't
            # blacklist the id for these; transient failures may
            # recover on a later reload.
            logger.warning(
                "SafeAnlzParser: parse failed for track=%s: %s",
                track_id,
                exc,
            )
            return None

    @property
    def stats(self) -> dict:
        """Diagnostic counters for logging / health endpoints."""
        return {
            "bad_ids": len(self._bad_ids),
            "panics": self._panic_count,
            "worker_alive": self._executor is not None,
        }

    def shutdown(self) -> None:
        """Release the worker process. Safe to call multiple times."""
        self._restart_executor()
