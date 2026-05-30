"""metadata-fixer undo-log schema tests (T4 — app/metadata_fixer/schema.py).

Covers schema-create, the run/mutation round-trip, the revert-row shape
(pre-image JSON survives a round-trip), undo ordering, and status transitions.
"""

from __future__ import annotations

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
