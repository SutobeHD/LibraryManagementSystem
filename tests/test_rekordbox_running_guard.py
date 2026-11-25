"""Live master.db writers refuse while Rekordbox runs (B13); playlist create + XML export.

Rekordbox keeps master.db open and overwrites or corrupts rows written behind its back.
Every route that reaches a live master.db write answers 409 before touching the library
while a Rekordbox process runs; an XML library never triggers the process scan.

Also covers ``/api/playlists/create`` (answered "success" with the whole node, or with
``id: null`` when the live write failed) and ``/api/rekordbox/export`` (joined the
client's file name onto ``exports/`` unchecked: ``../x.xml`` or an absolute path wrote
outside it, ``None`` was a 500).

Every library is a stub and every file lives in ``tmp_path``; no real master.db or
Rekordbox process is touched.
"""

from __future__ import annotations

import asyncio
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import httpx
import pytest

from app import main, rekordbox_bridge
from app.main import app

GUARDED: list[tuple[str, str, dict[str, Any] | None]] = [
    ("POST", "/api/track/1", {"Rating": 3}),
    ("PATCH", "/api/tracks/batch", {"track_ids": ["1"], "updates": {"Rating": 3}}),
    ("POST", "/api/mytags", {"name": "Peak"}),
    ("DELETE", "/api/mytags/7", None),
    ("POST", "/api/track/1/mytags", {"tag_ids": ["7"]}),
    ("DELETE", "/api/track/1", None),
    ("POST", "/api/playlists/create", {"name": "New"}),
    ("POST", "/api/playlists/rename", {"pid": "1", "name": "x"}),
    ("POST", "/api/playlists/move", {"pid": "1", "parent_id": "ROOT"}),
    ("POST", "/api/playlists/delete", {"pid": "1"}),
    ("POST", "/api/playlists/add-track", {"pid": "1", "track_id": "1"}),
    ("POST", "/api/playlists/remove-track", {"pid": "1", "track_id": "1"}),
    ("POST", "/api/playlists/reorder", {"pid": "1", "track_id": "1", "target_index": 0}),
    ("POST", "/api/playlists/smart/create", {"name": "S"}),
    ("POST", "/api/playlists/folder/create", {"name": "F"}),
    ("POST", "/api/library/clean-titles", {"track_ids": ["1"]}),
    ("POST", "/api/library/smart-playlists", {}),
    ("POST", "/api/rekordbox/import", {"xml_path": "C:/nowhere/rb.xml"}),
    ("POST", "/api/library/scan-folder", {"path": "C:/nowhere"}),
    ("POST", "/api/library/import-paths", {"paths": ["C:/nowhere/a.mp3"]}),
    ("POST", "/api/tools/duplicates/merge", {"keep_id": "1", "remove_ids": ["2"]}),
    ("POST", "/api/tools/duplicates/merge-all", None),
    ("POST", "/api/duplicates/merge", {"keep_path": "C:/a.mp3", "remove_paths": ["C:/b.mp3"]}),
    ("POST", "/api/soundcloud/sync", {"playlist_ids": [1]}),
    ("POST", "/api/soundcloud/sync-all", None),
    ("POST", "/api/soundcloud/merge", {"playlist_ids": [1], "merged_name": "M"}),
    (
        "POST",
        "/api/usb/playcount/resolve",
        {"resolutions": [], "usb_root": "C:/nowhere", "usb_xml_path": "C:/nowhere/rb.xml"},
    ),
]
_IDS = [f"{m} {u}" for m, u, _ in GUARDED]


class _RecordingDB:
    """Facade stand-in: every public method call lands in ``calls``."""

    def __init__(self, mode: str, create_result: Any = None) -> None:
        self.mode = mode
        self.loaded = True
        self.live_db_path = "C:/nowhere/master.db"
        self.tracks: dict[str, Any] = {}
        self.playlists: list[dict[str, Any]] = []
        self.calls: list[str] = []
        self._create_result = {"ID": "1"} if create_result is None else create_result

    @property
    def active_db(self) -> _RecordingDB:
        return self

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)

        def _call(*_a: Any, **_k: Any) -> Any:
            self.calls.append(name)
            return self._create_result if name.startswith("create") else True

        return _call


