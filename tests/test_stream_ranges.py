"""RFC 7233 Range + HEAD on both stream routes, raw files and the AIFF WAV view alike.

``/api/stream`` answered ``bytes=-500`` with the first 501 bytes (its own parser read the
suffix form as ``0-500``), and ``/api/audio/stream`` served mp3/flac/m4a/wav through
Starlette 0.35's ``FileResponse``, which ignores Range (200 + whole body while advertising
``Accept-Ranges: bytes``). HEAD was 405 on both. One shared helper now answers all of it:
single range -> 206, none / malformed / multi-range -> 200 whole file, unsatisfiable ->
416 ``bytes */size``.

Every file lives in ``tmp_path``; the sandbox root is added for the test and removed after.
"""

from __future__ import annotations

import asyncio
import builtins
import contextlib
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest
import soundfile as sf

import app.main as main
from app import playable_audio as pa

ROUTES = ["/api/stream", "/api/audio/stream"]
RAW_TYPES = {
    ".mp3": "audio/mpeg",
    ".flac": "audio/flac",
    ".m4a": "audio/mp4",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
}


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


def _request(
    method: str, route: str, path: Path, headers: dict[str, str] | None = None
) -> httpx.Response:
    async def _go() -> httpx.Response:
        transport = httpx.ASGITransport(
            app=main.app, client=("127.0.0.1", 12345), raise_app_exceptions=False
        )
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            return await ac.request(method, route, params={"path": str(path)}, headers=headers)

    return asyncio.run(_go())


def _raw(root: Path, suffix: str = ".mp3", size: int = 5000) -> tuple[Path, bytes]:
    # Not decoded anywhere: only AIFF is parsed, every other format goes out byte for byte.
    data = os.urandom(size)
    p = root / f"song{suffix}"
    p.write_bytes(data)
    return p, data


def _aiff(root: Path) -> tuple[Path, bytes]:
    p = root / "song.aiff"
    sig = np.random.default_rng(3).standard_normal((3000, 2)) * 0.2
    sf.write(p, sig, 44100, format="AIFF", subtype="PCM_16")
    view = pa.describe(p)
    return p, b"".join(pa.iter_range(view, 0, view.size - 1))


@pytest.fixture(params=["raw", "aiff"])
def source(request: pytest.FixtureRequest, sandbox_root: Path) -> tuple[Path, bytes]:
    return _raw(sandbox_root) if request.param == "raw" else _aiff(sandbox_root)


# --- single ranges -------------------------------------------------------------


@pytest.mark.parametrize("route", ROUTES)
def test_suffix_range_returns_the_tail(source: tuple[Path, bytes], route: str) -> None:
    path, data = source
    size = len(data)
    r = _request("GET", route, path, {"Range": "bytes=-500"})
    assert r.status_code == 206, r.text
    assert r.headers["content-range"] == f"bytes {size - 500}-{size - 1}/{size}"
    assert r.headers["content-length"] == "500"
    assert r.content == data[-500:]


@pytest.mark.parametrize("route", ROUTES)
def test_suffix_longer_than_the_file_is_the_whole_file(
    source: tuple[Path, bytes], route: str
) -> None:
    path, data = source
    size = len(data)
    r = _request("GET", route, path, {"Range": f"bytes=-{size + 1000}"})
    assert r.status_code == 206, r.text
    assert r.headers["content-range"] == f"bytes 0-{size - 1}/{size}"
    assert r.content == data


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize(
    ("spec", "lo", "hi"),
    [("10-19", 10, 19), ("4000-", 4000, None), ("0-0", 0, 0), ("100-999999", 100, None)],
)
def test_closed_and_open_ranges(
    source: tuple[Path, bytes], route: str, spec: str, lo: int, hi: int | None
) -> None:
    path, data = source
    size = len(data)
    end = size - 1 if hi is None else hi
    r = _request("GET", route, path, {"Range": f"bytes={spec}"})
    assert r.status_code == 206, r.text
    assert r.headers["content-range"] == f"bytes {lo}-{end}/{size}"
    assert r.headers["content-length"] == str(end - lo + 1)
    assert r.content == data[lo : end + 1]


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("spec", ["bytes=999999-", "bytes=-0"])
def test_unsatisfiable_range_is_416(source: tuple[Path, bytes], route: str, spec: str) -> None:
    path, data = source
    r = _request("GET", route, path, {"Range": spec})
    assert r.status_code == 416, r.text
    assert r.headers["content-range"] == f"bytes */{len(data)}"


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize(
    "spec", ["bytes=0-1,5-6", "bytes=-5,10-", "bytes=9-3", "items=0-5", "bytes=x-y"]
)
def test_multi_range_and_malformed_serve_the_whole_file(
    source: tuple[Path, bytes], route: str, spec: str
) -> None:
    path, data = source
    r = _request("GET", route, path, {"Range": spec})
    assert r.status_code == 200, r.text
    assert "content-range" not in r.headers
    assert r.headers["content-length"] == str(len(data))
    assert r.content == data


# --- /api/audio/stream raw formats ------------------------------------------------


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("suffix", sorted(RAW_TYPES))
def test_raw_formats_range_and_content_type(sandbox_root: Path, route: str, suffix: str) -> None:
    path, data = _raw(sandbox_root, suffix)
    full = _request("GET", route, path)
    assert full.status_code == 200
    assert full.headers["content-type"] == RAW_TYPES[suffix]
    assert full.headers["accept-ranges"] == "bytes"
    assert full.content == data

    ranged = _request("GET", route, path, {"Range": "bytes=100-199"})
    assert ranged.status_code == 206, ranged.text
    assert ranged.headers["content-type"] == RAW_TYPES[suffix]
    assert ranged.content == data[100:200]


# --- HEAD ---------------------------------------------------------------------------


@pytest.mark.parametrize("route", ROUTES)
def test_head_reports_size_without_a_body(source: tuple[Path, bytes], route: str) -> None:
    path, data = source
    r = _request("HEAD", route, path)
    assert r.status_code == 200, r.text
    assert r.headers["content-length"] == str(len(data))
    assert r.headers["accept-ranges"] == "bytes"
    assert r.headers["content-type"].startswith("audio/")
    assert r.content == b""


@pytest.mark.parametrize("route", ROUTES)
def test_head_with_range_mirrors_get(source: tuple[Path, bytes], route: str) -> None:
    path, data = source
    size = len(data)
    r = _request("HEAD", route, path, {"Range": "bytes=-100"})
    assert r.status_code == 206, r.text
    assert r.headers["content-range"] == f"bytes {size - 100}-{size - 1}/{size}"
    assert r.headers["content-length"] == "100"
    assert r.content == b""


@pytest.mark.parametrize("route", ROUTES)
def test_head_reads_no_audio(
    sandbox_root: Path, route: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, _ = _raw(sandbox_root)
    opened: list[Any] = []

    def _open(file: Any, *a: Any, **kw: Any) -> Any:
        opened.append(file)
        return builtins.open(file, *a, **kw)

    monkeypatch.setattr(main, "open", _open, raising=False)
    assert _request("HEAD", route, path).status_code == 200
    assert opened == []


@pytest.mark.parametrize("route", ROUTES)
def test_head_keeps_the_sandbox(tmp_path: Path, route: str) -> None:
    outside = tmp_path / "outside.mp3"
    outside.write_bytes(b"ID3" + bytes(100))
    assert _request("HEAD", route, outside).status_code == 403
