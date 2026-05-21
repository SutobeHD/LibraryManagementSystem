"""First-run concurrency benchmark (D8).

The optimal download parallelism depends on the user's network: a fat
low-latency link benefits from 8-way concurrency, a rate-limited or
high-latency link is better served by 2. Rather than guess, the downloader
measures it once on first run.

Method (D8):

1. Fire a throwaway pre-warm request (amortises DNS + TLS handshake).
2. **Batch A — parallel**: fire 4 SoundCloud V2 ``/resolve`` probes at once
   via a thread pool; measure wall-time.
3. **Batch B — sequential**: fire the same 4 one at a time; measure
   cumulative wall-time.
4. ``speedup = batch_b_total / batch_a_total``.
5. Map the speedup onto a recommended concurrency via :data:`_THRESHOLDS`.
6. Persist to ``settings.json`` as ``unified_downloader.max_concurrency``,
   with a timestamp so the 7-day cache can decide when to re-benchmark.

The network probe is isolated behind the :class:`Probe` seam — tests inject
a fake that returns canned latencies, so the suite never touches the
network. The default :class:`HttpProbe` is the only thing that does I/O.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Protocol, TypedDict

logger = logging.getLogger("DOWNLOADER_CONCURRENCY")

#: Four stable, public SoundCloud track URLs used as benchmark probes. The
#: V2 ``/resolve`` endpoint is idempotent and fast — see D8. These are well-
#: known label uploads chosen for longevity.
BENCHMARK_URLS: tuple[str, ...] = (
    "https://soundcloud.com/monstercat/pegboard-nerds-disconnected",
    "https://soundcloud.com/spinninrecords/martin-garrix-animals-original-mix",
    "https://soundcloud.com/ovosound/drake-hotline-bling",
    "https://soundcloud.com/mad-decent/dj-snake-lil-jon-turn-down-for-what",
)

#: Speedup -> recommended concurrency. Ordered high-to-low; the first
#: threshold the measured speedup clears wins. Below all of them the link is
#: network-bound or rate-limited and gets the conservative floor of 2.
_THRESHOLDS: tuple[tuple[float, int], ...] = (
    (3.0, 8),
    (2.0, 6),
    (1.5, 4),
)

#: Concurrency used when no threshold is cleared (network-bound link).
_FLOOR_CONCURRENCY = 2

#: Concurrency used when the benchmark cannot run at all (probe failure).
_FALLBACK_CONCURRENCY = 4

#: Settings key (nested) the result is persisted under.
_SETTINGS_NS = "unified_downloader"

#: How long a benchmark result stays fresh before a re-benchmark is advised.
CACHE_TTL_DAYS = 7


class BenchmarkResult(TypedDict):
    """Structured return of :func:`benchmark_concurrency` (also the persist input)."""

    max_concurrency: int
    speedup: float
    parallel_s: float
    sequential_s: float
    benchmarked_at: str  # ISO-8601 UTC


class Probe(Protocol):
    """A single benchmark probe — resolve one URL, return its latency.

    The mockable seam: production uses :class:`HttpProbe` (real network),
    tests inject a fake whose ``__call__`` returns deterministic latencies.
    """

    def __call__(self, url: str) -> float:
        """Resolve ``url`` and return the elapsed wall-time in seconds."""
        ...


class HttpProbe:
    """Default :class:`Probe` — times a real SoundCloud V2 ``/resolve`` call.

    Imports ``soundcloud_api`` lazily so that merely importing this module
    (e.g. in a test that injects a fake probe) costs nothing and pulls in no
    network-capable code.
    """

    def __call__(self, url: str) -> float:
        from ..soundcloud_api import SoundCloudPlaylistAPI

        start = time.perf_counter()
        try:
            SoundCloudPlaylistAPI.resolve_track_from_url(url)
        except Exception as exc:
            logger.debug("[Concurrency] probe failed for %s: %s", url, exc)
        return time.perf_counter() - start


def _run_sequential(probe: Probe, urls: Sequence[str]) -> float:
    """Fire probes one at a time; return cumulative wall-time (seconds)."""
    start = time.perf_counter()
    for url in urls:
        probe(url)
    return time.perf_counter() - start


def _run_parallel(probe: Probe, urls: Sequence[str]) -> float:
    """Fire all probes at once via a thread pool; return wall-time (seconds)."""
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=len(urls)) as pool:
        list(pool.map(probe, urls))
    return time.perf_counter() - start


def speedup_to_concurrency(speedup: float) -> int:
    """Map a parallel-vs-sequential speedup ratio onto a concurrency value.

    Returns 8 / 6 / 4 for speedups clearing 3.0 / 2.0 / 1.5, else the
    conservative floor of 2. See :data:`_THRESHOLDS`.
    """
    for threshold, concurrency in _THRESHOLDS:
        if speedup > threshold:
            return concurrency
    return _FLOOR_CONCURRENCY


def benchmark_concurrency(
    *,
    probe: Probe | None = None,
    urls: Sequence[str] | None = None,
) -> BenchmarkResult:
    """Run the D8 benchmark and return a result dict (does not persist).

    ``probe`` defaults to :class:`HttpProbe` (real network); inject a fake to
    keep tests offline. ``urls`` defaults to :data:`BENCHMARK_URLS`.

    Result dict::

        {
            "max_concurrency": int,
            "speedup": float,
            "parallel_s": float,
            "sequential_s": float,
            "benchmarked_at": str,   # ISO-8601 UTC
        }

    A degenerate parallel time of ~0 s (or any probe exception bubbling out)
    yields the safe :data:`_FALLBACK_CONCURRENCY` rather than a divide-by-zero.
    """
    active_probe: Probe = probe if probe is not None else HttpProbe()
    active_urls = tuple(urls) if urls is not None else BENCHMARK_URLS
    now = datetime.now(timezone.utc).isoformat()

    try:
        # Pre-warm: amortise DNS + TLS handshake so it does not skew Batch A.
        active_probe(active_urls[0])
        parallel_s = _run_parallel(active_probe, active_urls)
        sequential_s = _run_sequential(active_probe, active_urls)
    except Exception as exc:
        logger.warning("[Concurrency] benchmark failed (%s) — using fallback", exc)
        return BenchmarkResult(
            max_concurrency=_FALLBACK_CONCURRENCY,
            speedup=0.0,
            parallel_s=0.0,
            sequential_s=0.0,
            benchmarked_at=now,
        )

    if parallel_s <= 1e-6:
        speedup = 0.0
        concurrency = _FALLBACK_CONCURRENCY
    else:
        speedup = sequential_s / parallel_s
        concurrency = speedup_to_concurrency(speedup)

    logger.info(
        "[Concurrency] benchmark: parallel=%.3fs sequential=%.3fs speedup=%.2f -> %d",
        parallel_s,
        sequential_s,
        speedup,
        concurrency,
    )
    return BenchmarkResult(
        max_concurrency=concurrency,
        speedup=round(speedup, 3),
        parallel_s=round(parallel_s, 3),
        sequential_s=round(sequential_s, 3),
        benchmarked_at=now,
    )


def _is_stale(benchmarked_at: str | None) -> bool:
    """True if a stored benchmark timestamp is older than :data:`CACHE_TTL_DAYS`."""
    if not benchmarked_at:
        return True
    try:
        ts = datetime.fromisoformat(benchmarked_at)
    except (TypeError, ValueError):
        return True
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - ts).days >= CACHE_TTL_DAYS


def persist_benchmark(result: BenchmarkResult) -> bool:
    """Write a benchmark result into ``settings.json`` under ``unified_downloader``.

    Stores ``max_concurrency`` plus ``concurrency_benchmarked_at`` (the 7-day
    cache key). Returns ``True`` on success, ``False`` on any settings I/O
    error — persistence is best-effort, a failure must not abort the caller.
    """
    try:
        from ..services import SettingsManager

        cfg = SettingsManager.load()
        ns = cfg.get(_SETTINGS_NS)
        if not isinstance(ns, dict):
            ns = {}
        ns["max_concurrency"] = int(result.get("max_concurrency", _FALLBACK_CONCURRENCY))
        ns["concurrency_benchmarked_at"] = str(result.get("benchmarked_at") or "")
        cfg[_SETTINGS_NS] = ns
        SettingsManager.save(cfg)
        logger.info("[Concurrency] persisted max_concurrency=%s", ns["max_concurrency"])
        return True
    except Exception as exc:
        logger.error("[Concurrency] persist_benchmark failed: %s", exc)
        return False


def ensure_concurrency_benchmark(
    *,
    probe: Probe | None = None,
    force: bool = False,
    persist: Callable[[BenchmarkResult], bool] | None = None,
) -> int:
    """Return the recommended concurrency, benchmarking on first run / staleness.

    Reads the cached value from ``settings.json``; re-benchmarks when it is
    missing, older than :data:`CACHE_TTL_DAYS`, or ``force`` is set (the
    "Re-benchmark" button). The fresh result is persisted via ``persist``
    (defaults to :func:`persist_benchmark`).

    ``probe`` is forwarded to :func:`benchmark_concurrency` — inject a fake
    to keep tests offline.
    """
    persist_fn = persist if persist is not None else persist_benchmark
    cached_value: int | None = None
    cached_at: str | None = None
    try:
        from ..services import SettingsManager

        ns = SettingsManager.load().get(_SETTINGS_NS)
        if isinstance(ns, dict):
            raw_val = ns.get("max_concurrency")
            if isinstance(raw_val, int) and raw_val > 0:
                cached_value = raw_val
            cached_at = ns.get("concurrency_benchmarked_at")
    except Exception as exc:
        logger.debug("[Concurrency] could not read cached benchmark: %s", exc)

    if not force and cached_value is not None and not _is_stale(cached_at):
        return cached_value

    result = benchmark_concurrency(probe=probe)
    persist_fn(result)
    return result["max_concurrency"]


__all__ = [
    "BENCHMARK_URLS",
    "CACHE_TTL_DAYS",
    "HttpProbe",
    "Probe",
    "benchmark_concurrency",
    "ensure_concurrency_benchmark",
    "persist_benchmark",
    "speedup_to_concurrency",
]
