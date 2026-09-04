"""
Safe wrapper around `rbox.MasterDb` + `rbox.Anlz` for PQTZ beatgrid loading.

Why this module exists
----------------------
The third-party `rbox` Rust crate (PyO3 binding) panics on certain
malformed Rekordbox content rows. Observed in the wild:

    thread '<unnamed>' panicked at rbox/src/masterdb/database.rs:1162:52:
    called `Option::unwrap()` on a `None` value

The panic site is in `MasterDb` itself, so it can be triggered by a
plain `db.get_content_anlz_paths(tid)` call — not just by `rbox.Anlz()`.
Because the crate aborts on panic, the panic terminates the entire
Python process (Windows exit 0xC0000409). A regular `try/except` cannot
catch this — the backend just dies.

Defense in depth
----------------
1. **Header validation** — reject files that fail a quick size + `PMAI`
   magic check before the parser ever sees them. Cheap; catches most
   truncated / zero-byte / unrelated files.
2. **Subprocess isolation** — the entire iteration (including
   `get_content_anlz_paths` and `rbox.Anlz`) runs in a
   `ProcessPoolExecutor` worker. If `rbox` aborts, only the worker dies
   (`BrokenExecutor`); the parent restarts and continues with the next
   chunk.
3. **Batch + bisect** — tracks are processed in chunks. On a worker
   crash the chunk is bisected to identify the offending track id; the
   bad id is blacklisted for the rest of the session so the same panic
   never re-fires on reload.

TODO(upstream-rbox-unwrap): the subprocess isolation here can be dropped
once rbox upstream guards the `unwrap()` at `masterdb/database.rs:1162`.
File an issue at https://github.com/dylanljones/rbox citing that line
and the symptom (Windows exit 0xC0000409 / `Option::unwrap()` on `None`
when iterating `get_content_anlz_paths` over a row with a stale ANLZ
pointer). When the upstream fix lands, swap `SafeAnlzParser` for direct
`rbox.Anlz` calls and remove `ProcessPoolExecutor` overhead.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from concurrent.futures import (
    BrokenExecutor,
    ProcessPoolExecutor,
)
from concurrent.futures import (
    TimeoutError as FuturesTimeout,
)
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

# Magic bytes at the start of every Rekordbox ANLZ DAT file.
# Reference: https://djl-analysis.deepsymmetry.org/djl-analysis/anlz.html
ANLZ_MAGIC = b"PMAI"

# Smallest plausible ANLZ DAT: 4-byte magic + 4-byte len_header
# + 4-byte len_file = 12 bytes minimum, but real files always carry at
# least one tag (PQTZ/PCOB/...). 28 bytes is a conservative floor.
ANLZ_MIN_SIZE = 28

# How many tracks to feed into a single subprocess invocation.
# Larger = fewer IPC round-trips (faster). Smaller = less work re-done
# when bisecting after a panic. 500 is a good compromise: the full
# library (a few thousand tracks) loads in 5-10 IPC calls.
DEFAULT_CHUNK_SIZE = 500

# How long a single chunk is allowed to run before we kill the worker
# and move on. A typical chunk of 500 tracks finishes in under 5s.
PER_CHUNK_TIMEOUT_S = 60.0

# Hard ceiling on subprocess restarts caused by panics. After this we
# stop bisecting and accept the loss — protects against a degenerate DB
# where every other row triggers the panic.
MAX_PANICS_PER_RUN = 32


# ---------------------------------------------------------------------------
# Single-file header validation (parent-side; used by parse_pqtz only)
# ---------------------------------------------------------------------------


def _validate_anlz_header(dat_path: str) -> bool:
    """Quick sanity check before handing a file to rbox.

    Catches truncated, zero-byte, or non-ANLZ files that would otherwise
    have a high chance of panicking inside the Rust parser.
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


# ---------------------------------------------------------------------------
# Worker-side functions
# ---------------------------------------------------------------------------
#
# These run in a subprocess spawned by ProcessPoolExecutor. They MUST be
# top-level functions (picklable) and MUST import rbox lazily so the
# parent process never pulls rbox into its address space just for these
# calls — keeping the panic blast radius limited to the subprocess.
# ---------------------------------------------------------------------------


def _validate_anlz_header_worker(dat_path: str) -> bool:
    """Worker-side mirror of `_validate_anlz_header` (no logger access)."""
    try:
        if not os.path.isfile(dat_path):
            return False
        if os.path.getsize(dat_path) < ANLZ_MIN_SIZE:
            return False
        with open(dat_path, "rb") as f:
            return f.read(4) == ANLZ_MAGIC
    except OSError:
        return False


