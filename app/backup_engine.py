"""Diff-tracked backup engine for Rekordbox Editor Pro.

Commits are stored as gzipped JSON under ``./backups/commits/<hash>.json.gz``.
Each commit currently contains a full snapshot of the tracked tables plus a
diff summary against the previous commit. The diff summary makes the UI
useful; the snapshot makes the restore reliable. True delta-only storage is
a future refactor — see ``docs/research/`` if/when it gets picked up.

Concurrency: every write to ``master.db`` must run under
``app.database._db_write_lock``. The engine itself does not acquire it —
callers (FastAPI routes) do. Both ``snapshot()`` and ``restore()`` mutate
filesystem state (commits dir / HEAD / timeline) but only ``restore()``
mutates the database file.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import re
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

from .config import BACKUP_DIR

logger = logging.getLogger(__name__)

COMMITS_DIR = BACKUP_DIR / "commits"
HEAD_FILE = BACKUP_DIR / "HEAD"
TIMELINE_FILE = BACKUP_DIR / "timeline.json"

# Tables we track for diffs. Immutable tuple — ordering matters for
# ``_snapshot_db`` and the allowlist is the only thing standing between this
# module and SQL injection (SQLite cannot parameterise identifiers).
TRACKED_TABLES: tuple[str, ...] = (
    "djmdContent",
    "djmdPlaylist",
    "djmdSongPlaylist",
    "djmdCue",
    "djmdArtist",
    "djmdAlbum",
    "djmdGenre",
    "djmdLabel",
    "djmdKey",
    "djmdColor",
)

_TABLE_ALLOWLIST: frozenset[str] = frozenset(TRACKED_TABLES)
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")

# Hash truncation length for commit identifiers in filenames.
_HASH_LEN = 12


def _check_table_name(table: str) -> None:
    """Reject identifiers not in the static ``TRACKED_TABLES`` allowlist."""
    if table not in _TABLE_ALLOWLIST:
        raise ValueError(f"backup_engine: table {table!r} is not in TRACKED_TABLES")


def _check_identifier(name: str) -> None:
    """Reject SQL identifiers that don't match ``_IDENT_RE``."""
    if not _IDENT_RE.match(name):
        raise ValueError(f"backup_engine: invalid SQL identifier {name!r}")


