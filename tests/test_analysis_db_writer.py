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

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.analysis_db_writer import AnalysisDBWriter  # noqa: E402

#: Engine pitch class (sharps) -> the name Rekordbox's own analysis stores.
_RB_ROOT = {
    "C": "C", "C#": "Db", "D": "D", "D#": "Eb", "E": "E", "F": "F",
    "F#": "F#", "G": "G", "G#": "Ab", "A": "A", "A#": "Bb", "B": "B",
}  # fmt: skip


def test_key_id_to_name_inverts_engine_map_in_rekordbox_spelling():
    """The master.db key write must invert analysis_engine's key_id map exactly, and
    spell the key the way Rekordbox does ("Am", "Dbm", "F#").

    Drift between writer and engine would silently store the wrong key for half the
    wheel. A non-Rekordbox spelling ("A minor") made ``update_content_key`` add a new
    djmdKey row next to Rekordbox's own "Am" instead of reusing it.
    """
    from app.analysis_engine import _REKORDBOX_KEY_ID

    for full_key, key_id in _REKORDBOX_KEY_ID.items():
        root, mode = full_key.split()
        expected = _RB_ROOT[root] + ("m" if mode == "minor" else "")
        assert AnalysisDBWriter._key_id_to_name(key_id) == expected


def test_key_names_match_the_minor_set_of_a_real_library():
    # The twelve minor names a real master.db holds (2026-11-14 copy), verbatim.
    real = {"Cm", "Dbm", "Dm", "Ebm", "Em", "Fm", "F#m", "Gm", "Abm", "Am", "Bbm", "Bm"}
    assert {AnalysisDBWriter._key_id_to_name(i) for i in range(13, 25)} == real


def test_key_id_to_name_unknown():
    assert AnalysisDBWriter._key_id_to_name(0) is None
    assert AnalysisDBWriter._key_id_to_name(99) is None
    assert AnalysisDBWriter._key_id_to_name(None) is None
    assert AnalysisDBWriter._key_id_to_name(True) is None


def test_anlz_rel_path_follows_rekordbox_uuid_layout():
    from app.analysis_db_writer import rekordbox_anlz_rel_path

    # A real row: uuid 44d00cc2-... is recorded at /PIONEER/USBANLZ/44d/00cc2-.../.
    assert (
        rekordbox_anlz_rel_path("44d00cc2-7321-4a2e-88d7-fbcc7074c1b3")
        == "/PIONEER/USBANLZ/44d/00cc2-7321-4a2e-88d7-fbcc7074c1b3/ANLZ0000.DAT"
    )
    for bad in (None, "", "abc", "../x/y", "a/b-cdef", "c:\\evil", "ab\\cd"):
        assert rekordbox_anlz_rel_path(bad) is None


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
    monkeypatch.setattr(writer, "_run_analysis", lambda p, depth: ran.append(p) or dict(_ANALYSIS))

    result = writer.analyze_and_save("9", force=True)

    assert result["status"] == "error"
    assert result["reason"] == "no_anlz_path"
    assert ran == []
    assert master.writes == []
    assert not share.exists()


def test_failed_dat_write_leaves_master_db_untouched(tmp_path, monkeypatch):
    master = _RecordingMasterDb(str(tmp_path / "share"), {"9": _REL})
    writer = AnalysisDBWriter(_LiveDBWith({"9": {"BPM": 0, "path": _audio_file(tmp_path)}}, master))
    monkeypatch.setattr(writer, "_run_analysis", lambda p, depth: dict(_ANALYSIS))
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
    monkeypatch.setattr(writer, "_run_analysis", lambda p, depth: dict(_ANALYSIS))
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
    assert master.writes == ["update_content(9, analysed=105)", "update_content_key(9)"]