def resolve_anlz_paths(
    db_path: str, track_ids: Iterable[str] | None = None
) -> dict[str, dict[str, str]]:
    """Map track id -> {"DAT", "EXT", "EX2"} absolute ANLZ paths.

    Replaces `rbox.MasterDb.get_content_anlz_paths()`, which calls
    `unwrap()` on the AnalysisDataPath column (masterdb/database.rs:1165)
    and therefore ABORTS the whole process for any row that has none.
    That abort — not a parsing problem — is what capped the beat-grid
    load at 3468 of 4719 tracks: isolating one bad row costs ~9 worker
    restarts, so `MAX_PANICS_PER_RUN` ran out after a handful of them and
    the rest of the library was abandoned unscanned.

    `get_contents()` never panics, and the row already carries the path,
    so the whole mapping is a pure-Python string join. Verified against
    the live 4719-track library on 2026-09-03: 4668 of 4668 resolved
    paths byte-identical to the rbox call, DAT/EXT/EX2 alike, every file
    present on disk, 0.27s for the full pass, zero panics.

    Rows with an empty path are skipped — that set is exactly the set
    that used to abort (46 aborts + 5 catchable MasterDbError), and they
    are tracks Rekordbox has never analysed, so there is no file to find.
    """
    import rbox

    db = rbox.MasterDb(db_path)
    share = Path(db.share_directory())  # a method, not a property
    wanted = None if track_ids is None else {str(t) for t in track_ids}

    out: dict[str, dict[str, str]] = {}
    for content in db.get_contents():
        tid = str(content.id)
        if wanted is not None and tid not in wanted:
            continue
        rel = getattr(content, "analysis_data_path", None)
        if not rel:
            continue
        # lstrip is load-bearing: Path("C:/share") / "/PIONEER/x" throws the
        # share root away and yields "C:/PIONEER/x".
        dat = share / str(rel).lstrip("/\\").replace("/", os.sep)
        out[tid] = {
            "DAT": str(dat),
            "EXT": str(dat.with_suffix(".EXT")),
            "EX2": str(dat.with_suffix(".2EX")),  # rbox spells the key EX2
        }
    return out


def resolve_anlz_dir(db, track_id: str) -> str | None:
    """Directory holding a track's ANLZ files, or None if it has none.

    Safe replacement for `MasterDb.get_content_anlz_dir()` /
    `get_content_anlz_paths()`, both of which `unwrap()` on the
    AnalysisDataPath column and ABORT the process for a track Rekordbox
    has never analysed. A `try/except` cannot catch that — a Rust panic
    is a process abort — so calling them from the backend process is a
    crash waiting for the first unanalysed track.

    `get_content_by_id` returns those rows normally (verified against
    all six ids that abort the other call), so read the column and join
    the path here.

    Args:
        db: An open `rbox.MasterDb`.
        track_id: Stringified track id.
    """
    try:
        content = db.get_content_by_id(str(track_id))
    except Exception as exc:
        logger.debug("resolve_anlz_dir: content %s unreadable: %s", track_id, exc)
        return None
    if content is None:
        return None

    rel = getattr(content, "analysis_data_path", None)
    if not rel:
        return None
    dat = Path(db.share_directory()) / str(rel).lstrip("/\\").replace("/", os.sep)
    return str(dat.parent)


def _import_anlz_file_cls() -> Any:
    """Import `AnlzFile` without letting pyrekordbox touch our logging.

    Returns Any, not `type`: pyrekordbox ships no stubs, so a `type`
    annotation makes mypy reject every attribute access on the class.
    """
    from .pyrekordbox_compat import quiet_import

    with quiet_import():
        from pyrekordbox.anlz import AnlzFile

    return AnlzFile


def _pqtz_entries_from_dat(dat_path: str) -> list[dict] | None:
    """Read the PQTZ beat grid out of one ANLZ .DAT.

    Uses `pyrekordbox.AnlzFile` (pure Python), not `rbox.Anlz`: on a Rekordbox
    6.8.4 library rbox reports "no PQTZ" for every file it does not outright
    panic on (measured 2026-09-03: 0 grids over 40 real files, vs 39 for
    pyrekordbox), which silently produced `hits=0` for the whole library. The
    same parser already backs tests/test_anlz_reference_parse.py.

    Returns `None` when the file carries no beat grid or cannot be parsed.

    Never call `AnlzFile.keys()` on the result — its mapping protocol recurses
    into itself and raises RecursionError. `get_tag()` is safe.
    """
    try:
        anlz_cls = _import_anlz_file_cls()
        anlz = anlz_cls.parse_file(dat_path)
        tag = anlz.get_tag("PQTZ")
    except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
        # One unreadable file must not cost the rest of the batch, but it
        # stays visible: the corrupt-ANLZ case is a real library defect.
        logger.debug("PQTZ parse failed for %s: %s", dat_path, type(exc).__name__)
        return None
    except Exception as exc:  # construct raises its own ConstError hierarchy
        if type(exc).__module__.split(".")[0] != "construct":
            raise
        logger.debug("PQTZ parse failed for %s: %s", dat_path, type(exc).__name__)
        return None

    if isinstance(tag, list):
        tag = tag[0] if tag else None
    entries = getattr(getattr(tag, "content", None), "entries", None)
    if not entries:
        return None

    out: list[dict] = []
    for entry in entries:
        try:
            out.append(
                {
                    "time": float(entry.time) / 1000.0,
                    "bpm": float(entry.tempo) / 100.0,
                    "beat": int(entry.beat),
                }
            )
        except (AttributeError, TypeError, ValueError):
            continue
    return out or None


