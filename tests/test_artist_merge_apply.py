"""Artist-Hub merge apply/revert tests (T-6 + T-11a — app/artist_store/merge.py).

Everything here runs against a **mocked facade**. No Rekordbox library is opened, no
``master.db`` is read, no audio file is written — the fake models the two rbox
behaviours the whole design rests on, both measured against a copy of the real library
(``docs/research/implement/inprogress_library-artist-hub.md``, wave 5):

  * ``update_content(item)`` writes the **whole row**. ``FakeFacade.update_content``
    therefore replaces every column from the object it is handed, so an implementation
    that wrote a row it read before taking the lock loses a concurrent BPM edit —
    which is exactly what ``test_concurrent_bpm_edit_survives_the_merge`` catches.
  * ``update_content_artist(id, name)`` does **not** bump ``rb_local_usn``, so it is
    banned: the fake raises if it is ever called.

The lock is a counting stand-in that records whether it is held; the fake refuses any
write taken outside it, so "every write sits inside ``db_lock()``" is enforced on every
test in the file, not only on the one named after it.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any, ClassVar

import pytest

from app.artist_store import merge
from app.artist_store import schema as artist_schema
from app.metadata_fixer import schema as fixer_log

CANONICAL = "Boys Noize"
VARIANTS = ("boys noize", "BOYS NOIZE")


# --------------------------------------------------------------------------- fakes


class FakeArtist:
    """An rbox ``DjmdArtist`` row: an id and a name, nothing else the merge reads."""

    def __init__(self, artist_id: str, name: str) -> None:
        self.id = artist_id
        self.name = name


class FakeContent:
    """An rbox ``DjmdContent`` row — a WHOLE row, written whole by ``update_content``."""

    _COLUMNS = ("id", "artist_id", "bpm", "key_id", "commnt", "rating", "color_id", "rb_local_usn")

    def __init__(self, content_id: str, artist_id: str | None) -> None:
        self.id = content_id
        self.artist_id = artist_id
        self.bpm = 12000
        self.key_id = "K1"
        self.commnt = "original comment"
        self.rating = 4
        self.color_id = 3
        self.rb_local_usn = 1000

    def snapshot(self) -> FakeContent:
        clone = FakeContent(self.id, self.artist_id)
        for column in self._COLUMNS:
            setattr(clone, column, getattr(self, column))
        return clone


class CountingLock:
    """``db_lock()`` stand-in: counts acquisitions and knows whether it is held.

    ``on_enter`` is how a concurrent editor is injected — it fires while the lock is
    being taken, i.e. after any read the implementation might have done too early.
    """

    def __init__(self, on_enter: Any = None) -> None:
        self.entered = 0
        self.held = False
        self.on_enter = on_enter

    @contextmanager
    def __call__(self):
        self.entered += 1
        self.held = True
        if self.on_enter is not None:
            self.on_enter()
        try:
            yield
        finally:
            self.held = False


class FakeFacade:
    """The slice of ``RekordboxDB`` the merge uses, plus tripwires for the banned paths."""

    def __init__(self, lock: CountingLock) -> None:
        self._lock = lock
        self.artists: list[dict[str, Any]] = []
        self.tracks_by_ui_id: dict[str, list[dict[str, Any]]] = {}
        self.contents: dict[str, FakeContent] = {}
        self.artist_rows: dict[str, FakeArtist] = {}
        self.created_artists: list[str] = []
        self.deleted_artists: list[str] = []
        self.update_content_calls: list[str] = []

    # --- library reads (UI layer) -----------------------------------------
    def get_tracks_by_artist(self, aid: str) -> list[dict[str, Any]]:
        return [dict(t) for t in self.tracks_by_ui_id.get(str(aid), [])]

    # --- rbox passthroughs ------------------------------------------------
    def get_content_by_id(self, tid: str) -> FakeContent | None:
        row = self.contents.get(str(tid))
        return row.snapshot() if row is not None else None

    def update_content(self, item: FakeContent) -> bool:
        assert self._lock.held, "update_content called outside db_lock()"
        self.update_content_calls.append(str(item.id))
        stored = item.snapshot()
        stored.rb_local_usn = self.contents[str(item.id)].rb_local_usn + 1
        self.contents[str(item.id)] = stored
        return True

    def get_artist_by_name(self, name: str) -> FakeArtist | None:
        for row in self.artist_rows.values():
            if row.name == name:  # exact + case-sensitive, like rbox
                return row
        return None

    def create_artist(self, name: str) -> FakeArtist:
        assert self._lock.held, "create_artist called outside db_lock()"
        artist_id = f"A{len(self.artist_rows) + 90}"
        row = FakeArtist(artist_id, name)
        self.artist_rows[artist_id] = row
        self.created_artists.append(name)
        return row

    def delete_artist(self, artist_id: str) -> bool:
        assert self._lock.held, "delete_artist called outside db_lock()"
        self.deleted_artists.append(str(artist_id))
        self.artist_rows.pop(str(artist_id), None)
        return True

    # --- banned paths -----------------------------------------------------
    def update_content_artist(self, tid: str, name: str) -> bool:
        raise AssertionError("update_content_artist leaves rb_local_usn stale — never use it")

    def update_tracks_metadata(self, ids: list[str], updates: dict[str, Any]) -> bool:
        raise AssertionError("the merge must not go through update_tracks_metadata")


def _facade(lock: CountingLock, rows: list[tuple[str, str]]) -> FakeFacade:
    """Build a library from ``[(content_id, artist_name)]``. Paths are derived per id."""
    db = FakeFacade(lock)
    names: list[str] = []
    for _cid, name in rows:
        if name not in names:
            names.append(name)
    artist_id_by_name = {name: f"A{i + 1}" for i, name in enumerate(names)}
    for name, artist_id in artist_id_by_name.items():
        db.artist_rows[artist_id] = FakeArtist(artist_id, name)
    for index, name in enumerate(names):
        owned = [(cid, n) for cid, n in rows if n == name]
        db.artists.append({"id": f"art_{index}", "name": name, "track_count": len(owned)})
        db.tracks_by_ui_id[f"art_{index}"] = [
            {"ID": cid, "Artist": name, "path": f"C:/music/{cid}.aiff"} for cid, _ in owned
        ]
    for cid, name in rows:
        db.contents[cid] = FakeContent(cid, artist_id_by_name[name])
    return db


# --------------------------------------------------------------------------- fixtures


@pytest.fixture
def lock(monkeypatch) -> CountingLock:
    counting = CountingLock()
    monkeypatch.setattr(merge, "_db_lock", counting)
    return counting


@pytest.fixture(autouse=True)
def _no_rekordbox(monkeypatch):
    """Never scan the real process list — and never fail because the user has RB open."""
    monkeypatch.setattr(merge, "_rekordbox_running", lambda: False)


@pytest.fixture(autouse=True)
def _no_real_files(monkeypatch):
    """Tag reads/writes and hashing are faked: the merge must not need real audio."""
    written: list[tuple[str, str]] = []
    hashed: list[str] = []
    locked: set[str] = set()

    def _write(path: str, updates: dict[str, Any]) -> bool:
        assert set(updates) == {"Artist"}, f"unexpected tag fields {sorted(updates)}"
        if path in locked:
            return False
        written.append((path, updates["Artist"]))
        return True

    def _sha1(path: str | None) -> str | None:
        if not path:
            return None
        hashed.append(path)
        return f"sha1:{path}:{len(hashed)}"

    monkeypatch.setattr(merge, "_write_tags", _write)
    monkeypatch.setattr(merge, "_read_tag_artist", lambda path: f"tag:{path}" if path else None)
    monkeypatch.setattr(merge, "_file_sha1", _sha1)
    return {"written": written, "hashed": hashed, "locked": locked}


@pytest.fixture(autouse=True)
def _fresh_log(tmp_path, monkeypatch):
    """Undo log in a throwaway file; the artists.db sidecar must stay untouched."""
    monkeypatch.setattr(fixer_log, "_db_path", lambda: tmp_path / "metadata_fixer_log.db")
    monkeypatch.setattr(artist_schema, "_db_path", lambda: tmp_path / "artists.db")
    monkeypatch.setattr(artist_schema, "_initialised", False)
    _close_log_conn()
    fixer_log.init_db()
    yield
    _close_log_conn()
    assert not (tmp_path / "artists.db").exists(), "the merge must not touch artists.db"


def _close_log_conn() -> None:
    conn = getattr(fixer_log._local, "conn", None)
    if conn is not None:
        conn.close()
        del fixer_log._local.conn


def _rows(count: int) -> list[tuple[str, str]]:
    """``count`` variant-spelled tracks plus one already-canonical track."""
    out = [(f"t{i}", VARIANTS[i % len(VARIANTS)]) for i in range(count)]
    out.append(("tc", CANONICAL))
    return out


# ------------------------------------------------------- the full-row clobber (T4)


def test_concurrent_bpm_edit_survives_the_merge(lock, monkeypatch) -> None:
    """The regression this whole write loop exists for.

    ``update_content`` writes the whole row, so a row read before the lock and written
    inside it silently reverts every other column. The concurrent editor here fires
    while the lock is being acquired — after any premature read would already have
    happened — and the merged row must still carry its new BPM, key, comment, colour
    and rating.
    """
    db = _facade(lock, _rows(4))

    def _concurrent_edit() -> None:
        for row in db.contents.values():
            row.bpm = 12850
            row.commnt = "edited by the user mid-merge"
            row.rating = 5

    lock.on_enter = _concurrent_edit

    result = merge.apply(db, [*VARIANTS, CANONICAL], CANONICAL)

    canonical_id = db.get_artist_by_name(CANONICAL).id
    assert result.tracks_rewritten == 4
    for cid in ("t0", "t1", "t2", "t3"):
        row = db.contents[cid]
        assert row.artist_id == canonical_id
        assert row.bpm == 12850, "a stale row snapshot clobbered the concurrent BPM edit"
        assert row.commnt == "edited by the user mid-merge"
        assert row.rating == 5


def test_merge_bumps_the_content_usn(lock) -> None:
    db = _facade(lock, _rows(2))
    before = {cid: row.rb_local_usn for cid, row in db.contents.items()}

    merge.apply(db, [*VARIANTS, CANONICAL], CANONICAL)

    assert db.contents["t0"].rb_local_usn == before["t0"] + 1
    assert db.contents["tc"].rb_local_usn == before["tc"], "already-canonical rows are not written"


# ----------------------------------------------------------- the writer + the lock


def test_writer_is_update_content_never_update_content_artist(lock) -> None:
    """``update_content_artist`` and ``update_tracks_metadata`` are tripwires on the fake."""
    db = _facade(lock, _rows(3))
    # Credited to a variant spelling but already pointing at the canonical row: read,
    # recognised, left alone — and never journalled, because nothing changed.
    db.contents["t2"].artist_id = db.get_artist_by_name(CANONICAL).id

    result = merge.apply(db, [*VARIANTS, CANONICAL], CANONICAL)

    assert sorted(db.update_content_calls) == ["t0", "t1"]
    assert result.tracks_rewritten == 2
    assert result.tracks_already_canonical == 1
    assert {m["content_id"] for m in fixer_log.get_mutations(result.run_id)} == {"t0", "t1"}


def test_db_lock_is_held_once_per_chunk(lock, monkeypatch) -> None:
    monkeypatch.setattr(merge, "CHUNK_SIZE", 2)
    db = _facade(lock, _rows(5))
    # Pre-create the canonical row so the only acquisitions are the chunks themselves.
    assert db.get_artist_by_name(CANONICAL) is not None

    merge.apply(db, [*VARIANTS, CANONICAL], CANONICAL)

    # 5 absorbed tracks (the canonical one is never read) -> 3 chunks of 2.
    assert lock.entered == 3
    assert not lock.held


def test_canonical_artist_is_created_once_under_the_lock(lock) -> None:
    db = _facade(lock, [(f"t{i}", VARIANTS[i % 2]) for i in range(4)])

    result = merge.apply(db, list(VARIANTS), CANONICAL)

    assert db.created_artists == [CANONICAL]
    assert result.canonical_artist_id == db.get_artist_by_name(CANONICAL).id


# --------------------------------------------------------------- apply then revert


def test_apply_then_revert_restores_the_artist_id(lock) -> None:
    db = _facade(lock, _rows(4))
    before = {cid: row.artist_id for cid, row in db.contents.items()}

    applied = merge.apply(db, [*VARIANTS, CANONICAL], CANONICAL)
    assert applied.revertable

    reverted = merge.revert(db, applied.run_id)

    assert reverted.complete
    assert reverted.tracks_restored == 4
    assert {cid: row.artist_id for cid, row in db.contents.items()} == before


def test_revert_restores_the_file_tag(lock, _no_real_files) -> None:
    db = _facade(lock, _rows(2))

    applied = merge.apply(db, [*VARIANTS, CANONICAL], CANONICAL)
    assert sorted(_no_real_files["written"]) == [
        ("C:/music/t0.aiff", CANONICAL),
        ("C:/music/t1.aiff", CANONICAL),
    ]
    _no_real_files["written"].clear()

    merge.revert(db, applied.run_id)

    assert sorted(_no_real_files["written"]) == [
        ("C:/music/t0.aiff", "tag:C:/music/t0.aiff"),
        ("C:/music/t1.aiff", "tag:C:/music/t1.aiff"),
    ]


def test_revert_marks_every_mutation_and_is_idempotent(lock) -> None:
    db = _facade(lock, _rows(3))
    applied = merge.apply(db, [*VARIANTS, CANONICAL], CANONICAL)

    merge.revert(db, applied.run_id)
    second = merge.revert(db, applied.run_id)

    assert second.tracks_restored == 0
    assert fixer_log.get_run(applied.run_id)["status"] == fixer_log.RUN_REVERTED
    assert all(m["reverted"] for m in fixer_log.get_mutations(applied.run_id))


def test_revert_refuses_a_run_it_did_not_write(lock) -> None:
    """The undo log is shared with the metadata fixer — its runs must bounce off."""
    db = _facade(lock, _rows(1))
    foreign = fixer_log.create_run([1], note="name fixer, not a merge")

    with pytest.raises(ValueError, match="not an artist-merge run"):
        merge.revert(db, foreign)


def test_revert_of_an_unknown_run_raises(lock) -> None:
    with pytest.raises(KeyError):
        merge.revert(_facade(lock, _rows(1)), "nope")


# ------------------------------------------------------------------- file handling


def test_locked_file_is_skipped_and_reported(lock, _no_real_files) -> None:
    """The DB row is still merged and journalled; the file is reported, never half-written."""
    _no_real_files["locked"].add("C:/music/t1.aiff")
    db = _facade(lock, _rows(3))

    result = merge.apply(db, [*VARIANTS, CANONICAL], CANONICAL)

    assert result.tracks_rewritten == 3
    assert result.files_retagged == 2
    assert [(f.content_id, f.reason) for f in result.files_skipped] == [
        ("t1", merge.SKIP_TAG_WRITE_FAILED)
    ]
    assert ("C:/music/t1.aiff", CANONICAL) not in _no_real_files["written"]
    # The row is journalled either way, so the skipped file is still revertable.
    journalled = {m["content_id"] for m in fixer_log.get_mutations(result.run_id)}
    assert journalled == {"t0", "t1", "t2"}


def test_revert_leaves_a_failed_tag_write_unreverted_and_reports_partial(
    lock, _no_real_files
) -> None:
    db = _facade(lock, _rows(2))
    applied = merge.apply(db, [*VARIANTS, CANONICAL], CANONICAL)
    _no_real_files["locked"].add("C:/music/t1.aiff")

    reverted = merge.revert(db, applied.run_id)

    assert not reverted.complete
    assert reverted.tracks_restored == 2
    assert [f.content_id for f in reverted.files_skipped] == ["t1"]
    assert fixer_log.get_run(applied.run_id)["status"] == fixer_log.RUN_REVERT_PARTIAL
    still_open = [m for m in fixer_log.get_mutations(applied.run_id) if not m["reverted"]]
    assert [m["content_id"] for m in still_open] == ["t1"]


# ------------------------------------------------------------- the _file_sha1 budget


def test_verify_bytes_defaults_off_above_the_threshold(lock, monkeypatch, _no_real_files) -> None:
    monkeypatch.setattr(merge, "VERIFY_BYTES_MAX_TRACKS", 2)
    db = _facade(lock, _rows(4))

    result = merge.apply(db, [*VARIANTS, CANONICAL], CANONICAL)

    assert result.verify_bytes is False
    assert _no_real_files["hashed"] == []


def test_verify_bytes_defaults_on_below_the_threshold(lock, monkeypatch, _no_real_files) -> None:
    monkeypatch.setattr(merge, "VERIFY_BYTES_MAX_TRACKS", 250)
    db = _facade(lock, _rows(2))

    result = merge.apply(db, [*VARIANTS, CANONICAL], CANONICAL)

    assert result.verify_bytes is True
    # Two files, hashed before and after their tag write.
    assert len(_no_real_files["hashed"]) == 4
    assert result.files_verified_changed == 2


def test_no_hashing_and_no_file_access_when_tags_are_off(lock, _no_real_files) -> None:
    db = _facade(lock, _rows(3))

    result = merge.apply(db, [*VARIANTS, CANONICAL], CANONICAL, write_tags=False, verify_bytes=True)

    assert result.write_tags is False
    assert result.verify_bytes is False, "verification never runs when no file is touched"
    assert _no_real_files["hashed"] == []
    assert _no_real_files["written"] == []
    assert result.files_retagged == 0
    assert result.tracks_rewritten == 3


def test_revert_of_a_tagless_run_touches_no_file(lock, _no_real_files) -> None:
    db = _facade(lock, _rows(2))
    applied = merge.apply(db, [*VARIANTS, CANONICAL], CANONICAL, write_tags=False)

    reverted = merge.revert(db, applied.run_id)

    assert reverted.complete
    assert _no_real_files["written"] == []


# --------------------------------------------------------------- Rekordbox running


def test_apply_refuses_to_start_while_rekordbox_runs(lock, monkeypatch) -> None:
    monkeypatch.setattr(merge, "_rekordbox_running", lambda: True)
    db = _facade(lock, _rows(2))

    with pytest.raises(merge.RekordboxRunningError):
        merge.apply(db, [*VARIANTS, CANONICAL], CANONICAL)

    assert db.update_content_calls == []
    assert fixer_log.list_runs() == []


def test_run_aborts_cleanly_when_rekordbox_starts_mid_way(lock, monkeypatch) -> None:
    monkeypatch.setattr(merge, "CHUNK_SIZE", 2)
    db = _facade(lock, _rows(5))
    calls = {"n": 0}

    def _running() -> bool:
        calls["n"] += 1
        # 1 = start guard, 2 = first chunk, 3 = second chunk (Rekordbox just opened).
        return calls["n"] >= 3

    monkeypatch.setattr(merge, "_rekordbox_running", _running)

    result = merge.apply(db, [*VARIANTS, CANONICAL], CANONICAL)

    assert result.aborted is True
    assert result.abort_reason == merge.ABORT_REKORDBOX_RUNNING
    assert result.tracks_rewritten == 2, "one chunk written, the rest untouched"
    assert len(db.update_content_calls) == 2
    assert fixer_log.get_run(result.run_id)["status"] == fixer_log.RUN_FAILED
    # What did land is still journalled, so the partial run reverts cleanly.
    assert len(fixer_log.get_mutations(result.run_id)) == 2


def test_aborted_run_reverts_only_what_it_wrote(lock, monkeypatch) -> None:
    monkeypatch.setattr(merge, "CHUNK_SIZE", 2)
    db = _facade(lock, _rows(5))
    before = {cid: row.artist_id for cid, row in db.contents.items()}
    calls = {"n": 0}
    monkeypatch.setattr(
        merge, "_rekordbox_running", lambda: (calls.update(n=calls["n"] + 1), calls["n"] >= 3)[1]
    )

    applied = merge.apply(db, [*VARIANTS, CANONICAL], CANONICAL)
    monkeypatch.setattr(merge, "_rekordbox_running", lambda: False)
    reverted = merge.revert(db, applied.run_id)

    assert reverted.complete
    assert {cid: row.artist_id for cid, row in db.contents.items()} == before


# ----------------------------------------------------------------------- orphans


def test_delete_orphans_is_off_by_default(lock) -> None:
    db = _facade(lock, _rows(3))

    result = merge.apply(db, [*VARIANTS, CANONICAL], CANONICAL)

    assert db.deleted_artists == []
    assert result.orphans_deleted == ()
    assert result.as_dict()["orphan_warning"] == ""


def test_delete_orphans_removes_the_emptied_rows_and_journals_them_last(lock) -> None:
    db = _facade(lock, _rows(4))
    emptied = {db.get_artist_by_name(name).id for name in VARIANTS}

    result = merge.apply(db, [*VARIANTS, CANONICAL], CANONICAL, delete_orphans=True)

    assert set(db.deleted_artists) == emptied
    assert sorted(result.orphans_deleted) == sorted(VARIANTS)
    assert merge.ORPHAN_WARNING in result.as_dict()["orphan_warning"]
    journal = fixer_log.get_mutations(result.run_id)
    assert [m["entity_kind"] for m in journal[-2:]] == [fixer_log.ENTITY_ARTIST] * 2


def test_revert_reinserts_the_artist_first_and_remaps_the_new_id(lock) -> None:
    """rbox mints a fresh id on insert, so the tracks must follow the NEW id."""
    db = _facade(lock, _rows(4))
    applied = merge.apply(db, [*VARIANTS, CANONICAL], CANONICAL, delete_orphans=True)

    reverted = merge.revert(db, applied.run_id)

    assert reverted.artists_restored == 2
    assert reverted.orphan_links_not_restored is True
    remap = {r["old"]: r["new"] for r in reverted.artist_id_remap}
    assert remap and all(old != new for old, new in remap.items())
    for cid in ("t0", "t1", "t2", "t3"):
        artist_id = db.contents[cid].artist_id
        assert artist_id in remap.values()
        assert db.artist_rows[artist_id].name in VARIANTS


def test_orphan_deletion_is_skipped_when_a_row_is_still_referenced(lock) -> None:
    """A variant the merge could not fully empty is reported, never deleted blindly."""
    db = _facade(lock, _rows(4))
    # The UI says this spelling owns one more track than the merge will repoint.
    stale = next(a for a in db.artists if a["name"] == VARIANTS[0])
    stale["track_count"] += 1

    result = merge.apply(db, [*VARIANTS, CANONICAL], CANONICAL, delete_orphans=True)

    skipped = {o["name"]: o["reason"] for o in result.orphans_skipped}
    assert VARIANTS[0] in skipped
    assert "still referenced" in skipped[VARIANTS[0]]
    assert db.get_artist_by_name(VARIANTS[0]) is not None


def test_orphans_are_left_alone_when_the_run_aborted(lock, monkeypatch) -> None:
    monkeypatch.setattr(merge, "CHUNK_SIZE", 2)
    db = _facade(lock, _rows(5))
    calls = {"n": 0}
    monkeypatch.setattr(
        merge, "_rekordbox_running", lambda: (calls.update(n=calls["n"] + 1), calls["n"] >= 3)[1]
    )

    result = merge.apply(db, [*VARIANTS, CANONICAL], CANONICAL, delete_orphans=True)

    assert result.aborted
    assert db.deleted_artists == []
    assert all(o["reason"] == "run did not finish cleanly" for o in result.orphans_skipped)


# ------------------------------------------------------------------- journal shape


def test_journal_captures_the_artist_id_not_only_the_name(lock) -> None:
    """The name alone cannot restore the entity link — the id is what revert needs."""
    db = _facade(lock, _rows(2))
    before_artist_id = db.contents["t0"].artist_id

    result = merge.apply(db, [*VARIANTS, CANONICAL], CANONICAL)

    row = next(m for m in fixer_log.get_mutations(result.run_id) if m["content_id"] == "t0")
    assert row["field"] == merge.FIELD_ARTIST_ID
    assert row["before_value"] == before_artist_id
    assert row["before_value"] != result.canonical_artist_id
    assert row["after_value"] == result.canonical_artist_id
    assert row["before_json"]["artist_name"] == VARIANTS[0]
    assert row["before_json"]["tag_artist"] == "tag:C:/music/t0.aiff"
    assert row["entity_kind"] == merge.ENTITY_MERGE_CONTENT
    assert row["rule_id"] is None


def test_run_note_marks_the_run_as_an_artist_merge(lock) -> None:
    db = _facade(lock, _rows(2))

    result = merge.apply(db, [*VARIANTS, CANONICAL], CANONICAL)

    note = json.loads(fixer_log.get_run(result.run_id)["note"])
    assert note["kind"] == merge.MERGE_RUN_KIND
    assert note["canonical"] == CANONICAL
    assert sorted(note["absorbing"]) == sorted(VARIANTS)


# -------------------------------------------------------------------- refusals


def test_apply_refuses_a_backend_without_the_artist_writers(lock) -> None:
    class Bare:
        artists: ClassVar[list[dict[str, Any]]] = []

    with pytest.raises(merge.MergeUnavailable):
        merge.apply(Bare(), list(VARIANTS), CANONICAL)


def test_apply_refuses_a_group_with_nothing_to_absorb(lock) -> None:
    db = _facade(lock, [("t0", CANONICAL)])

    with pytest.raises(ValueError, match="nothing to merge"):
        merge.apply(db, [CANONICAL], CANONICAL)


def test_apply_refuses_a_bare_artist_name_where_a_group_id_belongs(lock) -> None:
    db = _facade(lock, _rows(2))

    with pytest.raises(ValueError, match="not a group id"):
        merge.apply(db, CANONICAL, CANONICAL)


def test_tag_updates_only_ever_carries_the_allowlisted_field() -> None:
    assert merge._tag_updates("X") == {merge.TAG_FIELD_ARTIST: "X"}
    assert merge.TAG_FIELD_ARTIST == "Artist", "'ArtistName' is a silent no-op in rbox"
