"""taste-vector store tests (recommender-taste-llm-audio T1 — app/db_taste.py).

Covers schema-create idempotency, the INSERT OR REPLACE round-trip + overwrite,
kind validation, listing, and profile deletion. Pure stdlib sqlite3 — no app.main,
no numpy.
"""

from __future__ import annotations

import pytest

from app import db_taste


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Point db_taste at a throwaway DB file."""
    db_file = tmp_path / "track_vectors.db"
    monkeypatch.setattr(db_taste, "_TASTE_DB", db_file)
    db_taste.init_taste_db()
    return db_taste


def test_init_is_idempotent(fresh_db):
    fresh_db.init_taste_db()  # second call must not raise
    names = {
        r["name"]
        for r in fresh_db._conn()
        .execute("SELECT name FROM sqlite_master WHERE type='table'")
        .fetchall()
    }
    assert "user_taste_vectors" in names


def test_upsert_round_trip(fresh_db):
    fresh_db.upsert_taste_vector("user-1", "centroid", b"\x00\x01\x02", n_source_tracks=42)
    got = fresh_db.get_taste_vector("user-1", "centroid")
    assert got is not None
    assert got["vector_blob"] == b"\x00\x01\x02"
    assert got["n_source_tracks"] == 42
    assert got["computed_at"]  # stamped


def test_insert_or_replace_overwrites_in_place(fresh_db):
    fresh_db.upsert_taste_vector("user-1", "centroid", b"old", n_source_tracks=8)
    fresh_db.upsert_taste_vector("user-1", "centroid", b"new", n_source_tracks=99)
    got = fresh_db.get_taste_vector("user-1", "centroid")
    assert got["vector_blob"] == b"new"
    assert got["n_source_tracks"] == 99
    # exactly one row for that (profile, kind) — no duplicate
    assert len(fresh_db.list_taste_vectors("user-1")) == 1


def test_get_unknown_returns_none(fresh_db):
    assert fresh_db.get_taste_vector("nobody", "centroid") is None


def test_invalid_kind_rejected(fresh_db):
    with pytest.raises(ValueError):
        fresh_db.upsert_taste_vector("user-1", "bogus", b"x", n_source_tracks=1)


def test_empty_profile_id_rejected(fresh_db):
    with pytest.raises(ValueError):
        fresh_db.upsert_taste_vector("", "centroid", b"x", n_source_tracks=1)


def test_list_and_delete_profile(fresh_db):
    fresh_db.upsert_taste_vector("u", "centroid", b"a", n_source_tracks=1)
    fresh_db.upsert_taste_vector("u", "cluster_0", b"b", n_source_tracks=1)
    fresh_db.upsert_taste_vector("other", "centroid", b"c", n_source_tracks=1)
    assert {v["kind"] for v in fresh_db.list_taste_vectors("u")} == {"centroid", "cluster_0"}
    assert fresh_db.delete_profile("u") == 2
    assert fresh_db.list_taste_vectors("u") == []
    assert fresh_db.get_taste_vector("other", "centroid") is not None  # untouched
