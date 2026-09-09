"""artist_store.sync — the idle signal + the background catalogue refresh (T-17).

Two halves, deliberately in one module because neither is useful alone:

**The idle signal.** Nothing in this app exposed "open, but not under load", so it is
*composed* here out of the trackers that already exist — the phrase batch, the artist
jobs, the duplicate scan, the SoundCloud downloader, the local-import tracker, and the
single-flight locks that guard USB sync / merge / projection / batch download.
:func:`is_idle` returns ``(bool, reason)`` so a log line and the UI can say **why** a run
did not happen instead of shrugging. Every probe fails **closed**: an exception, an
unknown job status or an unreadable tracker means *busy*, never *idle*.

One load path is **not observable** and is named rather than hidden:
``POST /api/library/analyze-batch`` streams NDJSON straight from the writer and keeps no
job record, so nothing here can see it. :func:`idle_report` lists it under
``unobservable``; :func:`register_probe` is the hook for ``app/main.py`` to close that
gap once the route counts its in-flight runs.

**The background pass.** For every favourite whose mode is ``auto`` or ``review``:
refresh the catalogue through the caller's refresher — the *same* route body the manual
Update button uses, never a second fetcher — oldest-last-synced first, under **one**
:class:`CallBudget` shared by the whole run, re-checking idle between artists. Mode
``off`` is skipped without a single call.

The pass **never downloads and never queues anything**: a download is user-initiated
(owner decision, ToU guardrails in ``docs/research/implement/inprogress_library-artist-hub.md``).
All it does is keep the catalogue cache — and therefore the badge counts — current.
``downloads_queued`` is in the run record and is always ``0`` so that invariant is
observable rather than merely asserted. ``auto`` and ``review`` fetch identically here;
they differ only in what the *foreground* is allowed to offer afterwards.

No HTTP, no credentials, no ``master.db`` in this module. The refresher owns all three.
"""

from __future__ import annotations

import inspect
import json
import logging
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.artist_store import catalogue as catalogue_mod
from app.artist_store import schema

logger = logging.getLogger("ARTIST_STORE")

#: Settings key for the one boolean this feature owns. Opt-in: the user turns background
#: sync on, it is never on by default.
SETTING_KEY = "artist_background_sync"
SETTING_DEFAULT = False

#: Hard per-run call cap, shared by every artist in the run and logged when the run ends.
#: Deliberately far below `SC_DEFAULT_CALL_BUDGET * MAX_ARTISTS_PER_RUN`: a background
#: pass is a refresh, not a crawl. An artist the budget cut off sorts first next run.
SYNC_CALL_BUDGET = 60

#: Hard per-run artist cap. Second belt beside the call budget — a 300-favourite library
#: still only touches a slice per pass.
MAX_ARTISTS_PER_RUN = 20

#: An artist refreshed more recently than this is left alone: the payload would still be
#: inside the catalogue TTL, so the calls would buy nothing.
MIN_RESYNC_INTERVAL_S = float(catalogue_mod.CACHE_TTL_S)

#: A tracker entry older than this with no terminal status is treated as abandoned, not
#: as running work. Only applied where the tracker stamps a start time. Every entry
#: dropped this way is listed in `idle_report()["stale_ignored"]` — never silently.
STALE_TASK_S = 2 * 60 * 60.0

#: Job/task states that mean "finished". Anything else — including a status this module
#: has never heard of — counts as running.
TERMINAL_STATES = frozenset(
    {
        "analysis failed",
        "cancelled",
        "canceled",
        "completed",
        "done",
        "duplicate",
        "error",
        "failed",
        "skipped",
    }
)

STOP_IDLE = "idle"
STOP_DISABLED = "disabled"
STOP_BUSY = "busy"
STOP_CALL_BUDGET = "call_budget_exhausted"
STOP_ARTIST_CAP = "artist_cap_reached"
STOP_COMPLETED = "completed"
STOP_NO_REFRESHER = "refresher_unsupported"
STOP_NOT_CONNECTED = "not_connected"

