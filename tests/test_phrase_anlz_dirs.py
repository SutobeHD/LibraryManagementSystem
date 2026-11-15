"""One master.db open per phrase batch via `resolve_anlz_dirs`.

`extract_beats_from_db` and `commit_phrase_cues` each opened master.db (a
SQLCipher key derivation, ~0.2 s) per track — two opens per track in a phrase
batch. `resolve_anlz_dirs` resolves the whole batch on one handle and hands
plain strings to both via `anlz_dirs=`. A counting fake `rbox` module stands
in for master.db; no real library is touched.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import phrase_generator as pg

N_TRACKS = 5000
# Even ids are analysed in the DB; only those <= ON_DISK have ANLZ dirs on disk
# (the rest model "path in master.db, files gone").
ON_DISK = 400


class FakeMasterDb:
    def __init__(self, share: Path, analysed: set[int]):
        self._share = share
        self._analysed = analysed
        self.by_id_calls = 0

    def get_content_by_id(self, ident):
        self.by_id_calls += 1
        tid = int(ident)
        rel = f"/PIONEER/USBANLZ/{tid:05d}/ANLZ0000.DAT" if tid in self._analysed else None
        return SimpleNamespace(id=ident, analysis_data_path=rel)

    def share_directory(self):
        return str(self._share)


@pytest.fixture
def library(tmp_path: Path, monkeypatch):
    """Fake rbox; every even id analysed, ANLZ dirs on disk up to ON_DISK."""
    share = tmp_path / "share"
    analysed = set(range(2, N_TRACKS + 1, 2))
    for tid in range(2, ON_DISK + 1, 2):
        (share / "PIONEER" / "USBANLZ" / f"{tid:05d}").mkdir(parents=True)

    state = {"opens": 0, "fail": False, "db": FakeMasterDb(share, analysed)}

    def _open(path):
        state["opens"] += 1
        if state["fail"]:
            raise RuntimeError("database is locked")
        return state["db"]

    mod = types.ModuleType("rbox")
    mod.MasterDb = _open  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "rbox", mod)

    beats_read: list[str] = []
    patched: list[str] = []
    monkeypatch.setattr(
        pg, "read_beats_from_anlz", lambda d: beats_read.append(d) or [0.5 * i for i in range(64)]
    )
    monkeypatch.setattr(
        pg, "patch_memory_cues", lambda d, cues: patched.append(d) or {"anlz_dir": d}
    )
    state.update(share=share, beats_read=beats_read, patched=patched)
    return state


def _anlz(share: Path, tid: int) -> str:
    return str(share / "PIONEER" / "USBANLZ" / f"{tid:05d}")


class TestResolveAnlzDirs:
    def test_one_open_for_5k_tracks(self, library) -> None:
        dirs = pg.resolve_anlz_dirs(range(1, N_TRACKS + 1), "master.db")
        assert library["opens"] == 1
        assert len(dirs) == N_TRACKS
        assert dirs[2] == _anlz(library["share"], 2)
        assert dirs[1] is None  # never analysed
        assert dirs[ON_DISK + 2] is None  # analysed in the DB, dir gone
        assert sum(d is not None for d in dirs.values()) == ON_DISK // 2

    def test_same_answers_as_per_track_resolution(self, library) -> None:
        ids = list(range(1, 41))
        batch = pg.resolve_anlz_dirs(ids, "master.db")
        single = {tid: pg.resolve_anlz_dir(tid, "master.db") for tid in ids}
        assert batch == single

    def test_open_failure_returns_empty_so_callers_fall_back(self, library) -> None:
        library["fail"] = True
        assert pg.resolve_anlz_dirs([2, 4], "master.db") == {}

    def test_dir_missing_on_disk_is_none(self, library) -> None:
        (Path(_anlz(library["share"], 4))).rmdir()
        assert pg.resolve_anlz_dirs([4], "master.db") == {4: None}


class TestPhraseBatchOpens:
    def _batch(self, ids, anlz_dirs):
        for tid in ids:
            beats = pg.extract_beats_from_db(tid, "master.db", anlz_dirs=anlz_dirs)
            if not beats:
                continue
            cues = pg.generate_phrase_cues(beats, phrase_length=16)
            pg.commit_phrase_cues(tid, cues, "master.db", anlz_dirs=anlz_dirs)

    def test_batch_with_prefetch_opens_once(self, library) -> None:
        ids = list(range(1, N_TRACKS + 1))
        dirs = pg.resolve_anlz_dirs(ids, "master.db")
        self._batch(ids, dirs)
        assert library["opens"] == 1
        assert len(library["patched"]) == ON_DISK // 2
        assert library["patched"][0] == _anlz(library["share"], 2)

    def test_batch_without_prefetch_is_two_opens_per_analysed_track(self, library) -> None:
        # Baseline the prefetch replaces: extract + commit each open master.db.
        ids = list(range(1, 201))
        self._batch(ids, None)
        assert library["opens"] == 200 + 100

    def test_prefetch_and_fresh_lookup_write_the_same_dirs(self, library) -> None:
        ids = list(range(1, 101))
        self._batch(ids, None)
        fresh = list(library["patched"])
        library["patched"].clear()
        self._batch(ids, pg.resolve_anlz_dirs(ids, "master.db"))
        assert library["patched"] == fresh

    def test_track_missing_from_map_falls_back_to_lookup(self, library) -> None:
        beats = pg.extract_beats_from_db(2, "master.db", anlz_dirs={4: None})
        assert beats
        assert library["opens"] == 1

    def test_empty_map_after_failed_prefetch_falls_back(self, library) -> None:
        library["fail"] = True
        dirs = pg.resolve_anlz_dirs([2], "master.db")
        library["fail"] = False
        assert pg.extract_beats_from_db(2, "master.db", anlz_dirs=dirs)
        assert library["opens"] == 2

    def test_stale_map_entry_is_rechecked(self, library) -> None:
        dirs = pg.resolve_anlz_dirs([2], "master.db")
        Path(dirs[2]).rmdir()  # type: ignore[arg-type]
        assert pg.extract_beats_from_db(2, "master.db", anlz_dirs=dirs) == []
        with pytest.raises(pg.PhraseNotAnalysedError):
            pg.commit_phrase_cues(2, [], "master.db", anlz_dirs=dirs)
        assert library["opens"] == 1

    def test_not_analysed_in_map_raises_without_open(self, library) -> None:
        with pytest.raises(pg.PhraseNotAnalysedError):
            pg.commit_phrase_cues(1, [], "master.db", anlz_dirs={1: None})
        assert library["opens"] == 0
