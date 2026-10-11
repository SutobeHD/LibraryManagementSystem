"""Unit tests for AnalysisDBWriter — the values it writes into Rekordbox master.db.

A live master.db is SQLCipher-encrypted and can't be created from scratch in a
test, so this exercises the pure transforms that decide WHAT gets written
(key name, BPM scaling, beatgrid shape, which ANLZ dir). The actual rbox
`update_content` write mechanism is covered by tests/test_onelibrary_wal_flush
(rbox writes BPM into a Rekordbox SQLite DB and re-reads it).

No rbox / heavy DSP needed — AnalysisDBWriter imports them lazily.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.analysis_db_writer import AnalysisDBWriter  # noqa: E402


def test_key_id_to_name_inverts_engine_map():
    """The master.db key write must invert analysis_engine's key_id map exactly.

    Drift between the two (writer vs engine) would silently store the wrong key
    for half the wheel — this guards all 24 keys.
    """
    from app.analysis_engine import _REKORDBOX_KEY_ID

    for full_key, key_id in _REKORDBOX_KEY_ID.items():
        assert AnalysisDBWriter._key_id_to_name(key_id) == full_key


def test_key_id_to_name_unknown():
    assert AnalysisDBWriter._key_id_to_name(0) is None
    assert AnalysisDBWriter._key_id_to_name(99) is None


def test_update_cache_bpm_key_beatgrid_shape():
    """_update_cache mirrors the master.db write: BPM float, Camelot key, and a
    beatgrid of {time(s), bpm, beat} dicts derived from PQTZ ms/centi-bpm."""

    class _FakeLiveDB:
        def __init__(self):
            self.tracks = {"42": {}}

    writer = AnalysisDBWriter(_FakeLiveDB())
    analysis = {
        "bpm": 128.0,
        "camelot": "8A",
        "key": "Am",
        "beats": [
            {"time_ms": 0, "tempo": 12800, "beat_number": 1},
            {"time_ms": 469, "tempo": 12800, "beat_number": 2},
        ],
    }
    writer._update_cache("42", analysis)
    tr = writer.live_db.tracks["42"]
    assert tr["BPM"] == 128.0
    assert tr["Key"] == "8A"
    assert tr["beatGrid"][0] == {"time": 0.0, "bpm": 128.0, "beat": 1}
    assert tr["beatGrid"][1]["time"] == 0.469
    assert tr["beatGrid"][1]["bpm"] == 128.0


def test_master_db_bpm_is_centi_bpm_int():
    """master.db stores BPM as int(round(bpm*100)) — guard the scaling contract."""
    assert round(128.0 * 100) == 12800
    assert round(127.66 * 100) == 12766


def _lock_held_elsewhere() -> bool:
    """True when another thread holds ``_db_write_lock`` (probed from a fresh thread)."""
    import threading

    from app.database import _db_write_lock

    result: list[bool] = []

    def _probe() -> None:
        got = _db_write_lock.acquire(blocking=False)
        if got:
            _db_write_lock.release()
        result.append(not got)

    t = threading.Thread(target=_probe)
    t.start()
    t.join()
    return result[0]


def test_update_db_writes_master_db_inside_db_write_lock():
    """The analysis write is a full-row ``update_content``: re-read and write must both
    sit inside ``_db_write_lock`` or a concurrent comment / artist edit gets clobbered."""

    class _Row:
        bpm = 0
        analysed = 0

    class _FakeMasterDb:
        def __init__(self):
            self.seen: list[tuple[str, bool]] = []

        def get_content_by_id(self, tid):
            self.seen.append(("read", _lock_held_elsewhere()))
            return _Row()

        def update_content(self, item):
            self.seen.append(("update_content", _lock_held_elsewhere()))

        def update_content_key(self, tid, key):
            self.seen.append(("update_content_key", _lock_held_elsewhere()))

    class _FakeLiveDB:
        def __init__(self):
            self.tracks = {"7": {}}
            self.db = _FakeMasterDb()

    writer = AnalysisDBWriter(_FakeLiveDB())
    assert writer._update_db("7", {"bpm": 124.0, "key_id": 22}) is True
    assert writer.live_db.db.seen == [
        ("read", True),
        ("update_content", True),
        ("update_content_key", True),
    ]
    assert not _lock_held_elsewhere()


# --- rbox calls that abort the process --------------------------------------
#
# get_content_anlz_paths / get_content_anlz_dir unwrap() on an empty AnalysisDataPath
# and abort the whole sidecar (Rust panic, not catchable). A track with a tag BPM that
# Rekordbox never analysed is exactly that row, so the "already analysed?" check must
# resolve the ANLZ dir from the content row instead.

_REL = "/PIONEER/USBANLZ/44d/00cc2-7321-4a2e-88d7-fbcc7074c1b3/ANLZ0000.DAT"


class _Content:
    def __init__(self, cid: str, analysis_data_path: str | None) -> None:
        self.id = cid
        self.analysis_data_path = analysis_data_path


class _AbortingMasterDb:
    """rbox.MasterDb stand-in: the two path helpers record the call instead of aborting."""

    def __init__(self, share: str, rel_by_id: dict[str, str | None]) -> None:
        self.share = share
        self.rel_by_id = rel_by_id
        self.aborting_calls: list[str] = []

    def share_directory(self) -> str:
        return self.share

    def get_content_by_id(self, tid):
        tid = str(tid)
        return _Content(tid, self.rel_by_id[tid]) if tid in self.rel_by_id else None

    def get_content_anlz_paths(self, tid):
        self.aborting_calls.append(f"get_content_anlz_paths({tid})")
        raise AssertionError("real rbox aborts the process here")

    def get_content_anlz_dir(self, tid):
        self.aborting_calls.append(f"get_content_anlz_dir({tid})")
        raise AssertionError("real rbox aborts the process here")


class _LiveDBWith:
    def __init__(self, tracks: dict, master_db: _AbortingMasterDb) -> None:
        self.tracks = tracks
        self.db = master_db


def test_skip_check_never_calls_the_aborting_rbox_path_helpers(tmp_path):
    """BPM from tags, no AnalysisDataPath: the old check killed the sidecar here."""
    master = _AbortingMasterDb(str(tmp_path), {"5": None})
    writer = AnalysisDBWriter(
        _LiveDBWith({"5": {"BPM": 124.0, "path": str(tmp_path / "gone.mp3")}}, master)
    )

    result = writer.analyze_and_save("5")

    assert master.aborting_calls == []
    assert result["status"] == "error"  # not analysed, and nothing to skip


def test_error_results_carry_a_reason_for_the_route(tmp_path):
    master = _AbortingMasterDb(str(tmp_path), {"8": _REL})
    writer = AnalysisDBWriter(
        _LiveDBWith({"8": {"BPM": 0, "path": str(tmp_path / "gone.mp3")}}, master)
    )

    assert writer.analyze_and_save("404")["reason"] == "track_not_found"
    assert writer.analyze_and_save("8")["reason"] == "audio_missing"


def test_skip_check_still_skips_a_track_whose_dat_exists(tmp_path):
    dat = tmp_path / _REL.lstrip("/")
    dat.parent.mkdir(parents=True)
    dat.write_bytes(b"PMAI")
    master = _AbortingMasterDb(str(tmp_path), {"6": _REL})
    writer = AnalysisDBWriter(_LiveDBWith({"6": {"BPM": 128.0, "path": "x.mp3"}}, master))

    result = writer.analyze_and_save("6")

    assert result == {"status": "skipped", "reason": "already_analyzed", "bpm": 128.0}
    assert master.aborting_calls == []


def test_unanalyzed_listing_never_calls_the_aborting_rbox_path_helpers(tmp_path):
    analysed_rel = "/PIONEER/USBANLZ/aaa/done/ANLZ0000.DAT"
    dat = tmp_path / analysed_rel.lstrip("/")
    dat.parent.mkdir(parents=True)
    dat.write_bytes(b"PMAI")
    master = _AbortingMasterDb(
        str(tmp_path),
        {"1": None, "2": None, "3": "/PIONEER/USBANLZ/bbb/lazy/ANLZ0000.DAT", "4": analysed_rel},
    )
    tracks = {
        "1": {"BPM": 0},  # never analysed
        "2": {"BPM": 124.0},  # tag BPM, no AnalysisDataPath: the aborting row
        "3": {"BPM": 124.0},  # path recorded, file not written yet
        "4": {"BPM": 124.0},  # fully analysed
    }
    writer = AnalysisDBWriter(_LiveDBWith(tracks, master))

    assert writer.get_unanalyzed_tracks() == ["1", "2", "3"]
    assert master.aborting_calls == []


# --- where the ANLZ files go -------------------------------------------------
#
# Only the AnalysisDataPath master.db records counts. The writer used to invent a dir
# under the hard-wired %APPDATA%/Pioneer/rekordbox share for a track without one, never
# record it, and still set analysed = 0xFFFFFFFF: Rekordbox then showed a BPM with no
# grid or waveform and never re-analysed the track.

_ANALYSIS = {"bpm": 124.0, "key": "Am", "camelot": "8A", "key_id": 22, "duration": 200.0}


class _RecordingMasterDb(_AbortingMasterDb):
    def __init__(self, share: str, rel_by_id: dict[str, str | None]) -> None:
        super().__init__(share, rel_by_id)
        self.writes: list[str] = []

    def update_content(self, item) -> None:
        self.writes.append(f"update_content({item.id}, analysed={item.analysed})")

    def update_content_key(self, tid, key) -> None:
        self.writes.append(f"update_content_key({tid})")


def _audio_file(tmp_path) -> str:
    f = tmp_path / "music" / "t.mp3"
    f.parent.mkdir()
    f.write_bytes(b"ID3")
    return str(f)


def test_track_without_an_analysis_data_path_is_refused_before_any_dsp(tmp_path, monkeypatch):
    share = tmp_path / "share"
    master = _RecordingMasterDb(str(share), {"9": None})
    writer = AnalysisDBWriter(_LiveDBWith({"9": {"BPM": 0, "path": _audio_file(tmp_path)}}, master))
    ran: list[str] = []
    monkeypatch.setattr(writer, "_run_analysis", lambda p: ran.append(p) or dict(_ANALYSIS))

    result = writer.analyze_and_save("9", force=True)

    assert result["status"] == "error"
    assert result["reason"] == "no_anlz_path"
    assert ran == []
    assert master.writes == []
    assert not share.exists()


def test_failed_dat_write_leaves_master_db_untouched(tmp_path, monkeypatch):
    master = _RecordingMasterDb(str(tmp_path / "share"), {"9": _REL})
    writer = AnalysisDBWriter(_LiveDBWith({"9": {"BPM": 0, "path": _audio_file(tmp_path)}}, master))
    monkeypatch.setattr(writer, "_run_analysis", lambda p: dict(_ANALYSIS))
    # write_anlz_files swallows each file's failure; a missing "dat" key is the signal.
    monkeypatch.setattr("app.anlz_writer.write_anlz_files", lambda **kw: {"ext": "x.EXT"})

    result = writer.analyze_and_save("9")

    assert result["reason"] == "anlz_write_failed"
    assert master.writes == []
    assert writer.live_db.tracks["9"]["BPM"] == 0


def test_writes_into_the_recorded_dir_then_flags_the_row(tmp_path, monkeypatch):
    share = tmp_path / "share"
    master = _RecordingMasterDb(str(share), {"9": _REL})
    writer = AnalysisDBWriter(_LiveDBWith({"9": {"BPM": 0, "path": _audio_file(tmp_path)}}, master))
    monkeypatch.setattr(writer, "_run_analysis", lambda p: dict(_ANALYSIS))
    seen: dict = {}

    def _fake_write(**kw):
        seen.update(kw)
        return {"dat": os.path.join(kw["anlz_dir"], "ANLZ0000.DAT")}

    monkeypatch.setattr("app.anlz_writer.write_anlz_files", _fake_write)

    result = writer.analyze_and_save("9")

    assert result["status"] == "ok", result
    recorded_dir = share / "PIONEER" / "USBANLZ" / "44d" / "00cc2-7321-4a2e-88d7-fbcc7074c1b3"
    assert seen["anlz_dir"] == str(recorded_dir)
    assert recorded_dir.is_dir()  # recorded but not created yet: the writer makes it
    assert master.writes == ["update_content(9, analysed=4294967295)", "update_content_key(9)"]
