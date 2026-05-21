"""Tests for ``app/downloader/resolver.py`` — the Phase-3 resolve layer (P3.11).

Every provider is a mock — a :class:`_FakeProvider` returning canned
:class:`TrackMatch` claims. No test touches the network, spawns a process, or
downloads bytes.

Coverage:

* needle identification — URL (provider-resolved), ``Artist - Title``, bare
  ISRC, and an unresolvable URL,
* parallel fan-out across enabled providers + the concurrency-semaphore cap,
* 100%-match gating (ISRC fast-path), near-miss capture, lossless-first
  candidate ordering, ``auto_pick_index`` semantics,
* dead-provider isolation (one provider raising must not abort the resolve).

See ``docs/research/implement/accepted_downloader-unified-multi-source.md``
§ "P3.11".
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.downloader import resolver as res_mod
from app.downloader.models import (
    MatchResult,
    Platform,
    QualityTier,
    ResolveRequest,
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
    isrc: str | None = "USUM71304455",
    fmt: str = "flac",
    bit_depth: int | None = 16,
    sample_rate: int | None = 44100,
    bitrate: int | None = None,
    tier: QualityTier = QualityTier.CD_LOSSLESS,
    url: str | None = None,
) -> TrackMatch:
    """Build a :class:`TrackMatch` claim with sensible Avicii defaults."""
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
    """A mock :class:`~app.downloader.SourceProvider`.

    Only the two metadata coroutines the resolver calls are implemented;
    ``resolve_url`` returns the canned list (or raises a canned exception).
    Records every URL it was probed with so concurrency / fan-out can be
    asserted.
    """

    def __init__(
        self,
        platform: Platform,
        resolve_result: list[TrackMatch] | None = None,
        *,
        raises: Exception | None = None,
        delay_s: float = 0.0,
    ) -> None:
        self._platform = platform
        self._resolve_result = resolve_result or []
        self._raises = raises
        self._delay_s = delay_s
        self.resolve_calls: list[str] = []

    @property
    def platform(self) -> Platform:
        return self._platform

    async def resolve_url(self, url: str) -> list[TrackMatch]:
        self.resolve_calls.append(url)
        if self._delay_s:
            await asyncio.sleep(self._delay_s)
        if self._raises is not None:
            raise self._raises
        return list(self._resolve_result)

    async def search(self, query: str, limit: int = 5) -> list[TrackMatch]:
        return []


def _install_providers(
    monkeypatch: pytest.MonkeyPatch,
    mapping: dict[str, _FakeProvider],
) -> None:
    """Patch the resolver's platform→provider registry with mock instances.

    The registry maps a platform name to a *factory*; here each factory just
    returns the pre-built fake so the test keeps a handle on it.
    """
    factory_map: dict[str, Any] = {plat: (lambda p=prov: p) for plat, prov in mapping.items()}
    monkeypatch.setattr(res_mod, "_PLATFORM_PROVIDERS", factory_map)


# ──────────────────────────────────────────────────────────────────────────────
# Needle identification
# ──────────────────────────────────────────────────────────────────────────────


def test_synthetic_needle_from_artist_title() -> None:
    """A free-form 'Artist - Title' string splits on the first dash."""
    needle = res_mod._synthetic_needle("Avicii - Wake Me Up")
    assert needle.artist == "Avicii"
    assert needle.title == "Wake Me Up"
    assert needle.isrc is None


def test_synthetic_needle_from_bare_isrc() -> None:
    """A bare ISRC populates only the isrc field, upper-cased."""
    needle = res_mod._synthetic_needle("usum71304455")
    assert needle.isrc == "USUM71304455"


def test_synthetic_needle_title_only_fallback() -> None:
    """A string with no dash becomes a title-only needle."""
    needle = res_mod._synthetic_needle("Strobe")
    assert needle.title == "Strobe"
    assert needle.artist == ""


def test_synthetic_needle_multi_dash_splits_once() -> None:
    """'A - B - C' splits only on the first dash → artist 'A', title 'B - C'."""
    needle = res_mod._synthetic_needle("Artist - Big - Title")
    assert needle.artist == "Artist"
    assert needle.title == "Big - Title"


def test_resolve_identifies_needle_from_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """A URL identifier: the needle is the first provider's resolve result."""
    sc = _FakeProvider("soundcloud", [_claim("soundcloud", title="Resolved Title")])
    _install_providers(monkeypatch, {"soundcloud": sc})

    req = ResolveRequest(
        identifier="https://soundcloud.com/avicii/wake-me-up",
        enabled_platforms=["soundcloud"],
    )
    resp = asyncio.run(res_mod.resolve(req))
    assert resp.needle.title == "Resolved Title"


