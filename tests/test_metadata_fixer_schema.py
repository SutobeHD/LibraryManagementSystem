"""metadata-fixer undo-log schema tests (T4 — app/metadata_fixer/schema.py).

Covers schema-create, the run/mutation round-trip, the revert-row shape
(pre-image JSON survives a round-trip), undo ordering, and status transitions.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from app.metadata_fixer import schema


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Point the schema module at a throwaway DB and reset the thread-local conn."""
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


def test_schema_create_tables_exist(fresh_db):
    names = {
        r["name"]
        for r in fresh_db._connect()
        .execute("SELECT name FROM sqlite_master WHERE type='table'")
        .fetchall()
    }
    assert {"runs", "mutations"} <= names


def test_create_run_round_trip(fresh_db):
    run_id = fresh_db.create_run([4, 1, 8], note="nightly")
    run = fresh_db.get_run(run_id)
    assert run is not None
    assert run["status"] == schema.RUN_IN_PROGRESS
    assert run["rule_ids"] == [1, 4, 8]  # stored sorted
    assert run["note"] == "nightly"
    assert run["mutation_count"] == 0


def test_record_mutation_revert_row_shape(fresh_db):
    run_id = fresh_db.create_run([1])
    pre_image = {"ID": "123", "Title": "01 - Intro", "ArtistName": "DJ"}
    mid = fresh_db.record_mutation(
        run_id,
        content_id="123",
        rule_id=4,
        field="title",
        before_value="01 - Intro",
        after_value="Intro",
        before_json=pre_image,
        before_sha1="aaa",
        after_sha1="bbb",
        file_path="/music/intro.mp3",
    )
    assert isinstance(mid, str) and len(mid) == 32
    (row,) = fresh_db.get_mutations(run_id)
    # full revert pre-image survives the round-trip
    assert row["before_json"] == pre_image
    assert row["before_value"] == "01 - Intro"
    assert row["after_value"] == "Intro"
    assert row["before_sha1"] == "aaa"
    assert row["file_path"] == "/music/intro.mp3"
    assert row["reverted"] is False
    # run counter bumped
    assert fresh_db.get_run(run_id)["mutation_count"] == 1


def test_get_mutations_reverse_order_for_undo(fresh_db):
    run_id = fresh_db.create_run([1])
    ids = [
        fresh_db.record_mutation(
            run_id,
            content_id=str(i),
            rule_id=1,
            field="title",
            before_value="b",
            after_value="a",
            before_json={"i": i},
        )
        for i in range(3)
    ]
    forward = [m["mutation_id"] for m in fresh_db.get_mutations(run_id)]
    reverse = [m["mutation_id"] for m in fresh_db.get_mutations(run_id, reverse=True)]
    assert forward == ids
    assert reverse == list(reversed(ids))


def test_mark_mutation_reverted_idempotent(fresh_db):
    run_id = fresh_db.create_run([1])
    mid = fresh_db.record_mutation(
        run_id,
        content_id="1",
        rule_id=1,
        field="title",
        before_value="b",
        after_value="a",
        before_json={},
    )
    assert fresh_db.mark_mutation_reverted(mid) is True
    assert fresh_db.mark_mutation_reverted(mid) is False  # already reverted
    (row,) = fresh_db.get_mutations(run_id)
    assert row["reverted"] is True


def test_set_run_status_and_list_newest_first(fresh_db):
    first = fresh_db.create_run([1])
    second = fresh_db.create_run([2])
    fresh_db.set_run_status(first, schema.RUN_COMPLETED)
    runs = fresh_db.list_runs()
    assert next(r["run_id"] for r in runs) == second  # newest first
    assert fresh_db.get_run(first)["status"] == schema.RUN_COMPLETED


def test_get_run_unknown_returns_none(fresh_db):
    assert fresh_db.get_run("nope") is None


# --- v2: entity-aware mutations -------------------------------------------
#
# Verbatim v1 DDL of a shipped install. Kept here (not imported) so a silent
# rewrite of the module's base DDL cannot make the migration test pass.
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


def write_v1_db(path) -> tuple[str, str]:
    """Create a pre-versioning log DB holding one journalled fix. Returns (run, mutation)."""
    run_id, mutation_id = "run-v1", "mut-v1"
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(_V1_DDL)
        conn.execute(
            "INSERT INTO runs (run_id, created_at, status, rule_ids, note, mutation_count) "
            "VALUES (?, '2026-01-01T00:00:00+00:00', 'completed', '[4]', '', 1)",
            (run_id,),
        )
        conn.execute(
            "INSERT INTO mutations (mutation_id, run_id, content_id, rule_id, field, "
            "before_value, after_value, before_json, before_sha1, after_sha1, file_path, "
            "reverted, created_at) VALUES (?, ?, '42', 4, 'Title', '01 - Intro', 'Intro', ?, "
            "'aaa', 'bbb', '/m/1.mp3', 0, '2026-01-01T00:00:01+00:00')",
            (mutation_id, run_id, json.dumps({"ID": "42", "Title": "01 - Intro"})),
        )
        conn.commit()
    finally:
        conn.close()
    return run_id, mutation_id


