"""Unified multi-source downloader package.

A two-phase (resolve → fetch) downloader that fans a single track identifier
out across multiple external platforms (SoundCloud / Tidal / Qobuz / Amazon /
Spotify / …), 100%-match-gates the claims, ranks them lossless-first, and
fetches the single winning candidate.

This ``__init__`` exports only the stable cross-phase surface:

* :class:`SourceProvider` — the provider contract (one implementation per
  platform or per coherent platform group).
* the Pydantic models re-exported from :mod:`app.downloader.models`.

Matching lives in :mod:`app.downloader.match_adapter` (a thin adapter over the
shared ``app.external_track_match`` module). Quality ranking lives in
:mod:`app.downloader.quality`.

See ``docs/research/implement/accepted_downloader-unified-multi-source.md``
§ "P1.4 — app/downloader/__init__.py SourceProvider ABC".
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from .models import (
    Candidate,
    FetchRequest,
    FetchResponse,
    JobStatus,
    MatchResult,
    Platform,
    ProvenanceRecord,
    QualityTier,
    ResolveRequest,
    ResolveResponse,
    SearchHit,
    SearchRequest,
    SearchResponse,
    TrackMatch,
)


class SourceProvider(ABC):
    """Provider contract — one implementation per platform OR per coherent group.

    A provider is the downloader's adapter to a single external source (or a
    group of sources served by one upstream library, e.g. SpotiFLAC covering
    Tidal/Qobuz/Amazon). All three methods are coroutines because providers are
    HTTP- and subprocess-bound.

    The two-phase split is deliberate: :meth:`resolve_url` and :meth:`search`
    are metadata-only probes (no audio bytes), so the orchestrator can gather
    and rank candidates before committing; :meth:`fetch` is the only method
    that pulls real bytes, and only for the single chosen winner.
    """

    @property
    @abstractmethod
    def platform(self) -> Platform:
        """The platform this provider serves (one of the :data:`Platform` literals)."""

    @abstractmethod
    async def resolve_url(self, url: str) -> list[TrackMatch]:
        """Phase-1 metadata-only probe of a platform URL.

        Returns 0-N :class:`TrackMatch` claims — most providers return exactly
        one (the track behind the URL); a provider that maps one URL onto
        several service-specific claims may return more. Empty list when the
        URL resolves to nothing this provider can serve.
        """

    @abstractmethod
    async def search(self, query: str, limit: int = 5) -> list[TrackMatch]:
        """Free-form search for a track.

        Returns up to ``limit`` :class:`TrackMatch` claims, best-effort ranked
        by the provider. Some providers cannot search and legitimately return
        an empty list (e.g. providers that only resolve a known URL).
        """

    @abstractmethod
    async def fetch(self, match: TrackMatch, dest_dir: Path) -> Path:
        """Phase-2 actual download of the audio for a chosen claim.

        Downloads the audio bytes for ``match`` into ``dest_dir`` and returns
        the final path on disk.

        Raises:
            Exception: any transport / decode / write failure — the
                orchestrator catches and surfaces it as a failed job.
        """


__all__ = [
    "Candidate",
    "FetchRequest",
    "FetchResponse",
    "JobStatus",
    "MatchResult",
    "Platform",
    "ProvenanceRecord",
    "QualityTier",
    "ResolveRequest",
    "ResolveResponse",
    "SearchHit",
    "SearchRequest",
    "SearchResponse",
    "SourceProvider",
    "TrackMatch",
]