@pytest.fixture
def tripwires(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Entry points that reach a library through their own ``db`` import, not ``main.db``."""
    hit: list[str] = []

    def _wire(label: str) -> Any:
        def _f(*_a: Any, **_k: Any) -> Any:
            hit.append(label)
            raise AssertionError(f"{label} ran past the Rekordbox guard")

        return staticmethod(_f)

    for owner, attr in (
        (main.LibraryTools, "clean_track_titles"),
        (main.LibraryTools, "generate_smart_playlists"),
        (main.LibraryTools, "find_duplicates"),
        (main.ImportManager, "process_import"),
        (main.RekordboxBridge, "import_library"),
    ):
        monkeypatch.setattr(owner, attr, _wire(f"{owner.__name__}.{attr}"))
    monkeypatch.setattr(main, "_sc_access_token", lambda: None)  # no keyring, no network
    return hit


def _send(
    method: str,
    url: str,
    body: dict[str, Any] | None,
    headers: dict[str, str],
    **kw: Any,
) -> httpx.Response:
    async def _go() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            if body is None:
                return await ac.request(method, url, headers=headers, **kw)
            return await ac.request(method, url, json=body, headers=headers, **kw)

    return asyncio.run(_go())


# --- B13: Rekordbox-running guard --------------------------------------------------


@pytest.mark.parametrize(("method", "url", "body"), GUARDED, ids=_IDS)
def test_live_write_refused_while_rekordbox_runs(
    monkeypatch: pytest.MonkeyPatch,
    auth_token: dict[str, str],
    tripwires: list[str],
    method: str,
    url: str,
    body: dict[str, Any] | None,
) -> None:
    fake = _RecordingDB("live")
    monkeypatch.setattr(main, "db", fake)
    monkeypatch.setattr(main, "_is_rekordbox_running", lambda: True)

    r = _send(method, url, body, auth_token)

    assert r.status_code == 409, r.text
    assert r.json()["detail"].startswith("Rekordbox is running. Close it before ")
    assert fake.calls == []
    assert tripwires == []


def test_live_audio_upload_refused_before_the_file_is_saved(
    monkeypatch: pytest.MonkeyPatch, auth_token: dict[str, str], tmp_path: Path
) -> None:
    monkeypatch.setattr(main, "db", _RecordingDB("live"))
    monkeypatch.setattr(main, "_is_rekordbox_running", lambda: True)
    monkeypatch.setattr(main, "MUSIC_DIR", tmp_path)

    files = {"files": ("a.mp3", b"ID3", "audio/mpeg")}
    r = _send("POST", "/api/audio/import", None, auth_token, files=files)

    assert r.status_code == 409, r.text
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(("method", "url", "body"), GUARDED, ids=_IDS)
def test_xml_mode_never_scans_for_rekordbox(
    monkeypatch: pytest.MonkeyPatch,
    auth_token: dict[str, str],
    tripwires: list[str],
    method: str,
    url: str,
    body: dict[str, Any] | None,
) -> None:
    scans: list[bool] = []
    monkeypatch.setattr(main, "db", _RecordingDB("xml"))
    monkeypatch.setattr(main, "_is_rekordbox_running", lambda: scans.append(True) or True)

    r = _send(method, url, body, auth_token)

    assert "Rekordbox is running" not in r.text  # other 4xx/5xx from the stub are fine
    assert scans == []


def test_live_write_goes_through_while_rekordbox_is_closed(
    monkeypatch: pytest.MonkeyPatch, auth_token: dict[str, str]
) -> None:
    fake = _RecordingDB("live")
    monkeypatch.setattr(main, "db", fake)
    monkeypatch.setattr(main, "_is_rekordbox_running", lambda: False)

    r = _send("POST", "/api/playlists/rename", {"pid": "1", "name": "x"}, auth_token)

    assert r.status_code == 200, r.text
    assert fake.calls == ["rename_playlist"]


def test_scan_failure_fails_open(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    import types

    def _boom() -> bool:
        raise RuntimeError("process table unreadable")

    monkeypatch.setitem(sys.modules, "rbox", types.SimpleNamespace(is_rekordbox_running=_boom))
    assert main._is_rekordbox_running() is False


# --- /api/usb/playcount/resolve -------------------------------------------------------


@pytest.fixture
def resolved(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """``resolve_playcounts`` stub: records the master.db path the route hands it."""
    db_paths: list[str] = []

    def _resolve(resolutions: list[dict], pc_db_path: str, usb_xml_path: str) -> dict:
        db_paths.append(pc_db_path)
        return {"committed": len(resolutions), "errors": []}

    monkeypatch.setattr(main, "resolve_playcounts", _resolve)
    monkeypatch.setattr(main, "load_usb_sync_meta", lambda _root: {})
    monkeypatch.setattr(main, "save_usb_sync_meta", lambda _root, _meta: None)
    return db_paths


_RESOLVE_BODY = {
    "resolutions": [{"track_id": "1", "strategy": "take_max", "pc_count": 2, "usb_count": 5}],
    "usb_root": "C:/nowhere",
    "usb_xml_path": "C:/nowhere/rb.xml",
}


def test_playcount_resolve_writes_the_live_master_db(
    monkeypatch: pytest.MonkeyPatch, auth_token: dict[str, str], resolved: list[str]
) -> None:
    fake = _RecordingDB("live")
    fake.live_db_path = "D:/libs/rekordbox6/master.db"  # not %APPDATA%/Pioneer/rekordbox
    monkeypatch.setattr(main, "db", fake)
    monkeypatch.setattr(main, "_is_rekordbox_running", lambda: False)

    r = _send("POST", "/api/usb/playcount/resolve", _RESOLVE_BODY, auth_token)

    assert r.status_code == 200, r.text
    assert r.json()["data"]["committed"] == 1
    assert resolved == [str(Path("D:/libs/rekordbox6/master.db"))]


def test_playcount_resolve_refused_while_rekordbox_runs(
    monkeypatch: pytest.MonkeyPatch, auth_token: dict[str, str], resolved: list[str]
) -> None:
    monkeypatch.setattr(main, "db", _RecordingDB("live"))
    monkeypatch.setattr(main, "_is_rekordbox_running", lambda: True)

    r = _send("POST", "/api/usb/playcount/resolve", _RESOLVE_BODY, auth_token)

    assert r.status_code == 409, r.text
    assert r.json()["detail"] == "Rekordbox is running. Close it before syncing play counts."
    assert resolved == []  # neither master.db nor the USB XML was touched


def test_playcount_resolve_in_xml_mode_patches_only_the_usb_xml(
    monkeypatch: pytest.MonkeyPatch, auth_token: dict[str, str], tmp_path: Path
) -> None:
    """XML library: no master.db to write, but the USB half of the sync still runs."""
    usb_xml = tmp_path / "rekordbox.xml"
    usb_xml.write_text(
        '<?xml version="1.0" encoding="UTF-8"?><DJ_PLAYLISTS Version="1.0.0">'
        '<COLLECTION Entries="1"><TRACK TrackID="1" Name="A" PlayCount="2"/></COLLECTION>'
        "</DJ_PLAYLISTS>",
        encoding="utf-8",
    )
    monkeypatch.setattr(main, "db", _RecordingDB("xml"))
    monkeypatch.setattr(main, "_is_rekordbox_running", lambda: True)  # XML mode never scans
    saved: list[dict] = []
    monkeypatch.setattr(main, "load_usb_sync_meta", lambda _root: {})
    monkeypatch.setattr(main, "save_usb_sync_meta", lambda _root, meta: saved.append(meta))
    body = {**_RESOLVE_BODY, "usb_root": str(tmp_path), "usb_xml_path": str(usb_xml)}

    r = _send("POST", "/api/usb/playcount/resolve", body, auth_token)

    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data == {"committed": 0, "usb_updated": 1, "pc_db_skipped": True, "errors": []}
    track = ET.parse(usb_xml).getroot().find(".//TRACK")
    assert track is not None and track.get("PlayCount") == "5"  # take_max(2, 5)
    assert saved and saved[0]["last_sync_ts"] > 0


# --- /api/playlists/create ---------------------------------------------------------


def test_create_playlist_answers_the_id_string(
    monkeypatch: pytest.MonkeyPatch, auth_token: dict[str, str]
) -> None:
    node = {"ID": 123, "Name": "New", "Type": "1", "ParentID": "ROOT"}
    monkeypatch.setattr(main, "db", _RecordingDB("live", create_result=node))
    monkeypatch.setattr(main, "_is_rekordbox_running", lambda: False)

    r = _send("POST", "/api/playlists/create", {"name": "New"}, auth_token)

    assert r.status_code == 200, r.text
    assert r.json() == {"status": "success", "id": "123"}


@pytest.mark.parametrize("result", [False, {}, {"Name": "no id"}])
def test_create_playlist_failure_is_500(
    monkeypatch: pytest.MonkeyPatch, auth_token: dict[str, str], result: Any
) -> None:
    # live create_playlist returns None on an rbox error (False here: the stub maps None)
    monkeypatch.setattr(main, "db", _RecordingDB("live", create_result=result))
    monkeypatch.setattr(main, "_is_rekordbox_running", lambda: False)

    r = _send("POST", "/api/playlists/create", {"name": "New"}, auth_token)

    assert r.status_code == 500, r.text
    assert "success" not in r.text


def test_create_playlist_xml_library_answers_the_new_id(
    monkeypatch: pytest.MonkeyPatch, auth_token: dict[str, str], tmp_path: Path
) -> None:
    from app.database import RekordboxDB

    lib = tmp_path / "lib.xml"
    lib.write_text(
        '<?xml version="1.0" encoding="UTF-8"?><DJ_PLAYLISTS Version="1.0.0">'
        '<COLLECTION Entries="0"/><PLAYLISTS><NODE Type="0" Name="ROOT" Count="0"/>'
        "</PLAYLISTS></DJ_PLAYLISTS>",
        encoding="utf-8",
    )
    db = RekordboxDB()
    db.mode = "xml"
    assert db.xml_db.load_xml(str(lib))
    db.loaded = True
    monkeypatch.setattr(main, "db", db)

    r = _send("POST", "/api/playlists/create", {"name": "New"}, auth_token)

    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    assert isinstance(pid, str) and pid
    assert db.get_playlist_by_id(pid) is not None


# --- /api/rekordbox/export ---------------------------------------------------------


class _TrackSource:
    def get_track_details(self, tid: str) -> dict[str, Any] | None:
        if tid != "1":
            return None
        return {"ID": "1", "Title": "T", "path": "C:/Music/t.aiff", "StockDate": "2022-02-02"}


@pytest.fixture
def exports(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    out = tmp_path / "sandbox" / "exports"
    out.mkdir(parents=True)
    monkeypatch.setattr(main, "EXPORT_DIR", out)
    monkeypatch.setattr(rekordbox_bridge, "db", _TrackSource())
    return out


@pytest.mark.parametrize(
    ("filename", "written"),
    [
        (None, "rekordbox_export.xml"),
        ("", "rekordbox_export.xml"),
        ("my set", "my set.xml"),
        ("my set.txt", "my set.txt.xml"),
        ("Set 21.11.2026", "Set 21.11.2026.xml"),
        ("loud.XML", "loud.xml"),  # generator normalises the suffix case
        ("../escape.xml", "escape.xml"),
        ("..\\..\\escape.xml", "escape.xml"),
        ("C:\\Windows\\abs.xml", "abs.xml"),
        ("/etc/abs.xml", "abs.xml"),
    ],
)
def test_export_stays_inside_exports(
    exports: Path, auth_token: dict[str, str], filename: str | None, written: str
) -> None:
    r = _send(
        "POST", "/api/rekordbox/export", {"track_ids": ["1"], "filename": filename}, auth_token
    )

    assert r.status_code == 200, r.text
    target = exports / written
    assert Path(r.json()["path"]) == target.resolve()
    assert [p.name for p in exports.iterdir()] == [written]
    assert [p.name for p in exports.parent.iterdir()] == ["exports"]  # nothing escaped
    track = ET.parse(target).getroot().find(".//TRACK")
    assert (track.get("TrackID"), track.get("Kind"), track.get("DateAdded")) == (
        "1",
        "AIFF File",
        "2022-02-02",
    )


@pytest.mark.parametrize("filename", ["..", ".", "a?b.xml", "a<b>.xml", "a|b", "x\x01.xml"])
def test_export_refuses_unusable_names(
    exports: Path, auth_token: dict[str, str], filename: str
) -> None:
    r = _send(
        "POST", "/api/rekordbox/export", {"track_ids": ["1"], "filename": filename}, auth_token
    )

    assert r.status_code == 400, r.text
    assert list(exports.iterdir()) == []


def test_export_with_no_known_track_is_400(exports: Path, auth_token: dict[str, str]) -> None:
    r = _send("POST", "/api/rekordbox/export", {"track_ids": ["nope"]}, auth_token)

    assert r.status_code == 400, r.text
    assert list(exports.iterdir()) == []