def _parse_pqtz_in_worker(dat_path: str) -> list[dict] | None:
    """Single-file PQTZ parse. Used by `SafeAnlzParser.parse_pqtz`."""
    return _pqtz_entries_from_dat(dat_path)


def _parse_beatgrids_in_worker(items: list[tuple[str, str]]) -> dict[str, list[dict]]:
    """Parse PQTZ for `(track_id, dat_path)` pairs.

    Touches no database at all — paths are resolved in the parent by
    `resolve_anlz_paths`, so nothing here can hit the rbox panic that
    used to kill this worker.
    """
    out: dict[str, list[dict]] = {}
    for tid, dat_path in items:
        if not _validate_anlz_header_worker(dat_path):
            continue
        entries = _pqtz_entries_from_dat(dat_path)
        if entries:
            out[tid] = entries
    return out


# ---------------------------------------------------------------------------
# Parent-side parser with respawnable worker
# ---------------------------------------------------------------------------


class SafeAnlzParser:
    """Process-isolated PQTZ extractor with crash recovery.

    Two entry points:

    - :meth:`load_all_beatgrids` — batch-load every requested track id;
      bisects on panic to identify and blacklist the offending row.
      Use this for full-library loads.
    - :meth:`parse_pqtz` — single-file parse for ad-hoc lookups.

    Both share the same respawnable worker process and bad-id cache.
    """

    def __init__(self) -> None:
        self._executor: ProcessPoolExecutor | None = None
        self._bad_ids: set[str] = set()
        self._panic_count: int = 0

    # ------------------------------------------------------------------
    # Executor lifecycle
    # ------------------------------------------------------------------
    def _ensure_executor(self) -> ProcessPoolExecutor:
        if self._executor is None:
            self._executor = ProcessPoolExecutor(max_workers=1)
            logger.debug("SafeAnlzParser: spawned worker process")
        return self._executor

    def _restart_executor(self) -> None:
        if self._executor is not None:
            try:
                self._executor.shutdown(wait=False, cancel_futures=True)
            except Exception as exc:
                logger.debug("SafeAnlzParser: shutdown error: %s", exc)
            self._executor = None

    # ------------------------------------------------------------------
    # Batch API — full-library load
    # ------------------------------------------------------------------
    def load_all_beatgrids(
        self,
        db_path: str,
        track_ids: Iterable[str],
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ) -> dict[str, list[dict]]:
        """Load PQTZ beatgrids for every track id in one efficient pass.

        Args:
            db_path: Filesystem path to ``master.db``.
            track_ids: Iterable of stringified track ids.
            chunk_size: How many ids per subprocess call. Default 500.

        Returns:
            Dict ``{track_id: [{"time", "bpm", "beat"}, ...]}`` for
            every track that yielded a valid PQTZ chunk. Missing keys
            mean "no beatgrid available" (never analysed by Rekordbox,
            missing file, invalid header, or a corrupt ANLZ).
        """
        if not isinstance(db_path, str) or not db_path:
            logger.error("load_all_beatgrids: invalid db_path=%r", db_path)
            return {}

        # Materialize and de-duplicate input, keeping only valid strings.
        ids: list[str] = [
            t for t in track_ids if isinstance(t, str) and t and t not in self._bad_ids
        ]
        if not ids:
            return {}

        # Resolve every path up front, in this process. Cheap (~0.3s for a
        # 4700-track library) and, unlike the old per-track rbox lookup in
        # the worker, incapable of panicking.
        try:
            paths = resolve_anlz_paths(db_path, ids)
        except Exception as exc:
            logger.error("SafeAnlzParser: could not resolve ANLZ paths: %s", exc)
            return {}

        items: list[tuple[str, str]] = [(t, paths[t]["DAT"]) for t in ids if t in paths]
        unanalysed = len(ids) - len(items)
        if not items:
            logger.info(
                "SafeAnlzParser: none of the %d requested tracks has an ANLZ file", len(ids)
            )
            return {}

        # FIFO of chunks waiting to be processed. Chunks are bisected
        # on worker crash, so we may push smaller chunks back to the
        # front of the queue.
        queue: list[list[tuple[str, str]]] = [
            items[i : i + chunk_size] for i in range(0, len(items), chunk_size)
        ]
        results: dict[str, list[dict]] = {}
        scanned = 0

        while queue:
            chunk = queue.pop(0)
            chunk = [it for it in chunk if it[0] not in self._bad_ids]
            if not chunk:
                continue

            executor = self._ensure_executor()
            try:
                future = executor.submit(_parse_beatgrids_in_worker, chunk)
                partial = future.result(timeout=PER_CHUNK_TIMEOUT_S)
                results.update(partial)
                scanned += len(chunk)

            except BrokenExecutor:
                # Worker aborted — almost certainly a Rust panic on one
                # of the ids in `chunk`. Restart and bisect.
                self._panic_count += 1
                self._restart_executor()

                if self._panic_count > MAX_PANICS_PER_RUN:
                    logger.error(
                        "SafeAnlzParser: panic budget exhausted "
                        "(%d panics) — aborting batch with %d unscanned",
                        self._panic_count,
                        sum(len(c) for c in queue) + len(chunk),
                    )
                    break

                if len(chunk) == 1:
                    bad = chunk[0][0]
                    self._bad_ids.add(bad)
                    logger.warning(
                        "SafeAnlzParser: track id %s blacklisted (rbox panic #%d)",
                        bad,
                        self._panic_count,
                    )
                else:
                    mid = len(chunk) // 2
                    # Re-queue both halves at the FRONT to find the bad
                    # id quickly. log2(N) restarts to isolate.
                    queue.insert(0, chunk[mid:])
                    queue.insert(0, chunk[:mid])
                    logger.info(
                        "SafeAnlzParser: bisecting chunk of %d after panic #%d",
                        len(chunk),
                        self._panic_count,
                    )

            except FuturesTimeout:
                logger.warning(
                    "SafeAnlzParser: chunk timeout (%ss, %d tracks) — skipping chunk",
                    PER_CHUNK_TIMEOUT_S,
                    len(chunk),
                )
                self._restart_executor()
                # Don't bisect on timeout: a hung worker is a different
                # failure mode and bisecting would just hang again.

            except Exception as exc:
                logger.warning(
                    "SafeAnlzParser: batch failed (%s) — skipping %d tracks",
                    exc,
                    len(chunk),
                )

        logger.info(
            "SafeAnlzParser: batch done — scanned=%d hits=%d no_anlz=%d bad_ids=%d panics=%d",
            scanned,
            len(results),
            unanalysed,
            len(self._bad_ids),
            self._panic_count,
        )
        return results

    # ------------------------------------------------------------------
    # Single-file API — kept for ad-hoc callers
    # ------------------------------------------------------------------
    def parse_pqtz(self, track_id: str, dat_path: str) -> list[dict] | None:
        """Parse PQTZ entries from one ANLZ DAT file.

        Returns ``None`` on any failure (invalid track id, header check
        fail, worker panic, timeout, missing PQTZ chunk).
        """
        if not isinstance(track_id, str) or not track_id:
            return None
        if not isinstance(dat_path, str) or not dat_path:
            return None
        if track_id in self._bad_ids:
            return None
        if not _validate_anlz_header(dat_path):
            self._bad_ids.add(track_id)
            return None

        executor = self._ensure_executor()
        try:
            future = executor.submit(_parse_pqtz_in_worker, dat_path)
            return future.result(timeout=10.0)
        except BrokenExecutor:
            self._panic_count += 1
            logger.warning(
                "SafeAnlzParser: rbox worker crashed on track=%s (panic #%d) — blacklisting",
                track_id,
                self._panic_count,
            )
            self._bad_ids.add(track_id)
            self._restart_executor()
            return None
        except FuturesTimeout:
            logger.warning(
                "SafeAnlzParser: rbox.Anlz timeout on track=%s file=%s",
                track_id,
                dat_path,
            )
            self._bad_ids.add(track_id)
            self._restart_executor()
            return None
        except Exception as exc:
            logger.warning(
                "SafeAnlzParser: parse failed for track=%s: %s",
                track_id,
                exc,
            )
            return None

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------
    @property
    def stats(self) -> dict:
        return {
            "bad_ids": len(self._bad_ids),
            "panics": self._panic_count,
            "worker_alive": self._executor is not None,
        }

    def shutdown(self) -> None:
        """Tear down the worker. Idempotent."""
        self._restart_executor()
