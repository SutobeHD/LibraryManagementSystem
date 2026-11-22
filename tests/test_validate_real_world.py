"""Unit tests for the pure helpers in scripts/validate_real_world.py.

The runner (rbox, audio, worker processes) needs a real Rekordbox library and
is meant to run locally.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import validate_real_world as v  # noqa: E402


def row(
    tid: str,
    rb: float = 128.0,
    ours: float = 128.0,
    rel: str = "match",
    key: str = "exact",
    grid: float = 5.0,
) -> dict:
    return {
        "id": tid,
        "status": "ok",
        "title": f"track {tid}",
        "rb_bpm": rb,
        "our_bpm": ours,
        "bpm_relation": rel,
        "key_relation": key,
        "beatgrid": {"mean_abs_err_ms": grid},
    }


# --- split_chunks ----------------------------------------------------------


def test_split_chunks_deals_round_robin():
    assert v.split_chunks(["a", "b", "c", "d", "e"], 2) == [["a", "c", "e"], ["b", "d"]]


def test_split_chunks_never_returns_empty_chunks():
    assert v.split_chunks(["a", "b"], 8) == [["a"], ["b"]]
    assert v.split_chunks([], 4) == []
    assert v.split_chunks(["a"], 0) == [["a"]]


# --- percentile / drift ----------------------------------------------------


def test_percentile_interpolates():
    assert v.percentile([10.0, 20.0, 30.0, 40.0], 50) == 25.0
    assert v.percentile([3.0], 90) == 3.0
    assert math.isnan(v.percentile([], 50))


def test_drift_is_relative_tempo_error_over_the_window():
    # 0.01 BPM at 100 BPM = 0.01 % -> 30 ms over 5 minutes
    assert round(v.drift_ms(100.0, 100.01), 3) == 30.0
    assert v.drift_ms(128.0, 128.0) == 0.0
    assert v.drift_ms(0.0, 128.0) == float("inf")


def test_bpm_exact_compares_at_two_decimals():
    assert v.bpm_exact(row("1", rb=127.999, ours=128.0))
    assert not v.bpm_exact(row("1", rb=128.0, ours=127.96))


# --- summarise -------------------------------------------------------------


def test_summarise_counts_and_grid_stats():
    rows = [
        row("1", grid=4.0),
        row("2", ours=127.96, grid=10.0, key="fifth"),
        row("3", ours=64.0, rel="half", grid=300.0, key="clash"),
        row("4", key="unknown", grid=-1.0),
        {"id": "5", "status": "error", "error": "audio missing"},
    ]
    s = v.summarise(rows)
    assert (s["tracks"], s["compared"], s["errors"]) == (5, 4, 1)
    assert s["error_pct"] == 20.0
    assert s["bpm_exact"] == 2
    assert s["bpm_acc1"] == 3
    assert s["bpm_acc2"] == 4
    # the unknown key is left out of the key denominator
    assert (s["key_compared"], s["key_exact"], s["key_compatible"]) == (3, 1, 2)
    # grid stats: only same-tempo tracks with a readable Rekordbox grid
    assert s["grid_compared"] == 2
    assert s["grid_median_ms"] == 7.0
    assert s["grid_max_ms"] == 10.0


def test_summarise_without_comparable_rows():
    s = v.summarise([{"id": "1", "status": "error", "error": "x"}])
    assert s["compared"] == 0
    assert s["grid_median_ms"] is None
    assert s["bpm_exact_pct"] == 0.0


# --- check_thresholds ------------------------------------------------------


def test_thresholds_pass_on_a_clean_run():
    s = v.summarise([row(str(i)) for i in range(10)])
    assert v.check_thresholds(s, v.DEFAULT_THRESHOLDS) == []


def test_thresholds_name_every_missed_floor():
    rows = [row(str(i), ours=120.0, rel="other", key="clash", grid=40.0) for i in range(4)]
    rows += [{"id": "e", "status": "error", "error": "x"}]
    fails = v.check_thresholds(v.summarise(rows), v.DEFAULT_THRESHOLDS)
    joined = "\n".join(fails)
    assert "octave-tolerant" in joined
    assert "identical to Rekordbox" in joined
    assert "key" in joined
    assert "failed to analyse" in joined


def test_thresholds_flag_the_grid_median():
    s = v.summarise([row(str(i), grid=40.0) for i in range(4)])
    assert any("grid median" in f for f in v.check_thresholds(s, v.DEFAULT_THRESHOLDS))


def test_thresholds_fail_when_nothing_compared():
    s = v.summarise([{"id": "1", "status": "error", "error": "x"}])
    assert v.check_thresholds(s, v.DEFAULT_THRESHOLDS) == ["no track could be compared"]


# --- pick_cdj_tracks -------------------------------------------------------


def test_picks_are_disjoint_and_ordered():
    rows = [
        row("a", grid=2.0),
        row("b", grid=1.0),
        row("c", grid=90.0),
        row("d", grid=200.0),
        row("e", ours=127.9, grid=6.0),
        row("f", ours=126.0, grid=8.0),
        {"id": "x", "status": "error", "error": "x"},
    ]
    picks = v.pick_cdj_tracks(rows, per_group=2)
    assert [r["id"] for r in picks["agree"]] == ["b", "a"]
    assert [r["id"] for r in picks["grid_off"]] == ["d", "c"]
    assert [r["id"] for r in picks["bpm_differ"]] == ["f", "e"]
    ids = [r["id"] for group in picks.values() for r in group]
    assert len(ids) == len(set(ids))


def test_picks_handle_an_empty_report():
    assert v.pick_cdj_tracks([]) == {"agree": [], "grid_off": [], "bpm_differ": []}


# --- db-write: diff + verdict ----------------------------------------------


def content(bpm: int = 12800, key_id: str = "1", analysed: int = 105, title: str = "t") -> dict:
    return {
        "bpm": bpm,
        "key_id": key_id,
        "analysed": analysed,
        "title": title,
        "updated_at": "2026-01-01",
    }


def test_is_within(tmp_path):
    assert v.is_within(tmp_path / "share" / "x.DAT", tmp_path)
    assert v.is_within(tmp_path, tmp_path)
    assert not v.is_within(tmp_path.parent / "other", tmp_path)
    assert not v.is_within(tmp_path / ".." / "escape", tmp_path)


def test_diff_table_reports_added_removed_and_changed_columns():
    before = {"1": content(), "2": content(), "3": content()}
    after = {"1": content(), "2": content(bpm=12600, title="x"), "4": content()}
    d = v.diff_table(before, after)
    assert d == {"added": ["4"], "removed": ["3"], "changed": {"2": ["bpm", "title"]}}


def test_db_diff_passes_when_only_written_rows_change_writer_columns():
    before = {"contents": {"1": content(bpm=0, analysed=0), "2": content()}, "keys": {"1": {}}}
    after = {
        "contents": {"1": content(bpm=12800) | {"updated_at": "2026-11-22"}, "2": content()},
        "keys": {"1": {}, "9": {"name": "F#m"}},
    }
    diffs = {t: v.diff_table(before[t], after[t]) for t in before}
    assert v.judge_db_diff(diffs, {"1"}) == []


def test_db_diff_flags_a_row_nobody_wrote():
    diffs = {
        "contents": v.diff_table(
            {"1": content(), "2": content()}, {"1": content(), "2": content(bpm=1)}
        )
    }
    fails = v.judge_db_diff(diffs, {"1"})
    assert len(fails) == 1 and "row 2 was not written" in fails[0]


def test_db_diff_flags_columns_beyond_the_writer():
    diffs = {"contents": v.diff_table({"1": content()}, {"1": content(bpm=1, title="gone")})}
    fails = v.judge_db_diff(diffs, {"1"})
    assert len(fails) == 1 and "['title']" in fails[0]


def test_db_diff_flags_lost_rows_and_foreign_tables():
    diffs = {
        "contents": v.diff_table({"1": content(), "2": content()}, {"1": content()}),
        "playlists": v.diff_table({"7": {"name": "a"}}, {"7": {"name": "b"}, "8": {"name": "c"}}),
    }
    joined = "\n".join(v.judge_db_diff(diffs, set()))
    assert "contents: 1 row(s) vanished" in joined
    assert "playlists: 1 unexpected new row(s)" in joined
    assert "playlists: row 7 changed (name)" in joined


def test_written_row_passes_when_db_and_dat_match_the_writer():
    res = {"status": "ok", "bpm": 127.96, "beat_count": 640}
    assert v.judge_written_row("1", res, content(bpm=12796), "Am", "Am", 640) == []


def test_written_row_reports_each_mismatch():
    res = {"status": "ok", "bpm": 128.0, "beat_count": 640}
    fails = v.judge_written_row("1", res, content(bpm=12700, analysed=0), "Am", "Cm", 600)
    joined = "\n".join(fails)
    assert "bpm in master.db is 12700" in joined
    assert "analysed flag is 0" in joined
    assert "key in master.db is 'Am', expected 'Cm'" in joined
    assert ".DAT holds 600 beats" in joined


def test_written_row_reports_writer_errors_and_missing_grid():
    assert v.judge_written_row(
        "1", {"status": "error", "reason": "audio_missing"}, None, None, None, 0
    ) == ["1: writer returned audio_missing"]
    assert v.judge_written_row("1", {"status": "ok", "bpm": 1.0}, None, None, None, 0) == [
        "1: row missing after the write"
    ]
    res = {"status": "ok", "bpm": 128.0, "beat_count": 10}
    assert v.judge_written_row("1", res, content(), None, None, 0) == [
        "1: written .DAT holds no beat grid"
    ]


def test_copy_library_takes_wal_files_and_adds_share(tmp_path):
    src = tmp_path / "rb"
    src.mkdir()
    for name in ("master.db", "master.db-wal", "master.db-shm", "other.db"):
        (src / name).write_bytes(name.encode())
    copy = v.copy_library(src / "master.db", tmp_path / "work")
    assert copy == tmp_path / "work" / "master.db"
    assert sorted(p.name for p in (tmp_path / "work").iterdir()) == [
        "master.db",
        "master.db-shm",
        "master.db-wal",
        "share",
    ]
    assert v.file_fingerprint(copy) == v.file_fingerprint(src / "master.db")
    assert v.file_fingerprint(tmp_path / "missing") is None


# --- CLI -------------------------------------------------------------------


def test_db_write_refuses_a_work_dir_inside_the_library(tmp_path, monkeypatch, capsys):
    rb = tmp_path / "rekordbox"
    rb.mkdir()
    (rb / "master.db").write_bytes(b"x")
    monkeypatch.setattr(v, "rekordbox_running", lambda: False)
    code = v.main(["db-write", "--db", str(rb / "master.db"), "--work", str(rb / "work")])
    assert code == 2
    assert "inside the Rekordbox folder" in capsys.readouterr().err
    assert not (rb / "work").exists()


def test_db_write_refuses_while_rekordbox_runs(tmp_path, monkeypatch, capsys):
    (tmp_path / "master.db").write_bytes(b"x")
    monkeypatch.setattr(v, "rekordbox_running", lambda: True)
    assert v.main(["db-write", "--db", str(tmp_path / "master.db")]) == 2
    assert "Rekordbox is running" in capsys.readouterr().out


def test_checklist_command_reads_a_report(tmp_path, capsys):
    import json

    report = tmp_path / "r.json"
    report.write_text(json.dumps({"rows": [row("1"), row("2", ours=127.5)]}), encoding="utf-8")
    assert v.main(["checklist", str(report)]) == 0
    out = capsys.readouterr().out
    assert "CDJ-3000 check" in out
    assert "track 1" in out


# --- sampling --------------------------------------------------------------


class _FakeMdb:
    def __init__(self, rows: dict):
        self._rows = rows

    def get_content_by_id(self, tid: str):
        return self._rows.get(tid)


def test_usable_ids_skips_streaming_and_missing_files(tmp_path):
    from types import SimpleNamespace

    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"x")
    mdb = _FakeMdb(
        {
            "local": SimpleNamespace(folder_path=str(audio), analysis_data_path="/P/ANLZ0000.DAT"),
            "stream": SimpleNamespace(folder_path="soundcloud:tracks:1", analysis_data_path="/P/x"),
            "gone": SimpleNamespace(
                folder_path=str(tmp_path / "gone.mp3"), analysis_data_path="/P/y"
            ),
            "no_anlz": SimpleNamespace(folder_path=str(audio), analysis_data_path=""),
        }
    )
    ids = ["stream", "unknown", "gone", "local", "no_anlz"]
    assert v.usable_ids(mdb, ids, 5) == ["local", "no_anlz"]
    assert v.usable_ids(mdb, ids, 5, need_anlz=True) == ["local"]
    assert v.usable_ids(mdb, ids, 1) == ["local"]


# --- db-write: table discovery + key notation -------------------------------


def test_table_getters_keeps_only_whole_table_listings():
    names = [
        "get_contents",
        "get_content_by_id",
        "get_contents_by_ids",
        "get_playlists",
        "get_playlist_tree",
        "get_playlist_children",
        "get_content_anlz_dir",
        "get_content_anlz_paths",
        "get_key_by_name",
        "get_keys",
        "get_local_usn",
        "update_content",
        "share_directory",
    ]
    assert v.table_getters(names) == ["contents", "keys", "playlists"]


def test_library_key_notation_follows_the_majority():
    assert v.library_key_notation(["8A", "12B", "1A", "Am"]) == "camelot"
    assert v.library_key_notation(["Am", "F#m", "Db", "8A"]) == "classic"
    assert v.library_key_notation(["8A", "Am"]) == "classic"
    assert v.library_key_notation([None, "", None]) == "classic"
    # "13A" / "0B" / "8C" are no Camelot codes
    assert v.library_key_notation(["13A", "0B", "8C"]) == "classic"


class _Row:
    def __init__(self, rid, **cols):
        self.id = rid
        self._cols = {"id": rid, **cols}

    def to_dict(self):
        return dict(self._cols)


class _SnapshotMdb:
    def get_contents(self):
        return [_Row("1", bpm=12800), _Row("2", bpm=14000)]

    def get_keys(self):
        return [_Row("7", name="8A")]

    def get_cues(self):
        raise RuntimeError("Diesel error: Unexpected null for non-null column")

    def get_local_usn(self):
        return 5

    def get_content_by_id(self, tid):
        raise AssertionError("not a table listing")

    def get_playlist_xml(self):
        return "not a list"


def test_snapshot_tables_reports_unreadable_tables_instead_of_dropping_them():
    snap, skipped = v.snapshot_tables(_SnapshotMdb())
    assert snap == {
        "contents": {"1": {"id": "1", "bpm": 12800}, "2": {"id": "2", "bpm": 14000}},
        "keys": {"7": {"id": "7", "name": "8A"}},
    }
    assert list(skipped) == ["cues"]
    assert "Unexpected null" in skipped["cues"]


class _MembershipMdb(_SnapshotMdb):
    def get_playlists(self):
        return [_Row("10", name="a"), _Row("11", name="b"), _Row("12", name="broken")]

    def get_playlist_songs(self, playlist_id):
        if playlist_id == "12":
            raise RuntimeError("Diesel error")
        return [_Row(f"{playlist_id}-1", playlist_id=playlist_id, content_id="1")]

    def get_playlist_contents(self, playlist_id):
        raise AssertionError("joined content rows are not snapshotted")


def test_snapshot_tables_walks_membership_tables_per_parent():
    snap, skipped = v.snapshot_tables(_MembershipMdb())
    assert sorted(snap["playlist_songs"]) == ["10-1", "11-1"]
    assert "playlist_contents" not in snap
    assert skipped["playlist_songs"] == "1 of 3 playlists unreadable, rest compared"
    assert "playlist_contents" not in skipped


def test_db_diff_accepts_only_the_usn_counter_in_the_registry():
    counter = {
        "agent_registries": {
            "added": [],
            "removed": [],
            "changed": {"localUpdateCount": ["int_1", "updated_at"]},
        }
    }
    assert v.judge_db_diff(counter, set()) == []
    other = {
        "agent_registries": {"added": [], "removed": [], "changed": {"agentCredentials": ["str_1"]}}
    }
    assert len(v.judge_db_diff(other, set())) == 1
    wide = {
        "agent_registries": {"added": [], "removed": [], "changed": {"localUpdateCount": ["str_1"]}}
    }
    assert len(v.judge_db_diff(wide, set())) == 1
