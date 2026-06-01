"""Per-batch format-conversion progress tracker.

Gives the frontend a live view of a running format-swap batch (see
`app/format_converter.py`). Thread-safe singleton, modelled on
`app/import_tracker.py` so a unified progress UI can show both pipelines.

A *task* is one batch run (not one track). The engine `update()`s it per track.

Statuses:
  Queued      — registered, daemon thread not started yet
  Converting  — transcoding + master.db row mutation in progress
  Completed   — all tracks done
  Aborted     — stopped mid-run (disk pressure / Rekordbox relaunch / user)
  Failed      — fatal error before/aside per-track handling (see `error`)
"""

from __future__ import annotations

import logging
import threading
import time
import uuid

logger = logging.getLogger(__name__)

_TASKS: dict[str, dict] = {}
_LOCK = threading.Lock()
_MAX_KEEP = 200  # cap retention so memory stays bounded over a long session

_FINISHED = ("Completed", "Aborted", "Failed")


def _prune_locked() -> None:
    if len(_TASKS) <= _MAX_KEEP:
        return
    finished = [(k, v) for k, v in _TASKS.items() if v.get("status") in _FINISHED]
    finished.sort(key=lambda kv: kv[1].get("start_time") or 0)
    for k, _ in finished[: len(_TASKS) - _MAX_KEEP]:
        _TASKS.pop(k, None)


def register(trigger: str, target: str, scope: str, total: int) -> str:
    """Create a task for a batch we're about to convert. Returns task_id."""
    tid = uuid.uuid4().hex[:12]
    now = time.time()
    with _LOCK:
        _TASKS[tid] = {
            "id": tid,
            "trigger": trigger,
            "target": target,
            "scope": scope,
            "status": "Queued",
            "progress": 0,  # 0-100
            "total": int(total),
            "converted": 0,
            "failed": 0,
            "current_track": None,
            "manifest_id": None,
            "beatgrid_preserved": True,
            "error": None,
            "start_time": now,
            "stage_history": [{"stage": "Queued", "ts": now}],
        }
        _prune_locked()
    return tid


def update(task_id: str | None, **kwargs) -> None:
    """Patch fields on a task. Recomputes `progress` from converted+failed/total
    unless `progress` is passed explicitly. Appends to stage_history on status
    change."""
    if not task_id:
        return
    with _LOCK:
        t = _TASKS.get(task_id)
        if not t:
            return
        if "status" in kwargs:
            new_stage = kwargs["status"]
            history = t.get("stage_history") or []
            if not history or history[-1].get("stage") != new_stage:
                history.append({"stage": new_stage, "ts": time.time()})
                t["stage_history"] = history
        t.update(kwargs)
        if "progress" not in kwargs:
            total = t.get("total") or 0
            if total > 0:
                done = (t.get("converted") or 0) + (t.get("failed") or 0)
                t["progress"] = min(100, round(done * 100 / total))


def mark_track(
    task_id: str | None, name: str, *, ok: bool, beatgrid_preserved: bool = True
) -> None:
    """Convenience: record one track outcome (increments converted/failed)."""
    if not task_id:
        return
    with _LOCK:
        t = _TASKS.get(task_id)
        if not t:
            return
        t["current_track"] = name
        if ok:
            t["converted"] = (t.get("converted") or 0) + 1
        else:
            t["failed"] = (t.get("failed") or 0) + 1
        if not beatgrid_preserved:
            t["beatgrid_preserved"] = False
        total = t.get("total") or 0
        if total > 0:
            done = (t.get("converted") or 0) + (t.get("failed") or 0)
            t["progress"] = min(100, round(done * 100 / total))


def get(task_id: str) -> dict | None:
    with _LOCK:
        v = _TASKS.get(task_id)
        return dict(v) if v else None


def get_all() -> dict[str, dict]:
    with _LOCK:
        return {k: dict(v) for k, v in _TASKS.items()}


def clear_finished() -> int:
    with _LOCK:
        before = len(_TASKS)
        for k in list(_TASKS.keys()):
            if _TASKS[k].get("status") in _FINISHED:
                _TASKS.pop(k, None)
        return before - len(_TASKS)
