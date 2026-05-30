"""variant_schema + variant_detector tests (analysis-remix-detector T-2, T-3).

Title-only M1 path: schema/migration, classification (consuming the shared
external_track_match API), canonical picking (OQ2), clustering + confidence
tiers (OQ3), and sidecar persistence. Pure stdlib sqlite3 — no network, no
master.db, no rbox. db_path injected so no real MUSIC_DIR is touched.
"""

from __future__ import annotations

import sqlite3

import pytest

from app import variant_detector as vd
from app import variant_schema

# ── variant_schema (T-2) ──────────────────────────────────────────────────────


def test_migrate_creates_tables_and_stamps_version():
    conn = sqlite3.connect(":memory:")
    assert variant_schema.migrate(conn) == variant_schema.SCHEMA_VERSION
    names = {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    assert {"track_variants", "variant_meta"} <= names
    idx = {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
    }
    assert {"ix_variants_root", "ix_variants_parent"} <= idx


def test_migrate_idempotent():
    conn = sqlite3.connect(":memory:")
    variant_schema.migrate(conn)
    assert variant_schema.migrate(conn) == variant_schema.SCHEMA_VERSION


def test_migrate_leaves_newer_db_untouched(caplog):
    conn = sqlite3.connect(":memory:")
    variant_schema.migrate(conn)
    variant_schema._set_schema_version(conn, variant_schema.SCHEMA_VERSION + 9)
    conn.commit()
    assert variant_schema.migrate(conn) == variant_schema.SCHEMA_VERSION + 9


# ── classify_track (T-3) ───────────────────────────────────────────────────────


def test_classify_extended_mix():
    c = vd.classify_track({"ID": 1, "Title": "Strobe (Extended Mix)", "Artist": "Deadmau5"})
    assert c["variant_label"] == "extended"
    assert c["normalised_root"] == "strobe"
    assert c["remixer"] is None


def test_classify_remix_captures_remixer():
    c = vd.classify_track({"ID": 2, "Title": "Strobe (Eric Prydz Remix)", "Artist": "Deadmau5"})
    assert c["variant_label"] == "remix"
    assert c["remixer"] == "Eric Prydz"


def test_classify_untagged_defaults_to_original():
    c = vd.classify_track({"ID": 3, "Title": "Strobe", "Artist": "Deadmau5"})
    assert c["variant_label"] == "original"


# ── pick_canonical (OQ2) ──────────────────────────────────────────────────────


def test_pick_canonical_prefers_original():
    members = [
        {"ID": 10, "Title": "Strobe (Extended Mix)"},
        {"ID": 11, "Title": "Strobe"},
    ]
    assert vd.pick_canonical(members) == 11


def test_pick_canonical_user_pin_overrides():
    members = [
        {"ID": 10, "Title": "Strobe", "is_canonical": 0},
        {"ID": 11, "Title": "Strobe (VIP)", "is_canonical": 1},
    ]
    assert vd.pick_canonical(members) == 11


def test_pick_canonical_tiebreak_lowest_id():
    members = [
        {"ID": 20, "Title": "Strobe"},
        {"ID": 9, "Title": "Strobe"},
    ]
    assert vd.pick_canonical(members) == 9


def test_pick_canonical_earliest_release():
    members = [
        {"ID": 30, "Title": "Strobe (Edit)", "ReleaseDate": "2010-01-01"},
        {"ID": 31, "Title": "Strobe (Edit)", "ReleaseDate": "2007-01-01"},
    ]
    assert vd.pick_canonical(members) == 31


# ── cluster_by_root + confidence tiers (OQ3) ──────────────────────────────────


def test_cluster_same_artist_high_confidence():
    tracks = [
        {"ID": 1, "Title": "Strobe", "Artist": "Deadmau5"},
        {"ID": 2, "Title": "Strobe (Extended Mix)", "Artist": "Deadmau5"},
    ]
    rows = vd.cluster_by_root(tracks)
    assert len(rows) == 1
    assert rows[0]["track_id"] == 2
    assert rows[0]["parent_track_id"] == 1
    assert rows[0]["confidence"] == vd.CONFIDENCE_SAME_ARTIST


def test_cluster_cross_artist_lower_confidence():
    tracks = [
        {"ID": 1, "Title": "Strobe", "Artist": "Deadmau5"},
        {"ID": 2, "Title": "Strobe (Someone Remix)", "Artist": "Other DJ"},
    ]
    rows = vd.cluster_by_root(tracks)
    assert rows[0]["confidence"] == vd.CONFIDENCE_ROOT_ONLY


def test_cluster_singleton_emits_no_edge():
    rows = vd.cluster_by_root([{"ID": 1, "Title": "Lonely Track", "Artist": "X"}])
    assert rows == []


# ── persistence round-trip (T-3) ──────────────────────────────────────────────


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "variants.db"


def test_scan_persists_and_reads_back(db_path):
    tracks = [
        {"ID": 1, "Title": "Strobe", "Artist": "Deadmau5"},
        {"ID": 2, "Title": "Strobe (Radio Edit)", "Artist": "Deadmau5"},
        {"ID": 3, "Title": "Strobe (Club Mix)", "Artist": "Deadmau5"},
    ]
    written = vd.scan(tracks, db_path=db_path)
    assert written == 2  # two non-canonical members
    v2 = vd.get_variants(2, db_path=db_path)
    assert v2[0]["parent_track_id"] == 1
    cluster = vd.get_cluster("strobe", db_path=db_path)
    assert {r["track_id"] for r in cluster} == {2, 3}


def test_upsert_replaces_in_place(db_path):
    vd.init(db_path)
    row = {
        "track_id": 5,
        "variant_label": "remix",
        "normalised_root": "x",
        "remixer": "A",
        "parent_track_id": 4,
        "confidence": 0.75,
        "source": vd.SOURCE_TITLE,
        "computed_at": "2026-05-30T00:00:00+00:00",
    }
    vd.upsert_variant(row, db_path=db_path)
    vd.upsert_variant({**row, "confidence": 0.55}, db_path=db_path)
    got = vd.get_variants(5, db_path=db_path)
    assert len(got) == 1
    assert got[0]["confidence"] == 0.55