def _atomic_write_text(path: Path, content: str) -> None:
    """Write ``content`` to ``path`` via tmp-file + ``os.replace``.

    Prevents corrupting ``HEAD`` / ``timeline.json`` if the process dies
    mid-write. Both files are load-bearing — a partial write leaves the
    backup store unusable until manually patched.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_name, path)
    except OSError:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _stable_row_id(row: dict) -> str:
    """Deterministic row identifier for diff-keying.

    Tracked Rekordbox tables all expose an ``ID`` column. The JSON-hash
    fallback below is reproducible across process starts — unlike
    ``hash()`` which is PYTHONHASHSEED-randomised and would mis-classify
    rows as "modified" after a restart.
    """
    if "ID" in row and row["ID"] is not None:
        return str(row["ID"])
    if "id" in row and row["id"] is not None:
        return str(row["id"])
    blob = json.dumps(row, default=str, sort_keys=True).encode("utf-8")
    return "h_" + hashlib.sha1(blob).hexdigest()[:16]  # noqa: S324 - non-crypto use


class BackupEngine:
    """Diff-tracked backup system inspired by Git."""

    def __init__(self, db_path: str) -> None:
        self.db_path = Path(db_path)
        COMMITS_DIR.mkdir(parents=True, exist_ok=True)

    # ── Snapshot & Diff ──────────────────────────────────────────────

    def _snapshot_db(self) -> dict[str, dict[str, dict]]:
        """Snapshot every tracked table via a single SQLite connection."""
        snapshot: dict[str, dict[str, dict]] = {table: {} for table in TRACKED_TABLES}

        try:
            conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        except sqlite3.Error as e:
            logger.error("backup_engine._snapshot_db: connect failed err=%s", e)
            return snapshot

        try:
            conn.row_factory = sqlite3.Row
            for table in TRACKED_TABLES:
                _check_table_name(table)
                cur = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                )
                if not cur.fetchone():
                    continue

                try:
                    cur = conn.execute(f"SELECT * FROM {table}")  # nosec B608 - allowlisted
                    rows: dict[str, dict] = {}
                    for row in cur:
                        d = dict(row)
                        rows[_stable_row_id(d)] = d
                    snapshot[table] = rows
                except sqlite3.Error as e:
                    logger.warning(
                        "backup_engine._snapshot_db: table=%s err=%s", table, e,
                    )
        finally:
            conn.close()

        return snapshot

    def _diff_tables(self, old: dict[str, dict], new: dict[str, dict]) -> dict:
        """Calculate per-table diff between two snapshots."""
        modified: list[dict] = []
        added: list[dict] = []
        deleted: list[str] = []

        old_ids = set(old.keys())
        new_ids = set(new.keys())

        for rid in new_ids - old_ids:
            added.append(new[rid])
        for rid in old_ids - new_ids:
            deleted.append(rid)
        for rid in old_ids & new_ids:
            if json.dumps(old[rid], default=str, sort_keys=True) != json.dumps(
                new[rid], default=str, sort_keys=True
            ):
                modified.append({"id": rid, "old": old[rid], "new": new[rid]})

        return {"modified": modified, "added": added, "deleted": deleted}

    # ── Commit / Restore ────────────────────────────────────────────

    def snapshot(self, message: str = "Manual backup") -> dict:
        """Create a commit. Returns ``{status, hash, stats, ...}``.

        Caller must already hold ``_db_write_lock`` if other writers might
        race against the read.
        """
        current = self._snapshot_db()
        head_hash = self._get_head()
        parent_snapshot: dict | None = None

        if head_hash:
            parent_commit = self._load_commit(head_hash)
            if parent_commit and "_snapshot" in parent_commit:
                parent_snapshot = parent_commit["_snapshot"]

        tables_diff: dict[str, dict] = {}
        stats = {"modified": 0, "added": 0, "deleted": 0}
        has_changes = False

        for table in TRACKED_TABLES:
            old_data = parent_snapshot.get(table, {}) if parent_snapshot else {}
            new_data = current.get(table, {})
            diff = self._diff_tables(old_data, new_data)
            if diff["modified"] or diff["added"] or diff["deleted"]:
                tables_diff[table] = diff
                has_changes = True
                stats["modified"] += len(diff["modified"])
                stats["added"] += len(diff["added"])
                stats["deleted"] += len(diff["deleted"])

        if not has_changes and head_hash:
            return {
                "status": "unchanged",
                "message": "No changes detected since last backup",
                "hash": head_hash,
            }

        timestamp = datetime.now().isoformat()
        commit_data = {
            "parent": head_hash,
            "timestamp": timestamp,
            "message": message,
            "tables": tables_diff,
            "stats": stats,
            "_snapshot": current,
        }

        commit_json = json.dumps(commit_data, default=str, sort_keys=True)
        commit_hash = hashlib.sha256(commit_json.encode("utf-8")).hexdigest()[:_HASH_LEN]

        commit_path = COMMITS_DIR / f"{commit_hash}.json.gz"
        try:
            with gzip.open(commit_path, "wt", encoding="utf-8") as f:
                json.dump(commit_data, f, default=str, sort_keys=True)
        except OSError as e:
            logger.error("backup_engine.snapshot: write failed path=%s err=%s", commit_path, e)
            return {"status": "error", "message": f"Failed to write commit: {e}"}

        try:
            _atomic_write_text(HEAD_FILE, commit_hash)
        except OSError as e:
            logger.error("backup_engine.snapshot: HEAD update failed err=%s", e)
            try:
                commit_path.unlink()
            except OSError:
                pass
            return {"status": "error", "message": f"Failed to update HEAD: {e}"}

        timeline = self._load_timeline()
        timeline.append(
            {
                "hash": commit_hash,
                "parent": head_hash,
                "message": message,
                "timestamp": timestamp,
                "stats": stats,
                "size": commit_path.stat().st_size,
            }
        )
        self._save_timeline(timeline)

        logger.info(
            "backup_engine.snapshot: hash=%s msg=%r stats=%s",
            commit_hash, message, stats,
        )

        return {
            "status": "success",
            "hash": commit_hash,
            "message": message,
            "stats": stats,
            "size": commit_path.stat().st_size,
            "timestamp": timestamp,
        }

    def restore(self, commit_hash: str) -> dict:
        """Restore the database to a specific commit state.

        Writes are wrapped in a single SQLite transaction — either the whole
        restore lands or none of it does. Caller must hold
        ``_db_write_lock`` since this rewrites every tracked table.
        """
        commit = self._load_commit(commit_hash)
        if not commit:
            return {"status": "error", "message": f"Commit {commit_hash} not found"}

        snapshot = commit.get("_snapshot")
        if not snapshot:
            return {"status": "error", "message": "Commit has no restorable snapshot"}

        auto_backup = self.snapshot(f"Auto-backup before restore to {commit_hash}")
        if auto_backup.get("status") == "error":
            logger.warning(
                "backup_engine.restore: pre-restore safety backup failed — proceeding anyway hash=%s",
                commit_hash,
            )

        try:
            conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        except sqlite3.Error as e:
            logger.error("backup_engine.restore: connect failed err=%s", e)
            return {"status": "error", "message": str(e)}

        try:
            conn.execute("PRAGMA busy_timeout=30000;")
            with conn:  # implicit BEGIN / COMMIT / ROLLBACK on exception
                for table, rows in snapshot.items():
                    try:
                        _check_table_name(table)
                    except ValueError as exc:
                        logger.warning(
                            "backup_engine.restore: skipping table — %s", exc,
                        )
                        continue

                    cur = conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                        (table,),
                    )
                    if not cur.fetchone():
                        continue

                    cur = conn.execute(f"PRAGMA table_info({table})")  # nosec B608 - allowlisted
                    columns = [row[1] for row in cur.fetchall()]
                    valid_columns = [c for c in columns if _IDENT_RE.match(c)]
                    if not valid_columns:
                        logger.warning(
                            "backup_engine.restore: no valid columns table=%s", table,
                        )
                        continue

                    conn.execute(f"DELETE FROM {table}")  # nosec B608 - allowlisted

                    insert_cols = ", ".join(valid_columns)
                    placeholders = ", ".join(["?"] * len(valid_columns))
                    sql = f"INSERT OR REPLACE INTO {table} ({insert_cols}) VALUES ({placeholders})"  # nosec B608 - allowlisted

                    for row_id, row_data in rows.items():
                        values = [row_data.get(c) for c in valid_columns]
                        try:
                            conn.execute(sql, values)
                        except sqlite3.Error as e:
                            logger.error(
                                "backup_engine.restore: insert failed table=%s id=%s err=%s — rolling back",
                                table, row_id, e,
                            )
                            raise

        except sqlite3.Error as e:
            logger.error("backup_engine.restore: transaction failed err=%s", e)
            return {"status": "error", "message": str(e)}
        finally:
            conn.close()

        try:
            _atomic_write_text(HEAD_FILE, commit_hash)
        except OSError as e:
            logger.warning(
                "backup_engine.restore: HEAD update failed — data restored but HEAD stale err=%s",
                e,
            )

        logger.info("backup_engine.restore: hash=%s ok", commit_hash)
        return {
            "status": "success",
            "message": f"Restored to commit {commit_hash}. Restart recommended.",
            "hash": commit_hash,
        }

    # ── History / Inspection ────────────────────────────────────────

    def get_history(self, limit: int = 50) -> list[dict]:
        """Get commit history (newest first).

        Combines incremental commits and legacy full-copy backups, sorts
        by timestamp, truncates to ``limit``. Caller wanting *all* entries
        can pass ``limit=0``.
        """
        timeline = self._load_timeline()
        legacy = self._get_legacy_backups()
        combined = timeline + legacy
        combined.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return combined if limit == 0 else combined[:limit]

    def get_diff(self, commit_hash: str) -> dict:
        """Get the detailed changeset for a specific commit."""
        commit = self._load_commit(commit_hash)
        if not commit:
            return {"error": "Commit not found"}
        return {
            "hash": commit_hash,
            "parent": commit.get("parent"),
            "timestamp": commit.get("timestamp"),
            "message": commit.get("message"),
            "stats": commit.get("stats"),
            "tables": {
                table: {
                    "modified": len(diff.get("modified", [])),
                    "added": len(diff.get("added", [])),
                    "deleted": len(diff.get("deleted", [])),
                    "details": diff,
                }
                for table, diff in commit.get("tables", {}).items()
            },
        }

    def prune(self, retention_days: int) -> dict:
        """Delete commits + legacy backups older than ``retention_days``.

        Returns ``{deleted_commits, deleted_legacy, freed_bytes}``. The
        latest commit on HEAD is never deleted, even if it's outside the
        window — otherwise restore would have no base to compare against.
        """
        if retention_days < 1:
            return {"deleted_commits": 0, "deleted_legacy": 0, "freed_bytes": 0}

        cutoff = datetime.now().timestamp() - retention_days * 86400
        head = self._get_head()

        deleted_commits = 0
        deleted_legacy = 0
        freed_bytes = 0

        # Commits: keep HEAD always, drop the rest if mtime < cutoff
        timeline = self._load_timeline()
        kept_timeline: list[dict] = []
        for entry in timeline:
            entry_hash = entry.get("hash", "")
            commit_file = COMMITS_DIR / f"{entry_hash}.json.gz"
            if not commit_file.exists():
                continue
            try:
                mtime = commit_file.stat().st_mtime
                size = commit_file.stat().st_size
            except OSError:
                continue
            if entry_hash != head and mtime < cutoff:
                try:
                    commit_file.unlink()
                    deleted_commits += 1
                    freed_bytes += size
                except OSError as e:
                    logger.warning(
                        "backup_engine.prune: failed to remove commit=%s err=%s",
                        entry_hash, e,
                    )
                    kept_timeline.append(entry)
            else:
                kept_timeline.append(entry)
        if len(kept_timeline) != len(timeline):
            self._save_timeline(kept_timeline)

        # Legacy: drop *.db files in BACKUP_DIR with old mtime, never the most
        # recent of each type (so the user always has a fallback).
        legacy_paths = sorted(
            BACKUP_DIR.glob("master_*.db"), key=lambda p: p.stat().st_mtime, reverse=True
        )
        keep_per_type: dict[str, bool] = {}
        for path in legacy_paths:
            kind = "session" if "session" in path.name else (
                "archive" if "ARCHIVE" in path.name else (
                    "prerestore" if "prerestore" in path.name else "other"
                )
            )
            try:
                mtime = path.stat().st_mtime
                size = path.stat().st_size
            except OSError:
                continue
            # Always keep at least the newest of each kind
            if not keep_per_type.get(kind):
                keep_per_type[kind] = True
                continue
            if mtime < cutoff:
                try:
                    path.unlink()
                    deleted_legacy += 1
                    freed_bytes += size
                except OSError as e:
                    logger.warning(
                        "backup_engine.prune: failed to remove legacy=%s err=%s",
                        path.name, e,
                    )

        logger.info(
            "backup_engine.prune: retention_days=%d deleted_commits=%d deleted_legacy=%d freed=%dB",
            retention_days, deleted_commits, deleted_legacy, freed_bytes,
        )
        return {
            "deleted_commits": deleted_commits,
            "deleted_legacy": deleted_legacy,
            "freed_bytes": freed_bytes,
        }

    # ── Internal helpers ────────────────────────────────────────────

    def _get_head(self) -> str | None:
        try:
            if HEAD_FILE.exists():
                return HEAD_FILE.read_text(encoding="utf-8").strip()
        except OSError as e:
            logger.warning("backup_engine._get_head: read failed err=%s", e)
        return None

    def _load_commit(self, commit_hash: str) -> dict | None:
        """Load a commit blob. Logs a warning on hash mismatch but still
        returns the data — silent corruption stays silent, but visible in
        the logs."""
        path = COMMITS_DIR / f"{commit_hash}.json.gz"
        if not path.exists():
            return None
        try:
            with gzip.open(path, "rt", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, gzip.BadGzipFile, json.JSONDecodeError) as e:
            logger.error("backup_engine._load_commit: hash=%s err=%s", commit_hash, e)
            return None

        # Best-effort integrity check: re-hash the canonical form and compare.
        # Older commits written with the same sort_keys+default=str contract
        # will still match. Anything else logs a warning.
        try:
            canonical = json.dumps(data, default=str, sort_keys=True)
            recomputed = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:_HASH_LEN]
            if recomputed != commit_hash:
                logger.warning(
                    "backup_engine._load_commit: hash mismatch want=%s got=%s",
                    commit_hash, recomputed,
                )
        except (TypeError, ValueError) as e:
            logger.warning(
                "backup_engine._load_commit: re-hash failed hash=%s err=%s",
                commit_hash, e,
            )
        return data

    def _load_timeline(self) -> list[dict]:
        try:
            if TIMELINE_FILE.exists():
                return json.loads(TIMELINE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("backup_engine._load_timeline: read failed err=%s", e)
        return []

    def _save_timeline(self, timeline: list[dict]) -> None:
        try:
            _atomic_write_text(
                TIMELINE_FILE,
                json.dumps(timeline, default=str, indent=2),
            )
        except OSError as e:
            logger.error("backup_engine._save_timeline: write failed err=%s", e)

    def _get_legacy_backups(self) -> list[dict]:
        legacy: list[dict] = []
        for f in BACKUP_DIR.glob("master_*.db"):
            try:
                stat = f.stat()
            except OSError as e:
                logger.warning(
                    "backup_engine._get_legacy_backups: stat failed file=%s err=%s",
                    f, e,
                )
                continue
            b_type = "legacy_session"
            if "ARCHIVE" in f.name:
                b_type = "legacy_archive"
            elif "prerestore" in f.name:
                b_type = "legacy_prerestore"
            legacy.append(
                {
                    "hash": f"legacy_{f.stem}",
                    "parent": None,
                    "message": f"Legacy backup: {f.name}",
                    "timestamp": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "stats": {"type": b_type, "size": stat.st_size},
                    "size": stat.st_size,
                    "is_legacy": True,
                    "filename": f.name,
                }
            )
        return legacy
