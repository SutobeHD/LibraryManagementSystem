"""Tests for app/variant_schema.py — variants.db DDL + migration runner.

Uses in-memory SQLite. Locks: fresh-DB create+stamp, idempotency, the
newer-than-code guard, and that the produced schema actually accepts a row.
"""

from __future__ import annotations

import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import variant_schema as vs  # noqa: E402


def _conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    return c


def test_fresh_db_creates_and_stamps():
    c = _conn()
    result = vs.migrate(c)
    assert result == vs.SCHEMA_VERSION
    assert vs._schema_version(c) == vs.SCHEMA_VERSION


def test_migrate_is_idempotent():
    c = _conn()
    vs.migrate(c)
    again = vs.migrate(c)  # second call must not raise or change version
    assert again == vs.SCHEMA_VERSION
    assert vs._schema_version(c) == vs.SCHEMA_VERSION


def test_tables_and_indexes_exist():
    c = _conn()
    vs.migrate(c)
    names = {
        r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type IN ('table','index')")
    }
    assert "track_variants" in names
    assert "variant_meta" in names
    assert "ix_variants_root" in names
    assert "ix_variants_parent" in names


def test_schema_accepts_a_variant_row():
    c = _conn()
    vs.migrate(c)
    c.execute(
        "INSERT INTO track_variants "
        "(track_id, variant_label, normalised_root, confidence, source, computed_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (42, "Remix", "song", 0.9, "title-regex", "2026-01-01T00:00:00+00:00"),
    )
    row = c.execute("SELECT track_id, is_canonical FROM track_variants").fetchone()
    assert row["track_id"] == 42
    assert row["is_canonical"] == 0  # default applied


def test_newer_schema_left_untouched(caplog):
    c = _conn()
    vs.migrate(c)
    vs._set_schema_version(c, vs.SCHEMA_VERSION + 5)  # pretend a newer code wrote it
    c.commit()
    result = vs.migrate(c)
    assert result == vs.SCHEMA_VERSION + 5  # not downgraded
    assert vs._schema_version(c) == vs.SCHEMA_VERSION + 5
