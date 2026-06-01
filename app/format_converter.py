"""Library format-converter engine — snapshot + transcode + content_id-keyed
`master.db` row mutation + rollback.

Ported from the proven `scripts/dev/safe_format_swap.py` (3041-track m4a→AIFF
run), generalised to any source → AIFF/FLAC/WAV/MP3 via `app.format_swap_codec`.
The correctness-critical pure logic (codec args, bit-depth, disk math) lives in
`format_swap_codec`; this module is the rbox + FFmpeg + filesystem orchestration.

Concurrency (research doc Gap 4): the whole batch holds `_db_write_lock` once
(`db_lock()`), in-process. rbox 0.1.7 cannot do concurrent `master.db` writes,
so single-writer is the only correct mode; the cost is that other writers wait
for the run (flagged in the doc's Performance Budget).

Integrity (OQ5): the engine mutates the existing `DjmdContent` row in place
(`folder_path`/`file_name_l`/`file_type`/`file_size` → `update_content`) and
NEVER deletes+re-adds — content_id stays stable, so beatgrid / cues / hot-cues /
memory-cues / MyTag / playlist membership survive the transcode.

Testability: `db` (rbox handle), the master.db path and backup dir are injected;
`_probe_sample_rate` / `_probe_bit_depth` / `_run_ffmpeg` / `_is_rekordbox_running`
/ `_kill_rekordbox_if_present` are module functions so tests monkeypatch them and
drive the full swap/rollback with a fake handle + dummy files (no rbox/FFmpeg).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from . import format_swap_codec as codec
from . import format_swap_tracker as tracker
from ._db_lock import db_lock
from .config import FFMPEG_BIN

logger = logging.getLogger(__name__)

_FFPROBE_BIN = "ffprobe"
_FFPROBE_TIMEOUT = 30
_FFMPEG_TIMEOUT = 600  # OQ3: 10x margin over worst 60-min-set-on-slow-USB case.
_WATCHDOG_EVERY = 50  # kill auto-relaunched Rekordbox every N tracks.


class FormatSwapError(Exception):
    """Raised for fatal, caller-visible engine failures (bad scope, RB running,
    disk abort). Per-track failures are recorded in the manifest, not raised."""


# --------------------------------------------------------------------------
# Process helpers (monkeypatched in tests; real impls shell out)
# --------------------------------------------------------------------------


def _is_rekordbox_running() -> bool:
    """True if rekordbox.exe is in the Windows tasklist. Non-Windows / probe
    failure → False (best-effort; the per-track DB-write failure is the backstop)."""
    try:
        result = subprocess.run(["tasklist"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    return "rekordbox.exe" in (result.stdout or "").lower()


def _kill_rekordbox_if_present() -> bool:
    """Watchdog: kill a Pioneer-relaunched Rekordbox before the next write hits
    a 'Rekordbox is running' error. Returns True if it killed something."""
    try:
        if not _is_rekordbox_running():
            return False
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-Process | Where-Object { $_.Name -match 'rekordbox|Upmgr' } "
                "| Stop-Process -Force",
            ],
            capture_output=True,
            timeout=15,
        )
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def _probe_sample_rate(src: Path) -> int:
    """Source sample rate via ffprobe. Output SR is locked to this → no resample
    → no cue/beatgrid drift (OQ1)."""
    result = subprocess.run(
        [
            _FFPROBE_BIN,
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=sample_rate",
            "-of",
            "csv=p=0",
            str(src),
        ],
        capture_output=True,
        text=True,
        timeout=_FFPROBE_TIMEOUT,
        check=True,
    )
    return int(result.stdout.strip())


def _probe_bit_depth(src: Path) -> int:
    """Source bit depth (16/24) via ffprobe sample_fmt (primary) +
    bits_per_raw_sample (fallback). See `codec.parse_bit_depth`."""
    result = subprocess.run(
        [
            _FFPROBE_BIN,
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=sample_fmt,bits_per_raw_sample",
            "-of",
            "csv=p=0",
            str(src),
        ],
        capture_output=True,
        text=True,
        timeout=_FFPROBE_TIMEOUT,
        check=True,
    )
    return codec.parse_bit_depth(result.stdout)


def _run_ffmpeg(cmd: list[str]) -> None:
    """Run an FFmpeg arg list (never a shell string — Threat CI-1). Raises
    FormatSwapError on non-zero exit / timeout."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=_FFMPEG_TIMEOUT)
    except subprocess.TimeoutExpired as e:
        raise FormatSwapError(f"ffmpeg timed out after {_FFMPEG_TIMEOUT}s") from e
    if result.returncode != 0:
        raise FormatSwapError(f"ffmpeg failed: {(result.stderr or '').strip()[:500]}")