#: Meta key holding the last run record, so the UI can render "last checked" without a
#: job store. `store_meta` is v1 — no migration needed for this.
META_LAST_RUN = "background_sync_last_run"

#: Load paths that exist but report nothing. Named so no caller can mistake "idle" for
#: "provably nothing running".
UNOBSERVABLE_LOAD = (
    "analyze_batch: POST /api/library/analyze-batch streams its progress and keeps no "
    "job record — register a probe from app/main.py to cover it",
)

#: A refresher must accept this keyword, or the run cannot honour one shared budget.
BUDGET_KWARG = "budget"


class SyncError(Exception):
    """Background sync could not run at all."""


#: Returns a reason string when the app is BUSY, None when this probe is quiet.
IdleProbe = Callable[[], "str | None"]

#: `(collection_id, *, budget) -> view`. The view is `_artist_catalogue_view`'s payload:
#: `status="ok"` plus the catalogue buckets, or a typed non-catalogue state.
Refresher = Callable[..., Mapping[str, Any]]

_extra_probes: dict[str, IdleProbe] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- probes


def _is_running(status: Any) -> bool:
    """True unless the status is a state we recognise as finished (fail closed)."""
    return str(status or "").strip().lower() not in TERMINAL_STATES


def _stale(entry: Mapping[str, Any], now: float) -> bool:
    started = entry.get("start_time")
    if not isinstance(started, (int, float)):
        return False
    return (now - float(started)) > STALE_TASK_S


def _busy_entries(
    tasks: Mapping[str, Mapping[str, Any]],
    label: str,
    stale_out: list[str],
) -> str | None:
    """First running entry's reason, ignoring (and reporting) abandoned ones."""
    now = time.time()
    for task_id, entry in tasks.items():
        if not isinstance(entry, Mapping) or not _is_running(entry.get("status")):
            continue
        if _stale(entry, now):
            stale_out.append(f"{label}:{task_id}")
            continue
        return f"{label}:{entry.get('status') or 'running'}"
    return None


def _main_module() -> Any:
    # Late import on purpose: `app.main` imports this package, so a module-level import
    # would be circular. Probes are only ever called from a running app or a test that
    # has already imported main.
    from app import main as main_module

    return main_module


def _probe_library(_stale_out: list[str]) -> str | None:
    """A library that is not loaded is either booting or mid-swap. Both mean wait."""
    from app.database import db

    return None if getattr(db, "loaded", False) else "library_not_loaded"


def _probe_phrase_jobs(stale_out: list[str]) -> str | None:
    return _busy_entries(_main_module()._phrase_jobs, "phrase_batch", stale_out)


def _probe_artist_jobs(stale_out: list[str]) -> str | None:
    return _busy_entries(_main_module()._artist_jobs, "artist_job", stale_out)


def _probe_duplicate_jobs(stale_out: list[str]) -> str | None:
    return _busy_entries(_main_module()._dup_jobs, "duplicate_scan", stale_out)


def _probe_sc_downloads(stale_out: list[str]) -> str | None:
    from app.soundcloud_downloader import sc_downloader

    # Read-only: snapshot under the downloader's own lock so a task mutating mid-walk
    # cannot produce a half-read verdict. Nothing here starts a download.
    with sc_downloader._lock:
        snapshot = {k: dict(v) for k, v in sc_downloader.tasks.items()}
    return _busy_entries(snapshot, "sc_download", stale_out)


def _probe_local_imports(stale_out: list[str]) -> str | None:
    from app import import_tracker

    return _busy_entries(import_tracker.get_all(), "local_import", stale_out)


def _probe_job_locks(_stale_out: list[str]) -> str | None:
    """The single-flight guards, which are held before their job record exists."""
    main_module = _main_module()
    guards = (
        ("usb_sync", "_sync_lock"),
        ("phrase_batch", "_phrase_batch_lock"),
        ("artist_job", "_artist_job_lock"),
        ("artist_download", "_artist_download_lock"),
    )
    for label, attr in guards:
        lock = getattr(main_module, attr, None)
        if lock is not None and lock.locked():
            return f"{label}:lock_held"
    return None


