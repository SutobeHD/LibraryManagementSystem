"""metadata-fixer apply/revert tests (T5 — app/metadata_fixer/applier.py).

Covers: db_lock held once per write, undo-log journalling, apply→revert DB
value byte-identity, file-SHA-1 round-trip through revert, and the
write_tags=False short-circuit. Uses a fake DB + monkeypatched lock/tag-write
so no real master.db or rbox import is touched.
"""

from __future__ import annotations

import hashlib
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