def default_backup_dir() -> Path:
    """App-data backup/manifest dir (NOT scripts/dev/backups). Created on use."""
    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home() / ".local" / "share"
    return base / "LibraryManagementSystem" / "format_swap_backups"


# --------------------------------------------------------------------------
# Engine
# --------------------------------------------------------------------------


@dataclass
class _Plan:
    scope_label: str
    convertible: list[Any]
    skipped: int
    source_bytes: int
    target: str


@dataclass
class FormatSwapEngine:
    """One engine per request. `db` is the rbox `MasterDb` handle (real:
    `app.database.db.active_db.db`; test: a fake). `master_db_path` is backed up
    before any write. `backup_dir` holds snapshots + manifests."""

    db: Any
    master_db_path: Path
    backup_dir: Path = field(default_factory=default_backup_dir)
    ffmpeg_bin: str = FFMPEG_BIN

    # ---- scope resolution -------------------------------------------------

    def _all_contents(self) -> list[Any]:
        return [c for c in self.db.get_contents() if not getattr(c, "rb_local_deleted", False)]

    def resolve_scope(self, scope: dict) -> tuple[list[Any], str]:
        """Return (content_rows, human_label) for a scope dict. Exactly one of
        track_ids / playlist_id / all_m4a / path. Path matching is
        separator-normalised + case-insensitive (master.db stores '/'). Caller
        (route) is responsible for the ALLOWED_AUDIO_ROOTS sandbox check on a
        user-supplied `path` BEFORE calling — Threat FS-1."""
        if scope.get("track_ids"):
            wanted = {str(i) for i in scope["track_ids"]}
            items = [c for c in self._all_contents() if str(c.id) in wanted]
            return items, f"{len(items)} selected track(s)"
        if scope.get("playlist_id") is not None:
            pid = scope["playlist_id"]
            items = list(self.db.get_playlist_contents(pid))
            items = [c for c in items if not getattr(c, "rb_local_deleted", False)]
            return items, f"playlist id={pid}"
        if scope.get("all_m4a"):
            items = [
                c
                for c in self._all_contents()
                if str(getattr(c, "folder_path", "")).lower().endswith((".m4a", ".m4p"))
            ]
            return items, "all m4a in library"
        if scope.get("path"):
            norm = str(scope["path"]).replace("\\", "/").rstrip("/").lower()
            items = [
                c
                for c in self._all_contents()
                if (fp := str(getattr(c, "folder_path", "")).replace("\\", "/").lower())
                and (fp.startswith(norm + "/") or fp == norm)
            ]
            return items, f"path {scope['path']!r}"
        raise FormatSwapError("scope must set one of track_ids / playlist_id / all_m4a / path")

    def _build_plan(self, scope: dict, target: str) -> _Plan:
        target = target.upper()
        if target not in codec.VALID_TARGETS:
            raise FormatSwapError(f"unknown target {target!r}; valid: {codec.VALID_TARGETS}")
        target_ext = codec.target_extension(target)
        items, label = self.resolve_scope(scope)
        convertible: list[Any] = []
        skipped = 0
        source_bytes = 0
        for c in items:
            fp = str(getattr(c, "folder_path", "") or "")
            if not fp or fp.lower().endswith(target_ext):
                skipped += 1  # already target format, or no path
                continue
            convertible.append(c)
            with contextlib.suppress(TypeError, ValueError):
                source_bytes += int(getattr(c, "file_size", 0) or 0)
        return _Plan(label, convertible, skipped, source_bytes, target)

    # ---- dry run ----------------------------------------------------------

    def dry_run(self, scope: dict, target: str) -> dict:
        """Synchronous plan — counts, size forecast, disk verdict, preview. No
        writes."""
        plan = self._build_plan(scope, target)
        est = codec.estimate_target_bytes(plan.source_bytes, plan.target)
        try:
            free = shutil.disk_usage(self.master_db_path.parent).free
        except OSError:
            free = 0
        verdict = codec.disk_verdict(free, est)
        preview = [
            {"id": getattr(c, "id", None), "name": Path(str(c.folder_path)).name}
            for c in plan.convertible[:8]
        ]
        return {
            "dry_run": True,
            "scope": plan.scope_label,
            "target": plan.target,
            "convertible": len(plan.convertible),
            "skipped": plan.skipped,
            "source_mb": round(plan.source_bytes / 1024 / 1024, 1),
            "estimated_target_mb": round(est / 1024 / 1024, 1),
            "disk_free_mb": round(verdict["free_bytes"] / 1024 / 1024, 1),
            "disk_warning": verdict["warning"],
            "disk_abort": verdict["abort"],
            "preview": preview,
        }

    # ---- snapshot + manifest ---------------------------------------------

    def _backup_master_db(self, ts: str) -> dict[str, str]:
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        backups: dict[str, str] = {}
        for suffix in ("", "-wal", "-shm"):
            srcp = Path(str(self.master_db_path) + suffix)
            if srcp.exists():
                dst = self.backup_dir / f"{srcp.name}.backup-{ts}"
                shutil.copy2(srcp, dst)
                backups[str(srcp)] = str(dst)
        return backups

    @staticmethod
    def _save_manifest(manifest: dict, path: Path) -> None:
        # Atomic: tmp write then replace, so a crash mid-write can't corrupt the
        # manifest rollback depends on.
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        tmp.replace(path)

    def _detect_target_file_type(self, target_ext: str, fallback: int) -> int:
        """Reuse the FileType integer Rekordbox already uses for rows of this
        extension; fall back to the codec module's provisional value."""
        for c in self.db.get_contents():
            fp = str(getattr(c, "folder_path", "") or "").lower()
            if fp.endswith(target_ext):
                try:
                    return int(c.file_type)
                except (TypeError, ValueError, AttributeError):
                    break
        return fallback

    # ---- the swap loop ----------------------------------------------------

    def run(
        self, scope: dict, target: str, *, options: dict | None = None, task_id: str | None = None
    ) -> dict:
        """Execute the batch. Acquires `db_lock()` once for the whole batch
        (Gap 4). Returns the manifest dict. Per-track failures are recorded, not
        raised; a fatal condition (RB running, disk abort) raises FormatSwapError
        or marks the manifest aborted."""
        options = options or {}
        plan = self._build_plan(scope, target)
        if not plan.convertible:
            if task_id:
                tracker.update(task_id, status="Completed", total=0)
            return {"tracks": [], "aborted": False, "converted": 0, "manifest_id": None}

        if _is_rekordbox_running():
            raise FormatSwapError("Rekordbox is running — close it before converting.")

        est = codec.estimate_target_bytes(plan.source_bytes, plan.target)

        free = shutil.disk_usage(self.master_db_path.parent).free
        verdict = codec.disk_verdict(free, est)
        if verdict["abort"]:
            raise FormatSwapError(
                f"insufficient disk: need ~{verdict['abort_threshold_bytes'] // 1024 // 1024} MB free, "
                f"have {free // 1024 // 1024} MB"
            )

        target_ext = codec.target_extension(plan.target)
        file_type = self._detect_target_file_type(
            target_ext, codec.rekordbox_file_type(plan.target)
        )
        force_16 = bool(options.get("force_16bit_flac"))
        mp3_quality = int(options.get("mp3_quality", 0))

        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        manifest_id = f"manifest-{ts}.json"
        manifest_path = self.backup_dir / manifest_id
        logger.info(
            "op=format_swap.start trigger=%s scope=%s target=%s n=%d dry_run=False",
            scope.get("trigger", "user_format_pick"),
            plan.scope_label,
            plan.target,
            len(plan.convertible),
        )
        logger.info(
            "op=format_swap.disk free_mb=%d est_mb=%d abort=False warn=%s",
            free // 1024 // 1024,
            est // 1024 // 1024,
            verdict["warning"],
        )

        if task_id:
            tracker.update(
                task_id,
                status="Converting",
                total=len(plan.convertible),
                manifest_id=manifest_id,
            )

        started = time.time()
        with db_lock():  # batch-scoped, in-process (Gap 4)
            manifest = self._convert_batch(
                plan,
                target_ext,
                file_type,
                force_16,
                mp3_quality,
                ts,
                manifest_path,
                task_id,
            )

        elapsed = time.time() - started
        converted = len(manifest["tracks"])
        logger.info(
            "op=format_swap.done converted=%d failed=%d aborted=%s elapsed_s=%.1f manifest=%s",
            converted,
            manifest["failed"],
            manifest["aborted"],
            elapsed,
            manifest_id,
        )
        if task_id:
            tracker.update(
                task_id,
                status="Aborted" if manifest["aborted"] else "Completed",
            )
        return manifest

    def _convert_batch(
        self,
        plan: _Plan,
        target_ext: str,
        file_type: int,
        force_16: bool,
        mp3_quality: int,
        ts: str,
        manifest_path: Path,
        task_id: str | None,
    ) -> dict:
        db_backups = self._backup_master_db(ts)
        manifest: dict = {
            "timestamp": ts,
            "scope": plan.scope_label,
            "target": plan.target,
            "db_backups": db_backups,
            "target_file_type": file_type,
            "tracks": [],
            "failed": 0,
            "aborted": False,
            "beatgrid_preserved": True,
        }
        self._save_manifest(manifest, manifest_path)  # anchor before first track

        for i, c in enumerate(plan.convertible, 1):
            if i > 1 and i % _WATCHDOG_EVERY == 0 and _kill_rekordbox_if_present():
                logger.info("op=format_swap.watchdog killed_rekordbox=true")

            src = Path(str(c.folder_path))
            dst = src.with_suffix(target_ext)
            name = src.name
            if not src.exists():
                manifest["failed"] += 1
                tracker.mark_track(task_id, name, ok=False)
                logger.info(
                    "op=format_swap.track i=%d/%d id=%s action=skip-missing",
                    i,
                    len(plan.convertible),
                    getattr(c, "id", "?"),
                )
                continue

            try:
                sr = _probe_sample_rate(src)
                bit_depth = 16 if force_16 else _probe_bit_depth(src)
                cmd = codec.build_ffmpeg_cmd(
                    self.ffmpeg_bin,
                    str(src),
                    str(dst),
                    plan.target,
                    bit_depth=bit_depth,
                    sample_rate=sr,
                    mp3_quality=mp3_quality,
                )
                _run_ffmpeg(cmd)
            except (FormatSwapError, subprocess.SubprocessError, ValueError, OSError) as e:
                manifest["failed"] += 1
                tracker.mark_track(task_id, name, ok=False)
                logger.warning(
                    "op=format_swap.track i=%d id=%s action=fail err=%s",
                    i,
                    getattr(c, "id", "?"),
                    e,
                )
                # Clean up a partial output; the original is still in place
                # (src not yet renamed) so no data is at risk.
                if dst.exists() and dst != src:
                    dst.unlink(missing_ok=True)
                continue

            backup_audio = src.with_name(src.name + f".backup-{ts}")
            old = {
                "folder_path": c.folder_path,
                "file_name_l": c.file_name_l,
                "file_type": int(getattr(c, "file_type", 0) or 0),
                "file_size": getattr(c, "file_size", 0),
            }
            src.rename(backup_audio)
            new_size = dst.stat().st_size
            c.folder_path = str(dst)
            c.file_name_l = dst.name
            c.file_type = file_type
            c.file_size = new_size
            try:
                self.db.update_content(c)
            except Exception as e:
                self._recover_track(c, src, dst, backup_audio, old)
                manifest["failed"] += 1
                tracker.mark_track(task_id, name, ok=False)
                logger.warning(
                    "op=format_swap.track i=%d id=%s action=db-fail err=%s",
                    i,
                    getattr(c, "id", "?"),
                    e,
                )
                if "Rekordbox is running" in str(e):
                    manifest["aborted"] = True
                    self._save_manifest(manifest, manifest_path)
                    break
                continue

            manifest["tracks"].append(
                {
                    "id": c.id,
                    "original": {**old, "audio_backup": str(backup_audio)},
                    "new": {
                        "folder_path": str(dst),
                        "file_name_l": dst.name,
                        "file_type": file_type,
                        "file_size": new_size,
                    },
                }
            )
            tracker.mark_track(task_id, name, ok=True)
            logger.info(
                "op=format_swap.track i=%d/%d id=%s sr=%d action=convert",
                i,
                len(plan.convertible),
                c.id,
                sr,
            )
            self._save_manifest(manifest, manifest_path)

        self._save_manifest(manifest, manifest_path)
        manifest["manifest_id"] = manifest_path.name
        return manifest

    @staticmethod
    def _recover_track(c: Any, src: Path, dst: Path, backup_audio: Path, old: dict) -> None:
        """Per-track recovery after a DB-write failure: restore the file pair +
        revert the in-memory rbox row attrs so files and DB stay consistent."""
        try:
            if backup_audio.exists():
                backup_audio.rename(src)
            if dst.exists():
                dst.unlink()
            c.folder_path = old["folder_path"]
            c.file_name_l = old["file_name_l"]
            c.file_type = old["file_type"]
            c.file_size = old["file_size"]
        except OSError as inner:
            logger.warning(
                "op=format_swap.recover-failed id=%s err=%s", getattr(c, "id", "?"), inner
            )

    # ---- rollback ---------------------------------------------------------

    def rollback(self, manifest_id: str) -> dict:
        """Restore DB+WAL+SHM from snapshot, rename `.backup-<ts>` audio back,
        delete the converted files. `manifest_id` is treated as an opaque
        basename under `backup_dir` (Threat FS-3 — no path traversal)."""
        if _is_rekordbox_running():
            raise FormatSwapError("Rekordbox is running — close it before rolling back.")
        safe_name = Path(manifest_id).name  # strip any path components
        if safe_name != manifest_id or not safe_name:
            raise FormatSwapError(f"invalid manifest id {manifest_id!r}")
        manifest_path = self.backup_dir / safe_name
        if not manifest_path.exists():
            raise FormatSwapError(f"manifest not found: {safe_name}")

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        db_restored = False
        for orig, bk in manifest.get("db_backups", {}).items():
            bkp = Path(bk)
            if not bkp.exists():
                raise FormatSwapError(f"db backup missing: {bkp}")
            shutil.copy2(bkp, Path(orig))
            db_restored = True

        restored = 0
        for track in manifest.get("tracks", []):
            backup_audio = Path(track["original"]["audio_backup"])
            original_audio = Path(track["original"]["folder_path"])
            new_audio = Path(track["new"]["folder_path"])
            if backup_audio.exists():
                backup_audio.rename(original_audio)
                restored += 1
            if new_audio.exists() and new_audio != original_audio:
                new_audio.unlink()
        logger.info("op=format_swap.rollback manifest=%s restored=%d", safe_name, restored)
        return {"restored_tracks": restored, "db_restored": db_restored}