class _CLongRow:
    """rbox content row: integer columns are C longs, so 0xFFFFFFFF raises on assignment."""

    def __init__(self, cid: str) -> None:
        self.id = cid
        self.analysis_data_path = _REL
        self._analysed = 0
        self.bpm = 0

    @property
    def analysed(self) -> int:
        return self._analysed

    @analysed.setter
    def analysed(self, value: int) -> None:
        if not -(2**31) <= value < 2**31:
            raise OverflowError("Python int too large to convert to C long")
        self._analysed = value


class _CLongMasterDb(_RecordingMasterDb):
    def get_content_by_id(self, tid):
        tid = str(tid)
        return _CLongRow(tid) if tid in self.rel_by_id else None


def test_analysed_flag_fits_rbox_c_long_column(tmp_path):
    """The old 0xFFFFFFFF raised OverflowError inside rbox, so BPM and key never landed
    while the route still said ok. 105 is what Rekordbox itself writes."""
    from app.analysis_db_writer import REKORDBOX_ANALYSED

    master = _CLongMasterDb(str(tmp_path / "share"), {"9": _REL})
    writer = AnalysisDBWriter(_LiveDBWith({"9": {"BPM": 0}}, master))

    assert REKORDBOX_ANALYSED == 105
    assert writer._update_db("9", dict(_ANALYSIS)) is True
    assert master.writes == ["update_content(9, analysed=105)", "update_content_key(9)"]


def test_refused_db_write_is_an_error_result_and_leaves_the_cache(tmp_path, monkeypatch):
    class _RefusingMasterDb(_RecordingMasterDb):
        def update_content(self, item) -> None:
            raise RuntimeError("database is locked")

    master = _RefusingMasterDb(str(tmp_path / "share"), {"9": _REL})
    writer = AnalysisDBWriter(_LiveDBWith({"9": {"BPM": 0, "path": _audio_file(tmp_path)}}, master))
    monkeypatch.setattr(writer, "_run_analysis", lambda p, depth: dict(_ANALYSIS))
    monkeypatch.setattr(
        "app.anlz_writer.write_anlz_files",
        lambda **kw: {"dat": os.path.join(kw["anlz_dir"], "ANLZ0000.DAT")},
    )

    result = writer.analyze_and_save("9", force=True)

    assert result["status"] == "error"
    assert result["reason"] == "db_update_failed"
    assert "database is locked" in result["error"]
    assert writer.live_db.tracks["9"]["BPM"] == 0  # cache still mirrors master.db


def test_update_db_raises_for_a_missing_row(tmp_path):
    from app.analysis_db_writer import AnalysisDbUpdateError

    master = _RecordingMasterDb(str(tmp_path / "share"), {})
    writer = AnalysisDBWriter(_LiveDBWith({}, master))
    with pytest.raises(AnalysisDbUpdateError):
        writer._update_db("9", dict(_ANALYSIS))
    assert master.writes == []


def test_failed_key_write_is_not_swallowed(tmp_path):
    from app.analysis_db_writer import AnalysisDbUpdateError

    class _KeyRefusingMasterDb(_RecordingMasterDb):
        def update_content_key(self, tid, key) -> None:
            raise RuntimeError("key table locked")

    master = _KeyRefusingMasterDb(str(tmp_path / "share"), {"9": _REL})
    writer = AnalysisDBWriter(_LiveDBWith({"9": {"BPM": 0}}, master))
    with pytest.raises(AnalysisDbUpdateError, match="key table locked"):
        writer._update_db("9", dict(_ANALYSIS))


# --- where the DSP runs ------------------------------------------------------


class _FakePool:
    def __init__(self, outcome) -> None:
        self.outcome = outcome
        self.submitted: list[tuple] = []

    def submit(self, fn, *args, **kwargs):
        from concurrent.futures import Future

        self.submitted.append((fn, args, kwargs))
        fut: Future = Future()
        if isinstance(self.outcome, BaseException):
            fut.set_exception(self.outcome)
        else:
            fut.set_result(self.outcome)
        return fut