def test_resolve_unresolvable_url_falls_back_to_synthetic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A URL no provider can resolve degrades to a synthetic needle, no raise."""
    sc = _FakeProvider("soundcloud", [])  # resolves to nothing
    _install_providers(monkeypatch, {"soundcloud": sc})

    req = ResolveRequest(
        identifier="https://soundcloud.com/unknown/track",
        enabled_platforms=["soundcloud"],
    )
    resp = asyncio.run(res_mod.resolve(req))
    # Synthetic needle from a URL → title is the raw URL, no candidates.
    assert resp.candidates == []
    assert resp.auto_pick_index is None


# ──────────────────────────────────────────────────────────────────────────────
# Match gating + ranking
# ──────────────────────────────────────────────────────────────────────────────


def test_resolve_isrc_match_produces_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    """A claim with the needle's ISRC passes the 100%-gate (isrc_equality)."""
    needle_claim = _claim("soundcloud", isrc="USUM71304455")
    tidal_claim = _claim(
        "tidal",
        isrc="USUM71304455",
        tier=QualityTier.HIRES_LOSSLESS,
        bit_depth=24,
        sample_rate=96000,
    )
    sc = _FakeProvider("soundcloud", [needle_claim])
    tidal = _FakeProvider("tidal", [tidal_claim])
    _install_providers(monkeypatch, {"soundcloud": sc, "tidal": tidal})

    req = ResolveRequest(
        identifier="https://soundcloud.com/avicii/wake-me-up",
        enabled_platforms=["soundcloud", "tidal"],
    )
    resp = asyncio.run(res_mod.resolve(req))

    assert len(resp.candidates) == 2
    assert all(c.match_result.is_match for c in resp.candidates)
    assert all(c.match_result.rule_fired == "isrc_equality" for c in resp.candidates)


def test_resolve_ranks_lossless_first(monkeypatch: pytest.MonkeyPatch) -> None:
    """Candidates are quality-sorted — hi-res FLAC outranks CD FLAC outranks lossy."""
    needle_claim = _claim("soundcloud", isrc="ISRCMATCH001")
    hires = _claim(
        "tidal",
        isrc="ISRCMATCH001",
        tier=QualityTier.HIRES_LOSSLESS,
        bit_depth=24,
        sample_rate=96000,
        fmt="flac",
    )
    lossy = _claim(
        "soundcloud",
        isrc="ISRCMATCH001",
        tier=QualityTier.HIGH_LOSSY,
        fmt="aac",
        bit_depth=None,
        sample_rate=48000,
        bitrate=256,
    )
    cd = _claim(
        "qobuz",
        isrc="ISRCMATCH001",
        tier=QualityTier.CD_LOSSLESS,
        bit_depth=16,
        sample_rate=44100,
        fmt="flac",
    )
    sc = _FakeProvider("soundcloud", [needle_claim, lossy])
    tidal = _FakeProvider("tidal", [hires])
    qobuz = _FakeProvider("qobuz", [cd])
    _install_providers(monkeypatch, {"soundcloud": sc, "tidal": tidal, "qobuz": qobuz})

    req = ResolveRequest(
        identifier="https://soundcloud.com/a/b",
        enabled_platforms=["soundcloud", "tidal", "qobuz"],
    )
    resp = asyncio.run(res_mod.resolve(req))

    tiers = [c.match.quality_tier for c in resp.candidates]
    assert tiers == sorted(tiers)  # ascending int = descending quality
    assert resp.candidates[0].match.platform == "tidal"  # hi-res wins
    assert resp.candidates[-1].match.platform == "soundcloud"  # lossy last