@pytest.fixture
def legacy_db(tmp_path, monkeypatch):
    """A v1 DB with a journalled row, pointed at but NOT yet migrated."""
    db_file = tmp_path / "metadata_fixer_log.db"
    ids = write_v1_db(db_file)
    monkeypatch.setattr(schema, "_db_path", lambda: db_file)
    if getattr(schema._local, "conn", None) is not None:
        schema._local.conn.close()
        del schema._local.conn
    yield ids
    if getattr(schema._local, "conn", None) is not None:
        schema._local.conn.close()
        del schema._local.conn


def test_entity_kind_migration(legacy_db):
    run_id, mutation_id = legacy_db
    schema.init_db()  # runs the v1 -> v2 step

    conn = schema._connect()
    assert schema._schema_version(conn) == schema.SCHEMA_VERSION
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(mutations)").fetchall()}
    assert {"entity_kind", "entity_id", "after_json"} <= cols

    # the shipped run survives verbatim and keeps everything a revert needs
    (row,) = schema.get_mutations(run_id)
    assert row["mutation_id"] == mutation_id
    assert row["entity_kind"] == schema.ENTITY_CONTENT  # default backfilled
    assert row["entity_id"] is None
    assert row["after_json"] is None
    assert row["content_id"] == "42"
    assert row["rule_id"] == 4
    assert row["field"] == "Title"
    assert row["before_value"] == "01 - Intro"
    assert row["before_json"] == {"ID": "42", "Title": "01 - Intro"}
    assert row["before_sha1"] == "aaa"
    assert row["file_path"] == "/m/1.mp3"
    assert row["reverted"] is False
    assert schema.get_run(run_id)["mutation_count"] == 1

    schema.init_db()  # idempotent: a second boot must not rebuild or lose rows
    assert len(schema.get_mutations(run_id)) == 1
    assert schema._schema_version(schema._connect()) == schema.SCHEMA_VERSION


def test_migration_makes_rule_id_nullable(legacy_db):
    schema.init_db()
    run_id = schema.create_run([])
    mid = schema.record_mutation(
        run_id,
        None,
        None,  # an artist merge has no fixer rule
        "Artist",
        before_value="boys noize",
        after_value=None,
        before_json={"ID": "7", "Name": "boys noize"},
        entity_kind=schema.ENTITY_ARTIST,
        entity_id="7",
    )
    (row,) = schema.get_mutations(run_id)
    assert row["mutation_id"] == mid
    assert row["rule_id"] is None
    assert row["content_id"] is None
    assert row["entity_kind"] == schema.ENTITY_ARTIST
    assert row["entity_id"] == "7"


def test_entity_mutation_round_trip(fresh_db):
    run_id = fresh_db.create_run([])
    pre = {"ID": "7", "Name": "boys noize"}
    post = {"ID": "7", "Name": "Boys Noize"}
    fresh_db.record_mutation(
        run_id,
        None,
        None,
        "Artist",
        before_value="boys noize",
        after_value="Boys Noize",
        before_json=pre,
        after_json=post,
        entity_kind=schema.ENTITY_ARTIST,
        entity_id="7",
    )
    (row,) = fresh_db.get_mutations(run_id)
    assert row["before_json"] == pre
    assert row["after_json"] == post  # post-image survives -> a delete can be re-INSERTed


def test_content_row_defaults_to_content_kind(fresh_db):
    run_id = fresh_db.create_run([1])
    fresh_db.record_mutation(
        run_id,
        "5",
        1,
        "Title",
        before_value="b",
        after_value="a",
        before_json={"ID": "5"},
    )
    (row,) = fresh_db.get_mutations(run_id)
    assert row["entity_kind"] == schema.ENTITY_CONTENT
    assert row["entity_id"] is None
    assert row["after_json"] is None


def test_migrate_leaves_newer_schema_alone(fresh_db, caplog):
    conn = fresh_db._connect()
    fresh_db._set_schema_version(conn, schema.SCHEMA_VERSION + 5)
    conn.commit()
    with caplog.at_level("WARNING"):
        assert fresh_db.migrate(conn) == schema.SCHEMA_VERSION + 5
    assert fresh_db._schema_version(conn) == schema.SCHEMA_VERSION + 5
