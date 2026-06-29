"""Library-wide audio format conversion engine.

Production port of ``scripts/dev/safe_format_swap.py`` (proof artefact, commit
``fdb461c``) into a FastAPI-callable module. Used by:

- ``POST /api/library/format-swap/dry-run``
- ``POST /api/library/format-swap/execute``
- ``POST /api/library/format-swap/rollback``
- ``GET  /api/library/format-swap/manifests``
- ``GET  /api/library/format-swap/batch/{batch_id}``

Design source: ``docs/research/research/evaluated_library-format-converter.md``
(Stage-2 evaluated, Option A recommended). Behaviour parity with the proof
script: snapshot ``master.db`` trio (db + WAL + SHM) under
``%APPDATA%/MusicLibraryManager/format-swap-backups/<ts>/`` before any write,
mutate ``rbox.MasterDb`` ``Content`` rows in place (preserves ``content_id`` →
beatgrid / cues / hot-cues / memory-cues / MyTag / playlist membership all stay
linked), Pioneer auto-restart watchdog every 50 tracks, per-track 600s FFmpeg
timeout, atomic JSON manifest written after every track.

Why deviates from rule ``coding-rules.md:35`` 30s subprocess default: a 60-min
DJ-set source converts in 60-180s on slow USB / antivirus-scanned targets per
OQ3 in the research doc. Per-track timeout cap = 600s = ~10x safety margin.

Source: per-Track AAC priming-drift was verified empirically (2026-05-30) — for
SoundCloud m4a, ``-flags2 +skip_manual`` is a no-op vs default decode (sample-
identical output). User's 3041-track production run with default flags
confirmed beatgrid alignment acceptable. iTunes-Store AAC may differ → Phase-1a
per-source sanity check still recommended at deployment.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from app import import_tracker
from app.config import FFMPEG_BIN

logger = logging.getLogger("LIBRARY_FORMAT_SWAP")

# ── Rekordbox FileType integers (verified via pyrekordbox 0.1.7 schema) ──

FILE_TYPE_MP3 = 1
FILE_TYPE_M4A = 4
FILE_TYPE_WAV = 5
FILE_TYPE_AIFF = 6
FILE_TYPE_FLAC = 11

LOSSY_SOURCE_EXTS = frozenset({".m4a", ".mp3", ".aac", ".ogg", ".opus"})
LOSSLESS_SOURCE_EXTS = frozenset({".aiff", ".aif", ".wav", ".flac", ".alac"})

TargetFormat = Literal["aiff", "flac", "wav", "mp3"]

TARGET_CONFIG: dict[str, dict[str, Any]] = {
    "aiff": {
        "ext": ".aiff",
        "codec_args": ["-c:a", "pcm_s16le"],
        "file_type": FILE_TYPE_AIFF,
        "expansion_ratio": 5.0,
    },
    "flac": {
        "ext": ".flac",
        "codec_args": ["-c:a", "flac"],
        "file_type": FILE_TYPE_FLAC,
        "expansion_ratio": 2.5,
    },
    "wav": {
        "ext": ".wav",
        "codec_args": ["-c:a", "pcm_s16le"],
        "file_type": FILE_TYPE_WAV,
        "expansion_ratio": 5.0,
    },
    "mp3": {
        "ext": ".mp3",
        "codec_args": ["-c:a", "libmp3lame", "-q:a", "0"],
        "file_type": FILE_TYPE_MP3,
        "expansion_ratio": 0.4,
    },
}

# OQ3 — 600s per-track subprocess timeout (deviates from 30s default; see docstring)
PER_TRACK_TIMEOUT_SEC = 600
WATCHDOG_INTERVAL = 50

# OQ4 — disk-space pre-flight thresholds
DISK_HARD_ABORT_FACTOR = 1.5
DISK_WARN_FACTOR = 1.2

# Engine-write lock — serialises every rbox.MasterDb mutation across the
# FastAPI worker thread pool. Single-process FastAPI per Gap 4 in the research
# doc; threading.RLock therefore suffices (no cross-process concerns).
_engine_lock = threading.RLock()


def _backup_root() -> Path:
    base = Path(os.environ.get("APPDATA", str(Path.home() / ".local" / "share")))
    return base / "MusicLibraryManager" / "format-swap-backups"


def _rekordbox_dir() -> Path:
    base = Path(os.environ.get("APPDATA", str(Path.home() / ".config")))
    return base / "Pioneer" / "rekordbox"


def _ffprobe_bin() -> str:
    # Mirror app.config.FFMPEG_BIN convention but for ffprobe sibling.
    if FFMPEG_BIN.lower().endswith("ffmpeg.exe"):
        return FFMPEG_BIN[:-10] + "ffprobe.exe"
    if FFMPEG_BIN.lower().endswith("ffmpeg"):
        return FFMPEG_BIN[:-6] + "ffprobe"
    return "ffprobe"


# ── Plan + result types ───────────────────────────────────────────────────


@dataclass
class TrackPlan:
    content_id: str
    source_path: Path
    target_path: Path
    source_file_type: int
    source_file_size: int


@dataclass
class DryRunResult:
    scope: dict[str, Any]
    target: str
    tracks: list[dict[str, Any]]
    total_source_mb: float
    estimated_target_mb: float
    drive_free_mb: float
    drive_check_pass: bool
    target_file_type: int
    warning: str | None
    error: str | None


@dataclass
class ExecuteResult:
    batch_id: str
    manifest_path: str
    tracks_planned: int
    tracks_converted: int
    tracks_failed: int
    failures: list[dict[str, Any]]
    aborted: bool
    timestamp: str
    finished: bool
    error: str | None = None
    task_ids: list[str] = field(default_factory=list)


# In-memory batch registry — keyed by batch_id, polled via GET /batch/{id}.
_BATCHES: dict[str, ExecuteResult] = {}
_BATCHES_LOCK = threading.Lock()


def _store_batch(batch_id: str, result: ExecuteResult) -> None:
    with _BATCHES_LOCK:
        _BATCHES[batch_id] = result


def get_batch(batch_id: str) -> ExecuteResult | None:
    with _BATCHES_LOCK:
        return _BATCHES.get(batch_id)


# ── Helpers ───────────────────────────────────────────────────────────────


def _check_rekordbox_running() -> bool:
    try:
        import psutil

        for proc in psutil.process_iter(attrs=["name"]):
            name = (proc.info.get("name") or "").lower()
            if name in ("rekordbox", "rekordbox.exe"):
                return True
        return False
    except ImportError:
        if os.name == "nt":
            try:
                r = subprocess.run(["tasklist"], capture_output=True, text=True, timeout=10)
                return "rekordbox.exe" in r.stdout.lower()
            except (subprocess.SubprocessError, OSError):
                return False
        return False


def _kill_rekordbox_if_present() -> bool:
    """Periodic watchdog: kill Pioneer auto-restart so master.db writes don't race."""
    if not _check_rekordbox_running():
        return False
    try:
        import psutil

        killed = 0
        for proc in psutil.process_iter(attrs=["name"]):
            name = (proc.info.get("name") or "").lower()
            if "rekordbox" in name or "upmgr" in name:
                try:
                    proc.kill()
                    killed += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                    continue
        return killed > 0
    except ImportError:
        if os.name == "nt":
            try:
                subprocess.run(
                    [
                        "powershell",
                        "-NoProfile",
                        "-Command",
                        "Get-Process | Where-Object { $_.Name -match 'rekordbox|Upmgr' } | "
                        "Stop-Process -Force",
                    ],
                    capture_output=True,
                    timeout=15,
                )
                return True
            except (subprocess.SubprocessError, OSError):
                return False
        return False


