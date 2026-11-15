"""GET /api/audio/waveform: off-loop compute, disk cache, in-flight dedup.

The DSP (librosa.load + 3x lfilter + rms, 1-3 s per track) used to run on the
event loop on every track open. Now: worker thread + ``WaveformCache`` keyed on
(path, pps) and validated against the source file's mtime_ns + size.

``AudioEngine.generate_multiband_waveform`` is replaced by a counting fake, so
no audio decoding happens here.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from starlette.responses import JSONResponse

import app.main as main
from app.analysis_cache import WaveformCache

FAKE_WAVEFORM: dict[str, Any] = {
    "low": [0.0, 0.5, 1.0],
    "mid": [0.25, 0.75, 0.1234],
    "high": [0.1, 0.2, 0.3],
    "duration": 1.5,
    "points": 3,
}


class FakeEngine:
    def __init__(self, block: bool = False, fail: bool = False) -> None:
        self.calls = 0
        self.started = threading.Event()
        self.release = threading.Event()
        self.block = block
        self.fail = fail
        if not block:
            self.release.set()

    def __call__(self, path: str, pixels_per_second: int = 50) -> dict[str, Any]:
        self.calls += 1
        self.started.set()
        self.release.wait(timeout=10)
        if self.fail:
            raise RuntimeError("decode failed")
        return dict(FAKE_WAVEFORM)


@pytest.fixture
def sandbox_root(tmp_path: Path) -> Iterator[Path]:
    root = (tmp_path / "lib").resolve()
    root.mkdir()
    main.ALLOWED_AUDIO_ROOTS.append(root)
    try:
        yield root
    finally:
        with contextlib.suppress(ValueError):
            main.ALLOWED_AUDIO_ROOTS.remove(root)


@pytest.fixture
def audio_file(sandbox_root: Path) -> Path:
    p = sandbox_root / "track.mp3"
    p.write_bytes(b"\x00" * 2048)
    return p


@pytest.fixture
def cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> WaveformCache:
    c = WaveformCache(tmp_path / "wfcache")
    monkeypatch.setattr(main, "get_waveform_cache", lambda: c)
    return c


def _install(monkeypatch: pytest.MonkeyPatch, engine: FakeEngine) -> FakeEngine:
    monkeypatch.setattr(main.AudioEngine, "generate_multiband_waveform", staticmethod(engine))
    return engine


def _client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(
        app=main.app, client=("127.0.0.1", 12345), raise_app_exceptions=False
    )
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


def _get(url: str, **params: Any) -> httpx.Response:
    async def _go() -> httpx.Response:
        async with _client() as ac:
            return await ac.get(url, params=params)

    return asyncio.run(_go())


# --- WaveformCache unit ---


def test_cache_roundtrip_and_key_includes_pps(tmp_path: Path, audio_file: Path) -> None:
    c = WaveformCache(tmp_path / "c")
    st = audio_file.stat()
    assert c.get(str(audio_file), 50, st) is None
    c.put(str(audio_file), 50, st, b'{"a":1}')
    assert c.get(str(audio_file), 50, st) == b'{"a":1}'
    assert c.get(str(audio_file), 51, st) is None
    assert WaveformCache.key(str(audio_file), 50) != WaveformCache.key(str(audio_file), 51)


def test_cache_invalidates_on_mtime_or_size_change(tmp_path: Path, audio_file: Path) -> None:
    c = WaveformCache(tmp_path / "c")
    c.put(str(audio_file), 50, audio_file.stat(), b"body")

    st = audio_file.stat()
    os.utime(audio_file, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
    assert c.get(str(audio_file), 50, audio_file.stat()) is None

    c.put(str(audio_file), 50, audio_file.stat(), b"body")
    with audio_file.open("ab") as f:
        f.write(b"x")
    assert c.get(str(audio_file), 50, audio_file.stat()) is None


@pytest.mark.skipif(os.name != "nt", reason="case-insensitive paths are a Windows property")
def test_cache_key_is_case_insensitive_on_windows(audio_file: Path) -> None:
    assert WaveformCache.key(str(audio_file).upper(), 50) == WaveformCache.key(
        str(audio_file).lower(), 50
    )


def test_cache_corrupt_entry_is_a_miss(tmp_path: Path, audio_file: Path) -> None:
    c = WaveformCache(tmp_path / "c")
    st = audio_file.stat()
    c._entry_path(str(audio_file), 50).write_bytes(b"not gzip")
    assert c.get(str(audio_file), 50, st) is None


def test_cache_prunes_least_recently_used(tmp_path: Path, audio_file: Path) -> None:
    c = WaveformCache(tmp_path / "c", max_entries=3)
    st = audio_file.stat()
    for i, pps in enumerate((10, 20, 30)):
        c.put(str(audio_file), pps, st, b"x")
        # Distinct, ascending ages independent of FS timestamp resolution.
        t = time.time() - 1000 + i
        os.utime(c._entry_path(str(audio_file), pps), (t, t))
    assert c.get(str(audio_file), 10, st) == b"x"  # touch -> most recent

    c.put(str(audio_file), 40, st, b"x")

    files = list(c.cache_dir.glob("*.wf.gz"))
    assert len(files) == 3
    assert c.get(str(audio_file), 20, st) is None  # oldest untouched -> pruned
    for pps in (10, 30, 40):
        assert c.get(str(audio_file), pps, st) == b"x"


def test_cache_prunes_by_total_bytes(tmp_path: Path, audio_file: Path) -> None:
    # Random bytes don't compress: one entry ~4.2 kB, two exceed the budget.
    c = WaveformCache(tmp_path / "c", max_entries=100, max_bytes=6000)
    st = audio_file.stat()
    c.put(str(audio_file), 10, st, os.urandom(4096))
    t = time.time() - 1000
    os.utime(c._entry_path(str(audio_file), 10), (t, t))
    c.put(str(audio_file), 20, st, os.urandom(4096))
    assert len(list(c.cache_dir.glob("*.wf.gz"))) == 1
    assert c.get(str(audio_file), 10, st) is None
    assert c.get(str(audio_file), 20, st) is not None
    assert not list(c.cache_dir.glob("*.tmp"))


# --- route ---


def test_second_call_is_cache_hit(
    monkeypatch: pytest.MonkeyPatch,
    audio_file: Path,
    cache: WaveformCache,
    caplog: pytest.LogCaptureFixture,
) -> None:
    engine = _install(monkeypatch, FakeEngine())

    r1 = _get("/api/audio/waveform", path=str(audio_file), pps=50)
    assert r1.status_code == 200, r1.text
    assert engine.calls == 1

    with caplog.at_level(logging.INFO, logger="APP_MAIN"):
        r2 = _get("/api/audio/waveform", path=str(audio_file), pps=50)
    assert r2.status_code == 200
    assert engine.calls == 1
    assert r2.content == r1.content
    assert any("waveform cache HIT" in rec.getMessage() for rec in caplog.records)

    _get("/api/audio/waveform", path=str(audio_file), pps=60)
    assert engine.calls == 2  # pps is part of the key


def test_response_bytes_match_previous_jsonresponse(
    monkeypatch: pytest.MonkeyPatch, audio_file: Path, cache: WaveformCache
) -> None:
    _install(monkeypatch, FakeEngine())
    miss = _get("/api/audio/waveform", path=str(audio_file), pps=50)
    hit = _get("/api/audio/waveform", path=str(audio_file), pps=50)
    expected = JSONResponse(FAKE_WAVEFORM).body
    assert miss.content == expected
    assert hit.content == expected
    assert hit.headers["content-type"] == "application/json"
    assert miss.json() == FAKE_WAVEFORM


def test_file_change_recomputes(
    monkeypatch: pytest.MonkeyPatch, audio_file: Path, cache: WaveformCache
) -> None:
    engine = _install(monkeypatch, FakeEngine())
    _get("/api/audio/waveform", path=str(audio_file), pps=50)
    with audio_file.open("ab") as f:
        f.write(b"more audio")
    _get("/api/audio/waveform", path=str(audio_file), pps=50)
    assert engine.calls == 2


def test_health_answers_while_waveform_computes(
    monkeypatch: pytest.MonkeyPatch, audio_file: Path, cache: WaveformCache
) -> None:
    engine = _install(monkeypatch, FakeEngine(block=True))

    async def _go() -> tuple[int, float, bool, int]:
        async with _client() as ac:
            wf = asyncio.create_task(
                ac.get("/api/audio/waveform", params={"path": str(audio_file), "pps": 50})
            )
            for _ in range(500):
                if engine.started.is_set():
                    break
                await asyncio.sleep(0.01)
            assert engine.started.is_set(), "waveform computation never started"
            t0 = time.perf_counter()
            health = await asyncio.wait_for(ac.get("/api/system/health"), timeout=5)
            latency = time.perf_counter() - t0
            still_running = not wf.done()
            engine.release.set()
            r = await wf
            return health.status_code, latency, still_running, r.status_code

    health_status, latency, still_running, wf_status = asyncio.run(_go())
    assert health_status == 200
    assert still_running, "health only answered after the waveform finished"
    assert latency < 2.0
    assert wf_status == 200


def test_concurrent_requests_share_one_computation(
    monkeypatch: pytest.MonkeyPatch, audio_file: Path, cache: WaveformCache
) -> None:
    engine = _install(monkeypatch, FakeEngine(block=True))

    async def _go() -> list[httpx.Response]:
        async with _client() as ac:
            params = {"path": str(audio_file), "pps": 50}
            tasks = [asyncio.create_task(ac.get("/api/audio/waveform", params=params))]
            for _ in range(500):
                if engine.started.is_set():
                    break
                await asyncio.sleep(0.01)
            tasks += [
                asyncio.create_task(ac.get("/api/audio/waveform", params=params)) for _ in range(3)
            ]
            await asyncio.sleep(0.05)
            engine.release.set()
            return list(await asyncio.gather(*tasks))

    responses = asyncio.run(_go())
    assert [r.status_code for r in responses] == [200] * 4
    assert len({r.content for r in responses}) == 1
    assert engine.calls == 1
    assert main._waveform_inflight == {}


def test_compute_error_is_500_and_not_cached(
    monkeypatch: pytest.MonkeyPatch, audio_file: Path, cache: WaveformCache
) -> None:
    engine = _install(monkeypatch, FakeEngine(fail=True))
    r = _get("/api/audio/waveform", path=str(audio_file), pps=50)
    assert r.status_code == 500
    assert main._waveform_inflight == {}
    assert not list(cache.cache_dir.glob("*.wf.gz"))
    engine.fail = False
    assert _get("/api/audio/waveform", path=str(audio_file), pps=50).status_code == 200
    assert engine.calls == 2


@pytest.mark.parametrize("pps", [0, -5])
def test_non_positive_pps_rejected(
    monkeypatch: pytest.MonkeyPatch, audio_file: Path, cache: WaveformCache, pps: int
) -> None:
    engine = _install(monkeypatch, FakeEngine())
    r = _get("/api/audio/waveform", path=str(audio_file), pps=pps)
    assert r.status_code == 422
    assert engine.calls == 0


def test_sandbox_still_enforced(monkeypatch: pytest.MonkeyPatch, cache: WaveformCache) -> None:
    engine = _install(monkeypatch, FakeEngine())
    r = _get("/api/audio/waveform", path="C:/Windows/System32/drivers/etc/hosts.mp3", pps=50)
    assert r.status_code in (403, 404)
    assert engine.calls == 0
