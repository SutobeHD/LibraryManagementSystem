"""One artwork resolver for the app and the stick (`app/library_artwork.py`).

`GET /api/artwork` resolved master.db ImagePath inline; the USB export read the
file's embedded tags instead, so the stick showed other covers than the app. Both
now go through `resolve_artwork_path`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from app import library_artwork
from app.library_artwork import ArtworkPathError, library_artwork_file, resolve_artwork_path

REL = "/PIONEER/Artwork/0ab/12345-abcd/artwork.jpg"


@pytest.fixture
def share(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """APPDATA -> tmp; returns the Rekordbox share folder (with one cover in it)."""
    appdata = tmp_path / "appdata"
    root = appdata / "Pioneer" / "rekordbox" / "share"
    cover = root / REL.lstrip("/")
    cover.parent.mkdir(parents=True)
    cover.write_bytes(b"\xff\xd8 library cover")
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setattr(library_artwork, "COVERS_DIR", tmp_path / "covers")
    return root


def _status(path: str) -> int:
    with pytest.raises(ArtworkPathError) as err:
        resolve_artwork_path(path)
    return err.value.status


def test_imagepath_resolves_inside_the_share(share: Path) -> None:
    assert resolve_artwork_path(REL) == (share / REL.lstrip("/")).resolve()


def test_absolute_path_in_the_covers_folder_passes(share: Path, tmp_path: Path) -> None:
    covers = tmp_path / "covers"
    covers.mkdir()
    (covers / "a.png").write_bytes(b"png")
    assert resolve_artwork_path(str(covers / "a.png")) == (covers / "a.png").resolve()


def test_refusals_carry_the_routes_status(share: Path, tmp_path: Path) -> None:
    outside = tmp_path / "elsewhere" / "x.jpg"
    outside.parent.mkdir()
    outside.write_bytes(b"x")
    # A sibling whose name starts with "share": the old str.startswith check let it through.
    sibling = share.parent / "share_evil" / "x.jpg"
    sibling.parent.mkdir()
    sibling.write_bytes(b"x")

    assert _status("") == 404
    assert _status(str(share / "notes.txt")) == 400
    assert _status(str(outside)) == 403
    assert _status(str(sibling)) == 403
    assert _status("/PIONEER/../../../../elsewhere/x.jpg") == 403
    assert _status("/PIONEER/Artwork/0ab/gone/artwork.jpg") == 404


def test_without_appdata_a_share_path_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.setattr(library_artwork, "COVERS_DIR", tmp_path / "covers")
    assert library_artwork.rekordbox_share_dir() is None
    assert _status(REL) == 403


def test_library_artwork_file_is_none_where_the_route_refuses(share: Path) -> None:
    assert library_artwork_file(REL) == (share / REL.lstrip("/")).resolve()
    for bad in (None, "", "/PIONEER/Artwork/0ab/gone/artwork.jpg", str(share / "x.txt")):
        assert library_artwork_file(bad) is None


def _get(path: str) -> httpx.Response:
    from app.main import app

    async def _go() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 12345))
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            return await ac.get("/api/artwork", params={"path": path})

    return asyncio.run(_go())


def test_route_serves_and_refuses_through_the_resolver(share: Path, tmp_path: Path) -> None:
    ok = _get(REL)
    assert ok.status_code == 200
    assert ok.content == b"\xff\xd8 library cover"

    outside = tmp_path / "elsewhere.jpg"
    outside.write_bytes(b"x")
    assert _get(str(outside)).status_code == 403
    assert _get(str(share / "x.txt")).status_code == 400
    assert _get("/PIONEER/Artwork/0ab/gone/artwork.jpg").status_code == 404