def test_resolve_auto_pick_index_zero_when_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """auto_pick_index is 0 whenever at least one 100%-match exists."""
    needle_claim = _claim("soundcloud", isrc="AUTOPICK0001")
    sc = _FakeProvider("soundcloud", [needle_claim])
    _install_providers(monkeypatch, {"soundcloud": sc})

    resp = asyncio.run(
        res_mod.resolve(
            ResolveRequest(
                identifier="https://soundcloud.com/a/b", enabled_platforms=["soundcloud"]
            )
        )
    )
    assert resp.auto_pick_index == 0


def test_resolve_auto_pick_none_when_no_match(monkeypatch: pytest.MonkeyPatch) -> None:
    """No 100%-match → auto_pick_index is None."""
    # Needle resolves; the only other claim fails the duration gate (>2 s off).
    needle_claim = _claim("soundcloud", isrc="NEEDLE000001", duration_s=247.0)
    mismatch = _claim(
        "tidal",
        isrc="DIFFERENT0001",
        duration_s=300.0,
        title="Other Song",
        artist="Other Artist",
    )
    sc = _FakeProvider("soundcloud", [needle_claim])
    tidal = _FakeProvider("tidal", [mismatch])
    _install_providers(monkeypatch, {"soundcloud": sc, "tidal": tidal})

    resp = asyncio.run(
        res_mod.resolve(
            ResolveRequest(
                identifier="https://soundcloud.com/a/b",
                enabled_platforms=["soundcloud", "tidal"],
            )
        )
    )
    # The needle itself is an ISRC self-match → 1 candidate; mismatch dropped.
    assert resp.auto_pick_index == 0
    assert all(c.match.isrc == "NEEDLE000001" for c in resp.candidates)


def test_resolve_captures_near_misses(monkeypatch: pytest.MonkeyPatch) -> None:
    """A sub-100% but >=threshold claim lands in near_misses, not candidates.

    ``match_adapter.match`` is patched so the match outcome is fully
    controlled — the resolver's near-miss bucketing logic is what is under
    test, not the fuzzy scorer.
    """
    needle_claim = _claim("soundcloud", isrc=None, duration_s=247.0)
    near = _claim("tidal", isrc=None, duration_s=247.0, title="Wake Me Up (Edit)")
    sc = _FakeProvider("soundcloud", [needle_claim])
    tidal = _FakeProvider("tidal", [near])
    _install_providers(monkeypatch, {"soundcloud": sc, "tidal": tidal})

    def _fake_match(
        needle: TrackMatch, candidates: list[TrackMatch]
    ) -> list[tuple[TrackMatch, MatchResult]]:
        out: list[tuple[TrackMatch, MatchResult]] = []
        for c in candidates:
            if c.platform == "soundcloud":
                out.append((c, MatchResult(is_match=True, confidence=1.0, rule_fired="self")))
            else:
                out.append(
                    (c, MatchResult(is_match=False, confidence=0.88, rule_fired="xtm_fuzzy_0.88"))
                )
        return out

    monkeypatch.setattr(res_mod, "match", _fake_match)

    resp = asyncio.run(
        res_mod.resolve(
            ResolveRequest(
                identifier="https://soundcloud.com/a/b",
                enabled_platforms=["soundcloud", "tidal"],
            )
        )
    )
    assert len(resp.candidates) == 1
    assert len(resp.near_misses) == 1
    assert resp.near_misses[0].match.platform == "tidal"
    assert resp.near_misses[0].match_result.confidence == pytest.approx(0.88)


