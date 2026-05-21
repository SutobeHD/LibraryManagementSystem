"""Tests for ``app/downloader/concurrency.py`` — first-run benchmark (D8).

Covers :func:`speedup_to_concurrency` threshold mapping, :func:`benchmark_concurrency`
with a mocked probe (no network), the divide-by-zero / probe-failure fallbacks,
and :func:`ensure_concurrency_benchmark`'s cache + force behaviour.

The network probe is injected via the :class:`~app.downloader.concurrency.Probe`
seam — every test passes a deterministic fake, so the suite never resolves a
real SoundCloud URL.

See ``docs/research/implement/accepted_downloader-unified-multi-source.md``
§ "P4.17" and "(D8) Concurrency auto-detection".
"""

from __future__ import annotations

import pytest

from app.downloader import concurrency

# ──────────────────────────────────────────────────────────────────────────────
# Fake probe — deterministic latency, no network
# ──────────────────────────────────────────────────────────────────────────────


class _FakeProbe:
    """A :class:`Probe` whose timing is driven by a fake monotonic clock.

    ``per_call`` is the synthetic latency every probe "takes". The benchmark's
    parallel batch advances the clock by one ``per_call`` (all calls overlap);
    the sequential batch advances it once per call. The resulting speedup is
    therefore exactly ``len(urls)`` — fully deterministic.
    """

    def __init__(self, per_call: float) -> None:
        self.per_call = per_call
        self.calls = 0

    def __call__(self, url: str) -> float:
        self.calls += 1
        return self.per_call


def _patch_clock(monkeypatch: pytest.MonkeyPatch, parallel_s: float, sequential_s: float):
    """Patch ``perf_counter`` so parallel and sequential batches get fixed wall-times.

    The benchmark calls ``perf_counter`` twice per batch (start, end), in order:
    pre-warm is a bare probe (no timing), then parallel (2 reads), then
    sequential (2 reads). We feed deltas so batch A measures ``parallel_s`` and
    batch B measures ``sequential_s``.
    """
    ticks = iter([0.0, parallel_s, parallel_s, parallel_s + sequential_s])
    monkeypatch.setattr(concurrency.time, "perf_counter", lambda: next(ticks))


# ──────────────────────────────────────────────────────────────────────────────
# speedup_to_concurrency — threshold table
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("speedup", "expected"),
    [
        (5.0, 8),  # > 3.0
        (3.01, 8),
        (3.0, 6),  # boundary — strictly greater required
        (2.5, 6),  # > 2.0
        (2.0, 4),  # boundary
        (1.8, 4),  # > 1.5
        (1.5, 2),  # boundary → floor
        (1.0, 2),  # network-bound
        (0.0, 2),
    ],
)
def test_speedup_to_concurrency_thresholds(speedup: float, expected: int) -> None:
    assert concurrency.speedup_to_concurrency(speedup) == expected


# ──────────────────────────────────────────────────────────────────────────────
# benchmark_concurrency — mocked probe
# ──────────────────────────────────────────────────────────────────────────────