#: Probe order is the report order. Cheapest and most decisive first.
_PROBES: tuple[tuple[str, Callable[[list[str]], str | None]], ...] = (
    ("library", _probe_library),
    ("job_locks", _probe_job_locks),
    ("phrase_jobs", _probe_phrase_jobs),
    ("artist_jobs", _probe_artist_jobs),
    ("duplicate_jobs", _probe_duplicate_jobs),
    ("sc_downloads", _probe_sc_downloads),
    ("local_imports", _probe_local_imports),
)


def register_probe(name: str, probe: IdleProbe) -> None:
    """Add a load signal this module cannot see itself (e.g. the streaming analyse run).

    ``probe()`` returns a reason string while that work is running, ``None`` when it is
    not. Registering the same name twice replaces the earlier probe.
    """
    _extra_probes[str(name)] = probe


def unregister_probe(name: str) -> bool:
    return _extra_probes.pop(str(name), None) is not None


def idle_report() -> dict[str, Any]:
    """Per-probe verdict, for the UI and the run log.

    ``probes`` maps every probe name to ``"quiet"`` or the reason it is busy. A probe
    that raised reads ``probe_error:…`` and counts as busy — this module never treats an
    unreadable tracker as proof of quiet. ``unobservable`` names the load paths nothing
    here can see, so "idle" is never mistaken for "nothing is running".
    """
    stale_ignored: list[str] = []
    verdicts: dict[str, str] = {}
    busy_reason = ""
    for name, probe in _PROBES:
        try:
            reason = probe(stale_ignored)
        except Exception as exc:
            # Fail closed: an unreadable tracker is not evidence of an idle app.
            reason = f"probe_error:{type(exc).__name__}"
            logger.debug("op=artist_sync_probe name=%s err=%s", name, exc)
        verdicts[name] = reason or "quiet"
        busy_reason = busy_reason or (reason or "")
    for name, extra in tuple(_extra_probes.items()):
        try:
            reason = extra()
        except Exception as exc:
            reason = f"probe_error:{type(exc).__name__}"
            logger.debug("op=artist_sync_probe name=%s err=%s", name, exc)
        verdicts[name] = reason or "quiet"
        busy_reason = busy_reason or (reason or "")
    return {
        "idle": not busy_reason,
        "reason": busy_reason or STOP_IDLE,
        "probes": verdicts,
        "stale_ignored": stale_ignored,
        "unobservable": list(UNOBSERVABLE_LOAD),
    }


def is_idle() -> tuple[bool, str]:
    """``(idle, reason)``. ``reason`` is ``"idle"`` when idle, else the first busy probe.

    Conservative by construction: any probe that cannot answer counts as busy.
    """
    report = idle_report()
    return bool(report["idle"]), str(report["reason"])


# --------------------------------------------------------------------------- settings


def background_sync_enabled() -> bool:
    """The single opt-in boolean, read fresh from ``settings.json``. Default False."""
    try:
        from app.services import SettingsManager

        return bool((SettingsManager.load() or {}).get(SETTING_KEY, SETTING_DEFAULT))
    except Exception as exc:
        logger.warning("op=artist_sync settings_unreadable err=%s", exc)
        return SETTING_DEFAULT


# --------------------------------------------------------------------------- refresher


def _default_refresher(collection_id: str, *, budget: Any) -> Mapping[str, Any]:
    """The route's own catalogue body, forced past the TTL, on the run's shared budget."""
    return _main_module()._artist_catalogue_view(
        collection_id, refresh=True, allow_fetch=True, budget=budget
    )


def _accepts_budget(refresher: Refresher) -> bool:
    try:
        params = inspect.signature(refresher).parameters
    except (TypeError, ValueError):
        return True  # not introspectable (a C callable, a mock) — let the call decide
    if BUDGET_KWARG in params:
        return True
    return any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())


