"""metadata-fixer apply/revert tests (T5 — app/metadata_fixer/applier.py).

Covers: db_lock held once per write, undo-log journalling, apply→revert DB
value byte-identity, file-SHA-1 round-trip through revert, and the
write_tags=False short-circuit. Uses a fake DB + monkeypatched lock/tag-write
so no real master.db or rbox import is touched.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager

import pytest

from app.metadata_fixer import applier, schema


class FakeDB:
    """Dict-backed stand-in for the RekordboxDB slice the applier uses."""

    def __init__(self, tracks):
        self.tracks = tracks  # {tid: {field: value, "path": ...}}

    def get_track_details(self, tid):
        t = self.tracks.get(tid)
        return dict(t) if t is not None else None

    def update_tracks_metadata(self, ids, updates):
        for tid in ids:
            if tid not in self.tracks:
                return False
            self.tracks[tid].update(updates)
        return True


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    db_file = tmp_path / "metadata_fixer_log.db"
    monkeypatch.setattr(schema, "_db_path", lambda: db_file)
    if getattr(schema._local, "conn", None) is not None:
        schema._local.conn.close()
        del schema._local.conn
    schema.init_db()
    yield schema
    if getattr(schema._local, "conn", None) is not None:
        schema._local.conn.close()
        del schema._local.conn


@pytest.fixture
def lock_counter(monkeypatch):
    """Replace the db_lock with a counting no-op context manager."""
    calls = {"n": 0}

    @contextmanager
    def _counting_lock():
        calls["n"] += 1
        yield

    monkeypatch.setattr(applier, "_db_lock", _counting_lock)
    return calls


@pytest.fixture
def no_tag_write(monkeypatch):
    """Stub the audio tag write so tests never touch real files by default."""
    written = []
    monkeypatch.setattr(applier, "_write_tags", lambda src, updates: written.append((src, updates)))
    return written


def test_apply_holds_db_write_lock(fresh_db, lock_counter, no_tag_write):
    db = FakeDB({"1": {"Title": "01 - Intro", "path": None}})
    fixes = [applier.FixRequest("1", rule_id=4, field="Title", after_value="Intro")]
    applier.apply_fixes(db, fixes, rule_ids=[4])
    assert lock_counter["n"] == 1  # exactly one locked write for one fix


def test_apply_writes_db_and_journals(fresh_db, lock_counter, no_tag_write):
    db = FakeDB({"1": {"Title": "01 - Intro", "path": "/m/1.mp3"}})
    fixes = [applier.FixRequest("1", rule_id=4, field="Title", after_value="Intro")]
    run_id, applied = applier.apply_fixes(db, fixes, rule_ids=[4])
    assert applied == 1
    assert db.tracks["1"]["Title"] == "Intro"  # master.db written
    run = fresh_db.get_run(run_id)
    assert run["status"] == schema.RUN_COMPLETED
    assert run["mutation_count"] == 1
    (mut,) = fresh_db.get_mutations(run_id)
    assert mut["before_value"] == "01 - Intro"
    assert mut["after_value"] == "Intro"
    assert mut["before_json"]["Title"] == "01 - Intro"  # full pre-image stored
    # tag mirror requested with the same updates
    assert no_tag_write == [("/m/1.mp3", {"Title": "Intro"})]


def test_apply_then_revert_restores_db_value(fresh_db, lock_counter, no_tag_write):
    db = FakeDB({"1": {"Title": "01 - Intro", "path": "/m/1.mp3"}})
    fixes = [applier.FixRequest("1", rule_id=4, field="Title", after_value="Intro")]
    run_id, _ = applier.apply_fixes(db, fixes, rule_ids=[4])
    assert db.tracks["1"]["Title"] == "Intro"

    reverted = applier.revert_run(db, run_id)
    assert reverted == 1
    assert db.tracks["1"]["Title"] == "01 - Intro"  # restored byte-identical
    assert fresh_db.get_run(run_id)["status"] == schema.RUN_REVERTED
    (mut,) = fresh_db.get_mutations(run_id)
    assert mut["reverted"] is True
    # second revert is a no-op (mutation already flagged)
    assert applier.revert_run(db, run_id) == 0


def test_apply_revert_file_sha1_round_trip(fresh_db, lock_counter, tmp_path, monkeypatch):
    # Real file whose bytes mirror the field value, with a tag-write stub that
    # actually rewrites the file -> proves the applier's SHA-1 capture + revert
    # restore the original bytes (ID3 byte-identity, modelled).
    audio = tmp_path / "track.mp3"
    audio.write_bytes(b"01 - Intro")

    def fake_write(src, updates):
        audio.write_bytes(updates["Title"].encode())

    monkeypatch.setattr(applier, "_write_tags", fake_write)
    before = hashlib.sha1(audio.read_bytes()).hexdigest()

    db = FakeDB({"1": {"Title": "01 - Intro", "path": str(audio)}})
    run_id, _ = applier.apply_fixes(
        db, [applier.FixRequest("1", 4, "Title", "Intro")], rule_ids=[4]
    )
    (mut,) = fresh_db.get_mutations(run_id)
    assert mut["before_sha1"] == before
    assert mut["after_sha1"] == hashlib.sha1(b"Intro").hexdigest()  # file changed

    applier.revert_run(db, run_id)
    assert hashlib.sha1(audio.read_bytes()).hexdigest() == before  # bytes restored


def test_write_tags_disabled_skips_tag_mirror(fresh_db, lock_counter, monkeypatch):
    called = []
    monkeypatch.setattr(applier, "_write_tags", lambda *a: called.append(a))
    db = FakeDB({"1": {"Title": "01 - Intro", "path": "/m/1.mp3"}})
    applier.apply_fixes(
        db, [applier.FixRequest("1", 4, "Title", "Intro")], rule_ids=[4], write_tags=False
    )
    assert called == []  # never mirrored to file


def test_apply_skips_failed_db_write(fresh_db, lock_counter, no_tag_write):
    db = FakeDB({})  # unknown track -> update_tracks_metadata returns False
    run_id, applied = applier.apply_fixes(
        db, [applier.FixRequest("missing", 4, "Title", "X")], rule_ids=[4]
    )
    assert applied == 0
    assert fresh_db.get_run(run_id)["mutation_count"] == 0  # nothing journalled


# --- v2: entity revert, honest status, sha1 skip ---------------------------

# Verbatim v1 DDL of a shipped install — the legacy log DB below is built from
# it, so the migration is exercised against the real pre-v2 shape.
_V1_DDL = """
CREATE TABLE runs (
    run_id         TEXT PRIMARY KEY,
    created_at     TEXT NOT NULL,
    status         TEXT NOT NULL,
    rule_ids       TEXT NOT NULL,
    note           TEXT NOT NULL DEFAULT '',
    mutation_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE mutations (
    mutation_id  TEXT PRIMARY KEY,
    run_id       TEXT NOT NULL REFERENCES runs(run_id),
    content_id   TEXT NOT NULL,
    rule_id      INTEGER NOT NULL,
    field        TEXT NOT NULL,
    before_value TEXT,
    after_value  TEXT,
    before_json  TEXT NOT NULL,
    before_sha1  TEXT,
    after_sha1   TEXT,
    file_path    TEXT,
    reverted     INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL
);
CREATE INDEX idx_mutations_run ON mutations(run_id);
"""


class EntityDB(FakeDB):
    """FakeDB that can also resurrect a journalled entity row (artist-merge undo)."""

    def __init__(self, tracks, *, restorable=True):
        super().__init__(tracks)
        self.restored = []
        self._restorable = restorable

    def restore_entity(self, entity_kind, entity_id, row):
        if not self._restorable:
            return False
        self.restored.append((entity_kind, entity_id, row))
        return True


def _sha1_spy(monkeypatch):
    """Count _file_sha1 calls instead of timing them."""
    calls = []

    def _spy(path):
        calls.append(path)
        return None

    monkeypatch.setattr(applier, "_file_sha1", _spy)
    return calls


def test_skips_sha1_when_not_writing_tags(fresh_db, lock_counter, monkeypatch, tmp_path):
    audio = tmp_path / "track.mp3"
    audio.write_bytes(b"01 - Intro")
    calls = _sha1_spy(monkeypatch)
    monkeypatch.setattr(applier, "_write_tags", lambda src, updates: None)

    db = FakeDB({"1": {"Title": "01 - Intro", "path": str(audio)}})
    run_id, applied = applier.apply_fixes(
        db, [applier.FixRequest("1", 4, "Title", "Intro")], rule_ids=[4], write_tags=False
    )

    assert applied == 1
    assert calls == []  # no file touched -> no whole-file read
    (mut,) = fresh_db.get_mutations(run_id)
    assert mut["before_sha1"] is None
    assert mut["after_sha1"] is None
    assert mut["file_path"] == str(audio)  # path still journalled


def test_hashes_twice_when_writing_tags(fresh_db, lock_counter, monkeypatch, tmp_path):
    audio = tmp_path / "track.mp3"
    audio.write_bytes(b"01 - Intro")
    calls = _sha1_spy(monkeypatch)
    monkeypatch.setattr(applier, "_write_tags", lambda src, updates: None)

    db = FakeDB({"1": {"Title": "01 - Intro", "path": str(audio)}})
    applier.apply_fixes(db, [applier.FixRequest("1", 4, "Title", "Intro")], rule_ids=[4])

    assert calls == [str(audio), str(audio)]  # before + after, behaviour unchanged


def test_revert_reinserts_deleted_entity(fresh_db, lock_counter, no_tag_write):
    run_id = fresh_db.create_run([])
    pre = {"ID": "7", "Name": "boys noize"}
    fresh_db.record_mutation(
        run_id,
        None,
        None,
        "Artist",
        before_value="boys noize",
        after_value=None,
        before_json=pre,
        entity_kind=schema.ENTITY_ARTIST,
        entity_id="7",
    )
    db = EntityDB({})

    assert applier.revert_run(db, run_id) == 1
    assert db.restored == [(schema.ENTITY_ARTIST, "7", pre)]
    assert lock_counter["n"] == 1  # the re-INSERT holds the master.db lock
    assert fresh_db.get_run(run_id)["status"] == schema.RUN_REVERTED
    (mut,) = fresh_db.get_mutations(run_id)
    assert mut["reverted"] is True
    assert no_tag_write == []  # entity row never touches a file


def test_revert_reinserts_entity_from_after_json(fresh_db, lock_counter, no_tag_write):
    run_id = fresh_db.create_run([])
    removed = {"ID": "7", "Name": "boys noize"}
    fresh_db.record_mutation(
        run_id,
        None,
        None,
        "Artist",
        before_value=None,
        after_value=None,
        before_json={},  # caller journalled the removed row as the post-image
        after_json=removed,
        entity_kind=schema.ENTITY_ARTIST,
        entity_id="7",
    )
    db = EntityDB({})
    assert applier.revert_run(db, run_id) == 1
    assert db.restored == [(schema.ENTITY_ARTIST, "7", removed)]


def test_entity_revert_without_support_is_not_complete(
    fresh_db, lock_counter, no_tag_write, caplog
):
    run_id = fresh_db.create_run([])
    fresh_db.record_mutation(
        run_id,
        None,
        None,
        "Artist",
        before_value="boys noize",
        after_value=None,
        before_json={"ID": "7", "Name": "boys noize"},
        entity_kind=schema.ENTITY_ARTIST,
        entity_id="7",
    )
    db = FakeDB({})  # plain fixer DB slice: no restore_entity

    with caplog.at_level("WARNING"):
        assert applier.revert_run(db, run_id) == 0
    assert fresh_db.get_run(run_id)["status"] == schema.RUN_REVERT_PARTIAL
    (mut,) = fresh_db.get_mutations(run_id)
    assert mut["reverted"] is False  # still pending, so a retry picks it up


def test_partial_revert_is_not_reported_complete(fresh_db, lock_counter, no_tag_write):
    db = FakeDB({"1": {"Title": "a1", "path": None}, "2": {"Title": "a2", "path": None}})
    run_id, applied = applier.apply_fixes(
        db,
        [applier.FixRequest("1", 4, "Title", "b1"), applier.FixRequest("2", 4, "Title", "b2")],
        rule_ids=[4],
    )
    assert applied == 2

    del db.tracks["1"]  # one track vanished -> its revert write fails
    assert applier.revert_run(db, run_id) == 1
    assert db.tracks["2"]["Title"] == "a2"  # the survivor was restored
    assert fresh_db.get_run(run_id)["status"] == schema.RUN_REVERT_PARTIAL

    db.tracks["1"] = {"Title": "b1", "path": None}  # retry once it is back
    assert applier.revert_run(db, run_id) == 1
    assert db.tracks["1"]["Title"] == "a1"
    assert fresh_db.get_run(run_id)["status"] == schema.RUN_REVERTED


def test_pre_v2_row_still_reverts(tmp_path, monkeypatch, lock_counter, no_tag_write):
    """A run journalled by the shipped v1 name-fixer reverts after the migration."""
    db_file = tmp_path / "metadata_fixer_log.db"
    conn = sqlite3.connect(str(db_file))
    try:
        conn.executescript(_V1_DDL)
        conn.execute(
            "INSERT INTO runs (run_id, created_at, status, rule_ids, note, mutation_count) "
            "VALUES ('run-v1', '2026-01-01T00:00:00+00:00', 'completed', '[4]', '', 1)"
        )
        conn.execute(
            "INSERT INTO mutations (mutation_id, run_id, content_id, rule_id, field, "
            "before_value, after_value, before_json, before_sha1, after_sha1, file_path, "
            "reverted, created_at) VALUES ('mut-v1', 'run-v1', '1', 4, 'Title', '01 - Intro', "
            "'Intro', ?, NULL, NULL, NULL, 0, '2026-01-01T00:00:01+00:00')",
            (json.dumps({"ID": "1", "Title": "01 - Intro"}),),
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(schema, "_db_path", lambda: db_file)
    if getattr(schema._local, "conn", None) is not None:
        schema._local.conn.close()
        del schema._local.conn
    try:
        schema.init_db()
        db = FakeDB({"1": {"Title": "Intro", "path": None}})
        assert applier.revert_run(db, "run-v1") == 1
        assert db.tracks["1"]["Title"] == "01 - Intro"
        assert schema.get_run("run-v1")["status"] == schema.RUN_REVERTED
    finally:
        if getattr(schema._local, "conn", None) is not None:
            schema._local.conn.close()
            del schema._local.conn
