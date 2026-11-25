"""One artwork resolver for the app and the stick (`app/library_artwork.py`).

`GET /api/artwork` resolved master.db ImagePath inline; the USB export read the
file's embedded tags instead, so the stick showed other covers than the app. Both
now go through `resolve_artwork_path`.

The import used to write extracted covers to `%APPDATA%/Pioneer/app/data/covers`,
a folder the resolver refused (403): imported tracks showed no cover and reached
the stick with the embedded one. Import and resolver now share `COVERS_DIR`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
from mutagen.id3 import APIC, ID3

from app import library_artwork, services
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
    monkeypatch.setattr(library_artwork, "LEGACY_COVERS_DIR", tmp_path / "code" / "covers")
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


def test_covers_dir_is_the_per_user_data_folder_not_the_code_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    assert library_artwork._lms_data_dir() == tmp_path / "appdata" / "MusicLibraryManager"
    # The onefile sidecar unpacks the code tree to a temp dir that is deleted on exit.
    code_tree = Path(library_artwork.__file__).resolve().parent
    assert not library_artwork.COVERS_DIR.resolve().is_relative_to(code_tree)
    assert library_artwork.COVERS_DIR.name == "covers"


def test_legacy_covers_folders_stay_readable(share: Path, tmp_path: Path) -> None:
    pioneer_covers = share.parent.parent / "app" / "data" / "covers"  # old import target
    code_covers = tmp_path / "code" / "covers"
    for folder in (pioneer_covers, code_covers):
        folder.mkdir(parents=True)
        (folder / "old.jpg").write_bytes(b"old")
        assert resolve_artwork_path(str(folder / "old.jpg")) == (folder / "old.jpg").resolve()

    # Neighbours of the legacy folders are not part of the jail.
    evil = share.parent.parent / "app" / "data" / "covers_evil" / "x.jpg"
    evil.parent.mkdir(parents=True)
    evil.write_bytes(b"x")
    loose = share.parent.parent / "app" / "x.jpg"
    loose.write_bytes(b"x")
    assert _status(str(evil)) == 403
    assert _status(str(loose)) == 403
    assert _status(str(pioneer_covers / "notes.txt")) == 400


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


class _Facade:
    """The `db` facade as `ImportManager.process_import` sees it (XML mode)."""

    mode = "xml"

    def __init__(self) -> None:
        self.playlists = [{"ID": "p1", "Name": "Import"}]
        self.added: list[dict] = []

    def add_track(self, track_data: dict) -> str:
        self.added.append(track_data)
        return "1"

    def get_playlist_tracks(self, pid: str) -> list[dict]:
        return [{"ID": "1"}]  # already in "Import": no XML auto-export side effect


def test_imported_cover_is_served_and_picked_for_the_stick(
    share: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    art = b"\xff\xd8\xff\xe0 embedded cover"
    audio = tmp_path / "music" / "track.mp3"
    audio.parent.mkdir()
    audio.write_bytes(b"\xff\xfb" + b"\0" * 64)
    tags = ID3()
    tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="", data=art))
    tags.save(str(audio))

    facade = _Facade()
    monkeypatch.setattr(services, "db", facade)
    monkeypatch.setattr(services, "REKORDBOX_ROOT", share.parent)
    monkeypatch.setattr("app.audio_tags.read_tags", lambda p: {"title": "T"})
    monkeypatch.setattr(services.SettingsManager, "load", lambda: {"write_tags_to_files": False})
    monkeypatch.setattr("app.anlz_sidecar.write_companion_anlz", lambda p, r=None: None)

    services.ImportManager.process_import(
        audio, analysis_result={"bpm": 120.0, "key": "Am", "duration": 10.0, "beats": []}
    )

    stored = facade.added[0]["Artwork"]
    covers = (tmp_path / "covers").resolve()
    assert stored and Path(stored).is_relative_to(covers)
    assert not (share.parent.parent / "app").exists()  # nothing left in Pioneer's folder
    served = _get(stored)
    assert served.status_code == 200
    assert served.content == art
    assert library_artwork_file(stored) == Path(stored)
