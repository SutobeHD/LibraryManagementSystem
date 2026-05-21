"""Phase-3 resolver — single-identifier → ranked cross-platform candidates.

Implements ``P3.11`` of
``docs/research/implement/accepted_downloader-unified-multi-source.md``.

The resolver is the entry point for the *single-input* flow (a platform URL, a
free-form ``Artist - Title`` string, or a bare ISRC). It:

1. **Identifies the needle** — the canonical track the user is asking for. A
   platform URL is resolved through whichever provider serves it; a free-form
   string or ISRC has no URL to resolve, so a synthetic needle is built from
   the parsed identifier (its quality fields are placeholders — the needle is
   a matching reference, never a download candidate).
2. **Fans out** ``resolve_url`` across every enabled provider *in parallel*
   (:func:`asyncio.gather`), each call bounded by a shared
   :class:`asyncio.Semaphore` sized to the D8 concurrency budget. A provider
   that cannot serve the identifier returns an empty list (its contract) and
   simply contributes nothing.
3. **Matches** every returned :class:`TrackMatch` against the needle via
   :func:`app.downloader.match_adapter.match` (the I1 shared-matcher delegate).
4. **Classifies + ranks** — each claim is re-tiered with
   :func:`app.downloader.quality.classify` and the surviving 100%-matches are
   sorted by :attr:`Candidate.quality_sort_key` (lossless-first).
5. **Reports** an ``auto_pick_index`` (``0`` whenever any 100%-match exists,
   since the list is quality-sorted) and a ``near_misses`` list — the closest
   sub-100% claims at or above the ``match_threshold_near_miss`` setting (Q7).

Concurrency note (D8): the semaphore caps how many provider probes run at
once. A dead/slow provider therefore cannot starve the others, and the total
outbound request rate stays inside the budget the first-run benchmark picked.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid

from .match_adapter import match
from .models import (
    Candidate,
    Platform,
    QualityTier,
    ResolveRequest,
    ResolveResponse,
    TrackMatch,
)
from .providers import SoundCloudProvider, SpotiFlacProvider
from .quality import classify

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Settings access — the ``unified_downloader`` block of settings.json
# ──────────────────────────────────────────────────────────────────────────────

#: Fallback near-miss threshold when settings.json carries no override. Mirrors
#: the ``unified_downloader.match_threshold_near_miss`` default in the spec's
#: "Settings schema additions" block.
_DEFAULT_NEAR_MISS_THRESHOLD: float = 0.85

#: Fallback concurrency budget — the spec's ``max_concurrency`` default. The D8
#: first-run benchmark overwrites this in settings.json; until it has run, 4 is
#: the conservative starting point.
_DEFAULT_MAX_CONCURRENCY: int = 4

#: Fallback enabled-platform set when settings.json carries no override — only
#: SoundCloud, matching the spec's default ``enabled_platforms`` block (every
#: paid service ships disabled until the user opts in).
_DEFAULT_ENABLED_PLATFORMS: tuple[Platform, ...] = ("soundcloud",)


def _unified_settings() -> dict[str, object]:
    """Return the ``unified_downloader`` settings block, or an empty dict.

    Read through :class:`app.services.SettingsManager` so the same sanitising
    load path the rest of the app uses applies here too. Any failure (missing
    file, missing key, import error in a stripped-down test env) degrades to an
    empty dict — every consumer below has a hard-coded fallback.
    """
    try:
        from app.services import SettingsManager

        block = SettingsManager.load().get("unified_downloader")
    except Exception as exc:
        logger.debug("[resolver] settings load failed, using defaults: %s", exc)
        return {}
    return block if isinstance(block, dict) else {}


def _near_miss_threshold() -> float:
    """The ``match_threshold_near_miss`` setting, clamped to ``[0.0, 1.0]``."""
    raw = _unified_settings().get("match_threshold_near_miss", _DEFAULT_NEAR_MISS_THRESHOLD)
    try:
        value = float(str(raw))
    except (TypeError, ValueError):
        return _DEFAULT_NEAR_MISS_THRESHOLD
    return min(1.0, max(0.0, value))


def _max_concurrency() -> int:
    """The D8 ``max_concurrency`` budget, clamped to a sane ``[1, 32]`` range."""
    raw = _unified_settings().get("max_concurrency", _DEFAULT_MAX_CONCURRENCY)
    try:
        value = int(str(raw))
    except (TypeError, ValueError):
        return _DEFAULT_MAX_CONCURRENCY
    return min(32, max(1, value))


def _enabled_platforms() -> list[Platform]:
    """Resolve the enabled-platform set from settings.json.

    The spec stores ``enabled_platforms`` as a ``{platform: bool}`` map; this
    flattens it to the list of truthy platform names. An absent / malformed
    block falls back to :data:`_DEFAULT_ENABLED_PLATFORMS`.
    """
    raw = _unified_settings().get("enabled_platforms")
    if not isinstance(raw, dict):
        return list(_DEFAULT_ENABLED_PLATFORMS)
    enabled: list[Platform] = [p for p, on in raw.items() if on and p in _PLATFORM_PROVIDERS]
    return enabled or list(_DEFAULT_ENABLED_PLATFORMS)


# ──────────────────────────────────────────────────────────────────────────────
# Provider registry — platform → SourceProvider factory
# ──────────────────────────────────────────────────────────────────────────────


def _make_spotiflac(platform: Platform) -> SpotiFlacProvider:
    """Construct a SpotiFLAC provider bound to one served paid service."""
    return SpotiFlacProvider(platform)


#: Default platform → provider factory map. Each SpotiFLAC-served paid service
#: gets its own ``SpotiFlacProvider`` instance (bound to that platform) so the
#: orchestrator can hold one provider per platform; SoundCloud has its own.
#: ``spotify`` / ``youtube`` have no Phase-1 provider yet — they are absent so
#: an enabled-but-unbuilt platform is silently skipped, never crashes.
_PLATFORM_PROVIDERS: dict[str, object] = {
    "soundcloud": SoundCloudProvider,
    "tidal": lambda: _make_spotiflac("tidal"),
    "qobuz": lambda: _make_spotiflac("qobuz"),
    "amazon": lambda: _make_spotiflac("amazon"),
    "apple_music": lambda: _make_spotiflac("apple_music"),
    "deezer": lambda: _make_spotiflac("deezer"),
}


def _providers_for(platforms: list[Platform]) -> list[object]:
    """Instantiate one :class:`SourceProvider` per platform that has a factory.

    Platforms with no registered factory (``spotify`` / ``youtube`` — no
    Phase-1 provider exists yet) are skipped with a debug log rather than
    raising: an enabled-but-unimplemented platform must degrade gracefully.
    """
    out: list[object] = []
    for p in platforms:
        factory = _PLATFORM_PROVIDERS.get(p)
        if factory is None:
            logger.debug("[resolver] no provider for enabled platform %r — skipped", p)
            continue
        out.append(factory())  # type: ignore[operator]
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Needle identification
# ──────────────────────────────────────────────────────────────────────────────

#: A bare ISRC: 2-letter country, 3-char registrant, 2-digit year, 5-digit
#: designation — 12 alphanumerics total. Matched case-insensitively.
_ISRC_RE = re.compile(r"^[A-Za-z]{2}[A-Za-z0-9]{3}\d{2}\d{5}$")

#: Dash characters that can separate a free-form ``Artist - Title``: ASCII
#: hyphen-minus, en-dash (U+2013), em-dash (U+2014). Built with ``chr`` so the
#: source file stays pure-ASCII (no ambiguous-unicode lint hit).
_TITLE_DASHES = "-" + chr(0x2013) + chr(0x2014)

#: Free-form ``Artist - Title`` split — one of :data:`_TITLE_DASHES` with
#: surrounding whitespace. Only the *first* such dash splits, so ``"A - B - C"``
#: becomes ``("A", "B - C")``.
_ARTIST_TITLE_RE = re.compile(rf"\s+[{_TITLE_DASHES}]\s+")


def _looks_like_url(identifier: str) -> bool:
    """True when ``identifier`` is an ``http(s)://`` URL."""
    return identifier.strip().lower().startswith(("http://", "https://"))