def _resolve_refresher(refresher: Refresher | None) -> Refresher:
    """The caller's refresher, or the route body — but only if it takes the budget.

    A refresher that makes its own budget would give every artist a fresh cap and quietly
    turn the run's one hard limit into N of them. Refusing is the honest answer.
    """
    resolved = refresher or _default_refresher
    if resolved is _default_refresher:
        try:
            target = _main_module()._artist_catalogue_view
        except (ImportError, AttributeError) as exc:
            raise SyncError(f"no catalogue refresher available: {exc}") from exc
        if not _accepts_budget(target):
            raise SyncError(
                "app.main._artist_catalogue_view does not accept a `budget=` keyword, so "
                "one shared call budget cannot be enforced across the run; add "
                "`budget: sc_api.CallBudget | None = None` to it (falling back to its own "
                "CallBudget when None) before enabling background sync"
            )
    elif not _accepts_budget(resolved):
        raise SyncError("refresher must accept a `budget=` keyword")
    return resolved


# --------------------------------------------------------------------------- the run


@dataclass
class ArtistSyncResult:
    """What one artist's pass did. ``missing`` is ``None`` when it was not measured."""

    collection_id: str
    name: str
    mode: str
    status: str
    missing: int | None = None
    auto_queue_candidates: int | None = None
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "collection_id": self.collection_id,
            "name": self.name,
            "mode": self.mode,
            "status": self.status,
            "missing": self.missing,
            "auto_queue_candidates": self.auto_queue_candidates,
            "detail": self.detail,
        }


@dataclass
class SyncRun:
    """One background pass, start to stop. Every number here was actually counted."""

    started: str = ""
    finished: str = ""
    artists_synced: int = 0
    artists_skipped: int = 0
    reason_stopped: str = STOP_COMPLETED
    calls_used: int = 0
    call_budget: int = SYNC_CALL_BUDGET
    #: Always 0. The background pass refreshes; it never queues and never downloads.
    downloads_queued: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)
    results: list[ArtistSyncResult] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "started": self.started,
            "finished": self.finished,
            "artists_synced": self.artists_synced,
            "artists_skipped": self.artists_skipped,
            "reason_stopped": self.reason_stopped,
            "calls_used": self.calls_used,
            "call_budget": self.call_budget,
            "downloads_queued": self.downloads_queued,
            "errors": list(self.errors),
            "results": [r.as_dict() for r in self.results],
        }


def _view_counts(view: Mapping[str, Any]) -> tuple[int | None, int | None]:
    """``(missing, auto_queue_candidates)`` — ``(None, None)`` when nothing was diffed.

    A payload without bucket keys carries no ownership verdict, so no count is printed
    for it. Guessing zero here would be inventing a measurement.
    """
    present = [key for key in catalogue_mod.BUCKET_KEYS if isinstance(view.get(key), list)]
    if not present:
        return None, None
    missing = 0
    queueable = 0
    for key in present:
        for track in view[key]:
            if not isinstance(track, Mapping):
                continue
            if track.get("in_library") is False:
                missing += 1
            if track.get("auto_queue_allowed") is True:
                queueable += 1
    return missing, queueable


def _pending(favourites: Iterable[Mapping[str, Any]], now: datetime) -> list[dict[str, Any]]:
    """Eligible favourites, oldest-last-synced first. ``off`` never appears."""
    rows: list[dict[str, Any]] = []
    for fav in favourites:
        collection_id = str(fav.get("id") or "")
        if not collection_id:
            continue
        mode = schema.get_sync_mode(collection_id)
        if mode == schema.SYNC_OFF:
            continue
        state = schema.get_sync_state(collection_id) or {}
        last = str(state.get("last_sync_at") or "")
        rows.append(
            {
                "collection_id": collection_id,
                "name": str(fav.get("canonical_name") or ""),
                "mode": mode,
                "last_sync_at": last,
                "age_s": _age_seconds(last, now),
            }
        )
    # "" (never synced) sorts before every ISO timestamp, which is exactly the order we
    # want: an artist nobody has ever fetched goes first.
    rows.sort(key=lambda r: r["last_sync_at"])
    return rows