def test_analysis_runs_in_the_worker_pool_not_the_sidecar(monkeypatch):
    """librosa/madmom in the sidecar process held the GIL for minutes per batch."""
    from app import analysis_engine

    pool = _FakePool({"bpm": 124.0})
    monkeypatch.setattr(analysis_engine.AnalysisEngine, "get_executor", lambda: pool)

    out = AnalysisDBWriter(object())._run_analysis("x.mp3")

    assert out == {"bpm": 124.0}
    assert pool.submitted == [
        (analysis_engine.run_full_analysis, ("x.mp3",), {"depth": "rekordbox"})
    ]


def test_a_crashed_worker_drops_the_pool_for_the_next_track(monkeypatch):
    from concurrent.futures.process import BrokenProcessPool

    from app import analysis_engine

    pool = _FakePool(BrokenProcessPool("worker died"))
    dropped: list[bool] = []
    monkeypatch.setattr(analysis_engine.AnalysisEngine, "get_executor", lambda: pool)
    monkeypatch.setattr(analysis_engine.AnalysisEngine, "shutdown", lambda: dropped.append(True))

    with pytest.raises(BrokenProcessPool):
        AnalysisDBWriter(object())._run_analysis("x.mp3")

    assert dropped == [True]


def test_rewrites_a_rekordbox_reanalysis_under_its_recorded_file_name(tmp_path, monkeypatch):
    # 8 rows of a real library record ANLZ0001.DAT (Rekordbox re-analysis); the USB
    # export ships exactly that file, so writing ANLZ0000.* never reached the stick.
    rel = "/PIONEER/USBANLZ/72a/fb195-5909/ANLZ0001.DAT"
    master = _RecordingMasterDb(str(tmp_path / "share"), {"9": rel})
    writer = AnalysisDBWriter(_LiveDBWith({"9": {"BPM": 0, "path": _audio_file(tmp_path)}}, master))
    monkeypatch.setattr(writer, "_run_analysis", lambda p, depth: dict(_ANALYSIS))
    seen: dict = {}

    def _fake_write(**kw):
        seen.update(kw)
        return {"dat": os.path.join(kw["anlz_dir"], f"{kw['filename_base']}.DAT")}

    monkeypatch.setattr("app.anlz_writer.write_anlz_files", _fake_write)

    assert writer.analyze_and_save("9")["status"] == "ok"
    assert seen["filename_base"] == "ANLZ0001"
    assert seen["anlz_dir"].endswith(os.path.join("72a", "fb195-5909"))


def test_key_failure_after_the_row_write_keeps_the_cache_on_the_new_bpm(tmp_path, monkeypatch):
    class _KeyRefusingMasterDb(_RecordingMasterDb):
        def update_content_key(self, tid, key) -> None:
            raise RuntimeError("key table locked")

    master = _KeyRefusingMasterDb(str(tmp_path / "share"), {"9": _REL})
    writer = AnalysisDBWriter(_LiveDBWith({"9": {"BPM": 0, "path": _audio_file(tmp_path)}}, master))
    monkeypatch.setattr(writer, "_run_analysis", lambda p, depth: dict(_ANALYSIS))
    monkeypatch.setattr(
        "app.anlz_writer.write_anlz_files",
        lambda **kw: {"dat": os.path.join(kw["anlz_dir"], "ANLZ0000.DAT")},
    )

    result = writer.analyze_and_save("9", force=True)

    assert result["reason"] == "db_update_failed"
    assert master.writes == ["update_content(9, analysed=105)"]  # BPM landed
    assert writer.live_db.tracks["9"]["BPM"] == 124.0  # so the cache shows it


# --- depth -------------------------------------------------------------------


def test_the_worker_gets_the_requested_depth(monkeypatch):
    from app import analysis_engine

    pool = _FakePool({"bpm": 124.0})
    monkeypatch.setattr(analysis_engine.AnalysisEngine, "get_executor", lambda: pool)

    AnalysisDBWriter(object())._run_analysis("x.mp3", "high")

    assert pool.submitted == [(analysis_engine.run_full_analysis, ("x.mp3",), {"depth": "high"})]