def test_benchmark_high_speedup_yields_8(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_clock(monkeypatch, parallel_s=1.0, sequential_s=4.0)  # speedup 4.0
    result = concurrency.benchmark_concurrency(probe=_FakeProbe(0.1), urls=("u1", "u2", "u3", "u4"))
    assert result["max_concurrency"] == 8
    assert result["speedup"] == 4.0
    assert result["parallel_s"] == 1.0
    assert result["sequential_s"] == 4.0
    assert isinstance(result["benchmarked_at"], str) and result["benchmarked_at"]


def test_benchmark_medium_speedup_yields_6(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_clock(monkeypatch, parallel_s=1.0, sequential_s=2.5)  # speedup 2.5
    result = concurrency.benchmark_concurrency(probe=_FakeProbe(0.1), urls=("a", "b"))
    assert result["max_concurrency"] == 6


def test_benchmark_low_speedup_yields_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_clock(monkeypatch, parallel_s=1.0, sequential_s=1.2)  # speedup 1.2
    result = concurrency.benchmark_concurrency(probe=_FakeProbe(0.1), urls=("a", "b"))
    assert result["max_concurrency"] == 2


def test_benchmark_zero_parallel_time_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    # A degenerate ~0 s parallel batch must not divide-by-zero.
    _patch_clock(monkeypatch, parallel_s=0.0, sequential_s=2.0)
    result = concurrency.benchmark_concurrency(probe=_FakeProbe(0.0), urls=("a", "b"))
    assert result["max_concurrency"] == 4  # _FALLBACK_CONCURRENCY
    assert result["speedup"] == 0.0


def test_benchmark_probe_exception_falls_back() -> None:
    class _BoomProbe:
        def __call__(self, url: str) -> float:
            raise RuntimeError("probe exploded")

    result = concurrency.benchmark_concurrency(probe=_BoomProbe(), urls=("a", "b"))
    assert result["max_concurrency"] == 4  # _FALLBACK_CONCURRENCY


def test_benchmark_uses_all_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_clock(monkeypatch, parallel_s=1.0, sequential_s=4.0)
    probe = _FakeProbe(0.1)
    concurrency.benchmark_concurrency(probe=probe, urls=("a", "b", "c", "d"))
    # 1 pre-warm + 4 parallel + 4 sequential = 9 probe calls.
    assert probe.calls == 9


# ──────────────────────────────────────────────────────────────────────────────
# ensure_concurrency_benchmark — cache + force
# ──────────────────────────────────────────────────────────────────────────────


def test_ensure_benchmarks_when_no_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    # No cached value → benchmark runs, result is persisted.
    monkeypatch.setattr(
        concurrency,
        "benchmark_concurrency",
        lambda **_kw: {"max_concurrency": 8, "benchmarked_at": "2026-05-21T00:00:00+00:00"},
    )
    persisted: list[dict] = []
    value = concurrency.ensure_concurrency_benchmark(
        probe=_FakeProbe(0.1), persist=lambda r: persisted.append(r) or True
    )
    assert value == 8
    assert len(persisted) == 1


def test_ensure_uses_fresh_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import datetime, timezone

    import app.services as services

    fresh = datetime.now(timezone.utc).isoformat()
    # Patch the lazily-imported SettingsManager.load to report a fresh cache.
    monkeypatch.setattr(
        services.SettingsManager,
        "load",
        classmethod(
            lambda cls: {
                "unified_downloader": {"max_concurrency": 6, "concurrency_benchmarked_at": fresh}
            }
        ),
    )

    def _should_not_run(**_kw):
        raise AssertionError("benchmark must not run when cache is fresh")

    monkeypatch.setattr(concurrency, "benchmark_concurrency", _should_not_run)
    value = concurrency.ensure_concurrency_benchmark(probe=_FakeProbe(0.1))
    assert value == 6


def test_ensure_rebenchmarks_when_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services as services

    stale = "2020-01-01T00:00:00+00:00"  # far older than CACHE_TTL_DAYS
    monkeypatch.setattr(
        services.SettingsManager,
        "load",
        classmethod(
            lambda cls: {
                "unified_downloader": {"max_concurrency": 6, "concurrency_benchmarked_at": stale}
            }
        ),
    )
    monkeypatch.setattr(
        concurrency,
        "benchmark_concurrency",
        lambda **_kw: {"max_concurrency": 2, "benchmarked_at": "2026-05-21T00:00:00+00:00"},
    )
    value = concurrency.ensure_concurrency_benchmark(probe=_FakeProbe(0.1), persist=lambda _r: True)
    assert value == 2  # stale cache discarded, re-benchmarked


def test_ensure_force_ignores_fresh_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import datetime, timezone

    import app.services as services

    fresh = datetime.now(timezone.utc).isoformat()
    monkeypatch.setattr(
        services.SettingsManager,
        "load",
        classmethod(
            lambda cls: {
                "unified_downloader": {"max_concurrency": 6, "concurrency_benchmarked_at": fresh}
            }
        ),
    )
    monkeypatch.setattr(
        concurrency,
        "benchmark_concurrency",
        lambda **_kw: {"max_concurrency": 8, "benchmarked_at": "2026-05-21T00:00:00+00:00"},
    )
    value = concurrency.ensure_concurrency_benchmark(
        probe=_FakeProbe(0.1), force=True, persist=lambda _r: True
    )
    assert value == 8  # force → re-benchmark even though cache is fresh


# ──────────────────────────────────────────────────────────────────────────────
# persist_benchmark — settings round-trip
# ──────────────────────────────────────────────────────────────────────────────


def test_persist_benchmark_writes_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services as services

    store: dict = {}
    monkeypatch.setattr(services.SettingsManager, "load", classmethod(lambda cls: dict(store)))
    monkeypatch.setattr(
        services.SettingsManager,
        "save",
        classmethod(lambda cls, cfg: store.update(cfg)),
    )

    ok = concurrency.persist_benchmark(
        {"max_concurrency": 8, "benchmarked_at": "2026-05-21T00:00:00+00:00"}
    )
    assert ok is True
    assert store["unified_downloader"]["max_concurrency"] == 8
    assert store["unified_downloader"]["concurrency_benchmarked_at"] == (
        "2026-05-21T00:00:00+00:00"
    )