def _synthetic_needle(identifier: str) -> TrackMatch:
    """Build a placeholder needle for a non-URL identifier.

    Free-form ``Artist - Title`` is split on the first dash; a bare ISRC sets
    only :attr:`TrackMatch.isrc`; anything else becomes a title-only needle.
    The quality fields are dummies — a synthetic needle is a matching
    *reference*, never itself a download candidate, so its tier is irrelevant
    to ranking. ``duration_s`` is ``0.0`` which, combined with the matcher's
    ±2 s gate, means a synthetic needle can only ever match on ISRC or on a
    candidate that also reports ~0 s; that is intentional — without a real
    duration the resolver cannot 100%-gate a free-form query, and the caller
    should prefer :func:`app.downloader.search.search` for those.
    """
    ident = identifier.strip()

    if _ISRC_RE.match(ident):
        return TrackMatch(
            platform="spotify",
            url="",
            title=ident,
            artist="",
            duration_s=0.0,
            isrc=ident.upper(),
            claimed_format="flac",
            quality_tier=QualityTier.CD_LOSSLESS,
        )

    parts = _ARTIST_TITLE_RE.split(ident, maxsplit=1)
    if len(parts) == 2:
        artist, title = parts[0].strip(), parts[1].strip()
    else:
        artist, title = "", ident

    return TrackMatch(
        platform="spotify",
        url="",
        title=title or ident,
        artist=artist,
        duration_s=0.0,
        claimed_format="flac",
        quality_tier=QualityTier.CD_LOSSLESS,
    )


