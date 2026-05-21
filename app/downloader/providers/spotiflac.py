"""SpotiFLAC-backed multi-service provider (crash-isolated).

Wraps the third-party ``SpotiFLAC`` reverse-engineering library. SpotiFLAC
hits a rotating set of community mirror APIs and does opaque crypto / manifest
parsing; like the ``rbox`` crate behind :mod:`app.anlz_safe`, it is *not*
trusted to keep a long-lived process alive. Every call therefore runs inside a
``ProcessPoolExecutor(max_workers=1)`` worker that the parent can kill and
respawn.

This module copies the full :mod:`app.anlz_safe` crash-recovery shape:

* a single restart-able module-level executor singleton,
* a per-run panic budget (:data:`_MAX_PANICS_PER_RUN`),
* ``future.result(timeout=...)`` with a hard per-call timeout,
* ``BrokenExecutor`` catch + worker restart + single bounded retry.

All ``SpotiFLAC`` imports are **lazy, inside the worker functions** — the
parent process never pulls SpotiFLAC (or its ``cryptography`` / ``mutagen``
dependency graph) into its address space, keeping the crash blast radius
inside the worker.

Real-API note (vs. the plan's P1.5 sketch)
------------------------------------------
The plan assumed each ``SpotiFLAC`` service provider exposes a metadata-only
``probe(url)`` and a ``download(url, dest_dir)``. The installed
``SpotiFLAC==0.5.0`` exposes **neither**: a provider's only public method is
``download_track(metadata: TrackMetadata, output_dir, *, quality, ...)``,
which both resolves Spotify→service *and* pulls audio bytes in one opaque
call. There is no way to "probe quality without downloading". Phase-1
resolution therefore returns *claimed* quality synthesised from each service's
publicly-known format ceiling (see :data:`_SERVICE_CEILING`); the true quality
is only known after :meth:`SpotiFlacProvider.fetch` runs ``quality_engine``
post-download (downstream, Phase 3). This is a deliberate, documented
deviation — see the module's research doc.

See ``docs/research/implement/accepted_downloader-unified-multi-source.md``
§ "P1.5".
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable
from concurrent.futures import (
    BrokenExecutor,
    Future,
    ProcessPoolExecutor,
)
from concurrent.futures import (
    TimeoutError as FuturesTimeout,
)
from pathlib import Path
from typing import Any

from anyio import to_thread

from .. import SourceProvider
from ..models import AudioFormat, Platform, QualityTier, TrackMatch

logger = logging.getLogger(__name__)

# ``SourceProvider`` is referenced as the base class of ``SpotiFlacProvider``
# below; the import above must not be pruned as unused.

# ──────────────────────────────────────────────────────────────────────────────
# Tunables — mirror app/anlz_safe.py
# ──────────────────────────────────────────────────────────────────────────────

#: Hard ceiling on worker restarts caused by crashes within a single process
#: lifetime. After this the provider stops retrying and fails fast — protects
#: against a degenerate state where every SpotiFLAC call aborts the worker.
_MAX_PANICS_PER_RUN = 16

#: How long a single worker call may run before the worker is killed. SpotiFLAC
#: fans out across mirror APIs with its own ~8 s per-API timeouts; a metadata
#: resolve finishes well under 30 s. ``coding-rules.md`` requires an explicit
#: timeout on every subprocess-bound call.
_RESOLVE_TIMEOUT_S = 30.0

#: Downloads pull real audio bytes (lossless FLAC can be 30-80 MB) — a far
#: more generous ceiling than the metadata probe.
_FETCH_TIMEOUT_S = 300.0

#: Platforms SpotiFLAC can serve, in the downloader's :data:`Platform`
#: vocabulary → SpotiFLAC's own ``PROVIDER_REGISTRY`` service key.
_PLATFORM_TO_SERVICE: dict[Platform, str] = {
    "tidal": "tidal",
    "qobuz": "qobuz",
    "amazon": "amazon",
    "apple_music": "apple",
    "deezer": "deezer",
}

#: Odesli (``LinkResolver.resolve_all``) keys its result dict with these
#: platform names — map them back to the downloader's :data:`Platform` literals.
_ODESLI_KEY_TO_PLATFORM: dict[str, Platform] = {
    "tidal": "tidal",
    "qobuz": "qobuz",
    "amazonMusic": "amazon",
    "appleMusic": "apple_music",
    "deezer": "deezer",
    "soundcloud": "soundcloud",
    "spotify": "spotify",
    "youtube": "youtube",
}

#: Publicly-known *best-case* delivery ceiling per service. Phase-1 cannot
#: probe the real per-track quality (see the module docstring) — these claims
#: are the optimistic upper bound; ``quality_engine.probe()`` corrects them
#: post-download. ``(format, bit_depth, sample_rate_hz, bitrate_kbps, tier)``.
_SERVICE_CEILING: dict[
    Platform, tuple[AudioFormat, int | None, int | None, int | None, QualityTier]
] = {
    "qobuz": ("flac", 24, 96000, None, QualityTier.HIRES_LOSSLESS),
    "tidal": ("flac", 24, 96000, None, QualityTier.HIRES_LOSSLESS),
    "amazon": ("flac", 24, 96000, None, QualityTier.HIRES_LOSSLESS),
    "apple_music": ("alac", 24, 96000, None, QualityTier.HIRES_LOSSLESS),
    "deezer": ("flac", 16, 44100, None, QualityTier.CD_LOSSLESS),
}


# ──────────────────────────────────────────────────────────────────────────────
# Restart-able worker pool (module-level singleton — the anlz_safe shape)
# ──────────────────────────────────────────────────────────────────────────────

_EXECUTOR: ProcessPoolExecutor | None = None
_PANIC_COUNT: int = 0


def _get_executor() -> ProcessPoolExecutor:
    """Return the live worker pool, spawning it on first use."""
    global _EXECUTOR
    if _EXECUTOR is None:
        _EXECUTOR = ProcessPoolExecutor(max_workers=1)
        logger.debug("[spotiflac] spawned worker process")
    return _EXECUTOR


def _restart_executor() -> None:
    """Tear down a (probably broken) worker pool and spawn a fresh one.

    Increments the panic counter. Idempotent w.r.t. a missing executor.
    """
    global _EXECUTOR, _PANIC_COUNT
    if _EXECUTOR is not None:
        try:
            _EXECUTOR.shutdown(wait=False, cancel_futures=True)
        except Exception as exc:
            logger.debug("[spotiflac] executor shutdown error: %s", exc)
        _EXECUTOR = None
    _PANIC_COUNT += 1
    _EXECUTOR = ProcessPoolExecutor(max_workers=1)
    logger.warning("[spotiflac] PPE restarted (panic %d/%d)", _PANIC_COUNT, _MAX_PANICS_PER_RUN)


def _reset_state_for_tests() -> None:
    """Tear down the worker pool and zero the panic counter.

    Test-only helper — production code never resets the budget mid-run.
    """
    global _EXECUTOR, _PANIC_COUNT
    if _EXECUTOR is not None:
        with contextlib.suppress(Exception):
            _EXECUTOR.shutdown(wait=False, cancel_futures=True)
        _EXECUTOR = None
    _PANIC_COUNT = 0


def _await_future(future: Future[Any], timeout_s: float) -> Any:
    """Block on ``future`` with a hard timeout.

    A module-level helper (not an inline closure) so it does not capture a
    loop variable — keeps :func:`_submit_with_recovery` free of the
    capture-late-binding footgun.
    """
    return future.result(timeout=timeout_s)


async def _submit_with_recovery(func: Callable[..., Any], *args: Any, timeout_s: float) -> Any:
    """Submit ``func`` to the worker pool with crash recovery.

    On a ``BrokenExecutor`` (worker aborted — a SpotiFLAC crash) or a
    ``FuturesTimeout`` (worker hung) the pool is restarted and the call is
    retried exactly once. A second failure, or exhausting the panic budget,
    raises ``RuntimeError``.

    The blocking ``future.result(...)`` is offloaded to a thread via
    :func:`anyio.to_thread.run_sync` so the calling coroutine never blocks
    the event loop.

    Raises:
        RuntimeError: panic budget exhausted, or the retry also failed.
        Exception: any non-recoverable error raised inside the worker
            (``ValueError`` for a bad URL, SpotiFLAC errors, …) — propagated
            unchanged on the first attempt.
    """
    last_exc: BaseException | None = None
    for attempt in range(2):
        if _PANIC_COUNT >= _MAX_PANICS_PER_RUN:
            raise RuntimeError(
                f"SpotiFLAC PPE exceeded panic budget ({_MAX_PANICS_PER_RUN})"
            ) from last_exc

        executor = _get_executor()
        future = executor.submit(func, *args)
        try:
            return await to_thread.run_sync(_await_future, future, timeout_s)
        except (BrokenExecutor, FuturesTimeout) as exc:
            last_exc = exc
            logger.warning(
                "[spotiflac] worker call %s failed (%s) — attempt %d/2",
                getattr(func, "__name__", repr(func)),
                type(exc).__name__,
                attempt + 1,
            )
            _restart_executor()
            if attempt == 1:
                raise RuntimeError(f"SpotiFLAC worker call failed after restart: {exc}") from exc

    # Unreachable — the loop either returns or raises.
    raise RuntimeError("SpotiFLAC worker call exhausted retries")  # pragma: no cover


# ──────────────────────────────────────────────────────────────────────────────
# Worker functions — top-level (picklable), SpotiFLAC imported lazily inside
# ──────────────────────────────────────────────────────────────────────────────
#
# These run in the ProcessPoolExecutor subprocess. They MUST stay importable
# without SpotiFLAC present (the import happens inside the body), so the parent
# never loads SpotiFLAC just to reference them — exactly the anlz_safe rule.
# ──────────────────────────────────────────────────────────────────────────────


def _worker_resolve_spotify_url(url: str) -> dict[str, Any]:
    """Worker: resolve a Spotify track URL to metadata + cross-platform links.

    Uses ``SpotifyMetadataClient.get_track`` for the canonical metadata and the
    Odesli-backed ``LinkResolver.resolve_all`` for sibling URLs on the paid
    services. Returns a plain pickle-safe dict; the parent maps it to
    :class:`TrackMatch` claims.

    Raises:
        ValueError: ``url`` is not a Spotify *track* URL.
    """
    from SpotiFLAC.core.http import HttpClient
    from SpotiFLAC.core.link_resolver import LinkResolver
    from SpotiFLAC.providers.spotify_metadata import (
        SpotifyMetadataClient,
        parse_spotify_url,
    )

    parsed = parse_spotify_url(url)
    if not parsed or parsed.get("type") != "track":
        raise ValueError(f"not a Spotify track URL: {url!r}")

    track = SpotifyMetadataClient().get_track(parsed["id"])

    cross_urls: dict[str, str] = {}
    try:
        resolved = LinkResolver(HttpClient("link_resolver")).resolve_all(parsed["id"])
        cross_urls = {k: v for k, v in (resolved or {}).items() if v}
    except Exception as exc:
        logging.getLogger("SpotiFLAC").debug("link resolve failed: %s", exc)

    return {
        "spotify_id": parsed["id"],
        "spotify_url": track.external_url or url,
        "title": track.title,
        "artist": track.artists,
        "album": track.album,
        "duration_s": track.duration_seconds,
        "isrc": track.isrc or None,
        "year": int(track.year) if track.year.isdigit() else None,
        "cover_url": track.cover_url or None,
        "cross_urls": cross_urls,
    }


def _worker_fetch(platform: str, spotify_url: str, isrc: str | None, dest_dir: str) -> str:
    """Worker: download a track from one SpotiFLAC service.

    SpotiFLAC's provider ``download_track`` is Spotify-pivoted — it takes a
    ``TrackMetadata`` (built from the Spotify URL) and internally resolves the
    chosen service. We pass the Spotify URL through ``SpotifyMetadataClient``
    to build that metadata, then call the single-service provider directly.

    Returns the final on-disk path.

    Raises:
        ValueError: ``platform`` is not a SpotiFLAC-served service.
        RuntimeError: SpotiFLAC reported a failed download.
    """
    from SpotiFLAC.providers import PROVIDER_REGISTRY
    from SpotiFLAC.providers.spotify_metadata import (
        SpotifyMetadataClient,
        parse_spotify_url,
    )

    service = {
        "tidal": "tidal",
        "qobuz": "qobuz",
        "amazon": "amazon",
        "apple_music": "apple",
        "deezer": "deezer",
    }.get(platform)
    if service is None:
        raise ValueError(f"platform {platform!r} is not served by SpotiFLAC")

    provider_cls = PROVIDER_REGISTRY.get(service)
    if provider_cls is None:
        raise ValueError(f"SpotiFLAC has no provider for service {service!r}")

    parsed = parse_spotify_url(spotify_url)
    if not parsed or parsed.get("type") != "track":
        raise ValueError(f"not a Spotify track URL: {spotify_url!r}")

    metadata = SpotifyMetadataClient().get_track(parsed["id"])
    if isrc and not metadata.isrc:
        metadata = metadata.model_copy(update={"isrc": isrc})

    result = provider_cls().download_track(metadata, dest_dir)
    if not result.success or not result.file_path:
        raise RuntimeError(
            f"SpotiFLAC {service} download failed: {result.error or 'unknown error'}"
        )
    return result.file_path


# ──────────────────────────────────────────────────────────────────────────────
# Provider
# ──────────────────────────────────────────────────────────────────────────────


class SpotiFlacProvider(SourceProvider):
    """:class:`~app.downloader.SourceProvider` over the SpotiFLAC library.

    One instance covers all five SpotiFLAC-served paid services. It is
    constructed with a single :data:`Platform` so the orchestrator can hold one
    provider per platform and rank them uniformly — the ``platform`` property
    reports that target; ``resolve_url`` still surfaces *every* sibling service
    URL Odesli finds, so a Tidal-targeted instance can also yield the Qobuz
    claim for the same track.

    Note: SpotiFLAC has no free-form search — :meth:`search` always returns an
    empty list (it can only resolve a known Spotify URL).
    """

    def __init__(self, platform: Platform = "tidal") -> None:
        """Bind the provider to one served platform.

        Raises:
            ValueError: ``platform`` is not a SpotiFLAC-served service.
        """
        if platform not in _PLATFORM_TO_SERVICE:
            raise ValueError(
                f"SpotiFlacProvider cannot serve platform {platform!r}; "
                f"served: {sorted(_PLATFORM_TO_SERVICE)}"
            )
        self._platform: Platform = platform

    @property
    def platform(self) -> Platform:
        """The SpotiFLAC service this instance targets."""
        return self._platform

    async def resolve_url(self, url: str) -> list[TrackMatch]:
        """Resolve a Spotify track URL to per-service :class:`TrackMatch` claims.

        Returns one claim per SpotiFLAC-served service that Odesli found a
        sibling URL for (Tidal / Qobuz / Amazon / Apple Music / Deezer). Each
        claim's quality is the service's *optimistic* ceiling (see the module
        docstring) — true quality is verified post-download.

        Returns an empty list when ``url`` is not a Spotify track URL or the
        resolve crashed past the panic budget; never raises for those cases —
        a dead source must not abort a multi-provider resolve.
        """
        try:
            meta = await _submit_with_recovery(
                _worker_resolve_spotify_url, url, timeout_s=_RESOLVE_TIMEOUT_S
            )
        except (ValueError, RuntimeError) as exc:
            logger.info("[spotiflac] resolve_url(%s) yielded nothing: %s", url, exc)
            return []

        cross_urls: dict[str, str] = meta.get("cross_urls", {})
        matches: list[TrackMatch] = []
        for odesli_key, svc_url in cross_urls.items():
            platform = _ODESLI_KEY_TO_PLATFORM.get(odesli_key)
            if platform is None or platform not in _SERVICE_CEILING:
                continue  # not a SpotiFLAC-served paid service
            matches.append(self._build_claim(platform, svc_url, meta))

        logger.debug("[spotiflac] resolve_url(%s) -> %d service claim(s)", url, len(matches))
        return matches

    async def search(self, query: str, limit: int = 5) -> list[TrackMatch]:
        """Free-form search — unsupported by SpotiFLAC, always ``[]``.

        SpotiFLAC can only act on a known Spotify URL. Per the
        :class:`~app.downloader.SourceProvider` contract a provider that cannot
        search legitimately returns an empty list; the orchestrator routes
        free-form queries to providers that can (e.g. SoundCloud).
        """
        logger.debug("[spotiflac] search() is a no-op (SpotiFLAC has no search)")
        return []

    async def fetch(self, match: TrackMatch, dest_dir: Path) -> Path:
        """Download the audio for a chosen :class:`TrackMatch`.

        ``match.url`` is a service URL with the originating Spotify URL appended
        as a ``#spotify=`` fragment (see :meth:`_build_claim`). SpotiFLAC's
        download is Spotify-pivoted — it resolves Spotify→service internally —
        so :meth:`fetch` recovers that Spotify origin from the fragment and
        hands it to the worker.

        Raises:
            RuntimeError: the download failed or the worker crashed.
            ValueError: ``match`` is not a SpotiFLAC-served claim.
        """
        if match.platform not in _PLATFORM_TO_SERVICE:
            raise ValueError(f"SpotiFlacProvider.fetch cannot serve platform {match.platform!r}")
        dest_dir.mkdir(parents=True, exist_ok=True)

        # The claim's Spotify origin is encoded in the synthetic URL fragment
        # written by _build_claim ("<service-url>#spotify=<spotify-url>").
        spotify_url = _extract_spotify_origin(match.url)
        if not spotify_url:
            raise ValueError(
                f"claim for {match.platform} has no Spotify origin — "
                "cannot drive SpotiFLAC's Spotify-pivoted download"
            )

        result = await _submit_with_recovery(
            _worker_fetch,
            match.platform,
            spotify_url,
            match.isrc,
            str(dest_dir),
            timeout_s=_FETCH_TIMEOUT_S,
        )
        return Path(result)

    # ──────────────────────────────────────────────────────────────────────
    # Internals
    # ──────────────────────────────────────────────────────────────────────

    def _build_claim(
        self, platform: Platform, service_url: str, meta: dict[str, Any]
    ) -> TrackMatch:
        """Build one per-service :class:`TrackMatch` from the worker's metadata.

        Quality fields are the service's optimistic ceiling (see
        :data:`_SERVICE_CEILING`). The Spotify origin URL is appended to the
        claim URL as a ``#spotify=`` fragment so :meth:`fetch` can recover it —
        :class:`TrackMatch` has no escape-hatch field and is frozen.
        """
        fmt, bit_depth, sample_rate, bitrate, tier = _SERVICE_CEILING[platform]
        origin = meta.get("spotify_url", "")
        claim_url = f"{service_url}#spotify={origin}" if origin else service_url
        return TrackMatch(
            platform=platform,
            url=claim_url,
            title=meta["title"],
            artist=meta["artist"],
            duration_s=meta["duration_s"],
            isrc=meta.get("isrc"),
            album=meta.get("album"),
            year=meta.get("year"),
            cover_url=meta.get("cover_url"),
            claimed_format=fmt,
            claimed_bit_depth=bit_depth,
            claimed_sample_rate_hz=sample_rate,
            claimed_bitrate_kbps=bitrate,
            quality_tier=tier,
        )


def _extract_spotify_origin(claim_url: str) -> str | None:
    """Pull the ``#spotify=`` origin fragment back out of a claim URL.

    :meth:`SpotiFlacProvider._build_claim` appends ``#spotify=<url>`` to every
    claim so :meth:`SpotiFlacProvider.fetch` can drive SpotiFLAC's
    Spotify-pivoted download. Returns ``None`` when the fragment is absent.
    """
    marker = "#spotify="
    idx = claim_url.find(marker)
    if idx == -1:
        return None
    origin = claim_url[idx + len(marker) :]
    return origin or None


__all__ = ["SpotiFlacProvider"]
