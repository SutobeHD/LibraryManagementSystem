"""Shared Pydantic v2 data models for the unified multi-source downloader.

Single source of truth for inter-module data flow. Every downloader phase
imports its types from here.

Two ``Candidate`` types exist in the downloader's world and must not be
confused:

* :class:`Candidate` (this module) — a track that already passed the
  100%-match gate. Carries the full :class:`TrackMatch` plus the
  :class:`MatchResult` that admitted it. This is the *richer* type — it
  knows quality tier, bit-depth, format.
* ``app.external_track_match.Candidate`` — the shared matcher's transient
  match candidate. Title/artist/duration only, no quality fields. The
  downloader maps :class:`TrackMatch` ↔ that type at the matcher boundary
  (``app/downloader/match_adapter.py``); quality data rides in its ``raw``
  escape-hatch dict.

See ``docs/research/implement/accepted_downloader-unified-multi-source.md``
§ "Shared data models (Pydantic v2)" for the design rationale.
"""

from __future__ import annotations

from enum import IntEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ──────────────────────────────────────────────────────────────────────────────
# Enums / literal vocabularies
# ──────────────────────────────────────────────────────────────────────────────

#: Every external platform the downloader can resolve against.
Platform = Literal[
    "spotify",
    "soundcloud",
    "tidal",
    "qobuz",
    "amazon",
    "apple_music",
    "deezer",
    "youtube",
]

#: Audio container / codec a source claims to deliver. ``flac``/``alac``/
#: ``wav``/``aiff`` are lossless; the rest are lossy. ``m4a`` is a container
#: that (for our sources) always holds AAC, so it is treated as lossy.
AudioFormat = Literal[
    "flac",
    "alac",
    "wav",
    "aiff",
    "mp3",
    "aac",
    "ogg",
    "opus",
    "m4a",
]


class QualityTier(IntEnum):
    """Coarse quality bucket. Lower int = higher quality.

    The ascending-int ordering is load-bearing: a default tuple-sort over
    ``(quality_tier.value, ...)`` then naturally descends quality, and every
    Tier 0/1 (lossless) candidate sorts ahead of every Tier 2/3/4 (lossy)
    candidate — the lossless-first hard rule, encoded structurally.
    """

    HIRES_LOSSLESS = 0  # FLAC/ALAC 24/96+, MQA HiRes
    CD_LOSSLESS = 1  # FLAC/ALAC 16/44.1, WAV, AIFF
    HIGH_LOSSY = 2  # 256+ kbps (Amazon HD, Tidal 320, SC Go+ AAC)
    STANDARD_LOSSY = 3  # 128-256 kbps lossy
    LAST_RESORT = 4  # YouTube MP3 (variable)


# ──────────────────────────────────────────────────────────────────────────────
# Core match / candidate models
# ──────────────────────────────────────────────────────────────────────────────


class TrackMatch(BaseModel):
    """One source's claim about a track — pre-download metadata only.

    Quality is *claimed*, not verified: the source tells us "I have this in
    FLAC 24/96"; final verification only happens at fetch time (post-download
    ``quality_engine.probe()``). Frozen so a claim is immutable once made —
    a re-tiered copy is produced via :meth:`pydantic.BaseModel.model_copy`.
    """

    model_config = ConfigDict(frozen=True)

    platform: Platform
    url: str
    title: str
    artist: str
    duration_s: float
    isrc: str | None = None
    album: str | None = None
    year: int | None = None
    genre: str | None = None
    cover_url: str | None = None

    claimed_format: AudioFormat
    claimed_bit_depth: int | None = None  # None when lossy
    claimed_sample_rate_hz: int | None = None
    claimed_bitrate_kbps: int | None = None  # None when lossless
    claimed_filesize_bytes: int | None = None  # tiebreak signal
    quality_tier: QualityTier

    def quality_sort_key(self) -> tuple[int, int, int, int, int]:
        """Quality picker key: tier, bit-depth, sample-rate, bitrate, filesize.

        Every term keeps the "lower tuple = better" invariant — higher-better
        fields (bit-depth, sample-rate, bitrate, filesize) are negated so the
        whole tuple is ascending-good. ``quality_tier`` is already ascending-
        good by construction (see :class:`QualityTier`).
        """
        return (
            self.quality_tier.value,
            -(self.claimed_bit_depth or 16),
            -(self.claimed_sample_rate_hz or 44100),
            -(self.claimed_bitrate_kbps or 0),
            -(self.claimed_filesize_bytes or 0),
        )