async def _identify_needle(
    identifier: str,
    provider_list: list[object],
    sem: asyncio.Semaphore,
) -> TrackMatch:
    """Identify the canonical needle track for ``identifier``.

    For a URL: probe the providers (already constructed by the caller) and
    take the first non-empty ``resolve_url`` result as the needle's canonical
    metadata — that is the track behind the URL, with a real duration + ISRC
    the 100%-gate can use. For a non-URL identifier: build a synthetic needle
    from the parsed string (see :func:`_synthetic_needle`).

    The needle probes share the *same* ``sem`` as the main fan-out, so the D8
    concurrency budget bounds total outbound requests across both phases — the
    needle-identification step cannot itself burst past the budget.

    A URL that no provider can resolve falls back to a synthetic needle too,
    so the resolver never hard-fails on an unrecognised URL.
    """
    if not _looks_like_url(identifier):
        return _synthetic_needle(identifier)

    probes = [_bounded_resolve(p, identifier, sem) for p in provider_list]
    results: list[list[TrackMatch]] = await asyncio.gather(*probes)
    for sub in results:
        if sub:
            return sub[0]

    logger.info("[resolver] URL %r resolved to nothing — using synthetic needle", identifier)
    return _synthetic_needle(identifier)


# ──────────────────────────────────────────────────────────────────────────────
# Provider fan-out
# ──────────────────────────────────────────────────────────────────────────────


async def _safe_resolve(provider: object, url: str) -> list[TrackMatch]:
    """Call ``provider.resolve_url(url)`` and never let it raise.

    The two real providers already swallow their own transport failures, but a
    third-party provider (or a malformed mock) might not — and one dead source
    must not abort the whole multi-provider fan-out. Any exception degrades to
    an empty list.
    """
    try:
        return await provider.resolve_url(url)  # type: ignore[attr-defined]
    except Exception as exc:
        platform = getattr(provider, "platform", "?")
        logger.warning("[resolver] provider %s resolve_url failed: %s", platform, exc)
        return []