def test_batch_depth_reaches_every_track_without_a_settings_read(tmp_path, monkeypatch):
    """The route resolves depth once; the writer only threads it through."""
    master = _RecordingMasterDb(str(tmp_path / "share"), {"9": _REL})
    writer = AnalysisDBWriter(_LiveDBWith({"9": {"BPM": 0, "path": _audio_file(tmp_path)}}, master))
    seen: list[str] = []
    monkeypatch.setattr(
        writer, "_run_analysis", lambda p, depth: seen.append(depth) or dict(_ANALYSIS)
    )
    monkeypatch.setattr("app.anlz_writer.write_anlz_files", lambda **kw: {"dat": "x.DAT"})
    monkeypatch.setattr(
        "app.services.SettingsManager.load", lambda: pytest.fail("settings read in the writer")
    )

    out = list(writer.analyze_batch(["9"], force=True, depth="high"))

    assert [o["status"] for o in out] == ["ok"]
    assert seen == ["high"]


# --- key notation ------------------------------------------------------------
#
# A real library stored its keys in Camelot ("7A", "9A": 4900 of 5000 tracks). The
# writer put the classic name of the same key ("Dm", "Em") next to them, and Rekordbox
# sorts and filters the key column by that text.


def test_camelot_codes_match_the_engine_for_every_key_id():
    """The code written is checked against the writer's own key-id table, so that table
    must say what the engine says for all 24 keys, or every Camelot write falls back."""
    from app.analysis_db_writer import KeyNotation, library_key_name
    from app.analysis_engine import _CAMELOT_MAP, _REKORDBOX_KEY_ID

    assert len(_REKORDBOX_KEY_ID) == 24
    for full_key, key_id in _REKORDBOX_KEY_ID.items():
        code = _CAMELOT_MAP[full_key]
        assert library_key_name(key_id, KeyNotation.CAMELOT, code) == code
        assert library_key_name(key_id, KeyNotation.CLASSIC, code) == (
            AnalysisDBWriter._key_id_to_name(key_id)
        )


@pytest.mark.parametrize(
    ("names", "expected"),
    [
        (["7A", "9A", "12B", "Dm"], "camelot"),
        (["Dm", "Em", "F#", "7A"], "classic"),
        (["7A", "Dm"], "classic"),  # tie
        ([], "classic"),
        ([None, "", "  "], "classic"),  # no keyed track
        (["7A", None, "", None], "camelot"),  # tracks without a key do not vote
        (["1A", "10A", "11B", "12A"], "camelot"),
        (["13A", "0B", "8C", "7a", "A7", "7AB"], "classic"),  # not Camelot codes
        (["13A", "7A", "8B"], "camelot"),
    ],
)
def test_library_key_notation_is_the_majority_of_the_keyed_tracks(names, expected):
    from app.analysis_db_writer import KeyNotation, library_key_notation

    assert library_key_notation(names) is KeyNotation(expected)
    assert library_key_notation(iter(names)) is KeyNotation(expected)  # one pass is enough


@pytest.mark.parametrize("camelot", [None, "", "7", "13A", "7a", " 7A", "7A ", 7, "8A", "7B"])
def test_library_key_name_falls_back_to_classic_without_a_usable_camelot_code(camelot):
    """Key id 15 is D minor = "7A". Anything else in the code slot is not written."""
    from app.analysis_db_writer import KeyNotation, library_key_name

    assert library_key_name(15, KeyNotation.CAMELOT, camelot) == "Dm"


def test_library_key_name_follows_the_notation():
    from app.analysis_db_writer import KeyNotation, library_key_name

    assert library_key_name(15, KeyNotation.CAMELOT, "7A") == "7A"
    assert library_key_name(15, KeyNotation.CLASSIC, "7A") == "Dm"
    assert library_key_name(17, KeyNotation.CAMELOT, "9A") == "9A"
    for no_key in (0, 25, None, True, "15"):
        assert library_key_name(no_key, KeyNotation.CAMELOT, "7A") is None
        assert library_key_name(no_key, KeyNotation.CLASSIC, "7A") is None