def _detect_filetype_for_target(live_db: Any, target: str) -> int:
    """Auto-detect the FileType integer Rekordbox uses for the target format.

    Reads any existing row of that format from master.db; falls back to the
    TARGET_CONFIG default when none present.
    """
    cfg = TARGET_CONFIG[target]
    fallback = int(cfg["file_type"])
    ext = str(cfg["ext"]).lower()
    try:
        rbox_db = live_db.db
        for c in rbox_db.get_contents():
            try:
                fp = (getattr(c, "folder_path", "") or "").lower()
            except (AttributeError, TypeError):
                continue
            if fp.endswith(ext) or (ext == ".aiff" and fp.endswith(".aif")):
                return int(getattr(c, "file_type", fallback))
    except (AttributeError, RuntimeError) as e:
        logger.warning(
            "library_format_swap: filetype auto-detect failed (%s) — fallback=%d",
            e,
            fallback,
        )
    return fallback


def _probe_sample_rate(audio_path: Path) -> int | None:
    try:
        r = subprocess.run(
            [
                _ffprobe_bin(),
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=sample_rate",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(audio_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.SubprocessError, OSError) as e:
        logger.debug("ffprobe SR failed for %s: %s", audio_path.name, e)
        return None
    m = re.search(r"\d+", r.stdout or "")
    if not m:
        return None
    try:
        return int(m.group())
    except ValueError:
        return None


def _build_ffmpeg_cmd(src: Path, dst: Path, sample_rate: int, target: str) -> list[str]:
    cfg = TARGET_CONFIG[target]
    cmd: list[str] = [
        FFMPEG_BIN,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(src),
        "-vn",
    ]
    cmd.extend(list(cfg["codec_args"]))
    cmd.extend(
        [
            "-ar",
            str(sample_rate),
            "-map_metadata",
            "0",
            "-write_id3v2",
            "1",
            "-y",
            str(dst),
        ]
    )
    return cmd


def _run_ffmpeg_convert(src: Path, dst: Path, sample_rate: int, target: str) -> None:
    """Raises ``RuntimeError`` on failure."""
    cmd = _build_ffmpeg_cmd(src, dst, sample_rate, target)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=PER_TRACK_TIMEOUT_SEC)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"ffmpeg timeout after {PER_TRACK_TIMEOUT_SEC}s") from e
    except OSError as e:
        raise RuntimeError(f"ffmpeg launch failed: {e}") from e
    if r.returncode != 0 or not dst.exists() or dst.stat().st_size < 1024:
        msg = (r.stderr or "").strip()[:300] or f"rc={r.returncode}"
        raise RuntimeError(f"ffmpeg failed: {msg}")


