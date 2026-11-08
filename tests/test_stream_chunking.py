"""GET /api/stream: file reads happen off the event loop, in 1 MiB chunks.

The ``_full`` / ``_ranged`` helpers used to be ``async def`` generators doing
blocking ``f.read(64 KiB)`` on the loop (1600 reads per 100 MB AIFF). They are
sync generators now, so Starlette iterates them in its threadpool.

``open`` is shadowed in ``app.main``'s globals to record which thread reads
and how much per call.
"""

from __future__ import annotations

import asyncio
import builtins
import contextlib
import os
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

import app.main as main

MiB = 1024 * 1024


class _RecordingFile:
    def __init__(self, f: Any, log: list[tuple[int, int]]) -> None:
        self._f = f
        self._log = log

    def read(self, n: int = -1) -> bytes:
        self._log.append((threading.get_ident(), n))
        return self._f.read(n)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._f, name)

    def __enter__(self) -> _RecordingFile:
        return self

    def __exit__(self, *exc: object) -> None:
        self._f.close()


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
def audio(sandbox_root: Path) -> tuple[Path, bytes]:
    data = os.urandom(3 * MiB + 12345)
    p = sandbox_root / "big.aiff"
    p.write_bytes(data)
    return p, data


@pytest.fixture
def reads(monkeypatch: pytest.MonkeyPatch) -> list[tuple[int, int]]:
    log: list[tuple[int, int]] = []

    def _open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        f = builtins.open(file, mode, *args, **kwargs)  # noqa: SIM115 - caller closes
        return _RecordingFile(f, log) if "b" in mode and "r" in mode else f

    monkeypatch.setattr(main, "open", _open, raising=False)
    return log


def _get(path: Path, headers: dict[str, str] | None = None) -> tuple[httpx.Response, int]:
    async def _go() -> tuple[httpx.Response, int]:
        transport = httpx.ASGITransport(
            app=main.app, client=("127.0.0.1", 12345), raise_app_exceptions=False
        )
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            r = await ac.get("/api/stream", params={"path": str(path)}, headers=headers)
            return r, threading.get_ident()

    return asyncio.run(_go())


def test_full_stream_reads_off_loop_in_1mib_chunks(
    audio: tuple[Path, bytes], reads: list[tuple[int, int]]
) -> None:
    path, data = audio
    r, loop_thread = _get(path)
    assert r.status_code == 200
    assert r.content == data
    assert r.headers["content-length"] == str(len(data))
    assert r.headers["accept-ranges"] == "bytes"

    assert reads, "stream did not read through app.main.open"
    assert all(tid != loop_thread for tid, _ in reads), "file read on the event-loop thread"
    assert all(n == main._STREAM_CHUNK_BYTES == MiB for _, n in reads)
    assert len(reads) == 5  # 4 data chunks + the empty EOF read


def test_ranged_stream_reads_off_loop(
    audio: tuple[Path, bytes], reads: list[tuple[int, int]]
) -> None:
    path, data = audio
    start, end = 1000, 2 * MiB + 500
    r, loop_thread = _get(path, headers={"Range": f"bytes={start}-{end}"})
    assert r.status_code == 206
    assert r.content == data[start : end + 1]
    assert r.headers["content-range"] == f"bytes {start}-{end}/{len(data)}"
    assert r.headers["content-length"] == str(end - start + 1)

    assert all(tid != loop_thread for tid, _ in reads)
    assert max(n for _, n in reads) <= MiB
    assert len(reads) == 2  # 2 MiB - 499 bytes: one full chunk + the remainder


def test_open_ended_range_to_eof(audio: tuple[Path, bytes], reads: list[tuple[int, int]]) -> None:
    path, data = audio
    r, _ = _get(path, headers={"Range": f"bytes={len(data) - 10}-"})
    assert r.status_code == 206
    assert r.content == data[-10:]


def test_invalid_range_is_416(audio: tuple[Path, bytes], reads: list[tuple[int, int]]) -> None:
    path, data = audio
    r, _ = _get(path, headers={"Range": f"bytes={len(data) + 5}-"})
    assert r.status_code == 416
    assert r.headers["content-range"] == f"bytes */{len(data)}"
    assert reads == []
