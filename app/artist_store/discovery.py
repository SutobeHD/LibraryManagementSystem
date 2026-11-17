"""artist_store.discovery — Tier-2 suggestions: artists the user does not have yet (T-16).

Seeded from the favourites, two tiers, primary first:

1. ``GET /users/{urn}/related`` once per favourite that has a linked SoundCloud account
   — **one hop**. ``related()`` is never called on a result; a transitive crawl is
   exactly what the ToU guardrails forbid. The returned User objects already carry
   ``track_count`` / ``followers_count``, so ranking costs no follow-up call.
2. Uploader co-occurrence over the catalogue payloads already cached in the sidecar —
   **zero network calls**. A niche artist plausibly has no related list, and a 404
   (deleted / private / renamed account) is a normal outcome, never an error.

Tier 2 always runs: it costs nothing, it sharpens the co-signal, and it is the *only*
source when tier 1 was empty, failed, or never queried. Which tier answered is reported
per source — an empty ``suggestions`` with ``sources.related == "failed"`` must render as
"we could not look", never as "nothing found".

Credentials never live here: the caller passes an already-resolved token (from
``app.soundcloud_auth``). Every run holds a hard :class:`~app.soundcloud_api.CallBudget`
— one is created when the caller supplies none, so an unbudgeted crawl is unreachable.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

import requests

from app import soundcloud_api as sc_api
from app.artist_store import registry, schema
from app.artist_store.merge import fold_key
from app.artist_store.schema import KIND_ARTIST

logger = logging.getLogger("ARTIST_STORE")

PROVIDER_SOUNDCLOUD = registry.PROVIDER_SOUNDCLOUD

#: Suggestions handed back at most. The panel is a shortlist, not a directory.
DEFAULT_SUGGESTION_LIMIT = 25

#: Hard per-run call cap when the caller brings no budget. One page of ``/related`` per
#: favourite plus headroom; anything past that is a crawl, not a discovery run.
DEFAULT_DISCOVERY_BUDGET = 15

SOURCE_RELATED = "related"
SOURCE_CO_OCCURRENCE = "co_occurrence"

#: Per-source states. ``not_queried`` and ``no_data`` are NOT "nothing found".
STATE_OK = "ok"
STATE_FAILED = "failed"
STATE_SKIPPED_BUDGET = "skipped_budget"
STATE_NOT_QUERIED = "not_queried"
STATE_NO_DATA = "no_data"

#: Per-seed outcomes of the related hop.
SEED_NOT_FOUND = "not_found"


class RelatedFetcher(Protocol):
    """The one client call this module makes. Injectable so tests need no network."""

    def __call__(
        self, user_urn_or_id: str, auth_token: str, *, budget: sc_api.CallBudget | None
    ) -> Sequence[Any]: ...


# --------------------------------------------------------------------------- candidates


@dataclass
class Candidate:
    """One suggested artist. Unmeasured fields stay ``None`` — never a guessed number."""

    name: str = ""
    urn: str = ""
    permalink_url: str = ""
    avatar_url: str = ""
    #: From the ``/related`` User object. ``None`` when only co-occurrence saw this
    #: artist: the cached track payloads carry an uploader, not their catalogue size.
    track_count: int | None = None
    followers_count: int | None = None
    #: Favourites that point at this candidate. Its length is the co-signal.
    seeds: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    #: Cached tracks this artist uploaded alongside a favourite. Measured, so printable.
    co_occurrence_tracks: int = 0

    @property
    def key(self) -> str:
        """Identity for de-duplication: the URN when SoundCloud gave one, else the fold."""
        return self.urn or f"name:{fold_key(self.name)}"

    @property
    def co_signal(self) -> int:
        return len(self.seeds)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "urn": self.urn,
            "permalink_url": self.permalink_url,
            "avatar_url": self.avatar_url,
            "track_count": self.track_count,
            "followers_count": self.followers_count,
            "co_signal": self.co_signal,
            "seeds": list(self.seeds),
            "sources": list(self.sources),
            "co_occurrence_tracks": self.co_occurrence_tracks,
        }


@dataclass
class Ranking:
    """Result of the pure rank/exclude pass."""

    suggestions: list[Candidate] = field(default_factory=list)
    excluded: int = 0
    #: The limit cut the list — more survived exclusion than are being shown.
    truncated: bool = False


def _merge_into(target: Candidate, other: Candidate) -> None:
    """Fold a second sighting of the same artist into the first."""
    seeds = list(target.seeds)
    for seed in other.seeds:
        if seed not in seeds:
            seeds.append(seed)
    target.seeds = tuple(seeds)
    target.sources = tuple(dict.fromkeys(target.sources + other.sources))
    target.co_occurrence_tracks += other.co_occurrence_tracks
    if target.track_count is None:
        target.track_count = other.track_count
    if target.followers_count is None:
        target.followers_count = other.followers_count
    if not target.urn:
        target.urn = other.urn
    if not target.permalink_url:
        target.permalink_url = other.permalink_url
    if not target.avatar_url:
        target.avatar_url = other.avatar_url


def _sort_key(candidate: Candidate) -> tuple[int, int, int, str, str]:
    """Co-signal first: two favourites pointing at one artist beats one big catalogue."""
    return (
        -candidate.co_signal,
        -(candidate.track_count or 0),
        -(candidate.followers_count or 0),
        fold_key(candidate.name),
        candidate.key,
    )


def rank_candidates(
    candidates: Iterable[Candidate],
    *,
    excluded_folds: Iterable[str] = (),
    excluded_urns: Iterable[str] = (),
    limit: int = DEFAULT_SUGGESTION_LIMIT,
) -> Ranking:
    """De-duplicate, drop what the user already has, rank. Pure — no DB, no network.

    Ranked by how many favourites point at the same candidate, then by ``track_count``
    (0 when it was never measured, so a co-occurrence hit never outranks a measured one
    on a number nobody counted), then followers, then name.
    """
    folds = {f for f in (fold_key(x) for x in excluded_folds) if f}
    urns = {str(u).strip() for u in excluded_urns if str(u or "").strip()}

    merged: dict[str, Candidate] = {}
    excluded = 0
    for candidate in candidates:
        name = str(candidate.name or "").strip()
        urn = str(candidate.urn or "").strip()
        if not name and not urn:
            continue
        if urn and urn in urns:
            excluded += 1
            continue
        if name and fold_key(name) in folds:
            excluded += 1
            continue
        existing = merged.get(candidate.key)
        if existing is None:
            merged[candidate.key] = Candidate(
                name=name,
                urn=urn,
                permalink_url=candidate.permalink_url,
                avatar_url=candidate.avatar_url,
                track_count=candidate.track_count,
                followers_count=candidate.followers_count,
                seeds=tuple(candidate.seeds),
                sources=tuple(dict.fromkeys(candidate.sources)),
                co_occurrence_tracks=candidate.co_occurrence_tracks,
            )
            continue
        _merge_into(existing, candidate)

    ranked = sorted(merged.values(), key=_sort_key)
    cut = max(0, int(limit))
    return Ranking(
        suggestions=ranked[:cut],
        excluded=excluded,
        truncated=len(ranked) > cut,
    )


# --------------------------------------------------------------------------- seeds


@dataclass
class _Seed:
    collection_id: str
    name: str
    names: tuple[str, ...]
    urn: str


def _seed_from(entry: Any, kind: str) -> _Seed | None:
    """Accept a collection id, a favourite row, or anything carrying a name."""
    if isinstance(entry, str):
        cid, name, urn = entry.strip(), "", ""
    elif isinstance(entry, Mapping):
        cid = str(entry.get("collection_id") or entry.get("id") or "").strip()
        name = str(entry.get("canonical_name") or entry.get("name") or "").strip()
        urn = str(entry.get("sc_urn") or entry.get("urn") or entry.get("remote_id") or "").strip()
    else:
        return None

    if not cid and name:
        known = schema.resolve_alias(name, kind)
        cid = str(known["id"]) if known is not None else schema.collection_id_for(name, kind)
    if not cid:
        return None

    names = registry.artist_names(cid, kind)
    if not name:
        name = names[0] if names else cid
    if not names:
        names = (name,)
    if not urn:
        link = registry.get_provider_link(cid, PROVIDER_SOUNDCLOUD)
        if link is not None and link["resolved"]:
            urn = str(link["remote_id"])
    return _Seed(collection_id=cid, name=name, names=names, urn=urn)


def _seeds(favourites: Iterable[Any] | None, kind: str) -> list[_Seed]:
    rows: Iterable[Any] = schema.list_favourites(kind) if favourites is None else favourites
    seeds: list[_Seed] = []
    seen: set[str] = set()
    for entry in rows:
        seed = _seed_from(entry, kind)
        if seed is None or seed.collection_id in seen:
            continue
        seen.add(seed.collection_id)
        seeds.append(seed)
    return seeds


# --------------------------------------------------------------------------- exclusions


@dataclass
class _LocalIndex:
    folds: set[str] = field(default_factory=set)
    urns: set[str] = field(default_factory=set)
    names: int = 0


def _local_index(kind: str) -> _LocalIndex:
    """Every artist the user already has, by folded name and by linked account.

    Names come from the registry's own store index — the library strings it recorded
    when it resolved the library. Re-deriving them here with a second normaliser would
    drift from ``_split_artists`` / ``_normalize_artist_name``.
    """
    index = _LocalIndex()
    store = registry._store_index(kind)
    for alias in store.by_alias:
        folded = fold_key(alias)
        if folded:
            index.folds.add(folded)
    for cid, collection in store.collections.items():
        folded = fold_key(str(collection.get("canonical_name") or ""))
        if folded:
            index.folds.add(folded)
        link = schema.get_link(cid, PROVIDER_SOUNDCLOUD)
        remote_id = str(link.get("remote_id") or "") if link is not None else ""
        if remote_id:
            index.urns.add(remote_id)
    index.names = len(index.folds)
    return index


# --------------------------------------------------------------------------- tier 1


def _related_candidates(result: Iterable[Any], seed: _Seed) -> list[Candidate]:
    out: list[Candidate] = []
    for raw in result:
        if not isinstance(raw, Mapping):
            continue
        name = str(raw.get("username") or "").strip()
        urn = str(raw.get("urn") or "").strip()
        if not name and not urn:
            continue
        track_count = raw.get("track_count")
        followers = raw.get("followers_count")
        out.append(
            Candidate(
                name=name or urn,
                urn=urn,
                permalink_url=str(raw.get("permalink_url") or ""),
                avatar_url=str(raw.get("avatar_url") or ""),
                track_count=int(track_count) if isinstance(track_count, int) else None,
                followers_count=int(followers) if isinstance(followers, int) else None,
                seeds=(seed.name,),
                sources=(SOURCE_RELATED,),
            )
        )
    return out


def _run_related(
    seeds: Sequence[_Seed],
    *,
    token: str,
    budget: sc_api.CallBudget,
    fetch: RelatedFetcher,
) -> tuple[list[Candidate], dict[str, Any]]:
    """One hop per seed. Never calls ``related()`` on a result — that is the whole rule."""
    detail: dict[str, Any] = {
        "state": STATE_NOT_QUERIED,
        "reason": "",
        "queried": [],
        "failed": [],
        "skipped": [],
        "not_linked": [seed.name for seed in seeds if not seed.urn],
        "returned": 0,
        "truncated": False,
    }
    linked = [seed for seed in seeds if seed.urn]

    if not token:
        detail["reason"] = "not_signed_in"
        return [], detail
    if not linked:
        detail["reason"] = "no_linked_accounts" if seeds else "no_favourites"
        return [], detail

    candidates: list[Candidate] = []
    stop_reason = ""
    for seed in linked:
        if stop_reason or budget.remaining <= 0:
            detail["skipped"].append(seed.name)
            continue
        try:
            result = fetch(seed.urn, token, budget=budget)
        except sc_api.NotFoundError:
            # Deleted, private or renamed account — normal, and never an error to show.
            detail["failed"].append({"artist": seed.name, "reason": SEED_NOT_FOUND})
            continue
        except (sc_api.AuthExpiredError, sc_api.RateLimitError) as exc:
            reason = "auth_expired" if isinstance(exc, sc_api.AuthExpiredError) else "rate_limited"
            detail["failed"].append({"artist": seed.name, "reason": reason})
            stop_reason = reason
            logger.warning("op=artist_discover related artist=%s stop=%s", seed.name, reason)
            continue
        except (requests.RequestException, ValueError) as exc:
            detail["failed"].append({"artist": seed.name, "reason": type(exc).__name__})
            logger.warning(
                "op=artist_discover related artist=%s err=%s: %s",
                seed.name,
                type(exc).__name__,
                exc,
            )
            continue

        # The client reports HOW the walk ended. An empty list is only "this artist has
        # no related accounts" when the walk actually ran: "budget" means the call never
        # went out, and "not_found" means the account is gone. Reading either as an
        # answer would turn an unqueried source into a fabricated "nothing found".
        stop = str(getattr(result, "stop_reason", "") or "")
        if stop == "budget":
            detail["skipped"].append(seed.name)
            continue
        if stop == SEED_NOT_FOUND:
            detail["failed"].append({"artist": seed.name, "reason": SEED_NOT_FOUND})
            continue
        detail["queried"].append(seed.name)
        detail["truncated"] = bool(detail["truncated"] or getattr(result, "truncated", False))
        candidates.extend(_related_candidates(result, seed))

    detail["returned"] = len(candidates)
    # Order matters: an abort or an unasked seed OUTRANKS a partial success. Reporting
    # STATE_OK because one seed answered let the UI print "both sources answered and
    # turned up nobody" for favourites that were never queried — fabricated absence,
    # the exact failure this module's contract exists to prevent. Only a run that asked
    # every seed it meant to ask, with nothing failed and nothing skipped, is "ok".
    if stop_reason:
        detail["state"] = STATE_FAILED
        detail["reason"] = stop_reason
    elif detail["skipped"]:
        detail["state"] = STATE_SKIPPED_BUDGET
        detail["reason"] = "call_budget_spent"
    elif detail["failed"]:
        detail["state"] = STATE_FAILED
        detail["reason"] = str(detail["failed"][0]["reason"])
    elif detail["queried"]:
        detail["state"] = STATE_OK
    return candidates, detail


# --------------------------------------------------------------------------- tier 2


def _co_occurrence(
    seeds: Sequence[_Seed], *, cache_max_age_s: float | None
) -> tuple[list[Candidate], dict[str, Any]]:
    """Uploaders that appear alongside a favourite in an already-cached catalogue.

    Zero network calls: nothing here fetches, it only reads payloads a catalogue view
    already put in the sidecar.
    """
    detail: dict[str, Any] = {
        "state": STATE_NO_DATA,
        "scanned": [],
        "no_cache": [],
        "tracks_scanned": 0,
    }
    candidates: list[Candidate] = []

    for seed in seeds:
        payload = schema.get_catalogue_cache(seed.collection_id, max_age_s=cache_max_age_s)
        tracks = payload.get("tracks") if isinstance(payload, Mapping) else None
        if not isinstance(tracks, list):
            detail["no_cache"].append(seed.name)
            continue
        detail["scanned"].append(seed.name)
        detail["tracks_scanned"] += len(tracks)

        own_folds = {f for f in (fold_key(n) for n in seed.names) if f}
        hits: dict[str, Candidate] = {}
        for track in tracks:
            if not isinstance(track, Mapping):
                continue
            name = str(track.get("uploader_name") or "").strip()
            urn = str(track.get("uploader_urn") or "").strip()
            if not name and not urn:
                continue
            if urn and seed.urn and urn == seed.urn:
                continue
            if name and fold_key(name) in own_folds:
                continue
            key = urn or f"name:{fold_key(name)}"
            entry = hits.get(key)
            if entry is None:
                hits[key] = Candidate(
                    name=name or urn,
                    urn=urn,
                    seeds=(seed.name,),
                    sources=(SOURCE_CO_OCCURRENCE,),
                    co_occurrence_tracks=1,
                )
                continue
            entry.co_occurrence_tracks += 1
        candidates.extend(hits.values())

    if detail["scanned"]:
        detail["state"] = STATE_OK
    return candidates, detail


# --------------------------------------------------------------------------- public


def discover(
    favourites: Iterable[Any] | None = None,
    *,
    token: str = "",
    budget: sc_api.CallBudget | None = None,
    kind: str = KIND_ARTIST,
    limit: int = DEFAULT_SUGGESTION_LIMIT,
    cache_max_age_s: float | None = None,
    related_fetch: RelatedFetcher | None = None,
) -> dict[str, Any]:
    """Artists the user does not have yet, seeded from the ones they favourited.

    ``favourites`` accepts collection ids, ``registry.list_favourite_artists`` rows, or
    ``None`` to read the store's favourites. A missing ``token`` is not an error: tier 1
    is then reported as ``not_queried`` and only the zero-call tier 2 runs.

    Returns ``{suggestions, sources, sources_detail, calls_used, call_budget, truncated,
    seeded_from, favourites, excluded, limit}``. ``sources`` is the honesty contract —
    a source that was not queried says so; it never reads as "nothing found".
    """
    seeds = _seeds(favourites, kind)
    run_budget = budget or sc_api.CallBudget(
        limit=DEFAULT_DISCOVERY_BUDGET, label="artist_discovery"
    )
    spent_before = run_budget.used
    fetch: RelatedFetcher = related_fetch or sc_api.get_related_artists

    related_hits, related_detail = _run_related(seeds, token=token, budget=run_budget, fetch=fetch)
    local_hits, co_detail = _co_occurrence(seeds, cache_max_age_s=cache_max_age_s)

    local = _local_index(kind)
    excluded_folds = set(local.folds)
    excluded_urns = set(local.urns)
    for seed in seeds:
        excluded_folds.update(f for f in (fold_key(n) for n in seed.names) if f)
        if seed.urn:
            excluded_urns.add(seed.urn)

    ranking = rank_candidates(
        related_hits + local_hits,
        excluded_folds=excluded_folds,
        excluded_urns=excluded_urns,
        limit=limit,
    )

    calls_used = run_budget.used - spent_before
    consulted = list(dict.fromkeys(related_detail["queried"] + co_detail["scanned"]))
    truncated = bool(
        ranking.truncated
        or related_detail["truncated"]
        or related_detail["skipped"]
        or (related_detail["queried"] and run_budget.exhausted)
    )

    logger.info(
        "op=artist_discover favourites=%d seeded=%d related=%s co=%s calls=%d/%d "
        "suggestions=%d excluded=%d truncated=%s",
        len(seeds),
        len(consulted),
        related_detail["state"],
        co_detail["state"],
        calls_used,
        run_budget.limit,
        len(ranking.suggestions),
        ranking.excluded,
        truncated,
    )

    return {
        "suggestions": [candidate.as_dict() for candidate in ranking.suggestions],
        "sources": {
            SOURCE_RELATED: related_detail["state"],
            SOURCE_CO_OCCURRENCE: co_detail["state"],
        },
        "sources_detail": {SOURCE_RELATED: related_detail, SOURCE_CO_OCCURRENCE: co_detail},
        "calls_used": calls_used,
        "call_budget": {
            "limit": run_budget.limit,
            "used": run_budget.used,
            "remaining": run_budget.remaining,
        },
        "truncated": truncated,
        "seeded_from": consulted,
        "favourites": len(seeds),
        "excluded": ranking.excluded,
        # What "you do not have this yet" was actually checked against. Zero here means
        # the store has not resolved the library yet — the claim is then unbacked, and
        # the caller must not present the list as "artists you do not own".
        "excluded_against": {
            "local_names": len(excluded_folds),
            "linked_accounts": len(excluded_urns),
        },
        "limit": limit,
    }


__all__ = [
    "DEFAULT_DISCOVERY_BUDGET",
    "DEFAULT_SUGGESTION_LIMIT",
    "SOURCE_CO_OCCURRENCE",
    "SOURCE_RELATED",
    "STATE_FAILED",
    "STATE_NOT_QUERIED",
    "STATE_NO_DATA",
    "STATE_OK",
    "STATE_SKIPPED_BUDGET",
    "Candidate",
    "Ranking",
    "discover",
    "rank_candidates",
]
