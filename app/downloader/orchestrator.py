"""Phase-5 orchestrator — request cache, job registry, post-download pipeline.

Implements ``P5.18`` of
``docs/research/implement/accepted_downloader-unified-multi-source.md``.

This module is the *fetch* half of the two-phase downloader. :mod:`resolver`
and :mod:`search` produce ranked candidates; this module commits the chosen
one to disk and runs the 9-step post-download pipeline.

Design — request cache ownership
--------------------------------
``/resolve`` and ``/search`` return a ``request_id``; a later ``/fetch`` only
carries that ``request_id`` plus a ``candidate_index`` — it has no copy of the
candidate itself. The chosen candidate therefore has to be looked up.

The orchestrator is **not** the entry point for resolve/search (the FastAPI
routes call :func:`resolver.resolve` / :func:`search.search` directly, exactly
as ``route-architect`` designed them). Instead this module owns a small bounded
cache and exposes :func:`remember_resolve` / :func:`remember_search`, which
``resolver`` and ``search`` call at the end of their pipelines to register
their result. This keeps resolve/search free of any orchestrator-fetch import
(no cycle: the orchestrator imports neither module) while still giving
``/fetch`` a single place to resolve a ``request_id`` against.

The cache is an ``OrderedDict`` capped at :data:`_CACHE_MAX_ENTRIES` with
LRU-style eviction and a :data:`_CACHE_TTL_S` time bound — a ``request_id``
that is never fetched ages out instead of leaking memory.

Job registry
------------
In-flight and finished jobs live in a module-level ``dict[str, JobStatus]``
guarded by a :class:`threading.Lock` — the same shape as
``app.soundcloud_downloader.SoundCloudDownloader.tasks``. Each fetch runs on
its own daemon thread; the thread mutates its :class:`JobStatus` in place as it
walks the pipeline so the poll endpoint can report live progress.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

from .. import audio_tags, download_registry
from ..config import MUSIC_DIR
from .aiff import convert_to_aiff
from .genre_sync import map_genre
from .models import (
    Candidate,
    FetchRequest,
    FetchResponse,
    JobStatus,
    ResolveResponse,
    SearchHit,
    SearchResponse,
)
from .providers import SoundCloudProvider, SpotiFlacProvider

logger = logging.getLogger("DOWNLOADER_ORCHESTRATOR")

# ──────────────────────────────────────────────────────────────────────────────
# Request cache — request_id → resolve/search result (bounded + TTL)
# ──────────────────────────────────────────────────────────────────────────────

#: Max distinct resolve/search results held at once. Old entries are evicted
#: LRU-style so a long session cannot grow the cache without bound.
_CACHE_MAX_ENTRIES: int = 128

#: A cached result older than this (seconds) is treated as expired — a
#: ``request_id`` the user resolved but never committed ages out. 30 min is
#: generous for a human picking a candidate from the grid.
_CACHE_TTL_S: float = 1800.0

#: ``request_id`` → ``(monotonic_timestamp, candidate_list)``. The candidate
#: list is the flattened set ``/fetch``'s ``candidate_index`` indexes into:
#: for a resolve that is ``ResolveResponse.candidates``; for a search it is one
#: synthetic :class:`Candidate` per :class:`SearchHit` representative.
_request_cache: OrderedDict[str, tuple[float, list[Candidate]]] = OrderedDict()
_cache_lock = threading.Lock()


def _evict_expired_locked() -> None:
    """Drop timed-out cache entries. Caller must hold :data:`_cache_lock`."""
    now = time.monotonic()
    stale = [rid for rid, (ts, _) in _request_cache.items() if now - ts > _CACHE_TTL_S]
    for rid in stale:
        _request_cache.pop(rid, None)


def _cache_put(request_id: str, candidates: list[Candidate]) -> None:
    """Insert a candidate list under ``request_id``, evicting old entries."""
    with _cache_lock:
        _evict_expired_locked()
        _request_cache[request_id] = (time.monotonic(), candidates)
        _request_cache.move_to_end(request_id)
        while len(_request_cache) > _CACHE_MAX_ENTRIES:
            _request_cache.popitem(last=False)


def _cache_get(request_id: str) -> list[Candidate] | None:
    """Return the candidate list for ``request_id``, or ``None`` if absent/expired."""
    with _cache_lock:
        _evict_expired_locked()
        entry = _request_cache.get(request_id)
        if entry is None:
            return None
        _request_cache.move_to_end(request_id)
        return entry[1]


def remember_resolve(resp: ResolveResponse) -> None:
    """Register a :class:`ResolveResponse` so a later ``/fetch`` can find it.

    Called by :func:`resolver.resolve` at the end of its pipeline. The
    response's ``candidates`` list is cached verbatim — ``/fetch``'s
    ``candidate_index`` indexes straight into it.
    """
    _cache_put(resp.request_id, list(resp.candidates))


def remember_search(resp: SearchResponse) -> None:
    """Register a :class:`SearchResponse` so a later ``/fetch`` can find it.

    Called by :func:`search.search`. A :class:`SearchHit` carries a
    representative :class:`~app.downloader.models.TrackMatch` but no
    :class:`Candidate`; this wraps each representative in a synthetic
    :class:`Candidate` (a search hit already passed clustering, so it is
    treated as a 100%-match for fetch purposes) so the fetch path is uniform
    regardless of whether the user came from resolve or search.
    """
    candidates = [_candidate_from_hit(hit) for hit in resp.hits]
    _cache_put(resp.request_id, candidates)


def _candidate_from_hit(hit: SearchHit) -> Candidate:
    """Wrap a :class:`SearchHit` representative as a fetch-ready :class:`Candidate`."""
    from .models import MatchResult

    return Candidate(
        match=hit.representative,
        match_result=MatchResult(
            is_match=True,
            confidence=1.0,
            rule_fired="search_cluster",
        ),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Job registry — job_id → JobStatus (threading.Lock-guarded)
# ──────────────────────────────────────────────────────────────────────────────

_jobs: dict[str, JobStatus] = {}
_jobs_lock = threading.Lock()


def _put_job(job: JobStatus) -> None:
    """Insert / replace a :class:`JobStatus` in the registry."""
    with _jobs_lock:
        _jobs[job.job_id] = job


def get_job(job_id: str) -> JobStatus | None:
    """Return the current :class:`JobStatus` for ``job_id``, or ``None``.

    Backs ``GET /api/downloads/unified/jobs/{job_id}``.
    """
    with _jobs_lock:
        return _jobs.get(job_id)


def _update_job(
    job_id: str,
    *,
    state: str | None = None,
    progress_pct: int | None = None,
    final_path: str | None = None,
    error: str | None = None,
) -> None:
    """Mutate a job's mutable fields under the registry lock.

    :class:`JobStatus` is a Pydantic model; a partial update is done by
    ``model_copy(update=...)`` so validation (e.g. the ``progress_pct`` 0-100
    bound, the ``state`` literal) still runs on every transition.
    """
    with _jobs_lock:
        current = _jobs.get(job_id)
        if current is None:
            return
        patch: dict[str, object] = {}
        if state is not None:
            patch["state"] = state
        if progress_pct is not None:
            patch["progress_pct"] = max(0, min(100, progress_pct))
        if final_path is not None:
            patch["final_path"] = final_path
        if error is not None:
            patch["error"] = error
        _jobs[job_id] = current.model_copy(update=patch)


# ──────────────────────────────────────────────────────────────────────────────
# Settings — the ``unified_downloader`` block
# ──────────────────────────────────────────────────────────────────────────────


def _downloader_enabled() -> bool:
    """Return the ``unified_downloader.enabled`` kill-switch state.

    Defaults to ``True`` when the setting is absent — the per-provider flags
    and the SpotiFLAC "backdoor" toggle are the real gating; this top-level
    switch only exists so the whole feature can be darkened. A settings-load
    failure also degrades to enabled so a missing settings file in a stripped
    test env does not make every fetch 503.
    """
    try:
        from app.services import SettingsManager

        block = SettingsManager.load().get("unified_downloader")
    except Exception as exc:
        logger.debug("[orchestrator] settings load failed, assuming enabled: %s", exc)
        return True
    if not isinstance(block, dict):
        return True
    return bool(block.get("enabled", True))


# ──────────────────────────────────────────────────────────────────────────────
# Provider lookup — platform → live SourceProvider for the fetch
# ──────────────────────────────────────────────────────────────────────────────


def _provider_for_platform(platform: str) -> object:
    """Construct the :class:`~app.downloader.SourceProvider` that can fetch ``platform``.

    SoundCloud has its own provider; the five SpotiFLAC-served paid services
    each get a :class:`SpotiFlacProvider` bound to that platform.

    Raises:
        RuntimeError: no provider can serve ``platform`` (e.g. a bare Spotify
            or YouTube claim — no fetch path exists for those yet).
    """
    if platform == "soundcloud":
        return SoundCloudProvider.from_keyring()
    try:
        return SpotiFlacProvider(platform)  # type: ignore[arg-type]
    except ValueError as exc:
        raise RuntimeError(f"no downloader provider can fetch platform {platform!r}") from exc


# ──────────────────────────────────────────────────────────────────────────────
# Public entry point — enqueue a fetch
# ──────────────────────────────────────────────────────────────────────────────


def enqueue_fetch(req: FetchRequest) -> FetchResponse:
    """Commit a chosen candidate to download — spawn a background fetch job.

    Looks the candidate up by ``req.request_id`` + ``req.candidate_index``
    against the request cache, registers a fresh :class:`JobStatus` in the
    ``queued`` state, spawns a daemon thread running :func:`execute_fetch`, and
    returns the job handle immediately — the HTTP request does not block on the
    download.

    Raises:
        KeyError: ``request_id`` is unknown / expired, or ``candidate_index``
            is out of range for that request's candidate list.
        RuntimeError: the downloader is disabled by the
            ``unified_downloader.enabled`` setting.
    """
    if not _downloader_enabled():
        raise RuntimeError("unified downloader is disabled in settings")

    candidates = _cache_get(req.request_id)
    if candidates is None:
        raise KeyError(f"unknown or expired request_id: {req.request_id!r}")
    if not 0 <= req.candidate_index < len(candidates):
        raise KeyError(
            f"candidate_index {req.candidate_index} out of range "
            f"(request has {len(candidates)} candidate(s))"
        )

    picked = candidates[req.candidate_index]
    job_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc).isoformat()
    _put_job(JobStatus(job_id=job_id, state="queued", progress_pct=0))

    thread = threading.Thread(
        target=execute_fetch,
        args=(job_id, picked, list(candidates)),
        daemon=True,
        name=f"unified-fetch-{job_id[:8]}",
    )
    thread.start()
    logger.info(
        "[orchestrator] enqueued fetch job=%s platform=%s title=%r",
        job_id,
        picked.match.platform,
        picked.match.title,
    )
    return FetchResponse(job_id=job_id, started_at=started_at)


# ──────────────────────────────────────────────────────────────────────────────
# The 9-step post-download pipeline
# ──────────────────────────────────────────────────────────────────────────────


def execute_fetch(job_id: str, picked: Candidate, all_candidates: list[Candidate]) -> None:
    """Run the 9-step post-download pipeline for one job (runs on a daemon thread).

    Walks: ``downloading → converting → tagging → analyzing → done`` and
    mutates the job's :class:`JobStatus` (state + ``progress_pct``) at every
    boundary. Any unhandled failure flips the job to ``failed`` with the error
    string attached — the thread never lets an exception escape.

    The nine steps (see the plan's Recommendation block):

    1. fetch bytes via the candidate's provider → ``MUSIC_DIR/.staging/``
    2. SHA-256 the bytes → dedup check via :mod:`download_registry`
    3. AIFF conversion (lossless only) via :func:`aiff.convert_to_aiff`
    4. genre-normalise via :func:`genre_sync.map_genre`
    5. provenance string via :func:`audio_tags.serialise_provenance`
    6. tag write via :func:`audio_tags.write_tags` (provenance/isrc/genre/year/art)
    7. move to ``MUSIC_DIR/<artist>/<title>.<ext>``
    8. registry update via :func:`download_registry.record_unified_download`
    9. background BPM/key analysis (best-effort)
    """
    match = picked.match
    staging = MUSIC_DIR / ".staging" / job_id
    raw_path: Path | None = None
    try:
        staging.mkdir(parents=True, exist_ok=True)

        # ── Step 1 — fetch bytes ───────────────────────────────────────────
        _update_job(job_id, state="downloading", progress_pct=5)
        provider = _provider_for_platform(match.platform)
        raw_path = _run_provider_fetch(provider, picked, staging)
        _update_job(job_id, progress_pct=35)

        # ── Step 2 — SHA-256 + dedup ───────────────────────────────────────
        sha = download_registry.compute_sha256(raw_path)
        if sha is None:
            raise RuntimeError(f"could not hash downloaded file {raw_path}")
        existing = download_registry.find_by_hash(sha)
        if existing and existing.get("file_path"):
            existing_path = str(existing["file_path"])
            logger.info("[orchestrator] job=%s dedup hit -> %s", job_id, existing_path)
            raw_path.unlink(missing_ok=True)
            _update_job(job_id, state="done", progress_pct=100, final_path=existing_path)
            _cleanup_staging(staging)
            return
        _update_job(job_id, progress_pct=45)

        # ── Step 3 — AIFF conversion (lossless only) ───────────────────────
        _update_job(job_id, state="converting", progress_pct=55)
        converted = convert_to_aiff(raw_path)
        audio_path = converted if converted is not None else raw_path

        # ── Step 4 — genre normalisation ───────────────────────────────────
        canonical_genre = map_genre(match.genre or "") or ""

        # ── Step 5 — provenance string ─────────────────────────────────────
        provenance = audio_tags.serialise_provenance(
            [c.match for c in all_candidates],
            match,
        )

        # ── Step 6 — tag write ─────────────────────────────────────────────
        _update_job(job_id, state="tagging", progress_pct=70)
        artwork = _fetch_artwork(match.cover_url)
        audio_tags.write_tags(
            audio_path,
            {
                "Title": match.title,
                "Artist": match.artist,
                "Album": match.album or "",
                "Year": str(match.year) if match.year else "",
                "Genre": canonical_genre,
                "ISRC": match.isrc or "",
                "Comment": provenance,
            },
            artwork=artwork,
        )

        # ── Step 7 — move to final location ────────────────────────────────
        final_path = _move_to_library(audio_path, match.artist, match.title)
        _update_job(job_id, progress_pct=82)

        # ── Step 8 — registry update ───────────────────────────────────────
        size = final_path.stat().st_size if final_path.exists() else None
        download_registry.record_unified_download(
            sha256_hash=sha,
            title=match.title,
            artist=match.artist,
            file_path=final_path,
            isrc=match.isrc,
            source=match.platform,
            provenance_urls=provenance,
            picked_quality_tier=int(match.quality_tier),
            file_format=final_path.suffix.lstrip(".") or None,
            file_size_bytes=size,
            duration_ms=int(match.duration_s * 1000),
            permalink_url=match.url,
        )

        # ── Step 9 — background BPM/key analysis ───────────────────────────
        _update_job(job_id, state="analyzing", progress_pct=90)
        _schedule_analysis(final_path)

        _update_job(job_id, state="done", progress_pct=100, final_path=str(final_path))
        logger.info("[orchestrator] job=%s done -> %s", job_id, final_path)
    except Exception as exc:
        logger.error("[orchestrator] job=%s failed: %s", job_id, exc, exc_info=True)
        _update_job(job_id, state="failed", error=str(exc))
        if raw_path is not None:
            raw_path.unlink(missing_ok=True)
    finally:
        _cleanup_staging(staging)


# ──────────────────────────────────────────────────────────────────────────────
# Pipeline helpers
# ──────────────────────────────────────────────────────────────────────────────


def _run_provider_fetch(provider: object, picked: Candidate, staging: Path) -> Path:
    """Run a provider's async ``fetch`` coroutine to completion on this thread.

    :func:`execute_fetch` runs on a plain daemon thread (no event loop), but
    :meth:`~app.downloader.SourceProvider.fetch` is a coroutine. A private
    ``asyncio`` loop is created, used for exactly this one call, and closed —
    the standard "drive one coroutine from sync code" pattern.
    """
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(
            provider.fetch(picked.match, staging)  # type: ignore[attr-defined]
        )
    finally:
        loop.close()


def _fetch_artwork(cover_url: str | None) -> bytes | None:
    """Best-effort download of cover art for the tag write.

    Returns the raw image bytes, or ``None`` when there is no cover URL or the
    fetch failed — artwork is cosmetic, never a reason to fail a download.
    """
    if not cover_url:
        return None
    try:
        import urllib.request

        req = urllib.request.Request(cover_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
        return data if data else None
    except Exception as exc:
        logger.debug("[orchestrator] artwork fetch failed for %s: %s", cover_url, exc)
        return None


def _move_to_library(audio_path: Path, artist: str, title: str) -> Path:
    """Move a finished file into ``MUSIC_DIR/<artist>/<title>.<ext>`` (D7 layout).

    Artist + title are sanitised into safe filesystem components via the
    existing SC sanitiser (handles Windows-reserved device names + illegal
    chars). On a name collision a numeric suffix is appended so an existing
    file is never silently overwritten.
    """
    from app.soundcloud_downloader import _sanitize_name

    safe_artist = _sanitize_name(artist or "Unknown")
    safe_title = _sanitize_name(title or audio_path.stem)
    dest_dir = MUSIC_DIR / safe_artist
    dest_dir.mkdir(parents=True, exist_ok=True)

    ext = audio_path.suffix or ".aiff"
    final_path = dest_dir / f"{safe_title}{ext}"
    counter = 1
    while final_path.exists():
        final_path = dest_dir / f"{safe_title} ({counter}){ext}"
        counter += 1

    audio_path.replace(final_path)
    return final_path


def _schedule_analysis(final_path: Path) -> None:
    """Kick off background BPM/key analysis + library auto-import for ``final_path``.

    Reuses the existing offline analysis stack: ``analysis_engine.run_full_analysis``
    for BPM/key and ``services.ImportManager.process_import`` for the library
    write. The auto-import path mutates the Rekordbox ``master.db`` singleton,
    so it is serialised through :func:`app.database.db_lock` — the one place in
    this pipeline that touches ``master.db`` (the registry write in step 8 uses
    its own separate DB and must NOT take that lock).

    Runs on its own daemon thread; any failure is logged and swallowed — the
    download itself already succeeded, analysis is a follow-up enrichment.
    """

    def _analyze() -> None:
        try:
            from ..analysis_engine import run_full_analysis
            from ..database import db_lock
            from ..services import ImportManager

            result = run_full_analysis(str(final_path))
            with db_lock():
                ImportManager.process_import(final_path, analysis_result=result)
            logger.info("[orchestrator] analysis + import done for %s", final_path.name)
        except Exception as exc:
            logger.warning(
                "[orchestrator] background analysis failed for %s: %s",
                final_path.name,
                exc,
            )

    threading.Thread(
        target=_analyze,
        daemon=True,
        name=f"unified-analyze-{final_path.stem[:16]}",
    ).start()


def _cleanup_staging(staging: Path) -> None:
    """Remove a job's per-job staging directory, ignoring any error."""
    try:
        if staging.exists():
            for child in staging.iterdir():
                child.unlink(missing_ok=True)
            staging.rmdir()
    except OSError as exc:
        logger.debug("[orchestrator] staging cleanup failed for %s: %s", staging, exc)


__all__ = [
    "enqueue_fetch",
    "execute_fetch",
    "get_job",
    "remember_resolve",
    "remember_search",
]
