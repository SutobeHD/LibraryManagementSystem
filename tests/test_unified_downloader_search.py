"""Tests for ``app/downloader/search.py`` — the Phase-3 search layer (P3.12).

Every provider is a mock — a :class:`_FakeProvider` whose ``search()`` returns
canned :class:`TrackMatch` claims. No test touches the network.

Coverage:

* parallel fan-out of ``search()`` across enabled providers + the
  concurrency-semaphore cap,
* ISRC clustering — same-ISRC claims from different platforms collapse into
  one :class:`SearchHit`,
* fallback identity clustering (no ISRC) via the title/artist/duration hash,
* representative selection (lossless-first) + ``cross_platform_urls`` build,
* hit ordering by representative quality,
* dead-provider isolation.

See ``docs/research/implement/accepted_downloader-unified-multi-source.md``
§ "P3.12".
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.downloader import search as search_mod
from app.downloader.models import (
    Platform,
    QualityTier,
    SearchRequest,
    TrackMatch,
)

# ──────────────────────────────────────────────────────────────────────────────
# Test helpers — canned claims + a mock SourceProvider
# ──────────────────────────────────────────────────────────────────────────────


def _claim(
    platform: Platform,
    *,
    title: str = "Wake Me Up",
    artist: str = "Avicii",
    duration_s: float = 247.0,
    isrc: str | None = None,
    fmt: str = "flac",
    bit_depth: int | None = 16,
    sample_rate: int | None = 44100,
    bitrate: int | None = None,
    tier: QualityTier = QualityTier.CD_LOSSLESS,
    url: str | None = None,
) -> TrackMatch:
    """Build a :class:`TrackMatch` claim with sensible defaults."""
    return TrackMatch(
        platform=platform,
        url=url if url is not None else f"https://{platform}/track/x",
        title=title,
        artist=artist,
        duration_s=duration_s,
        isrc=isrc,
        claimed_format=fmt,  # type: ignore[arg-type]
        claimed_bit_depth=bit_depth,
        claimed_sample_rate_hz=sample_rate,
        claimed_bitrate_kbps=bitrate,
        quality_tier=tier,
    )


class _FakeProvider:
    """A mock :class:`~app.downloader.SourceProvider` for the search layer."""

    def __init__(
        self,
        platform: Platform,
        search_result: list[TrackMatch] | None = None,
        *,
        raises: Exception | None = None,
        delay_s: float = 0.0,
    ) -> None:
        self._platform = platform
        self._search_result = search_result or []
        self._raises = raises
        self._delay_s = delay_s
        self.search_calls: list[tuple[str, int]] = []

    @property
    def platform(self) -> Platform:
        return self._platform

    async def resolve_url(self, url: str) -> list[TrackMatch]:
        return []

    async def search(self, query: str, limit: int = 5) -> list[TrackMatch]:
        self.search_calls.append((query, limit))
        if self._delay_s:
            await asyncio.sleep(self._delay_s)
        if self._raises is not None:
            raise self._raises
        return list(self._search_result)


def _install_providers(
    monkeypatch: pytest.MonkeyPatch,
    mapping: dict[str, _FakeProvider],
) -> None:
    """Patch the resolver registry (search reuses it) with mock instances."""
    from app.downloader import resolver as res_mod

    factory_map: dict[str, Any] = {plat: (lambda p=prov: p) for plat, prov in mapping.items()}
    monkeypatch.setattr(res_mod, "_PLATFORM_PROVIDERS", factory_map)


# ──────────────────────────────────────────────────────────────────────────────
# Clustering identity helpers
# ──────────────────────────────────────────────────────────────────────────────


def test_cluster_key_uses_isrc_when_present() -> None:
    """A claim with an ISRC clusters on the upper-cased ISRC."""
    key = search_mod._cluster_key(_claim("soundcloud", isrc="usum71304455"))
    assert key == "USUM71304455"


def test_cluster_key_hash_fallback_without_isrc() -> None:
    """Without an ISRC the key is a stable title/artist/duration hash."""
    key = search_mod._cluster_key(_claim("soundcloud", isrc=None))
    assert key.startswith("tad:")


def test_cluster_key_duration_bucket_tolerates_drift() -> None:
    """Sub-bucket duration drift hashes into the same cluster key."""
    a = search_mod._cluster_key(_claim("soundcloud", isrc=None, duration_s=247.1))
    b = search_mod._cluster_key(_claim("tidal", isrc=None, duration_s=247.9))
    assert a == b  # both round to the same 2 s bucket


def test_cluster_key_distinct_titles_differ() -> None:
    """Different titles hash to different cluster keys."""
    a = search_mod._cluster_key(_claim("soundcloud", isrc=None, title="Song A"))
    b = search_mod._cluster_key(_claim("soundcloud", isrc=None, title="Song B"))
    assert a != b


# ──────────────────────────────────────────────────────────────────────────────
# Search — fan-out
# ──────────────────────────────────────────────────────────────────────────────


def test_search_fans_out_to_all_enabled_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every enabled provider's search() is called once with the query."""
    sc = _FakeProvider("soundcloud", [_claim("soundcloud", isrc="A0000000001")])
    tidal = _FakeProvider("tidal", [_claim("tidal", isrc="B0000000002")])
    _install_providers(monkeypatch, {"soundcloud": sc, "tidal": tidal})

    asyncio.run(
        search_mod.search(
            SearchRequest(query="avicii wake me up", enabled_platforms=["soundcloud", "tidal"])
        )
    )
    assert sc.search_calls == [("avicii wake me up", search_mod._PER_PLATFORM_LIMIT)]
    assert tidal.search_calls == [("avicii wake me up", search_mod._PER_PLATFORM_LIMIT)]


