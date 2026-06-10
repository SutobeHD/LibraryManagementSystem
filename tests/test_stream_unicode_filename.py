"""Regression: GET /api/stream 500 on non-latin-1 filenames.

Bug: ``Content-Disposition: inline; filename="<name>"`` was built with the raw
file name. HTTP header values are latin-1 encoded by the ASGI server, so a name
with a non-latin-1 codepoint (e.g. ``ANNĒ …`` → U+0112) made Starlette's
``Response.init_headers`` raise ``UnicodeEncodeError`` → 500 for every track with
such a character. Fixed via RFC 6266 ``filename*=utf-8''…`` in
``app.main._content_disposition_inline`` (app/main.py:642 endpoint).

We drive the ASGI app via ``httpx.ASGITransport`` (TestClient is incompatible
with the pinned fastapi/httpx pair) with ``raise_app_exceptions=False`` so an
unfixed endpoint surfaces as a live-equivalent 500, not a test-time raise.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from app.main import ALLOWED_AUDIO_ROOTS, _content_disposition_inline, app

# U+0112 LATIN CAPITAL LETTER E WITH MACRON — not latin-1 encodable.
NON_LATIN1_NAME = "ANNĒ - A Wonder To Behold.aiff"


def _get(url: str, *, headers: dict[str, str] | None = None) -> httpx.Response:
    async def _go() -> httpx.Response:
        transport = httpx.ASGITransport(
            app=app, client=("127.0.0.1", 12345), raise_app_exceptions=False
        )
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            return await ac.get(url, headers=headers)

    return asyncio.run(_go())


@pytest.fixture
def sandbox_root(tmp_path: Path) -> Iterator[Path]:
    root = (tmp_path / "lib").resolve()
    root.mkdir()
    ALLOWED_AUDIO_ROOTS.append(root)
    try:
        yield root
    finally:
        with contextlib.suppress(ValueError):
            ALLOWED_AUDIO_ROOTS.remove(root)


# --- unit: helper output is always latin-1 safe (the violated invariant) ---


@pytest.mark.parametrize(
    "name",
    [
        "normal track.mp3",
        NON_LATIN1_NAME,  # U+0112
        "Beyoncé - Déjà Vu.flac",  # latin-1 chars
        "東京 - track.wav",  # CJK
        "Ē.aiff",  # strips to empty ASCII → fallback
        "",  # degenerate
        'a"quote.mp3',  # embedded double-quote
        "back\\slash.mp3",  # embedded backslash
        "tab\tnew\nline.mp3",  # control chars
        "cafécontrol.mp3",  # latin-1 + C1 control
    ],
)
def test_content_disposition_always_latin1_encodable(name: str) -> None:
    value = _content_disposition_inline(name)
    # THE invariant that was violated: header values must encode as latin-1.
    value.encode("latin-1")


def test_content_disposition_ascii_simple_form() -> None:
    assert _content_disposition_inline("song.mp3") == 'inline; filename="song.mp3"'


def test_content_disposition_non_ascii_uses_rfc6266() -> None:
    value = _content_disposition_inline(NON_LATIN1_NAME)
    assert "filename*=utf-8''" in value
    assert "ANN%C4%92" in value  # U+0112 percent-encoded as utf-8
    assert 'filename="' in value  # ASCII fallback present for legacy clients


def test_content_disposition_all_non_ascii_falls_back_to_audio() -> None:
    # Name with zero ASCII chars strips to empty → non-empty "audio" fallback.
    assert 'filename="audio"' in _content_disposition_inline("東京アイ")


def test_content_disposition_escapes_quoted_string_specials() -> None:
    # Embedded " and \ must be backslash-escaped (RFC 7230 quoted-string),
    # else the filename= token is malformed / header-injectable on reuse.
    assert _content_disposition_inline('a"b.mp3') == 'inline; filename="a\\"b.mp3"'
    assert _content_disposition_inline("a\\b.mp3") == 'inline; filename="a\\\\b.mp3"'


def test_content_disposition_strips_control_chars() -> None:
    # Newlines/tabs would fold the header — must be dropped from the token.
    assert _content_disposition_inline("a\tb\nc.mp3") == 'inline; filename="abc.mp3"'


# --- integration: the real endpoint no longer 500s on a non-latin-1 file ---


def test_stream_non_latin1_filename(sandbox_root: Path) -> None:
    f = sandbox_root / NON_LATIN1_NAME
    f.write_bytes(b"FORM\x00\x00\x00\x10AIFF" + b"\x00" * 64)

    # Build the query with proper percent-encoding of the unicode path.
    from urllib.parse import quote

    url = "/api/stream?path=" + quote(str(f))

    full = _get(url)
    assert full.status_code == 200, full.text
    assert "filename*=utf-8''" in full.headers["content-disposition"]
    # The actual response header — not just the helper — must survive the ASGI
    # latin-1 header encoding that originally raised UnicodeEncodeError → 500.
    full.headers["content-disposition"].encode("latin-1")

    ranged = _get(url, headers={"Range": "bytes=0-15"})
    assert ranged.status_code == 206, ranged.text
    assert "filename*=utf-8''" in ranged.headers["content-disposition"]
    # Ranged path is the dominant one (browser audio seeking) — same invariant.
    ranged.headers["content-disposition"].encode("latin-1")