class _KeyRow:
    def __init__(self, kid: str, name: str) -> None:
        self.id = kid
        self.name = name


class _KeyedContent:
    def __init__(self, key_id: str | None) -> None:
        self.key_id = key_id


class _LibraryMasterDb(_RecordingMasterDb):
    """A library whose tracks carry ``track_keys``; counts the library-wide reads."""

    def __init__(
        self, share: str, rel_by_id: dict[str, str | None], track_keys: list[str | None]
    ) -> None:
        super().__init__(share, rel_by_id)
        names = sorted({k for k in track_keys if k})
        self._keys = [_KeyRow(str(100 + i), name) for i, name in enumerate(names)]
        id_by_name = {row.name: row.id for row in self._keys}
        self._contents = [_KeyedContent(id_by_name.get(k) if k else None) for k in track_keys]
        self.scans = 0
        self.scan_lock_held: list[bool] = []
        self.key_writes: list[tuple[str, str]] = []

    def get_keys(self) -> list[_KeyRow]:
        return list(self._keys)

    def get_contents(self) -> list[_KeyedContent]:
        self.scans += 1
        self.scan_lock_held.append(_lock_held_elsewhere())
        return list(self._contents)

    def update_content_key(self, tid, key) -> None:
        super().update_content_key(tid, key)
        self.key_writes.append((str(tid), key))


_CAMELOT_LIBRARY = ["7A"] * 49 + ["Dm"]  # the measured shape: ~1 % stray classic names
_CLASSIC_LIBRARY = ["Dm", "Em", "F#m", "Ab", None]


@pytest.mark.parametrize(
    ("track_keys", "written"),
    [
        (_CAMELOT_LIBRARY, "8A"),
        (_CLASSIC_LIBRARY, "Am"),
        (["7A", "9A", "8B", "Dm", "Em"], "8A"),  # mixed: Camelot majority
        (["7A", "9A", "Bbm", "Dm", "Em"], "Am"),  # mixed: classic majority
        (["7A", "9A", "Dm", "Em"], "Am"),  # tie
        ([], "Am"),  # empty library
        ([None, None], "Am"),  # no track has a key yet
    ],
)
def test_update_db_writes_the_key_in_the_notation_of_the_library(tmp_path, track_keys, written):
    master = _LibraryMasterDb(str(tmp_path / "share"), {"9": _REL}, track_keys)
    writer = AnalysisDBWriter(_LiveDBWith({"9": {"BPM": 0}}, master))

    assert writer._update_db("9", dict(_ANALYSIS)) is True  # A minor: "Am" / "8A"

    assert master.key_writes == [("9", written)]
    assert master.writes == ["update_content(9, analysed=105)", "update_content_key(9)"]


@pytest.mark.parametrize("camelot", ["", None, "8", "8a", "13A", "7A"])
def test_camelot_library_gets_the_classic_name_when_the_code_is_unusable(tmp_path, camelot):
    master = _LibraryMasterDb(str(tmp_path / "share"), {"9": _REL}, _CAMELOT_LIBRARY)
    writer = AnalysisDBWriter(_LiveDBWith({"9": {"BPM": 0}}, master))

    writer._update_db("9", {**_ANALYSIS, "camelot": camelot})

    assert master.key_writes == [("9", "Am")]


def test_camelot_library_gets_the_classic_name_when_the_code_is_missing(tmp_path):
    master = _LibraryMasterDb(str(tmp_path / "share"), {"9": _REL}, _CAMELOT_LIBRARY)
    writer = AnalysisDBWriter(_LiveDBWith({"9": {"BPM": 0}}, master))

    writer._update_db("9", {"bpm": 124.0, "key_id": 22})

    assert master.key_writes == [("9", "Am")]


