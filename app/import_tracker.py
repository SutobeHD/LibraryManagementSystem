"""
Per-file import-progress tracker — gives the frontend a live transparent
view of what the local-file import pipeline is doing (Drag-Drop / Folder
Browse → analyse → library insert → ANLZ).

Thread-safe singleton. Stages mirror the SC-DL Download Manager so a
unified UI can show both pipelines side-by-side.

Stages:
  Queued      — registered, not started yet
  Analyzing   — running run_full_analysis (BPM/Key/Beats/Phrases/Cues)
  Importing   — inserting into library + cover art
  ANLZ        — writing DAT/EXT/2EX sidecars
  Completed   — done (track in library + ANLZ written)
  Skipped     — already known audio path
  Failed      — error, see `error` field
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


_TASKS: Dict[str, Dict] = {}
_LOCK = threading.Lock()
_MAX_KEEP = 500   # cap retention so memory stays bounded over a long session


def _prune_locked():
    if len(_TASKS) <= _MAX_KEEP:
        return
    # drop the oldest completed/failed/skipped first
    finished = [
        (k, v) for k, v in _TASKS.items()
        if v.get("status") in ("Completed", "Failed", "Skipped")
    ]
    finished.sort(key=lambda kv: kv[1].get("start_time") or 0)
    for k, _ in finished[: len(_TASKS) - _MAX_KEEP]:
        _TASKS.pop(k, None)


def register(file_path: str, source: str = "drag-drop") -> str:
    """Create a task for a file we're about to import. Returns task_id."""
    tid = uuid.uuid4().hex[:12]
    now = time.time()
    with _LOCK:
        _TASKS[tid] = {
            "id": tid,
            "file_path": str(file_path),
            "title": _basename(file_path),
            "source": source,
            "status": "Queued",
            "progress": 0,
            "error": None,
            "start_time": now,
            "stage_history": [{"stage": "Queued", "ts": now}],
            "bpm": None, "key": None,
            "local_track_id": None,
        }
        _prune_locked()
    return tid


def update(task_id: str, **kwargs) -> None:
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


def get_all() -> Dict[str, Dict]:
    """Return a shallow copy of all current tasks (for the API)."""
    with _LOCK:
        return {k: dict(v) for k, v in _TASKS.items()}


def get(task_id: str) -> Optional[Dict]:
    with _LOCK:
        v = _TASKS.get(task_id)
        return dict(v) if v else None


def clear_finished() -> int:
    """Remove all Completed/Failed/Skipped rows. Returns count removed."""
    with _LOCK:
        before = len(_TASKS)
        for k in list(_TASKS.keys()):
            if _TASKS[k].get("status") in ("Completed", "Failed", "Skipped"):
                _TASKS.pop(k, None)
        return before - len(_TASKS)


def _basename(p: str) -> str:
    s = str(p).replace("\\", "/").rsplit("/", 1)[-1]
    return s
