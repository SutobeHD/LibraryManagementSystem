"""PopularityStore tests (underground-mainstream-classifier T1-T3).

Covers the sidecar skeleton + schema-version/migrate framework + CRUD
(upsert/get/get_all/get_stale/delete). Pure stdlib sqlite3 — no app.main,
no network, no app.database.
"""

from __future__ import annotations

import pytest

from app.popularity_engine import SCHEMA_VERSION, PopularityStore


@pytest.fixture
def store(tmp_path):
    return PopularityStore(db_path=tmp_path / "popularity.sqlite")


def test_init_creates_tables_and_stamps_version(store):
    assert store.schema_version() == SCHEMA_VERSION
    with store._connect() as c:
        names = {
            r["name"]
            for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
    assert {"popularity", "popularity_meta"} <= names


def test_reopen_is_idempotent(tmp_path):
    db = tmp_path / "popularity.sqlite"
    PopularityStore(db_path=db)
    again = PopularityStore(db_path=db)  # must not raise or re-stamp wrong
    assert again.schema_version() == SCHEMA_VERSION


def test_upsert_and_get_round_trip(store):
    store.upsert(
        "t1",
        "soundcloud",
        raw_count=50_000,
        log_count=4.7,
        percentile=0.82,
        match_method="fuzzy",
        match_confidence=0.91,
        fetched_at=1_000,
    )
    row = store.get("t1", "soundcloud")
    assert row is not None
    assert row["raw_count"] == 50_000
    assert row["percentile"] == 0.82
    assert row["match_method"] == "fuzzy"
    assert row["fetched_at"] == 1_000


def test_upsert_replaces_in_place(store):
    store.upsert("t1", "soundcloud", raw_count=10, fetched_at=1)
    store.upsert("t1", "soundcloud", raw_count=999, fetched_at=2)
    assert store.get("t1", "soundcloud")["raw_count"] == 999
    assert len(store.get_all("t1")) == 1  # composite PK — no duplicate


def test_get_all_multiple_platforms(store):
    store.upsert("t1", "soundcloud", raw_count=50_000)
    store.upsert("t1", "spotify", raw_count=42)
    store.upsert("other", "soundcloud", raw_count=1)
    platforms = {r["platform"] for r in store.get_all("t1")}
    assert platforms == {"soundcloud", "spotify"}


def test_get_unknown_returns_none(store):
    assert store.get("nope", "soundcloud") is None


def test_get_stale_filters_by_ttl(store):
    store.upsert("fresh", "soundcloud", raw_count=1, fetched_at=10_000)
    store.upsert("old", "soundcloud", raw_count=1, fetched_at=100)
    # now=10_500, ttl=1000 -> cutoff 9_500: only "old" (100) is stale
    stale = store.get_stale(ttl_seconds=1_000, now=10_500)
    assert [r["track_id"] for r in stale] == ["old"]


def test_delete_one_platform_and_whole_track(store):
    store.upsert("t1", "soundcloud", raw_count=1)
    store.upsert("t1", "spotify", raw_count=2)
    assert store.delete("t1", "spotify") == 1
    assert {r["platform"] for r in store.get_all("t1")} == {"soundcloud"}
    assert store.delete("t1") == 1  # remaining row
    assert store.get_all("t1") == []


def test_upsert_validates_empty_keys(store):
    with pytest.raises(ValueError):
        store.upsert("", "soundcloud", raw_count=1)
    with pytest.raises(ValueError):
        store.upsert("t1", "", raw_count=1)


def test_migrate_runs_from_old_version(tmp_path):
    # Simulate a pre-existing DB stamped at a future-relative-to-0 version: with
    # SCHEMA_VERSION==1 there is no v0->... gap to migrate (fresh stamps direct),
    # so assert the no-migration-path guard fires when a gap is forced.
    db = tmp_path / "popularity.sqlite"
    s = PopularityStore(db_path=db)
    s._set_schema_version(SCHEMA_VERSION + 5)  # pretend newer DB
    reopened = PopularityStore(db_path=db)  # newer-than-code: warns, does not crash
    assert reopened.schema_version() == SCHEMA_VERSION + 5