def _age_seconds(last_sync_at: str, now: datetime) -> float | None:
    if not last_sync_at:
        return None
    try:
        return (now - datetime.fromisoformat(last_sync_at)).total_seconds()
    except (TypeError, ValueError):
        return None


def _remember_run(run: SyncRun) -> None:
    try:
        schema.set_meta(META_LAST_RUN, json.dumps(run.as_dict()))
    except Exception as exc:
        logger.warning("op=artist_sync run_record_unsaved err=%s", exc)


def last_run() -> dict[str, Any] | None:
    """The previous run record, or None when no pass has ever finished."""
    raw = schema.get_meta(META_LAST_RUN)
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        logger.warning("op=artist_sync run_record_unreadable err=%s", exc)
        return None
    return parsed if isinstance(parsed, dict) else None


def run_sync(
    *,
    refresher: Refresher | None = None,
    budget: Any = None,
    idle: Callable[[], tuple[bool, str]] | None = None,
    force: bool = False,
    max_artists: int = MAX_ARTISTS_PER_RUN,
    min_interval_s: float = MIN_RESYNC_INTERVAL_S,
    remember: bool = True,
) -> SyncRun:
    """One background pass over the favourites whose mode is ``auto`` or ``review``.

    Refreshes each artist's catalogue through ``refresher`` — the manual Update button's
    own body — oldest-last-synced first, under **one** :class:`CallBudget` for the whole
    run. Idle is re-checked before every artist and the run stops cleanly the moment the
    user starts doing something. Nothing is queued and nothing is downloaded, ever.

    ``force=True`` runs with the opt-in setting off (the manual "sync all now" path); it
    does **not** bypass the idle check — a run under load is the thing this exists to
    avoid.

    Nothing here schedules itself: a caller (route or timer) decides when to ask. That
    keeps "user-initiated or idle-only" a property of one place instead of a loop hidden
    in the store.

    Returns the run record. A run that actually walked artists is stored under
    :data:`META_LAST_RUN` unless ``remember=False``; a run that never started — disabled,
    busy, or no usable refresher — is not, so it cannot overwrite the last real result.
    """
    started_at = datetime.now(timezone.utc)
    run = SyncRun(started=started_at.isoformat(timespec="seconds"))
    check_idle = idle or is_idle

    if not force and not background_sync_enabled():
        run.reason_stopped = STOP_DISABLED
        return _finish(run, remember=False)

    try:
        refresh = _resolve_refresher(refresher)
    except SyncError as exc:
        run.reason_stopped = STOP_NO_REFRESHER
        run.errors.append({"collection_id": "", "status": STOP_NO_REFRESHER, "detail": str(exc)})
        logger.warning("op=artist_sync stop=%s err=%s", STOP_NO_REFRESHER, exc)
        return _finish(run, remember=False)

    quiet, reason = check_idle()
    if not quiet:
        run.reason_stopped = f"{STOP_BUSY}:{reason}"
        logger.info("op=artist_sync stop=%s", run.reason_stopped)
        return _finish(run, remember=False)

    if budget is None:
        from app import soundcloud_api as sc_api

        budget = sc_api.CallBudget(limit=SYNC_CALL_BUDGET, label="artist-background-sync")
    run.call_budget = int(getattr(budget, "limit", SYNC_CALL_BUDGET))

    pending = _pending(schema.list_favourites(), started_at)
    for index, row in enumerate(pending):
        collection_id = row["collection_id"]
        if index >= max_artists:
            run.artists_skipped += len(pending) - index
            run.reason_stopped = STOP_ARTIST_CAP
            break
        if getattr(budget, "exhausted", False):
            run.artists_skipped += len(pending) - index
            run.reason_stopped = STOP_CALL_BUDGET
            break
        quiet, reason = check_idle()
        if not quiet:
            run.artists_skipped += len(pending) - index
            run.reason_stopped = f"{STOP_BUSY}:{reason}"
            break
        age = row["age_s"]
        if age is not None and age < min_interval_s:
            run.artists_skipped += 1
            run.results.append(
                ArtistSyncResult(
                    collection_id=collection_id,
                    name=row["name"],
                    mode=row["mode"],
                    status="fresh",
                    detail=f"last synced {int(age)}s ago, inside the {int(min_interval_s)}s TTL",
                )
            )
            continue

        stop_run, result = _sync_one(collection_id, row, refresh, budget, run)
        run.results.append(result)
        if stop_run:
            run.reason_stopped = STOP_NOT_CONNECTED
            run.artists_skipped += len(pending) - index - 1
            break

    run.calls_used = int(getattr(budget, "used", 0) or 0)
    logger.info(
        "op=artist_sync finished synced=%d skipped=%d calls=%d cap=%d queued=%d stop=%s",
        run.artists_synced,
        run.artists_skipped,
        run.calls_used,
        run.call_budget,
        run.downloads_queued,
        run.reason_stopped,
    )
    return _finish(run, remember=remember)


