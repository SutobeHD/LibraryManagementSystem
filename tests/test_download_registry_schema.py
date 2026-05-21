"""Schema-migration tests for the unified multi-source downloader (Phase 0, P0.3).

Covers the additive migration in ``app/download_registry.py:init_registry()``:
four NULL-able columns on ``download_history`` (isrc / source /
provenance_urls / picked_quality_tier), two new indexes, and the genre-sync
tables (``canonical_genres`` / ``genre_mappings``).

The migration must be idempotent — ``init_registry()`` runs on every startup —
and must not disturb pre-migration rows.
"""

import sqlite3

import pytest

from app import download_registry


@pytest.fixture
def temp_registry(tmp_path, monkeypatch):
    """Point the registry module at an isolated temp DB for the test."""
    db_path = tmp_path / "test_registry.db"
    monkeypatch.setattr(download_registry, "_REGISTRY_DB", db_path)
    return db_path


def _columns(db_path, table: str) -> set[str]:
    with sqlite3.connect(db_path) as c:
        return {row[1] for row in c.execute(f"PRAGMA table_info({table})")}


def _objects(db_path, obj_type: str) -> set[str]:
    with sqlite3.connect(db_path) as c:
        return {
            row[0]
            for row in c.execute("SELECT name FROM sqlite_master WHERE type = ?", (obj_type,))
        }


def test_migration_adds_unified_downloader_columns(temp_registry):
    download_registry.init_registry()
    cols = _columns(temp_registry, "download_history")
    assert {"isrc", "source", "provenance_urls", "picked_quality_tier"} <= cols


def test_migration_creates_genre_tables(temp_registry):
    download_registry.init_registry()
    tables = _objects(temp_registry, "table")
    assert "canonical_genres" in tables
    assert "genre_mappings" in tables


def test_migration_creates_indexes(temp_registry):
    download_registry.init_registry()
    indexes = _objects(temp_registry, "index")
    assert {"idx_dh_isrc", "idx_dh_source", "idx_gm_canonical"} <= indexes


def test_init_registry_is_idempotent(temp_registry, caplog):
    """Second call must not log an error — ALTER guarded by PRAGMA, CREATE IF NOT EXISTS."""
    download_registry.init_registry()
    caplog.clear()
    download_registry.init_registry()
    errors = [r for r in caplog.records if r.levelname == "ERROR"]
    assert not errors, f"second init_registry logged errors: {[r.message for r in errors]}"
    # columns still intact after the re-run
    cols = _columns(temp_registry, "download_history")
    assert {"isrc", "source", "provenance_urls", "picked_quality_tier"} <= cols


def test_legacy_row_survives_migration(temp_registry):
    """A row in the pre-migration column set stays readable; new columns read NULL."""
    download_registry.init_registry()
    with sqlite3.connect(temp_registry) as c:
        c.execute(
            "INSERT INTO download_history (sc_track_id, downloaded_at, status) VALUES (?, ?, ?)",
            ("legacy-123", "2026-01-01T00:00:00Z", "downloaded"),
        )
        c.commit()
    # Re-run the migration — must be a no-op, must not corrupt the row.
    download_registry.init_registry()
    with sqlite3.connect(temp_registry) as c:
        c.row_factory = sqlite3.Row
        row = c.execute(
            "SELECT * FROM download_history WHERE sc_track_id = ?", ("legacy-123",)
        ).fetchone()
    assert row["sc_track_id"] == "legacy-123"
    assert row["isrc"] is None
    assert row["source"] is None
    assert row["provenance_urls"] is None
    assert row["picked_quality_tier"] is None


def test_new_columns_are_writable(temp_registry):
    """The four new columns accept values (round-trip)."""
    download_registry.init_registry()
    with sqlite3.connect(temp_registry) as c:
        c.execute(
            "INSERT INTO download_history "
            "(sc_track_id, downloaded_at, status, isrc, source, provenance_urls, picked_quality_tier) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "uni-1",
                "2026-05-21T00:00:00Z",
                "downloaded",
                "USUM71304455",
                "qobuz",
                '["https://qobuz.com/x", "https://tidal.com/y"]',
                0,
            ),
        )
        c.commit()
        c.row_factory = sqlite3.Row
        row = c.execute(
            "SELECT * FROM download_history WHERE sc_track_id = ?", ("uni-1",)
        ).fetchone()
    assert row["isrc"] == "USUM71304455"
    assert row["source"] == "qobuz"
    assert row["picked_quality_tier"] == 0
