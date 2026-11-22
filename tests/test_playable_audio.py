"""AIFF served as a virtual WAV (app/playable_audio.py + both stream routes).

Chromium / WebView2 decode no AIFF, so ``/api/stream`` and ``/api/audio/stream``
present AIFF as WAV computed from the source. Checked here: the WAV is valid
(stdlib ``wave`` + libsndfile both parse it), samples are bit-exact, every byte
range equals the same slice of the full WAV, and other formats stay untouched.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import io
import random
import threading
import wave
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import numpy as np
import pytest
import soundfile as sf

import app.main as main
from app import playable_audio as pa

RATE = 44100


def _signal(frames: int, channels: int, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return np.clip(rng.standard_normal((frames, channels)) * 0.3, -1.0, 1.0)


def _write_aiff(
    path: Path, subtype: str, *, frames: int = 5000, channels: int = 2, **kw: Any
) -> None:
    sf.write(path, _signal(frames, channels), RATE, format="AIFF", subtype=subtype, **kw)


def _full(view: pa.WavView) -> bytes:
    return b"".join(pa.iter_range(view, 0, view.size - 1))


# --- converter ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("subtype", "read_dtype", "bits"),
    [
        ("PCM_16", "int16", 16),
        ("PCM_24", "int32", 24),
        ("PCM_32", "int32", 32),
        ("FLOAT", "float32", 32),
    ],
)
@pytest.mark.parametrize("channels", [1, 2])
def test_wav_view_is_bit_exact(
    tmp_path: Path, subtype: str, read_dtype: str, bits: int, channels: int
) -> None:
    src = tmp_path / "t.aiff"
    _write_aiff(src, subtype, channels=channels, frames=4321)
    view = pa.describe(src)
    blob = _full(view)

    assert len(blob) == view.size == 44 + 4321 * channels * bits // 8
    assert blob[:4] == b"RIFF" and blob[8:16] == b"WAVEfmt "
    decoded, rate = sf.read(io.BytesIO(blob), dtype=read_dtype, always_2d=True)
    source, _ = sf.read(src, dtype=read_dtype, always_2d=True)
    assert rate == RATE
    assert sf.info(io.BytesIO(blob)).subtype == subtype
    np.testing.assert_array_equal(decoded, source)


def test_header_parses_with_stdlib_wave(tmp_path: Path) -> None:
    src = tmp_path / "t.aiff"
    _write_aiff(src, "PCM_24", frames=1000)
    blob = _full(pa.describe(src))
    with wave.open(io.BytesIO(blob)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()) == (
            2,
            3,
            RATE,
            1000,
        )


def test_aifc_sowt_little_endian(tmp_path: Path) -> None:
    # The library's AIFFs are 'FORM AIFC' with compression 'sowt' (little-endian PCM).
    src = tmp_path / "sowt.aiff"
    _write_aiff(src, "PCM_16", endian="LITTLE")
    raw = src.read_bytes()
    assert raw[8:12] == b"AIFC" and b"sowt" in raw[:256]
    decoded, _ = sf.read(io.BytesIO(_full(pa.describe(src))), dtype="int16")
    source, _ = sf.read(src, dtype="int16")
    np.testing.assert_array_equal(decoded, source)


@pytest.mark.parametrize("subtype", ["PCM_S8", "PCM_U8", "ULAW", "ALAW", "IMA_ADPCM"])
def test_rare_encodings_widen_to_pcm16(tmp_path: Path, subtype: str) -> None:
    src = tmp_path / "t.aiff"
    _write_aiff(src, subtype)
    view = pa.describe(src)
    assert view.encoding.bits == 16
    decoded, _ = sf.read(io.BytesIO(_full(view)), dtype="int16")
    source, _ = sf.read(src, dtype="int16")
    np.testing.assert_array_equal(decoded, source)


def test_double_narrows_to_float32(tmp_path: Path) -> None:
    src = tmp_path / "t.aiff"
    _write_aiff(src, "DOUBLE")
    view = pa.describe(src)
    assert (view.encoding.bits, view.encoding.format_tag) == (32, 3)
    decoded, _ = sf.read(io.BytesIO(_full(view)), dtype="float32")
    source, _ = sf.read(src, dtype="float32")
    np.testing.assert_array_equal(decoded, source)


def test_every_range_matches_the_full_wav(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Small chunks so ranges span several reads; 24-bit stereo = 6-byte frames, so most
    # boundaries fall mid-frame.
    monkeypatch.setattr(pa, "_CHUNK_BYTES", 600)
    src = tmp_path / "t.aiff"
    _write_aiff(src, "PCM_24", frames=3001)
    view = pa.describe(src)
    blob = _full(view)
    size = view.size
    edges = [(0, 0), (0, 43), (0, 44), (43, 44), (44, 44), (40, 60), (size - 1, size - 1)]
    rng = random.Random(3)
    ranges = edges + [
        (a, rng.randrange(a, size)) for a in (rng.randrange(size) for _ in range(300))
    ]
    for start, end in ranges:
        assert b"".join(pa.iter_range(view, start, end)) == blob[start : end + 1], (start, end)


def test_short_source_is_padded_to_the_announced_size(tmp_path: Path) -> None:
    src = tmp_path / "t.aiff"
    _write_aiff(src, "PCM_16", frames=1000)
    view = dataclasses.replace(pa.describe(src), frames=1010)  # file shrank after describe()
    blob = _full(view)
    assert len(blob) == view.size
    assert blob[-40:] == bytes(40)


def test_range_past_the_shrunk_source_is_silence(tmp_path: Path) -> None:
    # Seeking past the real end raises in libsndfile; it must turn into silence instead.
    src = tmp_path / "t.aiff"
    _write_aiff(src, "PCM_16", frames=1000)
    view = dataclasses.replace(pa.describe(src), frames=3000)
    start = 44 + 2000 * view.frame_bytes
    assert b"".join(pa.iter_range(view, start, view.size - 1)) == bytes(view.size - start)


def test_vanished_source_is_silence(tmp_path: Path) -> None:
    src = tmp_path / "t.aiff"
    _write_aiff(src, "PCM_16", frames=1000)
    view = pa.describe(src)
    src.unlink()
    blob = _full(view)
    assert len(blob) == view.size
    assert blob[44:] == bytes(view.data_bytes)


def test_no_file_handle_outlives_a_chunk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A dropped connection leaves its generator suspended until GC. The source must not stay
    # open meanwhile: Windows would refuse the in-place format converter's replace/delete.
    monkeypatch.setattr(pa, "_CHUNK_BYTES", 4096)
    src = tmp_path / "t.aiff"
    _write_aiff(src, "PCM_16", frames=20000)
    gen = pa.iter_range(pa.describe(src), 0, 50_000)
    next(gen)
    next(gen)
    src.replace(tmp_path / "moved.aiff")
    gen.close()


def test_unreadable_source_raises(tmp_path: Path) -> None:
    src = tmp_path / "fake.aiff"
    src.write_bytes(b"FORM\x00\x00\x00\x10AIFF" + b"\x00" * 64)
    with pytest.raises(pa.WavViewError):
        pa.describe(src)


def test_unsupported_encoding_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # DWVW reads but cannot seek in libsndfile 1.2.2 — reject it before any byte goes out.
    src = tmp_path / "t.aiff"
    _write_aiff(src, "PCM_16")
    _fake_subtype(monkeypatch, "DWVW_24")
    with pytest.raises(pa.WavViewError, match="DWVW_24"):
        pa.describe(src)


def _fake_subtype(monkeypatch: pytest.MonkeyPatch, subtype: str) -> None:
    real_info = pa.sf.info

    def _info(path: str) -> Any:
        i = real_info(path)
        return SimpleNamespace(
            channels=i.channels, samplerate=i.samplerate, frames=i.frames, subtype=subtype
        )

    monkeypatch.setattr(pa.sf, "info", _info)


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("bytes=0-", (0, 999)),
        ("bytes=0-0", (0, 0)),
        ("bytes=10-19", (10, 19)),
        ("bytes=990-5000", (990, 999)),
        ("bytes=-100", (900, 999)),
        ("bytes=-5000", (0, 999)),
        ("Bytes = 5 - 6", (5, 6)),
    ],
)
def test_parse_range(header: str, expected: tuple[int, int]) -> None:
    assert pa.parse_range(header, 1000) == expected


@pytest.mark.parametrize("header", ["bytes=1000-", "bytes=5000-6000", "bytes=-0"])
def test_parse_range_unsatisfiable(header: str) -> None:
    with pytest.raises(ValueError):
        pa.parse_range(header, 1000)


@pytest.mark.parametrize(
    "header",
    ["bytes=5-4", "bytes=-", "bytes=0-1,5-6", "items=0-1", "bytes", "bytes=a-b", "bytes=-5-"],
)
def test_parse_range_ignores_malformed(header: str) -> None:
    # RFC 7233: an invalid Range header is ignored (whole file, 200), not answered with 416.
    assert pa.parse_range(header, 1000) is None


def test_suffix_and_filename_helpers() -> None:
    assert pa.needs_wav_view(Path("x/Track.AIFF"))
    assert pa.needs_wav_view(Path("x/Track.aif"))
    assert not pa.needs_wav_view(Path("x/Track.aifc"))  # not in ALLOWED_AUDIO_EXTENSIONS
    assert not pa.needs_wav_view(Path("x/Track.mp3"))
    assert not pa.needs_wav_view(Path("x/Track.wav"))
    assert pa.wav_filename("A.B - Track.aiff") == "A.B - Track.wav"


# --- routes -------------------------------------------------------------------


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


def _get(route: str, path: Path, headers: dict[str, str] | None = None) -> httpx.Response:
    async def _go() -> httpx.Response:
        transport = httpx.ASGITransport(
            app=main.app, client=("127.0.0.1", 12345), raise_app_exceptions=False
        )
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            return await ac.get(route, params={"path": str(path)}, headers=headers)

    return asyncio.run(_go())


ROUTES = ["/api/stream", "/api/audio/stream"]


@pytest.mark.parametrize("route", ROUTES)
def test_route_serves_aiff_as_wav(sandbox_root: Path, route: str) -> None:
    src = sandbox_root / "Song.aiff"
    _write_aiff(src, "PCM_16", endian="LITTLE", frames=20000)
    expected = _full(pa.describe(src))

    r = _get(route, src)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "audio/wav"
    assert r.headers["accept-ranges"] == "bytes"
    assert r.headers["content-length"] == str(len(expected))
    assert 'filename="Song.wav"' in r.headers["content-disposition"]
    assert r.content == expected


@pytest.mark.parametrize("route", ROUTES)
def test_route_range_on_converted_file(sandbox_root: Path, route: str) -> None:
    src = sandbox_root / "Song.aif"
    _write_aiff(src, "PCM_24", frames=20000)
    expected = _full(pa.describe(src))
    size = len(expected)

    start, end = 1001, 70001  # mid-frame on both ends
    r = _get(route, src, headers={"Range": f"bytes={start}-{end}"})
    assert r.status_code == 206, r.text
    assert r.headers["content-range"] == f"bytes {start}-{end}/{size}"
    assert r.headers["content-length"] == str(end - start + 1)
    assert r.content == expected[start : end + 1]

    tail = _get(route, src, headers={"Range": "bytes=-10"})
    assert tail.status_code == 206
    assert tail.content == expected[-10:]

    bad = _get(route, src, headers={"Range": f"bytes={size}-"})
    assert bad.status_code == 416
    assert bad.headers["content-range"] == f"bytes */{size}"

    ignored = _get(route, src, headers={"Range": "bytes=500-400"})
    assert ignored.status_code == 200
    assert "content-range" not in ignored.headers
    assert ignored.content == expected


@pytest.mark.parametrize("route", ROUTES)
def test_route_unsupported_encoding_is_415(
    sandbox_root: Path, route: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = sandbox_root / "dwvw.aiff"
    _write_aiff(src, "PCM_16")
    _fake_subtype(monkeypatch, "DWVW_24")
    assert _get(route, src).status_code == 415


@pytest.mark.parametrize("route", ROUTES)
def test_route_unreadable_aiff_is_415(sandbox_root: Path, route: str) -> None:
    src = sandbox_root / "broken.aiff"
    src.write_bytes(b"FORM\x00\x00\x00\x10AIFF" + b"\x00" * 64)
    assert _get(route, src).status_code == 415


@pytest.mark.parametrize("route", ROUTES)
def test_route_keeps_sandbox_for_aiff(tmp_path: Path, route: str) -> None:
    outside = tmp_path / "outside.aiff"
    _write_aiff(outside, "PCM_16")
    assert _get(route, outside).status_code == 403


@pytest.mark.parametrize("route", ROUTES)
def test_route_other_formats_unchanged(sandbox_root: Path, route: str) -> None:
    src = sandbox_root / "song.mp3"
    data = bytes(range(256)) * 50
    src.write_bytes(data)
    r = _get(route, src)
    assert r.status_code == 200
    assert r.content == data
    assert r.headers["content-type"] == "audio/mpeg"
    ranged = _get(route, src, headers={"Range": "bytes=10-19"})
    if route == "/api/stream":
        assert ranged.status_code == 206
        assert ranged.content == data[10:20]
    else:
        # FileResponse on the pinned Starlette 0.35 ignores Range: whole file, as before.
        assert ranged.status_code == 200
        assert ranged.content == data


def test_route_reads_aiff_off_the_event_loop(
    sandbox_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = sandbox_root / "Song.aiff"
    _write_aiff(src, "PCM_16", frames=20000)
    threads: list[int] = []
    real = pa.sf.SoundFile

    def _recording(*args: Any, **kwargs: Any) -> Any:
        threads.append(threading.get_ident())
        return real(*args, **kwargs)

    monkeypatch.setattr(pa.sf, "SoundFile", _recording)

    async def _go() -> tuple[httpx.Response, int]:
        transport = httpx.ASGITransport(app=main.app, client=("127.0.0.1", 12345))
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            r = await ac.get("/api/stream", params={"path": str(src)})
            return r, threading.get_ident()

    r, loop_thread = asyncio.run(_go())
    assert r.status_code == 200
    assert threads and all(t != loop_thread for t in threads)