def test_unknown_key_writes_no_key_in_either_notation(tmp_path):
    for track_keys in (_CAMELOT_LIBRARY, _CLASSIC_LIBRARY):
        master = _LibraryMasterDb(str(tmp_path / "share"), {"9": _REL}, track_keys)
        writer = AnalysisDBWriter(_LiveDBWith({"9": {"BPM": 0}}, master))

        assert writer._update_db("9", {"bpm": 124.0, "key_id": 0, "camelot": ""}) is True

        assert master.writes == ["update_content(9, analysed=105)"]


def test_notation_is_detected_once_for_a_batch_of_writes(tmp_path, monkeypatch):
    """One ``get_contents`` per track would read 5000 rows 5000 times in a full re-analysis."""
    audio = _audio_file(tmp_path)
    ids = ["1", "2", "3", "4"]
    master = _LibraryMasterDb(str(tmp_path / "share"), dict.fromkeys(ids, _REL), _CAMELOT_LIBRARY)
    writer = AnalysisDBWriter(_LiveDBWith({i: {"BPM": 0, "path": audio} for i in ids}, master))
    monkeypatch.setattr(writer, "_run_analysis", lambda p, depth: dict(_ANALYSIS))
    monkeypatch.setattr(
        "app.anlz_writer.write_anlz_files",
        lambda **kw: {"dat": os.path.join(kw["anlz_dir"], "ANLZ0000.DAT")},
    )

    results = list(writer.analyze_batch(ids, force=True))

    assert [r["status"] for r in results] == ["ok"] * 4
    assert master.key_writes == [(i, "8A") for i in ids]
    assert master.scans == 1
    assert master.scan_lock_held == [False]  # the library-wide read never blocks writers


def test_failed_notation_read_writes_classic_and_is_retried(tmp_path):
    class _FlakyMasterDb(_LibraryMasterDb):
        def get_contents(self):
            if not self.scans:
                self.scans += 1
                raise RuntimeError("database is locked")
            return super().get_contents()

    master = _FlakyMasterDb(str(tmp_path / "share"), {"9": _REL}, _CAMELOT_LIBRARY)
    writer = AnalysisDBWriter(_LiveDBWith({"9": {"BPM": 0}}, master))

    assert writer._update_db("9", dict(_ANALYSIS)) is True  # the write itself still lands
    assert writer._update_db("9", dict(_ANALYSIS)) is True
    assert writer._update_db("9", dict(_ANALYSIS)) is True

    assert master.key_writes == [("9", "Am"), ("9", "8A"), ("9", "8A")]
    assert master.scans == 2  # the failure is not cached, the answer is


def test_forgetting_the_notation_reads_the_library_again(tmp_path):
    from app.analysis_db_writer import KeyNotation

    master = _LibraryMasterDb(str(tmp_path / "share"), {"9": _REL}, _CAMELOT_LIBRARY)
    writer = AnalysisDBWriter(_LiveDBWith({"9": {"BPM": 0}}, master))

    assert writer.key_notation() is KeyNotation.CAMELOT
    master._contents = [_KeyedContent(None)]  # reloaded: no keyed track left
    assert writer.key_notation() is KeyNotation.CAMELOT
    writer.forget_key_notation()
    assert writer.key_notation() is KeyNotation.CLASSIC
    assert master.scans == 2


def test_notation_does_not_come_from_the_partial_track_cache(tmp_path):
    """The cache may hold only the tracks being written, and its ``Key`` is the Camelot
    code after an analysis write even in a classic library."""
    master = _LibraryMasterDb(str(tmp_path / "share"), {"9": _REL}, _CLASSIC_LIBRARY)
    tracks = {"9": {"BPM": 0, "Key": "8A"}, "10": {"Key": "7A"}, "11": {"Key": "9A"}}
    writer = AnalysisDBWriter(_LiveDBWith(tracks, master))

    writer._update_db("9", dict(_ANALYSIS))

    assert master.key_writes == [("9", "Am")]
