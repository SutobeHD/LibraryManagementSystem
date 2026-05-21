"""Phase-3 search — free-form query → deduplicated cross-platform hit clusters.

Implements ``P3.12`` of
``docs/research/implement/accepted_downloader-unified-multi-source.md`` — the
D2 auto-search flow (Q1d).

Where :mod:`app.downloader.resolver` handles a *known* single track (URL /
ISRC / ``Artist - Title``), this module handles the *discovery* case: the user
types a free-form query, the app searches every enabled platform in parallel,
and returns a deduplicated candidate grid the UI renders as one card per
distinct recording.

Flow:

1. **Parallel search** — ``search()`` is fanned out across every enabled
   provider via :func:`asyncio.gather`, each call bounded by a shared
   :class:`asyncio.Semaphore` sized to the D8 concurrency budget. Providers
   that cannot search (e.g. SpotiFLAC) return an empty list per their
   contract and contribute nothing.
2. **Cross-platform pivot** — every claim for the same recording is collapsed
   so the resulting :class:`SearchHit` exposes one URL per platform. The D2
   sketch pivots via the SpotiFLAC ``LinkResolver``; that is a Spotify-URL-only
   probe and is wired in a later phase. Phase-3 builds ``cross_platform_urls``
   from the *clustered claims themselves* — every platform that independently
   returned a hit for the same ISRC contributes its URL.
3. **ISRC-dedupe** — claims are clustered by ISRC when present, else by a
   stable hash of normalised ``title + artist + rounded duration`` (the D1
   fallback identity). Each cluster becomes one :class:`SearchHit`.
4. **Rank** — within a cluster the best-quality claim is the representative
   (lossless-first :attr:`TrackMatch.quality_sort_key`); the hit list is then
   sorted by those representatives so the UI's "best available" card leads.

No network here — every outbound call goes through the providers, which the
tests mock wholesale.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid

from .models import (
    Platform,
    SearchHit,
    SearchRequest,
    SearchResponse,
    TrackMatch,
)
from .quality import classify
from .resolver import (
    _enabled_platforms,
    _max_concurrency,
    _providers_for,
)

logger = logging.getLogger(__name__)

#: Per-platform hit cap handed to each provider's ``search()`` — the D2 sketch's
#: "cap N=5 per platform". Keeps the candidate grid bounded.
_PER_PLATFORM_LIMIT: int = 5

#: Duration is rounded to this many seconds when building the non-ISRC cluster
#: key, so two providers reporting e.g. 247.3 s and 247.8 s for the same track
#: still hash into the same cluster. Matches the matcher's ±2 s gate spirit.
_DURATION_BUCKET_S: int = 2


# ──────────────────────────────────────────────────────────────────────────────
# Clustering identity
# ──────────────────────────────────────────────────────────────────────────────


def _normalise(text: str) -> str:
    """Lower-case + collapse whitespace — the cheap identity normaliser.

    Used only for the *fallback* cluster key (no ISRC); the real fuzzy
    title-variance work is :mod:`app.external_track_match`'s job and is applied
    when a representative is chosen, not when clustering.
    """
    return " ".join(text.lower().split())


def _cluster_key(claim: TrackMatch) -> str:
    """Stable cluster id for a claim.

    The ISRC when the claim carries one — that is a hard cross-platform
    identity. Otherwise a SHA-1 of normalised ``title|artist|duration-bucket``;
    the duration is bucketed (see :data:`_DURATION_BUCKET_S`) so small
    per-platform duration drift does not split a cluster.
    """
    if claim.isrc:
        return claim.isrc.upper()

    bucket = round(claim.duration_s / _DURATION_BUCKET_S)
    raw = f"{_normalise(claim.title)}|{_normalise(claim.artist)}|{bucket}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"tad:{digest}"


# ──────────────────────────────────────────────────────────────────────────────
# Provider fan-out
# ──────────────────────────────────────────────────────────────────────────────


async def _safe_search(provider: object, query: str, limit: int) -> list[TrackMatch]:
    """Call ``provider.search(query, limit)`` and never let it raise.

    The shipped providers swallow their own transport failures, but a dead or
    misbehaving provider must not abort the whole fan-out — any exception
    degrades to an empty list.
    """
    try:
        return await provider.search(query, limit)  # type: ignore[attr-defined]
    except Exception as exc:
        platform = getattr(provider, "platform", "?")
        logger.warning("[search] provider %s search failed: %s", platform, exc)
        return []


async def _bounded_search(
    provider: object,
    query: str,
    limit: int,
    sem: asyncio.Semaphore,
) -> list[TrackMatch]:
    """Run :func:`_safe_search` while holding ``sem`` — the D8 concurrency cap."""
    async with sem:
        return await _safe_search(provider, query, limit)


# ──────────────────────────────────────────────────────────────────────────────
# Cluster → SearchHit
# ──────────────────────────────────────────────────────────────────────────────


def _pick_representative(cluster: list[TrackMatch]) -> TrackMatch:
    """Return the best-quality claim in a cluster (lossless-first).

    Sorts by :meth:`TrackMatch.quality_sort_key`, which encodes the
    lossless-first hard rule; stable on ties, so the first-seen claim of two
    equal-quality ones wins.
    """
    return min(cluster, key=lambda c: c.quality_sort_key())


def _cross_platform_urls(cluster: list[TrackMatch]) -> dict[Platform, str]:
    """Collapse a cluster into one URL per platform.

    When several claims share a platform (rare in search results) the
    best-quality one's URL wins — same lossless-first key as the
    representative. Claims with an empty URL are skipped.
    """
    by_platform: dict[Platform, TrackMatch] = {}
    for claim in cluster:
        if not claim.url:
            continue
        incumbent = by_platform.get(claim.platform)
        if incumbent is None or claim.quality_sort_key() < incumbent.quality_sort_key():
            by_platform[claim.platform] = claim
    return {plat: claim.url for plat, claim in by_platform.items()}


def _build_hit(cluster_id: str, cluster: list[TrackMatch]) -> SearchHit:
    """Turn one ISRC/identity cluster into a :class:`SearchHit`."""
    representative = _pick_representative(cluster)
    return SearchHit(
        cluster_id=cluster_id,
        representative=representative,
        cross_platform_urls=_cross_platform_urls(cluster),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────


async def search(req: SearchRequest) -> SearchResponse:
    """Run a free-form query across enabled platforms into deduped hit clusters.

    Pipeline (full rationale in the module docstring):

    1. Determine the enabled platforms — ``req.enabled_platforms`` if given,
       else the settings.json default.
    2. Fan ``search()`` out across the enabled providers in parallel, each
       call capped at :data:`_PER_PLATFORM_LIMIT` hits and the whole fan-out
       bounded by an :class:`asyncio.Semaphore` of the D8 budget size.
    3. Re-tier every returned claim with :func:`app.downloader.quality.classify`.
    4. Cluster claims by ISRC (or the title/artist/duration fallback hash).
    5. Build one :class:`SearchHit` per cluster, then sort the hits by their
       representative's lossless-first quality key.

    Returns a fully-populated :class:`SearchResponse`; never raises for a dead
    provider or an empty result set.
    """
    platforms = req.enabled_platforms or _enabled_platforms()
    provider_list = _providers_for(platforms)

    sem = asyncio.Semaphore(_max_concurrency())
    tasks = [_bounded_search(p, req.query, _PER_PLATFORM_LIMIT, sem) for p in provider_list]
    results: list[list[TrackMatch]] = await asyncio.gather(*tasks)
    all_hits: list[TrackMatch] = [m for sub in results for m in sub]

    # Re-tier every claim so the representative pick + hit ordering use the
    # canonical classification, not whatever tier the provider stamped.
    retiered = [m.model_copy(update={"quality_tier": classify(m)}) for m in all_hits]

    # Cluster by ISRC / identity hash, preserving first-seen order so equal
    # clusters rank deterministically before the quality sort settles ties.
    clusters: dict[str, list[TrackMatch]] = {}
    for claim in retiered:
        clusters.setdefault(_cluster_key(claim), []).append(claim)

    hits = [_build_hit(cid, members) for cid, members in clusters.items()]
    hits.sort(key=lambda h: h.representative.quality_sort_key())

    logger.info(
        "[search] query=%r -> %d claim(s) across %d provider(s) -> %d hit cluster(s)",
        req.query,
        len(all_hits),
        len(provider_list),
        len(hits),
    )

    return SearchResponse(request_id=str(uuid.uuid4()), hits=hits)


__all__ = ["search"]