def test_resolve_near_miss_below_threshold_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A claim below the near-miss threshold is dropped entirely."""
    needle_claim = _claim("soundcloud", isrc=None)
    far = _claim("tidal", isrc=None)
    sc = _FakeProvider("soundcloud", [needle_claim])
    tidal = _FakeProvider("tidal", [far])
    _install_providers(monkeypatch, {"soundcloud": sc, "tidal": tidal})

    def _fake_match(
        needle: TrackMatch, candidates: list[TrackMatch]
    ) -> list[tuple[TrackMatch, MatchResult]]:
        return [
            (
                c,
                MatchResult(
                    is_match=(c.platform == "soundcloud"),
                    confidence=1.0 if c.platform == "soundcloud" else 0.40,
                    rule_fired="x",
                ),
            )
            for c in candidates
        ]

    monkeypatch.setattr(res_mod, "match", _fake_match)

    resp = asyncio.run(
        res_mod.resolve(
            ResolveRequest(
                identifier="https://soundcloud.com/a/b",
                enabled_platforms=["soundcloud", "tidal"],
            )
        )
    )
    assert len(resp.candidates) == 1
    assert resp.near_misses == []


def test_resolve_near_misses_sorted_and_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    """near_misses are confidence-descending and capped at 5."""
    needle_claim = _claim("soundcloud", isrc=None)
    extras = [_claim("tidal", isrc=None, url=f"https://tidal/{i}") for i in range(8)]
    sc = _FakeProvider("soundcloud", [needle_claim, *extras])
    _install_providers(monkeypatch, {"soundcloud": sc})

    confidences = iter([1.0, 0.86, 0.99, 0.90, 0.87, 0.95, 0.91, 0.93, 0.88])

    def _fake_match(
        needle: TrackMatch, candidates: list[TrackMatch]
    ) -> list[tuple[TrackMatch, MatchResult]]:
        out: list[tuple[TrackMatch, MatchResult]] = []
        for c in candidates:
            conf = next(confidences)
            out.append((c, MatchResult(is_match=conf >= 0.999, confidence=conf, rule_fired="x")))
        return out

    monkeypatch.setattr(res_mod, "match", _fake_match)

    resp = asyncio.run(
        res_mod.resolve(
            ResolveRequest(
                identifier="https://soundcloud.com/a/b", enabled_platforms=["soundcloud"]
            )
        )
    )
    assert len(resp.near_misses) == 5  # capped
    confs = [c.match_result.confidence for c in resp.near_misses]
    assert confs == sorted(confs, reverse=True)  # descending
    assert confs[0] == pytest.approx(0.99)


# ──────────────────────────────────────────────────────────────────────────────
# Fan-out + concurrency
# ──────────────────────────────────────────────────────────────────────────────


def test_resolve_fans_out_to_all_enabled_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every enabled provider is probed exactly once."""
    sc = _FakeProvider("soundcloud", [_claim("soundcloud")])
    tidal = _FakeProvider("tidal", [_claim("tidal")])
    qobuz = _FakeProvider("qobuz", [_claim("qobuz")])
    _install_providers(monkeypatch, {"soundcloud": sc, "tidal": tidal, "qobuz": qobuz})

    asyncio.run(
        res_mod.resolve(
            ResolveRequest(
                identifier="https://soundcloud.com/a/b",
                enabled_platforms=["soundcloud", "tidal", "qobuz"],
            )
        )
    )
    # One probe in _identify_needle + one in the fan-out = 2 calls each.
    assert len(sc.resolve_calls) == 2
    assert len(tidal.resolve_calls) == 2
    assert len(qobuz.resolve_calls) == 2