def _sync_one(
    collection_id: str,
    row: Mapping[str, Any],
    refresh: Refresher,
    budget: Any,
    run: SyncRun,
) -> tuple[bool, ArtistSyncResult]:
    """Refresh one artist. Returns ``(stop_whole_run, result)``.

    A signed-out session is the only thing that ends the run: it will fail identically
    for every remaining artist, and hammering the refresher to prove that is pointless.
    Everything else is this artist's problem and the next one still gets its turn.
    """
    mode = str(row["mode"])
    name = str(row["name"])
    try:
        view = refresh(collection_id, budget=budget)
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        schema.record_sync(collection_id, error=detail)
        run.errors.append({"collection_id": collection_id, "status": "error", "detail": detail})
        logger.warning("op=artist_sync artist=%s failed err=%s", collection_id, detail)
        return False, ArtistSyncResult(collection_id, name, mode, "error", detail=detail)

    status = str((view or {}).get("status") or "")
    if status != "ok":
        detail = str((view or {}).get("detail") or "")
        schema.record_sync(collection_id, error=detail or status or "unknown")
        run.errors.append({"collection_id": collection_id, "status": status, "detail": detail})
        return (
            status == STOP_NOT_CONNECTED,
            ArtistSyncResult(collection_id, name, mode, status or "unknown", detail=detail),
        )

    missing, queueable = _view_counts(view)
    schema.record_sync(collection_id, error=None)
    run.artists_synced += 1
    return False, ArtistSyncResult(
        collection_id=collection_id,
        name=name,
        mode=mode,
        status="ok",
        missing=missing,
        auto_queue_candidates=queueable,
    )


def _finish(run: SyncRun, *, remember: bool) -> SyncRun:
    run.finished = _now_iso()
    if remember:
        _remember_run(run)
    return run


__all__ = [
    "BUDGET_KWARG",
    "MAX_ARTISTS_PER_RUN",
    "META_LAST_RUN",
    "MIN_RESYNC_INTERVAL_S",
    "SETTING_DEFAULT",
    "SETTING_KEY",
    "STALE_TASK_S",
    "STOP_ARTIST_CAP",
    "STOP_BUSY",
    "STOP_CALL_BUDGET",
    "STOP_COMPLETED",
    "STOP_DISABLED",
    "STOP_IDLE",
    "STOP_NOT_CONNECTED",
    "STOP_NO_REFRESHER",
    "SYNC_CALL_BUDGET",
    "TERMINAL_STATES",
    "UNOBSERVABLE_LOAD",
    "ArtistSyncResult",
    "IdleProbe",
    "Refresher",
    "SyncError",
    "SyncRun",
    "background_sync_enabled",
    "idle_report",
    "is_idle",
    "last_run",
    "register_probe",
    "run_sync",
    "unregister_probe",
]
