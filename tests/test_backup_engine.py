"""Tests for `app/backup_engine.py`.

Focus: the SQL identifier allowlist added in Phase 1.1. SQLite cannot
parameterise table or column names, so `backup_engine` interpolates them
literally into f-strings — the allowlist is the only thing standing
between this and SQL injection. These tests pin that contract.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from app.backup_engine import (
    _IDENT_RE,
    _TABLE_ALLOWLIST,
    TRACKED_TABLES,
    BackupEngine,
    _check_identifier,
    _check_table_name,
)

# ---------------------------------------------------------------------------
# Allowlist invariants
# ---------------------------------------------------------------------------

class TestTableAllowlist:
    """The static allowlist must reject anything outside TRACKED_TABLES."""

    def test_tracked_tables_is_immutable(self) -> None:
        assert isinstance(TRACKED_TABLES, tuple), (
            "TRACKED_TABLES must be a tuple so it can't be appended to "
            "post-import (which would expand the SQL-injection surface)."
        )

    def test_table_allowlist_is_frozenset(self) -> None:
        assert isinstance(_TABLE_ALLOWLIST, frozenset)

    def test_table_allowlist_covers_every_tracked_table(self) -> None:
        assert set(_TABLE_ALLOWLIST) == set(TRACKED_TABLES)

    def test_known_table_passes(self) -> None:
        _check_table_name("djmdContent")  # must not raise
        _check_table_name("djmdPlaylist")

    @pytest.mark.parametrize(
        "evil",
        [
            "djmdContent; DROP TABLE x",
            "djmdContent--",
            "sqlite_master",
            "djmdContent UNION SELECT *",
            "; DROP TABLE djmdContent; --",
            "djmd_content",  # close but wrong
            "",
            "1; --",
            "'OR'1'='1",
        ],
    )
    def test_injection_attempts_rejected(self, evil: str) -> None:
        with pytest.raises(ValueError, match="not in TRACKED_TABLES"):
            _check_table_name(evil)


class TestIdentifierRegex:
    """`_IDENT_RE` gates column names interpolated into INSERT statements."""

    def test_valid_column_names(self) -> None:
        for name in ("ID", "TitleID", "_underscore", "foo123", "x"):
            _check_identifier(name)

    @pytest.mark.parametrize(
        "evil",
        [
            "1bad",       # starts with digit
            "no-dash",    # hyphen not allowed
            "space here",
            "semi;colon",
            "'quoted'",
            "",
            "DROP TABLE x",
            "x; DROP",
        ],
    )
    def test_invalid_identifier_rejected(self, evil: str) -> None:
        with pytest.raises(ValueError, match="invalid SQL identifier"):
            _check_identifier(evil)

    def test_max_length_enforced(self) -> None:
        # The regex caps identifiers at 64 chars; anything longer is suspicious.
        _check_identifier("a" * 64)  # ok
        with pytest.raises(ValueError):
            _check_identifier("a" * 65)


# ---------------------------------------------------------------------------
# Read / snapshot behaviour against a minimal SQLite fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def tiny_master_db(tmp_path: Path) -> Path:
    """Create a throwaway SQLite DB with one row in djmdContent."""
    db_path = tmp_path / "master.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE djmdContent (ID TEXT PRIMARY KEY, Title TEXT, Artist TEXT);
        INSERT INTO djmdContent (ID, Title, Artist) VALUES ('1', 'foo', 'bar');
        CREATE TABLE djmdPlaylist (ID TEXT PRIMARY KEY, Name TEXT);
        INSERT INTO djmdPlaylist (ID, Name) VALUES ('p1', 'House');
        """
    )
    conn.commit()
    conn.close()
    return db_path