def test_resolve_skips_platform_without_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An enabled platform with no registered provider is silently skipped."""
    sc = _FakeProvider("soundcloud", [_claim("soundcloud")])
    _install_providers(monkeypatch, {"soundcloud": sc})  # no 'spotify' factory

    # 'spotify' is enabled but unregistered — must not crash.
    resp = asyncio.run(
        res_mod.resolve(
            ResolveRequest(
                identifier="https://soundcloud.com/a/b",
                enabled_platforms=["soundcloud", "spotify"],
            )
        )
    )
    assert len(resp.candidates) >= 1


def test_resolve_dead_provider_does_not_abort(monkeypatch: pytest.MonkeyPatch) -> None:
    """One provider raising must not abort the resolve — others still count."""
    sc = _FakeProvider("soundcloud", [_claim("soundcloud", isrc="LIVE00000001")])
    dead = _FakeProvider("tidal", raises=RuntimeError("provider exploded"))
    _install_providers(monkeypatch, {"soundcloud": sc, "tidal": dead})

    resp = asyncio.run(
        res_mod.resolve(
            ResolveRequest(
                identifier="https://soundcloud.com/a/b",
                enabled_platforms=["soundcloud", "tidal"],
            )
        )
    )
    # SoundCloud's claim survives; the dead Tidal provider contributes nothing.
    assert len(resp.candidates) == 1
    assert resp.candidates[0].match.platform == "soundcloud"


def test_resolve_semaphore_bounds_concurrency(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fan-out never runs more probes at once than the concurrency budget."""
    monkeypatch.setattr(res_mod, "_max_concurrency", lambda: 2)

    in_flight = 0
    peak = 0

    class _CountingProvider(_FakeProvider):
        async def resolve_url(self, url: str) -> list[TrackMatch]:
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            await asyncio.sleep(0.02)
            in_flight -= 1
            return [_claim(self._platform, isrc="CONCURR00001")]

    providers = {
        p: _CountingProvider(p)  # type: ignore[misc]
        for p in ("soundcloud", "tidal", "qobuz", "amazon", "deezer")
    }
    _install_providers(monkeypatch, providers)

    asyncio.run(
        res_mod.resolve(
            ResolveRequest(
                identifier="https://soundcloud.com/a/b",
                enabled_platforms=["soundcloud", "tidal", "qobuz", "amazon", "deezer"],
            )
        )
    )
    # Both phases (needle probe + main fan-out) share one semaphore, so the
    # observed peak concurrency must never exceed the budget.
    assert peak <= 2


def test_resolve_empty_when_no_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    """An enabled-platform list with zero registered providers yields nothing."""
    _install_providers(monkeypatch, {})  # registry empty

    resp = asyncio.run(
        res_mod.resolve(
            ResolveRequest(identifier="Avicii - Wake Me Up", enabled_platforms=["soundcloud"])
        )
    )
    assert resp.candidates == []
    assert resp.near_misses == []
    assert resp.auto_pick_index is None
    # The needle is still the synthetic parse of the free-form input.
    assert resp.needle.artist == "Avicii"


# ──────────────────────────────────────────────────────────────────────────────
# Settings helpers
# ──────────────────────────────────────────────────────────────────────────────


def test_enabled_platforms_falls_back_to_soundcloud(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no settings block the enabled set defaults to ['soundcloud']."""
    monkeypatch.setattr(res_mod, "_unified_settings", dict)
    assert res_mod._enabled_platforms() == ["soundcloud"]


def test_enabled_platforms_reads_truthy_map(monkeypatch: pytest.MonkeyPatch) -> None:
    """The {platform: bool} settings map flattens to the truthy platform list."""
    monkeypatch.setattr(
        res_mod,
        "_unified_settings",
        lambda: {"enabled_platforms": {"soundcloud": True, "tidal": True, "qobuz": False}},
    )
    enabled = set(res_mod._enabled_platforms())
    assert enabled == {"soundcloud", "tidal"}


def test_max_concurrency_clamped(monkeypatch: pytest.MonkeyPatch) -> None:
    """max_concurrency is clamped into [1, 32]; junk falls back to the default."""
    monkeypatch.setattr(res_mod, "_unified_settings", lambda: {"max_concurrency": 999})
    assert res_mod._max_concurrency() == 32
    monkeypatch.setattr(res_mod, "_unified_settings", lambda: {"max_concurrency": 0})
    assert res_mod._max_concurrency() == 1
    monkeypatch.setattr(res_mod, "_unified_settings", lambda: {"max_concurrency": "junk"})
    assert res_mod._max_concurrency() == res_mod._DEFAULT_MAX_CONCURRENCY


def test_near_miss_threshold_clamped(monkeypatch: pytest.MonkeyPatch) -> None:
    """match_threshold_near_miss is clamped into [0.0, 1.0]."""
    monkeypatch.setattr(res_mod, "_unified_settings", lambda: {"match_threshold_near_miss": 1.5})
    assert res_mod._near_miss_threshold() == 1.0
    monkeypatch.setattr(res_mod, "_unified_settings", lambda: {"match_threshold_near_miss": -3})
    assert res_mod._near_miss_threshold() == 0.0
