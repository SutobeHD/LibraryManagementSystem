"""Tests for `app/backup_engine.py`.

Focus: the SQL identifier allowlist added in Phase 1.1. SQLite cannot
parameterise table or column names, so `backup_engine` interpolates them
literally into f-strings — the allowlist is the only thing standing
between this and SQL injection. These tests pin that contract.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

_HAS_RBOX = importlib.util.find_spec("rbox") is not None

from app.backup_engine import (
    _IDENT_RE,
    _TABLE_ALLOWLIST,
    TRACKED_TABLES,
    BackupEngine,
    _atomic_write_text,
    _check_identifier,
    _check_table_name,
    _stable_row_id,
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


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

class TestStableRowId:
    def test_uses_uppercase_ID_when_present(self) -> None:
        assert _stable_row_id({"ID": 42, "Title": "x"}) == "42"

    def test_uses_lowercase_id_when_no_ID(self) -> None:
        assert _stable_row_id({"id": "abc", "Title": "x"}) == "abc"

    def test_hash_fallback_is_deterministic_across_calls(self) -> None:
        row = {"NoIdField": True, "Title": "x"}
        first = _stable_row_id(row)
        second = _stable_row_id(row)
        assert first == second
        assert first.startswith("h_"), "hash fallback must be distinguishable from real IDs"

    def test_null_ID_falls_through_to_id_or_hash(self) -> None:
        # If ID is explicitly null in the row, the fallback must not key on it.
        assert _stable_row_id({"ID": None, "id": "fallback"}) == "fallback"
        assert _stable_row_id({"ID": None}).startswith("h_")


class TestAtomicWrite:
    def test_writes_file_with_expected_content(self, tmp_path: Path) -> None:
        target = tmp_path / "head.txt"
        _atomic_write_text(target, "abc123")
        assert target.read_text(encoding="utf-8") == "abc123"

    def test_overwrites_existing_file_atomically(self, tmp_path: Path) -> None:
        target = tmp_path / "head.txt"
        target.write_text("original", encoding="utf-8")
        _atomic_write_text(target, "new")
        assert target.read_text(encoding="utf-8") == "new"

    def test_no_tmp_files_left_behind_on_success(self, tmp_path: Path) -> None:
        target = tmp_path / "head.txt"
        _atomic_write_text(target, "x")
        leftovers = [p for p in tmp_path.iterdir() if p.name != "head.txt"]
        assert leftovers == []


# ---------------------------------------------------------------------------
# Restore — transactional rollback
# ---------------------------------------------------------------------------

class TestRestoreTransaction:
    """Restore wraps DELETE+INSERT in a single ``with conn:`` transaction.

    If any INSERT raises, the entire restore rolls back and the DB is
    untouched. These tests fabricate a poisoned snapshot to provoke
    failure mid-restore.
    """

    @pytest.fixture
    def scratch_engine(self, tiny_master_db: Path, tmp_path: Path, monkeypatch):
        from app import backup_engine
        scratch = tmp_path / "backups"
        monkeypatch.setattr(backup_engine, "BACKUP_DIR", scratch)
        monkeypatch.setattr(backup_engine, "COMMITS_DIR", scratch / "commits")
        monkeypatch.setattr(backup_engine, "HEAD_FILE", scratch / "HEAD")
        monkeypatch.setattr(backup_engine, "TIMELINE_FILE", scratch / "timeline.json")
        return BackupEngine(str(tiny_master_db)), tiny_master_db, scratch

    def test_failed_insert_rolls_back_delete(self, scratch_engine) -> None:
        """Core transaction invariant: a mid-restore failure must leave the
        DB exactly as it was before, not in a half-restored state.

        We poison the snapshot with an unbindable value (a Python dict in
        a TEXT column). sqlite3 raises ProgrammingError on bind, the
        ``with conn:`` block in ``restore()`` does an implicit ROLLBACK,
        and the DELETE that ran earlier in the transaction must vanish.
        """
        engine, db_path, scratch = scratch_engine
        first = engine.snapshot("baseline")
        assert first["status"] == "success"

        commit_path = scratch / "commits" / f"{first['hash']}.json.gz"
        import gzip
        with gzip.open(commit_path, "rt", encoding="utf-8") as f:
            data = json.load(f)
        # Inject a row whose Title is a nested dict — JSON survives this,
        # but sqlite3 refuses to bind a dict to a column.
        data["_snapshot"]["djmdContent"]["2"] = {"ID": "2", "Title": {"unbindable": True}}
        with gzip.open(commit_path, "wt", encoding="utf-8") as f:
            json.dump(data, f, default=str, sort_keys=True)

        conn = sqlite3.connect(str(db_path))
        before_rows = list(conn.execute("SELECT ID, Title FROM djmdContent"))
        conn.close()
        assert ("1", "foo") in before_rows

        result = engine.restore(first["hash"])
        assert result["status"] == "error"
        assert "dict" in result["message"].lower() or "supported" in result["message"].lower()

        # Rollback must restore the table to the pre-restore state.
        conn = sqlite3.connect(str(db_path))
        after_rows = list(conn.execute("SELECT ID, Title FROM djmdContent"))
        conn.close()
        assert after_rows == before_rows, (
            "rollback failed — DELETE landed without the INSERT recovering it"
        )

    def test_restore_missing_commit_returns_error(self, scratch_engine) -> None:
        engine, _db, _scratch = scratch_engine
        result = engine.restore("nonexistent00")
        assert result["status"] == "error"
        assert "not found" in result["message"].lower()

    def test_restore_commit_without_snapshot_returns_error(
        self, scratch_engine, tmp_path: Path
    ) -> None:
        engine, _db, scratch = scratch_engine
        first = engine.snapshot("baseline")

        commit_path = scratch / "commits" / f"{first['hash']}.json.gz"
        import gzip
        with gzip.open(commit_path, "rt", encoding="utf-8") as f:
            data = json.load(f)
        del data["_snapshot"]
        with gzip.open(commit_path, "wt", encoding="utf-8") as f:
            json.dump(data, f, default=str, sort_keys=True)

        result = engine.restore(first["hash"])
        assert result["status"] == "error"
        assert "no restorable snapshot" in result["message"].lower()


# ---------------------------------------------------------------------------
# Commit loading + integrity
# ---------------------------------------------------------------------------

class TestLoadCommit:
    @pytest.fixture
    def scratch_engine(self, tiny_master_db: Path, tmp_path: Path, monkeypatch):
        from app import backup_engine
        scratch = tmp_path / "backups"
        monkeypatch.setattr(backup_engine, "BACKUP_DIR", scratch)
        monkeypatch.setattr(backup_engine, "COMMITS_DIR", scratch / "commits")
        monkeypatch.setattr(backup_engine, "HEAD_FILE", scratch / "HEAD")
        monkeypatch.setattr(backup_engine, "TIMELINE_FILE", scratch / "timeline.json")
        return BackupEngine(str(tiny_master_db)), scratch

    def test_returns_none_for_nonexistent_hash(self, scratch_engine) -> None:
        engine, _ = scratch_engine
        assert engine._load_commit("deadbeef0000") is None

    def test_returns_none_for_corrupt_gzip(self, scratch_engine) -> None:
        engine, scratch = scratch_engine
        (scratch / "commits").mkdir(parents=True, exist_ok=True)
        bad = scratch / "commits" / "deadbeef0000.json.gz"
        bad.write_bytes(b"not a gzip file")
        assert engine._load_commit("deadbeef0000") is None

    def test_returns_data_on_hash_mismatch_with_warning(
        self, scratch_engine, caplog
    ) -> None:
        """Tampered commits load anyway but log a warning."""
        import gzip
        import logging
        engine, scratch = scratch_engine
        first = engine.snapshot("baseline")
        commit_path = scratch / "commits" / f"{first['hash']}.json.gz"
        with gzip.open(commit_path, "rt", encoding="utf-8") as f:
            data = json.load(f)
        # Tamper with the message — re-hashing will mismatch.
        data["message"] = "tampered"
        with gzip.open(commit_path, "wt", encoding="utf-8") as f:
            json.dump(data, f, default=str, sort_keys=True)

        with caplog.at_level(logging.WARNING, logger="app.backup_engine"):
            loaded = engine._load_commit(first["hash"])
        assert loaded is not None
        assert any("hash mismatch" in rec.message for rec in caplog.records)


# ---------------------------------------------------------------------------
# History + prune
# ---------------------------------------------------------------------------

class TestHistoryAndPrune:
    @pytest.fixture
    def scratch_engine(self, tiny_master_db: Path, tmp_path: Path, monkeypatch):
        from app import backup_engine
        scratch = tmp_path / "backups"
        monkeypatch.setattr(backup_engine, "BACKUP_DIR", scratch)
        monkeypatch.setattr(backup_engine, "COMMITS_DIR", scratch / "commits")
        monkeypatch.setattr(backup_engine, "HEAD_FILE", scratch / "HEAD")
        monkeypatch.setattr(backup_engine, "TIMELINE_FILE", scratch / "timeline.json")
        return BackupEngine(str(tiny_master_db)), scratch

    def test_history_includes_legacy_files(self, scratch_engine, tiny_master_db: Path) -> None:
        engine, scratch = scratch_engine
        scratch.mkdir(parents=True, exist_ok=True)
        (scratch / "master_session_old.db").write_bytes(b"legacy data")
        engine.snapshot("incremental_one")
        history = engine.get_history()
        kinds = {h.get("is_legacy", False) for h in history}
        assert True in kinds and False in kinds, "history must mix both legacy and incremental"

    def test_history_limit_zero_returns_everything(self, scratch_engine) -> None:
        engine, _ = scratch_engine
        engine.snapshot("c1")
        # Mutate the DB so the next snapshot actually produces a new commit.
        conn = sqlite3.connect(str(engine.db_path))
        conn.execute("INSERT INTO djmdContent (ID, Title) VALUES ('2', 'two')")
        conn.commit()
        conn.close()
        engine.snapshot("c2")
        all_entries = engine.get_history(limit=0)
        assert len(all_entries) >= 2

    def test_prune_with_zero_days_is_noop(self, scratch_engine) -> None:
        engine, _ = scratch_engine
        engine.snapshot("c1")
        result = engine.prune(retention_days=0)
        assert result == {"deleted_commits": 0, "deleted_legacy": 0, "freed_bytes": 0}

    def test_prune_keeps_head_even_when_old(self, scratch_engine) -> None:
        engine, scratch = scratch_engine
        engine.snapshot("c1")
        # Make the commit ancient
        import os
        for f in (scratch / "commits").glob("*.json.gz"):
            old = 1
            os.utime(f, (old, old))
        result = engine.prune(retention_days=1)
        assert result["deleted_commits"] == 0
        commit_files = list((scratch / "commits").glob("*.json.gz"))
        assert len(commit_files) == 1

    def test_prune_keeps_newest_legacy_of_each_kind(
        self, scratch_engine, tiny_master_db: Path
    ) -> None:
        engine, scratch = scratch_engine
        scratch.mkdir(parents=True, exist_ok=True)
        # Two session backups, both old; keep the newer one.
        old = scratch / "master_session_old.db"
        new = scratch / "master_session_new.db"
        old.write_bytes(b"old data")
        new.write_bytes(b"newer data")
        import os, time
        ancient = time.time() - 365 * 86400
        os.utime(old, (ancient, ancient))
        os.utime(new, (ancient + 1, ancient + 1))

        result = engine.prune(retention_days=1)
        assert result["deleted_legacy"] == 1
        assert not old.exists()
        assert new.exists()


# ---------------------------------------------------------------------------
# Pydantic RestoreReq
# ---------------------------------------------------------------------------

class TestRestoreReqValidation:
    """Pin the contract that restore needs at least one populated target.

    Skipped on platforms without ``rbox`` because ``app.main`` transitively
    imports ``app.database`` -> ``app.live_database`` -> ``rbox``.
    """

    pytestmark = pytest.mark.skipif(
        not _HAS_RBOX,
        reason="pyrekordbox not installed on this platform",
    )

    def test_blank_filename_and_null_hash_is_rejected(self) -> None:
        # Defer imports so the module is only loaded when running this test
        # — main.py is slow to import (loads the library).
        from app.main import RestoreReq
        with pytest.raises(ValueError, match="filename.*commit_hash"):
            RestoreReq(filename="", commit_hash=None)

    def test_whitespace_only_filename_is_rejected(self) -> None:
        from app.main import RestoreReq
        with pytest.raises(ValueError, match="filename.*commit_hash"):
            RestoreReq(filename="   ", commit_hash="")

    def test_filename_alone_is_accepted(self) -> None:
        from app.main import RestoreReq
        req = RestoreReq(filename="master_session_x.db")
        assert req.filename == "master_session_x.db"
        assert req.commit_hash is None

    def test_commit_hash_alone_is_accepted(self) -> None:
        from app.main import RestoreReq
        req = RestoreReq(commit_hash="abc123def456")
        assert req.filename == ""
        assert req.commit_hash == "abc123def456"

    def test_both_populated_is_accepted(self) -> None:
        from app.main import RestoreReq
        req = RestoreReq(filename="x.db", commit_hash="abc")
        assert req.filename == "x.db"
        assert req.commit_hash == "abc"