class MatchResult(BaseModel):
    """Output of the D1 title-variance match algorithm for one candidate.

    ``rule_fired`` is a short machine-readable trace of which gate decided
    the outcome — e.g. ``"isrc_equality"``, ``"duration_gate_failed"``,
    ``"xtm_fuzzy_0.94"``.
    """

    is_match: bool
    confidence: float = Field(ge=0.0, le=1.0)
    rule_fired: str


class Candidate(BaseModel):
    """A track that passed the 100%-match gate — eligible for ranking + download.

    Distinct from ``app.external_track_match.Candidate`` (see module docstring):
    this one bundles the full quality-bearing :class:`TrackMatch` with the
    :class:`MatchResult` that admitted it.
    """

    match: TrackMatch
    match_result: MatchResult

    @property
    def quality_sort_key(self) -> tuple[int, int, int, int, int]:
        """Delegate to the wrapped :class:`TrackMatch` quality key."""
        return self.match.quality_sort_key()


class ProvenanceRecord(BaseModel):
    """What gets persisted (DB column + COMMENT tag) per downloaded file.

    ``all_urls`` is the full descending-quality candidate URL list; by
    invariant ``all_urls[0] == picked_url`` (the winner is always the head).
    """

    picked_url: str
    all_urls: list[str]
    isrc: str | None = None
    picked_quality_tier: QualityTier
    picked_platform: Platform


# ──────────────────────────────────────────────────────────────────────────────
# Resolve flow (single-URL / single-identifier)
# ──────────────────────────────────────────────────────────────────────────────


class ResolveRequest(BaseModel):
    """Input for ``POST /api/downloads/unified/resolve``."""

    identifier: str = Field(
        ...,
        description="Any platform URL, free-form 'Artist - Title', or bare ISRC",
    )
    enabled_platforms: list[Platform] | None = None  # None → settings default


class ResolveResponse(BaseModel):
    """Output of the resolver: ranked candidates + an auto-pick hint.

    ``candidates`` is sorted by :attr:`Candidate.quality_sort_key` (best
    first). ``auto_pick_index`` is ``None`` when no 100%-match was found;
    ``near_misses`` then carries the closest sub-100% candidates (Q7).
    """

    request_id: str
    needle: TrackMatch
    candidates: list[Candidate]
    auto_pick_index: int | None
    near_misses: list[Candidate] = []


# ──────────────────────────────────────────────────────────────────────────────
# Search flow (free-form query)
# ──────────────────────────────────────────────────────────────────────────────


class SearchRequest(BaseModel):
    """Input for ``POST /api/downloads/unified/search`` (free-form query)."""

    query: str
    enabled_platforms: list[Platform] | None = None


class SearchHit(BaseModel):
    """One ISRC-deduped cluster from the auto-search flow.

    ``cluster_id`` is the ISRC when available, else a stable hash of
    ``title + artist + duration``. ``cross_platform_urls`` is filled via the
    SpotiFLAC ``LinkResolver`` pivot.
    """

    cluster_id: str
    representative: TrackMatch
    cross_platform_urls: dict[Platform, str]


class SearchResponse(BaseModel):
    """Output of the search flow: deduplicated, ranked hit clusters."""

    request_id: str
    hits: list[SearchHit]


# ──────────────────────────────────────────────────────────────────────────────
# Fetch flow (commit a chosen candidate) + job status
# ──────────────────────────────────────────────────────────────────────────────


class FetchRequest(BaseModel):
    """Input for ``POST /api/downloads/unified/fetch`` — commit a candidate."""

    request_id: str  # from a prior /resolve or /search
    candidate_index: int  # index into the candidates / hits list


class FetchResponse(BaseModel):
    """Output of the fetch flow: a job handle to poll."""

    job_id: str
    started_at: str  # ISO-8601 UTC


class JobStatus(BaseModel):
    """Polled state of an in-flight (or finished) download job."""

    job_id: str
    state: Literal[
        "queued",
        "downloading",
        "converting",
        "tagging",
        "analyzing",
        "done",
        "failed",
    ]
    progress_pct: int = Field(ge=0, le=100)
    final_path: str | None = None
    error: str | None = None


__all__ = [
    "AudioFormat",
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
    "TrackMatch",
]