def test_search_empty_when_no_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Zero registered providers → an empty hit list, no raise."""
    _install_providers(monkeypatch, {})
    resp = asyncio.run(
        search_mod.search(SearchRequest(query="anything", enabled_platforms=["soundcloud"]))
    )
    assert resp.hits == []
    assert resp.request_id


def test_search_dead_provider_does_not_abort(monkeypatch: pytest.MonkeyPatch) -> None:
    """A provider raising in search() must not abort the whole fan-out."""
    sc = _FakeProvider("soundcloud", [_claim("soundcloud", isrc="LIVE00000001")])
    dead = _FakeProvider("tidal", raises=RuntimeError("search backend down"))
    _install_providers(monkeypatch, {"soundcloud": sc, "tidal": dead})

    resp = asyncio.run(
        search_mod.search(SearchRequest(query="q", enabled_platforms=["soundcloud", "tidal"]))
    )
    assert len(resp.hits) == 1
    assert resp.hits[0].representative.platform == "soundcloud"


# ──────────────────────────────────────────────────────────────────────────────
# Search — ISRC clustering + dedupe
# ──────────────────────────────────────────────────────────────────────────────


def test_search_clusters_same_isrc_across_platforms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two platforms returning the same ISRC collapse into one SearchHit."""
    sc_hit = _claim(
        "soundcloud",
        isrc="USUM71304455",
        tier=QualityTier.HIGH_LOSSY,
        fmt="aac",
        bit_depth=None,
        sample_rate=48000,
        bitrate=256,
        url="https://soundcloud.com/avicii/wake",
    )
    tidal_hit = _claim(
        "tidal",
        isrc="USUM71304455",
        tier=QualityTier.HIRES_LOSSLESS,
        fmt="flac",
        bit_depth=24,
        sample_rate=96000,
        url="https://tidal.com/track/999",
    )
    sc = _FakeProvider("soundcloud", [sc_hit])
    tidal = _FakeProvider("tidal", [tidal_hit])
    _install_providers(monkeypatch, {"soundcloud": sc, "tidal": tidal})

    resp = asyncio.run(
        search_mod.search(
            SearchRequest(query="wake me up", enabled_platforms=["soundcloud", "tidal"])
        )
    )
    assert len(resp.hits) == 1
    hit = resp.hits[0]
    assert hit.cluster_id == "USUM71304455"
    # cross_platform_urls carries one URL per platform in the cluster.
    assert hit.cross_platform_urls == {
        "soundcloud": "https://soundcloud.com/avicii/wake",
        "tidal": "https://tidal.com/track/999",
    }


