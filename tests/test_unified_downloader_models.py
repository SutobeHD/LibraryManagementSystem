"""Tests for ``app/downloader/models.py`` — the unified-downloader data models.

Covers construction, validation, the frozen-model invariant, the
``quality_sort_key`` ordering contract, and the ``SourceProvider`` ABC's
abstract-method enforcement.

See ``docs/research/implement/accepted_downloader-unified-multi-source.md``
§ "Shared data models (Pydantic v2)".
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.downloader import SourceProvider
from app.downloader.models import (
    AudioFormat,
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

# ──────────────────────────────────────────────────────────────────────────────
# Builders
# ──────────────────────────────────────────────────────────────────────────────


def _flac_match(**overrides: object) -> TrackMatch:
    """A lossless FLAC 24/96 :class:`TrackMatch` with overridable fields."""
    base: dict[str, object] = {
        "platform": "qobuz",
        "url": "https://www.qobuz.com/track/1",
        "title": "Wake Me Up",
        "artist": "Avicii",
        "duration_s": 247.4,
        "isrc": "USUM71304455",
        "claimed_format": "flac",
        "claimed_bit_depth": 24,
        "claimed_sample_rate_hz": 96000,
        "quality_tier": QualityTier.HIRES_LOSSLESS,
    }
    base.update(overrides)
    return TrackMatch(**base)  # type: ignore[arg-type]


# ──────────────────────────────────────────────────────────────────────────────
# Enum sanity
# ──────────────────────────────────────────────────────────────────────────────


def test_quality_tier_is_ascending_good() -> None:
    """Lower QualityTier int must mean higher quality (sort-key invariant)."""
    assert QualityTier.HIRES_LOSSLESS < QualityTier.CD_LOSSLESS
    assert QualityTier.CD_LOSSLESS < QualityTier.HIGH_LOSSY
    assert QualityTier.HIGH_LOSSY < QualityTier.STANDARD_LOSSY
    assert QualityTier.STANDARD_LOSSY < QualityTier.LAST_RESORT
    assert int(QualityTier.HIRES_LOSSLESS) == 0
    assert int(QualityTier.LAST_RESORT) == 4


# ──────────────────────────────────────────────────────────────────────────────
# TrackMatch
# ──────────────────────────────────────────────────────────────────────────────


def test_trackmatch_minimal_construction() -> None:
    """A TrackMatch with only the required fields constructs; optionals default None."""
    m = TrackMatch(
        platform="soundcloud",
        url="https://soundcloud.com/x/y",
        title="Strobe",
        artist="deadmau5",
        duration_s=634.0,
        claimed_format="mp3",
        quality_tier=QualityTier.HIGH_LOSSY,
    )
    assert m.isrc is None
    assert m.album is None
    assert m.claimed_bit_depth is None
    assert m.claimed_bitrate_kbps is None


def test_trackmatch_is_frozen() -> None:
    """TrackMatch is frozen — attribute assignment raises ValidationError."""
    m = _flac_match()
    with pytest.raises(ValidationError):
        m.title = "mutated"  # type: ignore[misc]


def test_trackmatch_rejects_unknown_platform() -> None:
    """A platform outside the Literal set is rejected."""
    with pytest.raises(ValidationError):
        _flac_match(platform="bandcamp")


def test_trackmatch_rejects_unknown_format() -> None:
    """An audio format outside the Literal set is rejected."""
    with pytest.raises(ValidationError):
        _flac_match(claimed_format="wma")


def test_trackmatch_model_dump_roundtrip() -> None:
    """model_dump() → re-construct yields an equal model (Pydantic v2 API)."""
    m = _flac_match()
    rebuilt = TrackMatch(**m.model_dump())
    assert rebuilt == m


def test_trackmatch_quality_sort_key_shape_and_negation() -> None:
    """quality_sort_key is a 5-tuple; higher-better fields are negated."""
    m = _flac_match(
        claimed_bit_depth=24,
        claimed_sample_rate_hz=96000,
        claimed_bitrate_kbps=None,
        claimed_filesize_bytes=50_000_000,
    )
    key = m.quality_sort_key()
    assert key == (0, -24, -96000, 0, -50_000_000)


def test_quality_sort_key_lossless_beats_lossy() -> None:
    """A lossless candidate must sort strictly before any lossy candidate."""
    lossless = _flac_match(quality_tier=QualityTier.CD_LOSSLESS, claimed_bit_depth=16)
    lossy = _flac_match(
        platform="soundcloud",
        claimed_format="m4a",
        claimed_bit_depth=None,
        claimed_sample_rate_hz=None,
        claimed_bitrate_kbps=320,
        quality_tier=QualityTier.HIGH_LOSSY,
    )
    assert lossless.quality_sort_key() < lossy.quality_sort_key()


def test_quality_sort_key_defaults_for_missing_fields() -> None:
    """Missing bit-depth/sample-rate fall back to 16/44100 in the key."""
    m = _flac_match(claimed_bit_depth=None, claimed_sample_rate_hz=None)
    key = m.quality_sort_key()
    assert key[1] == -16
    assert key[2] == -44100


# ──────────────────────────────────────────────────────────────────────────────
# MatchResult
# ──────────────────────────────────────────────────────────────────────────────


def test_matchresult_confidence_bounds() -> None:
    """confidence must lie within [0.0, 1.0]."""
    MatchResult(is_match=True, confidence=0.0, rule_fired="x")
    MatchResult(is_match=True, confidence=1.0, rule_fired="x")
    with pytest.raises(ValidationError):
        MatchResult(is_match=True, confidence=1.01, rule_fired="x")
    with pytest.raises(ValidationError):
        MatchResult(is_match=False, confidence=-0.1, rule_fired="x")


# ──────────────────────────────────────────────────────────────────────────────
# Candidate
# ──────────────────────────────────────────────────────────────────────────────


def test_candidate_quality_sort_key_delegates_to_match() -> None:
    """Candidate.quality_sort_key must equal the wrapped TrackMatch's key."""
    m = _flac_match()
    cand = Candidate(
        match=m,
        match_result=MatchResult(is_match=True, confidence=1.0, rule_fired="isrc_equality"),
    )
    assert cand.quality_sort_key == m.quality_sort_key()