def _backup_master_db(timestamp: str) -> dict[str, str]:
    """Snapshot master.db + WAL + SHM. Returns ``{original_path: backup_path}``."""
    rb_dir = _rekordbox_dir()
    backup_dir = _backup_root() / timestamp
    backup_dir.mkdir(parents=True, exist_ok=True)
    out: dict[str, str] = {}
    for suffix in ("", "-wal", "-shm"):
        src = rb_dir / f"master.db{suffix}"
        if src.exists():
            dst = backup_dir / f"master.db{suffix}"
            shutil.copy2(src, dst)
            out[str(src)] = str(dst)
    return out


# ── Engine ─────────────────────────────────────────────────────────────────


class FormatSwapEngine:
    """Resolve a scope to a list of ``TrackPlan``s, dry-run or execute the
    batch swap, and provide manifest-backed rollback.

    ``live_db`` is a ``LiveRekordboxDB`` instance (typically
    ``app.main._require_live_db()``).
    """

    def __init__(self, live_db: Any, target: TargetFormat):
        if target not in TARGET_CONFIG:
            raise ValueError(f"Unknown target format: {target!r}")
        self.live_db = live_db
        self.target = target
        self.target_ext = str(TARGET_CONFIG[target]["ext"])

    # — Scope resolution —

    def _iter_live_contents(self) -> Any:
        """Shared iterator: yields rbox Content rows that aren't soft-deleted.

        Centralises the ``rb_local_deleted`` skip so the per-subset branches
        below stay focused on their predicate.
        """
        for c in self.live_db.db.get_contents():
            if getattr(c, "rb_local_deleted", False):
                continue
            yield c

    def _enumerate_by_track_ids(self, ids: list[str]) -> list[Any]:
        out: list[Any] = []
        for i in ids:
            try:
                c = self.live_db.db.get_content_by_id(str(i))
            except (RuntimeError, ValueError):
                continue
            if c is not None:
                out.append(c)
        return out

    def _enumerate_by_playlist(self, playlist_id: int | str) -> list[Any]:
        try:
            return list(self.live_db.db.get_playlist_contents(int(playlist_id)))
        except (RuntimeError, ValueError):
            return []

    def _enumerate_all_m4a(self) -> list[Any]:
        # Legacy entry point kept for the backward-compat 'all_m4a' alias —
        # see enumerate_scope. Implemented via _enumerate_by_subset to stay
        # in sync with the new subset_kind dispatch.
        return self._enumerate_by_subset(
            {"subset_kind": "by_file_type", "file_type": FILE_TYPE_M4A}
        )

    def _enumerate_by_path(self, base_path: str) -> list[Any]:
        norm = str(base_path).replace("\\", "/").rstrip("/").lower()
        if not norm:
            return []
        out: list[Any] = []
        for c in self._iter_live_contents():
            fp = (getattr(c, "folder_path", "") or "").replace("\\", "/").lower()
            if fp.startswith(norm + "/") or fp == norm:
                out.append(c)
        return out

    def _enumerate_by_subset(self, scope: dict[str, Any]) -> list[Any]:
        """Library-subset dispatcher.

        Accepts a scope dict with ``subset_kind`` in:
            all, all_lossy, all_lossless, ranked, unranked, by_color,
            uncolored, by_mytag, by_file_type
        Required extras:
            by_color → color_id (0..8)
            by_mytag → tag_id
            by_file_type → file_type (Rekordbox FileType integer)
        """
        sub = scope.get("subset_kind")
        if sub is None:
            raise ValueError("library_subset requires subset_kind")

        out: list[Any] = []

        if sub == "all":
            for c in self._iter_live_contents():
                if getattr(c, "folder_path", "") or "":
                    out.append(c)
            return out

        if sub in ("all_lossy", "all_lossless"):
            allowed = LOSSY_SOURCE_EXTS if sub == "all_lossy" else LOSSLESS_SOURCE_EXTS
            for c in self._iter_live_contents():
                fp = (getattr(c, "folder_path", "") or "").lower()
                if not fp:
                    continue
                # Match by extension suffix (frozenset of dotted exts)
                if any(fp.endswith(ext) for ext in allowed):
                    out.append(c)
            return out

        if sub == "by_file_type":
            ft_raw = scope.get("file_type")
            if ft_raw is None:
                raise ValueError("subset_kind=by_file_type requires file_type")
            try:
                ft = int(ft_raw)
            except (TypeError, ValueError) as e:
                raise ValueError("subset_kind=by_file_type file_type must be int") from e
            for c in self._iter_live_contents():
                if not (getattr(c, "folder_path", "") or ""):
                    continue
                try:
                    if int(getattr(c, "file_type", 0) or 0) == ft:
                        out.append(c)
                except (TypeError, ValueError):
                    continue
            return out

        if sub == "ranked":
            for c in self._iter_live_contents():
                if not (getattr(c, "folder_path", "") or ""):
                    continue
                try:
                    if int(getattr(c, "rating", 0) or 0) > 0:
                        out.append(c)
                except (TypeError, ValueError):
                    continue
            return out

        if sub == "unranked":
            for c in self._iter_live_contents():
                if not (getattr(c, "folder_path", "") or ""):
                    continue
                try:
                    if int(getattr(c, "rating", 0) or 0) == 0:
                        out.append(c)
                except (TypeError, ValueError):
                    continue
            return out

        if sub == "by_color":
            cid_raw = scope.get("color_id")
            if cid_raw is None:
                raise ValueError("subset_kind=by_color requires color_id")
            try:
                cid = int(cid_raw)
            except (TypeError, ValueError) as e:
                raise ValueError("subset_kind=by_color color_id must be int") from e
            for c in self._iter_live_contents():
                if not (getattr(c, "folder_path", "") or ""):
                    continue
                try:
                    if int(getattr(c, "color_id", 0) or 0) == cid:
                        out.append(c)
                except (TypeError, ValueError):
                    continue
            return out

        if sub == "uncolored":
            for c in self._iter_live_contents():
                if not (getattr(c, "folder_path", "") or ""):
                    continue
                try:
                    if int(getattr(c, "color_id", 0) or 0) == 0:
                        out.append(c)
                except (TypeError, ValueError):
                    continue
            return out

        if sub == "by_mytag":
            tag_raw = scope.get("tag_id")
            if tag_raw is None:
                raise ValueError("subset_kind=by_mytag requires tag_id")
            tag_id_str = str(tag_raw)
            # live_db.track_to_tag_ids keys are str(track_id), values list[str]
            mapping = getattr(self.live_db, "track_to_tag_ids", {}) or {}
            for c in self._iter_live_contents():
                if not (getattr(c, "folder_path", "") or ""):
                    continue
                cid_str = str(getattr(c, "id", ""))
                tag_ids = mapping.get(cid_str) or []
                if tag_id_str in (str(t) for t in tag_ids):
                    out.append(c)
            return out

        raise ValueError(f"Unknown subset_kind: {sub!r}")

    def enumerate_scope(self, scope: dict[str, Any]) -> list[Any]:
        """Resolve a scope dict to rbox Content rows.

        scope shapes::

            {"kind": "track_ids", "ids": ["123", "456"]}
            {"kind": "playlist", "playlist_id": 12345}
            {"kind": "all_m4a"}   # legacy alias kept for backward compat
            {"kind": "library_subset", "subset_kind": "...",
             "color_id": int?, "tag_id": int?, "file_type": int?}
            {"kind": "path", "path": "C:/Users/.../Music/sub"}
        """
        kind = scope.get("kind")
        if kind == "track_ids":
            return self._enumerate_by_track_ids(list(scope.get("ids") or []))
        if kind == "playlist":
            pid = scope.get("playlist_id")
            if pid is None:
                raise ValueError("scope.playlist_id required")
            return self._enumerate_by_playlist(pid)
        if kind == "all_m4a":
            # Legacy alias — shim to library_subset/by_file_type. Manifest
            # writers keep scope.kind=='all_m4a' verbatim (no normalisation),
            # so old assertions + old API callers stay valid.
            return self._enumerate_all_m4a()
        if kind == "library_subset":
            return self._enumerate_by_subset(scope)
        if kind == "path":
            p = scope.get("path") or ""
            if not p:
                raise ValueError("scope.path required")
            return self._enumerate_by_path(str(p))
        raise ValueError(f"Unknown scope kind: {kind!r}")

    def _track_needs_conversion(self, c: Any) -> bool:
        try:
            fp = (getattr(c, "folder_path", "") or "").lower()
        except (AttributeError, TypeError):
            return False
        if not fp:
            return False
        # Skip if already at target format
        return not fp.endswith(self.target_ext.lower())

    def build_plans(self, scope: dict[str, Any]) -> list[TrackPlan]:
        plans: list[TrackPlan] = []
        for c in self.enumerate_scope(scope):
            if not self._track_needs_conversion(c):
                continue
            try:
                src = Path(c.folder_path)
                if not src.exists():
                    continue
            except (TypeError, ValueError, OSError):
                continue
            dst = src.with_suffix(self.target_ext)
            try:
                plans.append(
                    TrackPlan(
                        content_id=str(c.id),
                        source_path=src,
                        target_path=dst,
                        source_file_type=int(getattr(c, "file_type", 0) or 0),
                        source_file_size=int(getattr(c, "file_size", 0) or 0),
                    )
                )
            except (TypeError, ValueError):
                continue
        return plans

    # — Dry-run —

    def dry_run(self, scope: dict[str, Any]) -> DryRunResult:
        target_file_type = _detect_filetype_for_target(self.live_db, self.target)
        try:
            plans = self.build_plans(scope)
        except ValueError as e:
            return DryRunResult(
                scope=scope,
                target=self.target,
                tracks=[],
                total_source_mb=0.0,
                estimated_target_mb=0.0,
                drive_free_mb=0.0,
                drive_check_pass=False,
                target_file_type=target_file_type,
                warning=None,
                error=str(e),
            )

        total_src = sum(p.source_file_size for p in plans)
        expansion = float(TARGET_CONFIG[self.target]["expansion_ratio"])
        estimated_target = total_src * expansion

        drive_free = 0
        drive_check_pass = True
        warning: str | None = None
        if plans:
            try:
                usage = shutil.disk_usage(str(plans[0].source_path.parent))
                drive_free = int(usage.free)
                required_hard = int(estimated_target * DISK_HARD_ABORT_FACTOR)
                required_warn = int(estimated_target * DISK_WARN_FACTOR)
                if drive_free < required_hard:
                    drive_check_pass = False
                elif drive_free < required_warn:
                    warning = (
                        f"Disk free {drive_free / 1024 / 1024:.0f} MB is borderline "
                        f"(need ~{required_warn / 1024 / 1024:.0f} MB at 1.2x margin)"
                    )
            except OSError as e:
                warning = f"Disk-free check failed: {e}"

        return DryRunResult(
            scope=scope,
            target=self.target,
            tracks=[
                {
                    "content_id": p.content_id,
                    "source": str(p.source_path),
                    "target": str(p.target_path),
                    "source_size": p.source_file_size,
                }
                for p in plans
            ],
            total_source_mb=round(total_src / 1024 / 1024, 1),
            estimated_target_mb=round(estimated_target / 1024 / 1024, 1),
            drive_free_mb=round(drive_free / 1024 / 1024, 1),
            drive_check_pass=drive_check_pass,
            target_file_type=target_file_type,
            warning=warning,
            error=(
                None
                if drive_check_pass
                else (
                    f"Insufficient disk: need ~"
                    f"{(estimated_target * DISK_HARD_ABORT_FACTOR) / 1024 / 1024:.0f} MB at "
                    f"1.5x margin, free {drive_free / 1024 / 1024:.0f} MB"
                )
            ),
        )

    # — Execute —

    def execute(self, scope: dict[str, Any], batch_id: str | None = None) -> ExecuteResult:
        """Run the batch. Reports per-track progress via ``import_tracker``.

        Holds ``_engine_lock`` for the entire batch — serialises any other
        format-swap call. Raises ``RuntimeError`` if Rekordbox is running.
        """
        if _check_rekordbox_running():
            raise RuntimeError("Rekordbox is running — close it before format-swap.")

        bid = batch_id or uuid.uuid4().hex[:12]
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        plans = self.build_plans(scope)

        result = ExecuteResult(
            batch_id=bid,
            manifest_path="",
            tracks_planned=len(plans),
            tracks_converted=0,
            tracks_failed=0,
            failures=[],
            aborted=False,
            timestamp=timestamp,
            finished=False,
        )
        _store_batch(bid, result)

        if not plans:
            result.finished = True
            _store_batch(bid, result)
            return result

        target_file_type = _detect_filetype_for_target(self.live_db, self.target)
        backup_dir = _backup_root() / timestamp
        backup_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = backup_dir / f"manifest-{timestamp}.json"
        result.manifest_path = str(manifest_path)
        _store_batch(bid, result)

        db_backups = _backup_master_db(timestamp)
        manifest: dict[str, Any] = {
            "timestamp": timestamp,
            "batch_id": bid,
            "scope": scope,
            "target": self.target,
            "target_file_type": target_file_type,
            "db_backups": db_backups,
            "tracks": [],
        }

        def save_manifest() -> None:
            tmp = manifest_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
            tmp.replace(manifest_path)

        save_manifest()

        with _engine_lock:
            rbox_db = self.live_db.db
            for i, plan in enumerate(plans, 1):
                if i > 1 and i % WATCHDOG_INTERVAL == 0 and _kill_rekordbox_if_present():
                    logger.info(
                        "library_format_swap: watchdog killed re-launched Rekordbox at track %d/%d",
                        i,
                        len(plans),
                    )

                task_id = import_tracker.register(str(plan.source_path), source="format-swap")
                result.task_ids.append(task_id)

                src = plan.source_path
                dst = plan.target_path
                if not src.exists():
                    import_tracker.update(
                        task_id, status="Skipped", progress=100, error="file missing"
                    )
                    result.tracks_failed += 1
                    result.failures.append({"id": plan.content_id, "error": "source missing"})
                    _store_batch(bid, result)
                    continue

                import_tracker.update(task_id, status="Analyzing", progress=10)
                sample_rate = _probe_sample_rate(src)
                if not sample_rate:
                    import_tracker.update(
                        task_id,
                        status="Failed",
                        progress=100,
                        error="ffprobe SR failed",
                    )
                    result.tracks_failed += 1
                    result.failures.append({"id": plan.content_id, "error": "ffprobe SR failed"})
                    _store_batch(bid, result)
                    continue

                import_tracker.update(task_id, status="Analyzing", progress=30)
                try:
                    _run_ffmpeg_convert(src, dst, sample_rate, self.target)
                except RuntimeError as e:
                    logger.error("convert failed for %s: %s", src.name, e)
                    import_tracker.update(task_id, status="Failed", progress=100, error=str(e))
                    result.tracks_failed += 1
                    result.failures.append({"id": plan.content_id, "error": str(e)})
                    _store_batch(bid, result)
                    continue

                import_tracker.update(task_id, status="Importing", progress=70)
                backup_audio = src.with_name(src.name + f".backup-{timestamp}")
                try:
                    src.rename(backup_audio)
                except OSError as e:
                    logger.error("backup-rename failed for %s: %s", src.name, e)
                    if dst.exists():
                        with contextlib.suppress(OSError):
                            dst.unlink()
                    import_tracker.update(
                        task_id,
                        status="Failed",
                        progress=100,
                        error=f"backup-rename: {e}",
                    )
                    result.tracks_failed += 1
                    result.failures.append({"id": plan.content_id, "error": f"backup-rename: {e}"})
                    _store_batch(bid, result)
                    continue

                try:
                    c = rbox_db.get_content_by_id(plan.content_id)
                    old_folder_path = c.folder_path
                    old_file_name_l = c.file_name_l
                    old_file_type = int(c.file_type)
                    old_file_size = int(c.file_size or 0)
                    new_size = dst.stat().st_size

                    c.folder_path = str(dst)
                    c.file_name_l = dst.name
                    c.file_type = target_file_type
                    c.file_size = new_size
                    rbox_db.update_content(c)
                except Exception as e:  # pyrekordbox raises generic MasterDbError
                    logger.error("DB update failed for %s: %s", plan.content_id, e)
                    try:
                        if backup_audio.exists():
                            backup_audio.rename(src)
                        if dst.exists():
                            dst.unlink()
                    except OSError as inner:
                        logger.warning(
                            "per-track rollback also failed for %s: %s",
                            plan.content_id,
                            inner,
                        )
                    import_tracker.update(task_id, status="Failed", progress=100, error=f"db: {e}")
                    result.tracks_failed += 1
                    result.failures.append({"id": plan.content_id, "error": f"db: {e}"})
                    if "Rekordbox is running" in str(e):
                        logger.warning(
                            "library_format_swap: Rekordbox detected mid-batch — aborting"
                        )
                        result.aborted = True
                        save_manifest()
                        _store_batch(bid, result)
                        break
                    _store_batch(bid, result)
                    continue

                manifest["tracks"].append(
                    {
                        "id": plan.content_id,
                        "original": {
                            "folder_path": old_folder_path,
                            "file_name_l": old_file_name_l,
                            "file_type": old_file_type,
                            "file_size": old_file_size,
                            "audio_backup": str(backup_audio),
                        },
                        "new": {
                            "folder_path": str(dst),
                            "file_name_l": dst.name,
                            "file_type": target_file_type,
                            "file_size": new_size,
                        },
                    }
                )
                save_manifest()
                result.tracks_converted += 1
                import_tracker.update(task_id, status="Completed", progress=100)
                _store_batch(bid, result)

        save_manifest()
        result.finished = True
        _store_batch(bid, result)
        return result

    # — Rollback —

    def rollback(self, manifest_filename: str) -> dict[str, Any]:
        """Restore from a manifest. Returns counters.

        ``manifest_filename`` may be a basename (searched under all backup
        timestamp subdirs) or an absolute path.
        """
        if _check_rekordbox_running():
            raise RuntimeError("Rekordbox is running — close it before rollback.")

        mp = Path(manifest_filename)
        if not mp.is_absolute() or not mp.exists():
            base = _backup_root()
            found: Path | None = None
            if base.exists():
                for sub in base.iterdir():
                    if not sub.is_dir():
                        continue
                    candidate = sub / Path(manifest_filename).name
                    if candidate.exists():
                        found = candidate
                        break
            if not found:
                raise FileNotFoundError(f"manifest not found: {manifest_filename}")
            mp = found

        try:
            manifest = json.loads(mp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise RuntimeError(f"manifest parse error: {e}") from e

        with _engine_lock:
            for orig_str, bk_str in (manifest.get("db_backups") or {}).items():
                bk = Path(bk_str)
                orig = Path(orig_str)
                if bk.exists():
                    try:
                        shutil.copy2(bk, orig)
                    except OSError as e:
                        logger.warning("rollback: DB restore failed for %s: %s", orig, e)

            restored_audio = 0
            deleted_target = 0
            for track in manifest.get("tracks") or []:
                try:
                    backup_audio = Path(track["original"]["audio_backup"])
                    original_audio = Path(track["original"]["folder_path"])
                    new_audio = Path(track["new"]["folder_path"])
                except (KeyError, TypeError):
                    continue
                if backup_audio.exists():
                    try:
                        backup_audio.rename(original_audio)
                        restored_audio += 1
                    except OSError as e:
                        logger.warning(
                            "rollback: audio restore failed for %s: %s",
                            backup_audio,
                            e,
                        )
                if new_audio.exists():
                    try:
                        new_audio.unlink()
                        deleted_target += 1
                    except OSError as e:
                        logger.warning("rollback: target delete failed for %s: %s", new_audio, e)

        return {
            "manifest": str(mp),
            "tracks_in_manifest": len(manifest.get("tracks") or []),
            "audio_restored": restored_audio,
            "target_deleted": deleted_target,
            "db_restored": bool(manifest.get("db_backups")),
        }

    # — Manifest listing —

    @staticmethod
    def list_manifests() -> list[dict[str, Any]]:
        base = _backup_root()
        if not base.exists():
            return []
        out: list[dict[str, Any]] = []
        for sub in sorted(base.iterdir(), reverse=True):
            if not sub.is_dir():
                continue
            for f in sub.iterdir():
                if not (f.name.startswith("manifest-") and f.suffix == ".json"):
                    continue
                try:
                    m = json.loads(f.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                out.append(
                    {
                        "filename": f.name,
                        "path": str(f),
                        "timestamp": m.get("timestamp"),
                        "target": m.get("target"),
                        "tracks": len(m.get("tracks") or []),
                        "scope_kind": (m.get("scope") or {}).get("kind"),
                        "batch_id": m.get("batch_id"),
                    }
                )
        return out