def test_search_representative_is_best_quality(monkeypatch: pytest.MonkeyPatch) -> None:
    """Within an ISRC cluster the representative is the lossless claim."""
    lossy = _claim(
        "soundcloud",
        isrc="REPISRC00001",
        tier=QualityTier.HIGH_LOSSY,
        fmt="aac",
        bit_depth=None,
        sample_rate=48000,
        bitrate=256,
    )
    lossless = _claim(
        "qobuz",
        isrc="REPISRC00001",
        tier=QualityTier.CD_LOSSLESS,
        fmt="flac",
        bit_depth=16,
        sample_rate=44100,
    )
    sc = _FakeProvider("soundcloud", [lossy])
    qobuz = _FakeProvider("qobuz", [lossless])
    _install_providers(monkeypatch, {"soundcloud": sc, "qobuz": qobuz})

    resp = asyncio.run(
        search_mod.search(SearchRequest(query="q", enabled_platforms=["soundcloud", "qobuz"]))
    )
    assert len(resp.hits) == 1
    assert resp.hits[0].representative.platform == "qobuz"  # lossless wins


def test_search_distinct_isrcs_stay_separate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two different ISRCs produce two separate hits."""
    a = _claim("soundcloud", isrc="ISRCAAAAAAA1", title="Track One")
    b = _claim("soundcloud", isrc="ISRCBBBBBBB2", title="Track Two")
    sc = _FakeProvider("soundcloud", [a, b])
    _install_providers(monkeypatch, {"soundcloud": sc})

    resp = asyncio.run(
        search_mod.search(SearchRequest(query="q", enabled_platforms=["soundcloud"]))
    )
    assert len(resp.hits) == 2
    assert {h.cluster_id for h in resp.hits} == {"ISRCAAAAAAA1", "ISRCBBBBBBB2"}


def test_search_no_isrc_dedupes_by_title_artist_duration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without ISRCs, identical title/artist/duration claims still cluster."""
    sc_hit = _claim(
        "soundcloud",
        isrc=None,
        title="Strobe",
        artist="deadmau5",
        duration_s=636.0,
        tier=QualityTier.HIGH_LOSSY,
        fmt="aac",
        bit_depth=None,
        bitrate=256,
        url="https://soundcloud.com/deadmau5/strobe",
    )
    tidal_hit = _claim(
        "tidal",
        isrc=None,
        title="Strobe",
        artist="deadmau5",
        duration_s=636.4,
        tier=QualityTier.HIRES_LOSSLESS,
        fmt="flac",
        bit_depth=24,
        sample_rate=96000,
        url="https://tidal.com/track/strobe",
    )
    sc = _FakeProvider("soundcloud", [sc_hit])
    tidal = _FakeProvider("tidal", [tidal_hit])
    _install_providers(monkeypatch, {"soundcloud": sc, "tidal": tidal})

    resp = asyncio.run(
        search_mod.search(SearchRequest(query="strobe", enabled_platforms=["soundcloud", "tidal"]))
    )
    # Both claims hash to the same title/artist/duration-bucket cluster.
    assert len(resp.hits) == 1
    assert set(resp.hits[0].cross_platform_urls) == {"soundcloud", "tidal"}


def test_search_cross_platform_urls_skips_empty_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A clustered claim with an empty URL is omitted from cross_platform_urls."""
    with_url = _claim("tidal", isrc="EMPTYURL0001", url="https://tidal.com/t/1")
    no_url = _claim("soundcloud", isrc="EMPTYURL0001", url="")
    sc = _FakeProvider("soundcloud", [no_url])
    tidal = _FakeProvider("tidal", [with_url])
    _install_providers(monkeypatch, {"soundcloud": sc, "tidal": tidal})

    resp = asyncio.run(
        search_mod.search(SearchRequest(query="q", enabled_platforms=["soundcloud", "tidal"]))
    )
    assert len(resp.hits) == 1
    assert resp.hits[0].cross_platform_urls == {"tidal": "https://tidal.com/t/1"}


def test_search_same_platform_in_cluster_keeps_best(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When one platform appears twice in a cluster, the best-quality URL wins."""
    cd = _claim(
        "tidal",
        isrc="DUPEPLAT0001",
        tier=QualityTier.CD_LOSSLESS,
        fmt="flac",
        bit_depth=16,
        sample_rate=44100,
        url="https://tidal.com/cd",
    )
    hires = _claim(
        "tidal",
        isrc="DUPEPLAT0001",
        tier=QualityTier.HIRES_LOSSLESS,
        fmt="flac",
        bit_depth=24,
        sample_rate=96000,
        url="https://tidal.com/hires",
    )
    tidal = _FakeProvider("tidal", [cd, hires])
    _install_providers(monkeypatch, {"tidal": tidal})

    resp = asyncio.run(search_mod.search(SearchRequest(query="q", enabled_platforms=["tidal"])))
    assert len(resp.hits) == 1
    assert resp.hits[0].cross_platform_urls == {"tidal": "https://tidal.com/hires"}


