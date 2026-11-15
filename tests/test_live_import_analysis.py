"""An imported track's analysis must reach master.db (B4, 0.1 core-loop test).

``add_track`` used to write only title / artist / album / genre / comment. After a
library reload the track showed BPM 0 and no key, the USB export wrote bpmx100 = 0 and
length = 0, and analyze-full refused the track (no AnalysisDataPath).

No real master.db: it is SQLCipher-encrypted. The rbox handle is a stand-in whose
integer columns reject C-long overflow like rbox does.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app import services
from app.live_database import LiveRekordboxDB

_UUID = "44d00cc2-7321-4a2e-88d7-fbcc7074c1b3"
_REL = "/PIONEER/USBANLZ/44d/00cc2-7321-4a2e-88d7-fbcc7074c1b3/ANLZ0000.DAT"


class _Row:
    def __init__(self, cid: str) -> None:
        self.id = cid
        self.uuid = _UUID
        self.title = ""
        self.commnt = ""
        self.folder_path = "C:/music/a.wav"
        self.bpm: int | None = None
        self.length: int | None = None
        self.analysed = 0
        self.analysis_data_path: str | None = None


class _MasterDb:
    """rbox.MasterDb stand-in: one row, records every write."""

    def __init__(self, share: Path) -> None:
        self.share = share
        self.row = _Row("1")
        self.writes: list[tuple[str, Any]] = []
        self.refuse_update = False

    def create_content(self, path: str) -> _Row:
        self.row.folder_path = path
        return self.row

    def get_content_by_id(self, tid: str) -> _Row | None:
        return self.row if str(tid) == "1" else None

    def update_content(self, item: _Row) -> None:
        if self.refuse_update:
            raise RuntimeError("database is locked")
        self.writes.append(
            ("update_content", (item.bpm, item.length, item.analysed, item.analysis_data_path))
        )

    def update_content_key(self, tid: str, name: str) -> None:
        self.writes.append(("update_content_key", name))

    def update_content_artist(self, tid: str, name: str) -> None:
        self.writes.append(("update_content_artist", name))

    def share_directory(self) -> str:
        return str(self.share)


@pytest.fixture
def master(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _MasterDb:
    handle = _MasterDb(tmp_path / "share")
    monkeypatch.setattr(LiveRekordboxDB, "db", property(lambda self: handle))
    return handle


@pytest.fixture
def live(master: _MasterDb) -> LiveRekordboxDB:
    db = LiveRekordboxDB("does-not-exist.db")
    db.tracks = {}
    return db


_TRACK = {
    "path": "C:/music/a.wav",
    "Title": "T",
    "BPM": 127.66,
    "TotalTime": 185.6,
    "Key": "Am",
    "KeyID": 22,
}


def test_add_track_writes_bpm_length_and_key(live: LiveRekordboxDB, master: _MasterDb) -> None:
    tid = live.add_track(dict(_TRACK))

    assert tid == "1"
    assert master.row.bpm == 12766  # centi-BPM, as Rekordbox stores it
    assert master.row.length == 186  # whole seconds
    assert ("update_content_key", "Am") in master.writes
    assert live.tracks["1"]["BPM"] == 127.66
    assert live.tracks["1"]["TotalTime"] == 186.0
    assert live.tracks["1"]["Key"] == "Am"
    # analysed / AnalysisDataPath belong to the ANLZ files, not to this step
    assert master.row.analysed == 0
    assert master.row.analysis_data_path is None


@pytest.mark.parametrize(
    ("key", "key_id", "expected"),
    [
        ("C#m", 0, "Dbm"),  # engine spells sharps, Rekordbox flats
        ("F#", 0, "F#"),
        ("A#m", 0, "Bbm"),
        ("Unknown", 0, None),
        ("Am", 14, "Dbm"),  # the id wins over the text
    ],
)
def test_import_key_is_stored_in_rekordbox_spelling(
    live: LiveRekordboxDB, master: _MasterDb, key: str, key_id: int, expected: str | None
) -> None:
    live.add_track({**_TRACK, "Key": key, "KeyID": key_id})
    keys = [v for name, v in master.writes if name == "update_content_key"]
    assert keys == ([expected] if expected else [])


def test_refused_analysis_write_leaves_the_cache_at_what_master_db_holds(
    live: LiveRekordboxDB, master: _MasterDb
) -> None:
    master.refuse_update = True
    # update_track_metadata refuses too (same handle) - that path already raises,
    # so only the analysis columns are exercised here.
    track = {k: v for k, v in _TRACK.items() if k != "Title"}

    tid = live.add_track(track)

    assert tid == "1"
    assert live.tracks["1"]["BPM"] == 0.0  # not 127.66: master.db never got it
    assert live.tracks["1"]["TotalTime"] == 0.0


def _fake_anlz_writer(written: list[dict[str, Any]], with_dat: bool = True):
    def _write(**kw: Any) -> dict[str, str]:
        written.append(kw)
        out = {}
        if with_dat:
            dat = Path(kw["anlz_dir"]) / f"{kw['filename_base']}.DAT"
            dat.write_bytes(b"PMAI")
            out["dat"] = str(dat)
        return out

    return _write


def test_attach_import_anlz_uses_rekordbox_share_layout(
    live: LiveRekordboxDB, master: _MasterDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    written: list[dict[str, Any]] = []
    monkeypatch.setattr("app.anlz_writer.write_anlz_files", _fake_anlz_writer(written))

    rel = live.attach_import_anlz("1", {"status": "ok", "bpm": 128.0})

    expected_dir = master.share / "PIONEER" / "USBANLZ" / "44d" / _UUID[3:]
    assert rel == _REL
    assert Path(written[0]["anlz_dir"]) == expected_dir.resolve()
    assert (expected_dir / "ANLZ0000.DAT").is_file()
    assert master.row.analysis_data_path == _REL
    assert master.row.analysed == 105


def test_attach_import_anlz_records_nothing_without_a_dat(
    live: LiveRekordboxDB, master: _MasterDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    written: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "app.anlz_writer.write_anlz_files", _fake_anlz_writer(written, with_dat=False)
    )

    assert live.attach_import_anlz("1", {"status": "ok"}) is None
    assert master.row.analysis_data_path is None
    assert master.row.analysed == 0
    assert master.writes == []


def test_attach_import_anlz_removes_its_files_when_master_db_refuses(
    live: LiveRekordboxDB, master: _MasterDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    written: list[dict[str, Any]] = []
    monkeypatch.setattr("app.anlz_writer.write_anlz_files", _fake_anlz_writer(written))
    master.refuse_update = True

    assert live.attach_import_anlz("1", {"status": "ok"}) is None
    assert master.writes == []  # nothing landed in master.db
    assert not (master.share / "PIONEER" / "USBANLZ" / "44d").exists()  # no orphan trio


def test_attach_import_anlz_never_replaces_a_recorded_path(
    live: LiveRekordboxDB, master: _MasterDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    master.row.analysis_data_path = "/PIONEER/USBANLZ/abc/rekordbox-own/ANLZ0000.DAT"
    written: list[dict[str, Any]] = []
    monkeypatch.setattr("app.anlz_writer.write_anlz_files", _fake_anlz_writer(written))

    assert live.attach_import_anlz("1", {"status": "ok"}) is None
    assert written == []
    assert master.writes == []


def test_attach_import_anlz_refuses_a_uuid_that_escapes_the_share(
    live: LiveRekordboxDB, master: _MasterDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    master.row.uuid = "../../evil"
    written: list[dict[str, Any]] = []
    monkeypatch.setattr("app.anlz_writer.write_anlz_files", _fake_anlz_writer(written))

    assert live.attach_import_anlz("1", {"status": "ok"}) is None
    assert written == []


# --- import pipeline --------------------------------------------------------------


class _Facade:
    """The ``db`` facade as ``ImportManager.process_import`` sees it in live mode."""

    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.playlists: list[dict[str, Any]] = [{"ID": "p1", "Name": "Import"}]
        self.added: list[dict[str, Any]] = []
        self.attached: list[tuple[str, dict[str, Any]]] = []

    def add_track(self, track_data: dict[str, Any]) -> str:
        self.added.append(track_data)
        return "1"

    def attach_import_anlz(self, tid: str, result: dict[str, Any]) -> str:
        self.attached.append((tid, result))
        return _REL

    def get_playlist_tracks(self, pid: str) -> list[dict[str, Any]]:
        return [{"ID": "1"}]  # already in "Import": no XML auto-export side effect


_FULL = {
    "status": "ok",
    "bpm": 128.0,
    "key": "Am",
    "camelot": "8A",
    "key_id": 22,
    "duration": 60.0,
    "beats": [{"time_ms": 500, "tempo": 12800, "beat_number": 1}],
}


@pytest.mark.parametrize("mode", ["live", "xml"])
def test_import_puts_anlz_in_the_share_in_live_mode_never_next_to_the_audio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    audio = tmp_path / "music" / "a.wav"
    audio.parent.mkdir()
    audio.write_bytes(b"RIFF")
    facade = _Facade(mode)
    companion: list[Path] = []
    monkeypatch.setattr(services, "db", facade)
    monkeypatch.setattr(services, "REKORDBOX_ROOT", tmp_path / "rb" / "rekordbox")
    monkeypatch.setattr("app.audio_tags.read_tags", lambda p: {"title": "T"})
    monkeypatch.setattr(services.SettingsManager, "load", lambda: {"write_tags_to_files": False})
    monkeypatch.setattr(
        "app.anlz_sidecar.write_companion_anlz", lambda p, r=None: companion.append(p)
    )

    tid, _ = services.ImportManager.process_import(audio, analysis_result=dict(_FULL))

    assert tid == "1"
    sent = facade.added[0]
    assert (sent["BPM"], sent["TotalTime"], sent["KeyID"]) == (128.0, 60.0, 22)
    if mode == "live":
        assert facade.attached == [("1", _FULL)]
        assert companion == []
    else:
        assert facade.attached == []
        assert companion == [audio]
    assert not (audio.parent / ".lms_anlz").exists()


@pytest.mark.parametrize(
    "result",
    [
        {**_FULL, "beats": []},  # analysis ran but found nothing
        {**_FULL, "status": "error"},
        {k: v for k, v in _FULL.items() if k != "status"},
    ],
)
def test_import_never_attaches_anlz_from_an_unusable_analysis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, result: dict[str, Any]
) -> None:
    # analysed=105 makes Rekordbox trust the files and never re-analyse the track.
    audio = tmp_path / "music" / "a.wav"
    audio.parent.mkdir()
    audio.write_bytes(b"RIFF")
    facade = _Facade("live")
    monkeypatch.setattr(services, "db", facade)
    monkeypatch.setattr(services, "REKORDBOX_ROOT", tmp_path / "rb" / "rekordbox")
    monkeypatch.setattr("app.audio_tags.read_tags", lambda p: {"title": "T"})
    monkeypatch.setattr(services.SettingsManager, "load", lambda: {"write_tags_to_files": False})

    services.ImportManager.process_import(audio, analysis_result=result)

    assert facade.attached == []