# ──────────────────────────────────────────────────────────────────────────────
# ProvenanceRecord
# ──────────────────────────────────────────────────────────────────────────────


def test_provenance_record_construction() -> None:
    """ProvenanceRecord holds the picked URL + descending-quality URL list."""
    rec = ProvenanceRecord(
        picked_url="https://www.qobuz.com/track/1",
        all_urls=["https://www.qobuz.com/track/1", "https://soundcloud.com/x/y"],
        isrc="USUM71304455",
        picked_quality_tier=QualityTier.HIRES_LOSSLESS,
        picked_platform="qobuz",
    )
    assert rec.all_urls[0] == rec.picked_url


# ──────────────────────────────────────────────────────────────────────────────
# Resolve / Search / Fetch request+response models
# ──────────────────────────────────────────────────────────────────────────────


def test_resolve_request_defaults_enabled_platforms_none() -> None:
    """ResolveRequest leaves enabled_platforms None when omitted."""
    req = ResolveRequest(identifier="Avicii - Wake Me Up")
    assert req.enabled_platforms is None


def test_resolve_response_near_misses_defaults_empty() -> None:
    """ResolveResponse.near_misses defaults to an empty list."""
    resp = ResolveResponse(
        request_id="r1",
        needle=_flac_match(),
        candidates=[],
        auto_pick_index=None,
    )
    assert resp.near_misses == []
    assert resp.auto_pick_index is None


def test_search_models_construct() -> None:
    """SearchRequest / SearchHit / SearchResponse construct with valid data."""
    req = SearchRequest(query="Avicii - Wake Me Up")
    assert req.enabled_platforms is None
    hit = SearchHit(
        cluster_id="USUM71304455",
        representative=_flac_match(),
        cross_platform_urls={"qobuz": "https://www.qobuz.com/track/1"},
    )
    resp = SearchResponse(request_id="s1", hits=[hit])
    assert resp.hits[0].cluster_id == "USUM71304455"


def test_search_hit_rejects_unknown_platform_key() -> None:
    """cross_platform_urls keys are validated against the Platform Literal."""
    with pytest.raises(ValidationError):
        SearchHit(
            cluster_id="c1",
            representative=_flac_match(),
            cross_platform_urls={"bandcamp": "https://example.com"},  # type: ignore[dict-item]
        )


def test_fetch_models_construct() -> None:
    """FetchRequest / FetchResponse construct with valid data."""
    req = FetchRequest(request_id="r1", candidate_index=0)
    assert req.candidate_index == 0
    resp = FetchResponse(job_id="j-1", started_at="2026-05-21T10:00:00Z")
    assert resp.job_id == "j-1"


# ──────────────────────────────────────────────────────────────────────────────
# JobStatus
# ──────────────────────────────────────────────────────────────────────────────


def test_jobstatus_progress_bounds() -> None:
    """progress_pct must lie within [0, 100]."""
    JobStatus(job_id="j", state="queued", progress_pct=0)
    JobStatus(job_id="j", state="done", progress_pct=100)
    with pytest.raises(ValidationError):
        JobStatus(job_id="j", state="downloading", progress_pct=101)
    with pytest.raises(ValidationError):
        JobStatus(job_id="j", state="downloading", progress_pct=-1)


def test_jobstatus_rejects_unknown_state() -> None:
    """A state outside the Literal set is rejected."""
    with pytest.raises(ValidationError):
        JobStatus(job_id="j", state="paused", progress_pct=50)  # type: ignore[arg-type]


# ──────────────────────────────────────────────────────────────────────────────
# SourceProvider ABC
# ──────────────────────────────────────────────────────────────────────────────


def test_source_provider_is_abstract() -> None:
    """SourceProvider cannot be instantiated directly — it is an ABC."""
    with pytest.raises(TypeError):
        SourceProvider()  # type: ignore[abstract]


def test_source_provider_partial_impl_still_abstract() -> None:
    """A subclass missing an abstract method is still not instantiable."""

    class HalfProvider(SourceProvider):
        @property
        def platform(self) -> Platform:
            return "soundcloud"

        # resolve_url / search / fetch deliberately not implemented.

    with pytest.raises(TypeError):
        HalfProvider()  # type: ignore[abstract]


def test_source_provider_complete_impl_instantiable() -> None:
    """A subclass implementing all four abstract members instantiates + works."""

    class FullProvider(SourceProvider):
        @property
        def platform(self) -> Platform:
            return "soundcloud"

        async def resolve_url(self, url: str) -> list[TrackMatch]:
            return []

        async def search(self, query: str, limit: int = 5) -> list[TrackMatch]:
            return []

        async def fetch(self, match: TrackMatch, dest_dir: Path) -> Path:
            return dest_dir / "out.flac"

    provider = FullProvider()
    assert provider.platform == "soundcloud"


# Keep the imported type aliases referenced so linters don't flag dead imports;
# they are part of the module's public surface under test.
def test_literal_aliases_are_importable() -> None:
    """Platform / AudioFormat literal aliases are importable from the module."""
    assert Platform is not None
    assert AudioFormat is not None