# ──────────────────────────────────────────────────────────────────────────────
# Search — hit ordering
# ──────────────────────────────────────────────────────────────────────────────


def test_search_hits_sorted_by_representative_quality(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The hit list is ordered best-representative-first (lossless before lossy)."""
    lossy_hit = _claim(
        "soundcloud",
        isrc="LOSSY0000001",
        title="Lossy Track",
        tier=QualityTier.HIGH_LOSSY,
        fmt="aac",
        bit_depth=None,
        bitrate=256,
    )
    hires_hit = _claim(
        "tidal",
        isrc="HIRES0000001",
        title="HiRes Track",
        tier=QualityTier.HIRES_LOSSLESS,
        fmt="flac",
        bit_depth=24,
        sample_rate=96000,
    )
    sc = _FakeProvider("soundcloud", [lossy_hit])
    tidal = _FakeProvider("tidal", [hires_hit])
    _install_providers(monkeypatch, {"soundcloud": sc, "tidal": tidal})

    resp = asyncio.run(
        search_mod.search(SearchRequest(query="q", enabled_platforms=["soundcloud", "tidal"]))
    )
    assert len(resp.hits) == 2
    assert resp.hits[0].representative.platform == "tidal"  # hi-res first
    assert resp.hits[1].representative.platform == "soundcloud"  # lossy last


def test_search_retiers_claims_before_ranking(monkeypatch: pytest.MonkeyPatch) -> None:
    """A provider's stale quality_tier is recomputed via classify() before ranking.

    The claim arrives mislabelled LAST_RESORT but is genuinely a 24/96 FLAC —
    after re-tiering it must rank as hi-res lossless, ahead of a real lossy hit.
    """
    mislabelled = _claim(
        "tidal",
        isrc="MISTIER00001",
        title="Mislabelled",
        fmt="flac",
        bit_depth=24,
        sample_rate=96000,
        tier=QualityTier.LAST_RESORT,  # wrong on purpose
    )
    honest_lossy = _claim(
        "soundcloud",
        isrc="HONEST000001",
        title="Honest Lossy",
        fmt="mp3",
        bit_depth=None,
        bitrate=320,
        tier=QualityTier.HIGH_LOSSY,
    )
    sc = _FakeProvider("soundcloud", [honest_lossy])
    tidal = _FakeProvider("tidal", [mislabelled])
    _install_providers(monkeypatch, {"soundcloud": sc, "tidal": tidal})

    resp = asyncio.run(
        search_mod.search(SearchRequest(query="q", enabled_platforms=["soundcloud", "tidal"]))
    )
    assert resp.hits[0].representative.platform == "tidal"
    assert resp.hits[0].representative.quality_tier == QualityTier.HIRES_LOSSLESS


# ──────────────────────────────────────────────────────────────────────────────
# Search — concurrency
# ──────────────────────────────────────────────────────────────────────────────


def test_search_semaphore_bounds_concurrency(monkeypatch: pytest.MonkeyPatch) -> None:
    """The search fan-out never exceeds the concurrency budget."""
    monkeypatch.setattr(search_mod, "_max_concurrency", lambda: 2)

    in_flight = 0
    peak = 0

    class _CountingProvider(_FakeProvider):
        async def search(self, query: str, limit: int = 5) -> list[TrackMatch]:
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            await asyncio.sleep(0.02)
            in_flight -= 1
            return [_claim(self._platform, isrc=f"C{self._platform[:10]:0>11}")]

    providers = {
        p: _CountingProvider(p)  # type: ignore[misc]
        for p in ("soundcloud", "tidal", "qobuz", "amazon", "deezer")
    }
    _install_providers(monkeypatch, providers)

    asyncio.run(
        search_mod.search(
            SearchRequest(
                query="q",
                enabled_platforms=["soundcloud", "tidal", "qobuz", "amazon", "deezer"],
            )
        )
    )
    assert peak <= 2