class TestSnapshotDb:
    """`_snapshot_db` is the gate that the allowlist guards.

    `_check_table_name` is exercised directly above via `TestTableAllowlist`;
    here we only verify the snapshot output contract.
    """

    def test_known_table_rows_appear(self, tiny_master_db: Path) -> None:
        engine = BackupEngine(str(tiny_master_db))
        snap = engine._snapshot_db()
        assert "1" in snap["djmdContent"]
        assert snap["djmdContent"]["1"]["Title"] == "foo"

    def test_missing_table_yields_empty_dict(self, tiny_master_db: Path) -> None:
        # djmdCue is tracked but not present in this fixture — should appear
        # in the snapshot as an empty dict, not raise.
        engine = BackupEngine(str(tiny_master_db))
        snap = engine._snapshot_db()
        assert snap["djmdCue"] == {}

    def test_every_tracked_table_appears_in_snapshot(self, tiny_master_db: Path) -> None:
        engine = BackupEngine(str(tiny_master_db))
        snap = engine._snapshot_db()
        assert set(snap.keys()) == set(TRACKED_TABLES)


# ---------------------------------------------------------------------------
# Commit / restore roundtrip
# ---------------------------------------------------------------------------

class TestSnapshotRoundtrip:
    """Create a snapshot, mutate the DB, restore the snapshot, observe revert."""

    def test_snapshot_then_restore_recovers_state(
        self, tiny_master_db: Path, tmp_path: Path, monkeypatch
    ) -> None:
        # Redirect BACKUP_DIR + its derived constants to a per-test scratch
        # area so we don't write into the user's real backup tree.
        from app import backup_engine
        scratch = tmp_path / "backups"
        monkeypatch.setattr(backup_engine, "BACKUP_DIR", scratch)
        monkeypatch.setattr(backup_engine, "COMMITS_DIR", scratch / "commits")
        monkeypatch.setattr(backup_engine, "HEAD_FILE", scratch / "HEAD")
        monkeypatch.setattr(backup_engine, "TIMELINE_FILE", scratch / "timeline.json")

        engine = BackupEngine(str(tiny_master_db))
        first = engine.snapshot("baseline")
        assert first["status"] == "success"
        head_hash = first["hash"]

        # Mutate
        conn = sqlite3.connect(str(tiny_master_db))
        conn.execute("UPDATE djmdContent SET Title='changed' WHERE ID='1'")
        conn.commit()
        conn.close()

        # Restore
        result = engine.restore(head_hash)
        assert result["status"] == "success"

        # Verify the row reverted
        conn = sqlite3.connect(str(tiny_master_db))
        cur = conn.execute("SELECT Title FROM djmdContent WHERE ID='1'")
        title = cur.fetchone()[0]
        conn.close()
        assert title == "foo"

    def test_unknown_table_in_snapshot_is_skipped_not_panicked(
        self, tiny_master_db: Path, tmp_path: Path, monkeypatch
    ) -> None:
        """A snapshot that references a now-deprecated table must skip, not raise."""
        from app import backup_engine
        scratch = tmp_path / "backups"
        monkeypatch.setattr(backup_engine, "BACKUP_DIR", scratch)
        monkeypatch.setattr(backup_engine, "COMMITS_DIR", scratch / "commits")
        monkeypatch.setattr(backup_engine, "HEAD_FILE", scratch / "HEAD")
        monkeypatch.setattr(backup_engine, "TIMELINE_FILE", scratch / "timeline.json")

        engine = BackupEngine(str(tiny_master_db))
        first = engine.snapshot("baseline")

        # Forge a commit file whose `_snapshot` references a poisoned table.
        commit_path = scratch / "commits" / f"{first['hash']}.json.gz"
        import gzip
        with gzip.open(commit_path, "rt", encoding="utf-8") as f:
            data = json.load(f)
        # Splice in a forbidden table
        data["_snapshot"]["evil_table"] = {"row": {"x": 1}}
        with gzip.open(commit_path, "wt", encoding="utf-8") as f:
            json.dump(data, f)

        # Restore must complete without raising — the evil_table row is silently skipped.
        result = engine.restore(first["hash"])
        assert result["status"] == "success"