async def _bounded_resolve(
    provider: object,
    url: str,
    sem: asyncio.Semaphore,
) -> list[TrackMatch]:
    """Run :func:`_safe_resolve` while holding ``sem`` — the D8 concurrency cap."""
    async with sem:
        return await _safe_resolve(provider, url)


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────


async def resolve(req: ResolveRequest) -> ResolveResponse:
    """Resolve a single identifier into ranked, match-gated candidates.

    Pipeline (see the module docstring for the full rationale):

    1. Determine the enabled platforms — ``req.enabled_platforms`` if given,
       else the settings.json default.
    2. Identify the needle (URL → provider resolve; free-form/ISRC →
       synthetic).
    3. Fan ``resolve_url`` out across the enabled providers in parallel,
       bounded by an :class:`asyncio.Semaphore` of the D8 budget size.
    4. Match every returned claim against the needle, re-tier it, and split
       into 100%-matches (``candidates``) vs. near-misses.
    5. Sort ``candidates`` lossless-first; ``auto_pick_index`` is ``0`` when
       any candidate exists (the head is the best by construction), else
       ``None``.

    Returns a fully-populated :class:`ResolveResponse`; never raises for a
    dead provider or an unrecognised identifier.
    """
    platforms = req.enabled_platforms or _enabled_platforms()
    provider_list = _providers_for(platforms)

    # One semaphore for the whole call — the needle probe and the main fan-out
    # share it, so the D8 budget caps total concurrent outbound requests.
    sem = asyncio.Semaphore(_max_concurrency())

    needle = await _identify_needle(req.identifier, provider_list, sem)

    # Fan-out target: every provider probes the *original identifier*. Each
    # provider's resolve_url rejects a URL it cannot serve (returns []), so a
    # SoundCloud URL only yields SC claims, a Spotify URL only SpotiFLAC ones.
    # When the needle resolved to a real URL distinct from the input (rare),
    # the needle's own URL is the better probe target for the paid services.
    probe_url = needle.url or req.identifier

    tasks = [_bounded_resolve(p, probe_url, sem) for p in provider_list]
    results: list[list[TrackMatch]] = await asyncio.gather(*tasks)
    all_matches: list[TrackMatch] = [m for sub in results for m in sub]

    threshold = _near_miss_threshold()
    candidates: list[Candidate] = []
    near_misses: list[Candidate] = []

    # Re-tier every claim before matching so quality_sort_key reflects the
    # canonical classification rather than whatever the provider stamped.
    retiered = [m.model_copy(update={"quality_tier": classify(m)}) for m in all_matches]

    for claim, result in match(needle, retiered):
        cand = Candidate(match=claim, match_result=result)
        if result.is_match:
            candidates.append(cand)
        elif result.confidence >= threshold:
            near_misses.append(cand)

    candidates.sort(key=lambda c: c.quality_sort_key)
    auto_pick_index = 0 if candidates else None
    near_misses.sort(key=lambda c: -c.match_result.confidence)

    logger.info(
        "[resolver] identifier=%r -> %d candidate(s), %d near-miss(es), auto_pick=%s",
        req.identifier,
        len(candidates),
        len(near_misses),
        auto_pick_index,
    )

    response = ResolveResponse(
        request_id=str(uuid.uuid4()),
        needle=needle,
        candidates=candidates,
        auto_pick_index=auto_pick_index,
        near_misses=near_misses[:5],
    )

    # Register the result with the orchestrator's request cache so a later
    # POST /fetch can resolve this request_id + candidate_index back to the
    # chosen Candidate. Imported lazily — the orchestrator imports neither this
    # module nor search.py, so this one-way edge stays cycle-free.
    from .orchestrator import remember_resolve

    remember_resolve(response)
    return response


__all__ = ["resolve"]
