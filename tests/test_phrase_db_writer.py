"""
Unit tests for app/phrase_db_writer.py (djmdCue memory-cue writer).

The DB is faked so the tests are hermetic — no real master.db, no SQLCipher key.
The fake mirrors the REAL pyrekordbox 0.1.7 `Rekordbox6Database` surface and
raises AttributeError on anything else: an earlier version of this suite was
green against `db.add()` / `db.generate_unused_id()`, neither of which exists in
the pinned release, so four passing tests certified a module that could not run.
`DjmdCue` is the real class (it rejects unknown column names), and one test
inserts the writer's exact kwargs into a real SQLite table built from
`DjmdCue.__table__` — that is what catches the NOT NULL audit columns.

pyrekordbox is excluded from the CI install (.github/workflows/ci.yml), so the
tests that need it go through `_patch()`, which importorskips. The backup /
restore tests touch no pyrekordbox symbol and keep running on the Linux runner.
"""

from __future__ import annotations

import ast
import contextlib
import logging
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app import phrase_db_writer as W

_SKIP_REASON = "pyrekordbox not installed on this platform"


class _FakeSession:
    def __init__(self, db: _FakeDB) -> None:
        self._db = db

    def add(self, row: Any) -> None:
        self._db.added.append(row)

    def delete(self, row: Any) -> None:
        self._db.deleted.append(row)


class _FakeQuery:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[Any, ...]]:
        return list(self._rows)


class _FakeDB:
    """Stand-in for Rekordbox6Database — pinned 0.1.7 surface only.

    `__getattr__` turns any other attribute into AttributeError, so a module
    calling a method the pinned class lacks fails here instead of passing.
    """

    def __init__(self, existing: list[Any] | None = None, cue_ids: tuple[str, ...] = ()) -> None:
        self._existing = list(existing or [])
        self._cue_ids = list(cue_ids)
        self.added: list[Any] = []
        self.deleted: list[Any] = []
        self.committed = False
        self.closed = False
        self.session = _FakeSession(self)

    def get_content(self, ID=None):
        return SimpleNamespace(UUID="content-uuid")

    def get_cue(self, **kwargs: Any) -> list[Any]:
        rows = list(self._existing)
        for key, value in kwargs.items():
            rows = [r for r in rows if str(getattr(r, key, None)) == str(value)]
        return rows

    def query(self, *entities: Any, **kwargs: Any) -> _FakeQuery:
        return _FakeQuery([(i,) for i in self._cue_ids])

    @property
    def no_autoflush(self):
        return contextlib.nullcontext()

    def delete(self, row: Any) -> None:
        self.deleted.append(row)

    def commit(self, autoinc: bool = True) -> None:
        self.committed = True

    def close(self) -> None:
        self.closed = True

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(f"Rekordbox6Database (pyrekordbox 0.1.7) has no attribute {name!r}")


def _patch(monkeypatch, fake: _FakeDB) -> dict[str, Any]:
    """Swap the DB constructor. Returns the recorded constructor kwargs."""
    pytest.importorskip("pyrekordbox", reason=_SKIP_REASON)
    seen: dict[str, Any] = {}

    def _factory(*args: Any, **kwargs: Any) -> _FakeDB:
        seen.update(kwargs)
        seen["_args"] = args
        return fake

    monkeypatch.setattr("pyrekordbox.Rekordbox6Database", _factory)
    return seen


def _module_tree() -> ast.Module:
    return ast.parse(Path(W.__file__).read_text(encoding="utf-8"))


def _inside_with(tree: ast.Module, target_line: int, func_name: str) -> bool:
    """True if `target_line` sits inside a `with <func_name>():` block."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.With):
            continue
        takes = any(
            isinstance(item.context_expr, ast.Call)
            and getattr(item.context_expr.func, "id", None) == func_name
            for item in node.items
        )
        if takes and node.lineno <= target_line <= getattr(node, "end_lineno", node.lineno):
            return True
    return False


# ── write path ────────────────────────────────────────────────────────────


def test_write_creates_kind0_memory_cues(monkeypatch):
    fake = _FakeDB()
    seen = _patch(monkeypatch, fake)
    mcues = [{"time_ms": 1000, "name": "P1"}, {"time_ms": 17000, "name": "P2"}]
    res = W.write_phrase_memory_cues(42, mcues, "x", backup=False, db_file="copy")

    assert (res["written"], res["removed"]) == (2, 0)
    assert fake.committed and fake.closed
    assert len(fake.added) == 2
    a0 = fake.added[0]
    assert a0.Kind == 0 and a0.ContentID == "42"
    assert a0.InMsec == 1000 and a0.InFrame == int(1000 * 0.15)  # 150
    assert a0.OutMsec == -1 and a0.OutFrame == 0
    assert a0.Comment == "P1" and a0.ContentUUID == "content-uuid"
    # NOT NULL with no default — DjmdCue.create does not fill them.
    assert isinstance(a0.created_at, datetime) and isinstance(a0.updated_at, datetime)
    assert seen["path"] == "copy"


def test_copy_is_opened_without_sqlcipher_unlock(monkeypatch):
    """A decrypted copy must not go through pyrekordbox's unlock branch."""
    fake = _FakeDB()
    seen = _patch(monkeypatch, fake)
    W.write_phrase_memory_cues(42, [], "x", backup=False, db_file="copy")
    assert seen["unlock"] is False


def test_live_path_opens_the_caller_db_path(monkeypatch):
    """Not pyrekordbox's auto-detected DB — the backup must match the target."""
    fake = _FakeDB()
    seen = _patch(monkeypatch, fake)
    W.write_phrase_memory_cues(42, [], "C:/rb/master.db", backup=False)
    assert seen["path"] == "C:/rb/master.db"
    assert "unlock" not in seen


def test_generated_ids_are_unique_strings_not_in_use(monkeypatch):
    fake = _FakeDB(cue_ids=("1", "2", "3"))
    _patch(monkeypatch, fake)
    mcues = [{"time_ms": i * 1000, "name": f"P{i}"} for i in range(1, 9)]
    W.write_phrase_memory_cues(42, mcues, "x", backup=False, db_file="c")

    ids = [row.ID for row in fake.added]
    assert all(isinstance(i, str) for i in ids)
    assert len(set(ids)) == len(ids)
    assert not set(ids) & {"1", "2", "3"}


def test_generated_ids_are_deduped_against_each_other(monkeypatch):
    """A newer pyrekordbox's `generate_unused_id` only knows what is in the DB.

    It cannot see the IDs this same call already handed out, so two rows would
    race for one VARCHAR primary key.
    """
    fake = _FakeDB()
    # Instance attribute, not a method on _FakeDB: the pinned 0.1.7 has no
    # generate_unused_id, and the fake's class surface must keep matching it.
    handed_out = iter(["7", "7", "8"])
    fake.generate_unused_id = lambda table: next(handed_out)
    _patch(monkeypatch, fake)
    mcues = [{"time_ms": 0, "name": "P1"}, {"time_ms": 1000, "name": "P2"}]

    W.write_phrase_memory_cues(42, mcues, "x", backup=False, db_file="c")
    assert [row.ID for row in fake.added] == ["7", "8"]


def test_prefetched_used_ids_skip_the_per_call_id_query():
    """Batch callers pay the `SELECT ID` once; the shared set keeps IDs disjoint."""

    class _NoQueryDB(_FakeDB):
        def query(self, *entities: Any, **kwargs: Any) -> _FakeQuery:
            raise AssertionError("queried the cue table although `used` was supplied")

    db = _NoQueryDB()
    table = SimpleNamespace(ID="ID")
    used = {"1", "2"}

    first = W._new_cue_ids(db, table, 2, used)
    second = W._new_cue_ids(db, table, 2, used)
    assert len(first) == 2 and len(second) == 2
    assert not (set(first) | set(second)) & {"1", "2"}
    assert not set(first) & set(second)
    assert used >= set(first) | set(second)  # mutated, so the next call sees them


def test_write_idempotent_removes_only_prior_phrase_cues(monkeypatch):
    prior = [
        SimpleNamespace(ContentID="42", Kind=0, Comment="P1"),  # phrase -> remove
        SimpleNamespace(ContentID="42", Kind=0, Comment="P2"),  # phrase -> remove
        SimpleNamespace(ContentID="42", Kind=0, Comment="Drop"),  # manual memory -> keep
        SimpleNamespace(ContentID="42", Kind=1, Comment="P3"),  # hot cue -> keep
        SimpleNamespace(ContentID="99", Kind=0, Comment="P1"),  # other track -> keep
    ]
    fake = _FakeDB(existing=prior)
    _patch(monkeypatch, fake)
    res = W.write_phrase_memory_cues(
        42, [{"time_ms": 0, "name": "P1"}], "x", backup=False, db_file="c"
    )

    assert res["removed"] == 2
    assert {id(x) for x in fake.deleted} == {id(prior[0]), id(prior[1])}
    assert res["written"] == 1


@pytest.mark.parametrize("message", ["database is locked", "attempt to write a readonly database"])
def test_locked_db_raises_rekordbox_locked(monkeypatch, message):
    fake = _FakeDB()

    def _boom(autoinc=True):
        raise Exception(message)

    fake.commit = _boom
    _patch(monkeypatch, fake)
    with pytest.raises(W.RekordboxLockedError):
        W.write_phrase_memory_cues(
            42, [{"time_ms": 0, "name": "P1"}], "x", backup=False, db_file="c"
        )
    assert fake.closed  # the finally ran on the error path


def test_non_lock_exception_propagates_unchanged(monkeypatch):
    """The broad `except Exception` must not widen into RekordboxLockedError."""
    fake = _FakeDB()

    def _boom(autoinc=True):
        raise ValueError("boom")

    fake.commit = _boom
    _patch(monkeypatch, fake)
    with pytest.raises(ValueError, match="boom"):
        W.write_phrase_memory_cues(
            42, [{"time_ms": 0, "name": "P1"}], "x", backup=False, db_file="c"
        )
    assert fake.closed


def test_missing_content_raises_before_deleting(monkeypatch):
    prior = [SimpleNamespace(ContentID="42", Kind=0, Comment="P1")]
    fake = _FakeDB(existing=prior)
    fake.get_content = lambda ID=None: None
    _patch(monkeypatch, fake)
    with pytest.raises(ValueError, match="not found"):
        W.write_phrase_memory_cues(
            42, [{"time_ms": 0, "name": "P1"}], "x", backup=False, db_file="c"
        )
    assert fake.deleted == [] and fake.added == [] and not fake.committed


def test_content_without_uuid_raises(monkeypatch):
    fake = _FakeDB()
    fake.get_content = lambda ID=None: SimpleNamespace(UUID=None)
    _patch(monkeypatch, fake)
    with pytest.raises(ValueError, match="orphan"):
        W.write_phrase_memory_cues(
            42, [{"time_ms": 0, "name": "P1"}], "x", backup=False, db_file="c"
        )
    assert fake.added == [] and not fake.committed


def test_no_backup_is_written_for_a_rejected_content_id(monkeypatch, tmp_path):
    db = tmp_path / "master.db"
    db.write_bytes(b"DBDATA")
    fake = _FakeDB()
    fake.get_content = lambda ID=None: None
    _patch(monkeypatch, fake)
    with pytest.raises(ValueError):
        W.write_phrase_memory_cues(42, [{"time_ms": 0, "name": "P1"}], str(db), db_file="c")
    assert list(tmp_path.glob("*.phrasebak-*")) == []


def test_backup_snapshots_the_copy_that_is_written_not_the_live_db(monkeypatch, tmp_path):
    """`db_file` is the file that gets mutated — snapshotting master.db protects nothing."""
    live = tmp_path / "master.db"
    live.write_bytes(b"LIVE")
    copy = tmp_path / "decrypted.db"
    copy.write_bytes(b"COPY")
    (tmp_path / "decrypted.db-wal").write_bytes(b"COPY-WAL")
    fake = _FakeDB()
    _patch(monkeypatch, fake)

    res = W.write_phrase_memory_cues(
        42, [{"time_ms": 0, "name": "P1"}], str(live), db_file=str(copy)
    )

    assert res["written"] == 1 and fake.committed
    assert list(tmp_path.glob("master.db*.phrasebak-*")) == []
    assert sorted(Path(b).name for b in res["backups"]) == sorted(
        p.name for p in tmp_path.glob("decrypted.db*.phrasebak-*")
    )
    assert len(res["backups"]) == 2  # the copy + its -wal


def test_rollback_hint_points_at_the_written_file(monkeypatch, tmp_path, caplog):
    """Following the logged hint must not restore (and wipe the -wal of) the live DB."""
    live = tmp_path / "master.db"
    live.write_bytes(b"LIVE")
    copy = tmp_path / "decrypted.db"
    copy.write_bytes(b"COPY")
    fake = _FakeDB()

    def _boom(autoinc=True):
        raise ValueError("boom")

    fake.commit = _boom
    _patch(monkeypatch, fake)

    with caplog.at_level(logging.ERROR), pytest.raises(ValueError, match="boom"):
        W.write_phrase_memory_cues(42, [{"time_ms": 0, "name": "P1"}], str(live), db_file=str(copy))

    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors, "a failure after the snapshot must log the rollback hint"
    assert "restore_master_db" in errors[0].msg
    # %r-formatted, so assert on the arg itself — not on the escaped message.
    assert errors[0].args[0] == str(copy)


# ── dependency-surface regression guards ──────────────────────────────────


def test_fake_db_only_exposes_real_pyrekordbox_methods():
    """Pins the fake to the pinned dependency, so it cannot invent an API."""
    pytest.importorskip("pyrekordbox", reason=_SKIP_REASON)
    from pyrekordbox import Rekordbox6Database

    real = set(dir(Rekordbox6Database)) | {"session"}  # session is set in __init__
    faked = {name for name in vars(_FakeDB) if not name.startswith("_")}
    assert not faked - real, f"fake invents methods pyrekordbox does not have: {faked - real}"


def test_module_only_uses_attributes_the_pinned_class_has():
    """`db.<attr>` in the module must exist on Rekordbox6Database 0.1.7.

    Optional newer-version methods are reached through `getattr(db, ...)`
    probes, which are Calls, not Attributes, so they are exempt by construction.
    """
    pytest.importorskip("pyrekordbox", reason=_SKIP_REASON)
    from pyrekordbox import Rekordbox6Database

    real = set(dir(Rekordbox6Database)) | {"session"}
    used = {
        node.attr
        for node in ast.walk(_module_tree())
        if isinstance(node, ast.Attribute) and getattr(node.value, "id", None) == "db"
    }
    assert used, "no db.<attr> access found — did the parameter get renamed?"
    assert not used - real, f"module calls attributes 0.1.7 does not have: {used - real}"


def test_cue_row_satisfies_real_schema():
    """The writer's exact kwargs must survive a real INSERT (NOT NULL columns)."""
    pytest.importorskip("pyrekordbox", reason=_SKIP_REASON)
    from pyrekordbox.db6.tables import DjmdCue
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    engine = create_engine("sqlite://")
    DjmdCue.__table__.create(engine)
    kwargs = W._cue_row_kwargs(
        "1001", "42", "content-uuid", {"time_ms": 1000, "name": "P1"}, datetime.now()
    )
    with Session(engine) as session:
        session.add(DjmdCue.create(**kwargs))
        session.commit()
        row = session.query(DjmdCue).one()

    assert row.Kind == 0 and row.InFrame == 150 and row.OutMsec == -1
    assert row.created_at is not None and row.updated_at is not None


# ── backup ────────────────────────────────────────────────────────────────


def test_backup_master_db(tmp_path):
    db = tmp_path / "master.db"
    db.write_bytes(b"DBDATA")
    (tmp_path / "master.db-wal").write_bytes(b"WAL")
    backups = W.backup_master_db(str(db))
    # db + wal copied (no -shm present)
    assert len(backups) == 2
    assert any(".db.phrasebak-" in b for b in backups)
    assert all(Path(b).exists() for b in backups)
    assert (tmp_path / "master.db").read_bytes() == b"DBDATA"  # original untouched


def test_backup_skips_shm(tmp_path):
    """-shm is a rebuildable wal-index; a stale copy has no value."""
    db = tmp_path / "master.db"
    db.write_bytes(b"DBDATA")
    (tmp_path / "master.db-wal").write_bytes(b"WAL")
    (tmp_path / "master.db-shm").write_bytes(b"SHM")
    backups = W.backup_master_db(str(db))
    assert len(backups) == 2
    assert not any("-shm" in b for b in backups)


def test_backup_stamps_do_not_collide(tmp_path):
    """Two snapshots inside one second must not overwrite each other."""
    db = tmp_path / "master.db"
    db.write_bytes(b"DBDATA")
    first = W.backup_master_db(str(db))
    second = W.backup_master_db(str(db))
    assert set(first) != set(second)
    assert len(list(tmp_path.glob("master.db.phrasebak-*"))) == 2


def test_backup_keeps_both_sets_when_the_clock_does_not_tick(
    tmp_path, monkeypatch, _rekordbox_closed
):
    """`datetime.now()` steps ~16 ms on Windows/py3.11 — two snapshots fit in one tick.

    Measured: 45 of 200 consecutive snapshot pairs shared a stamp, i.e. the
    second copy overwrote the first generation.
    """

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 21, 1, 2, 3, 400000)

    monkeypatch.setattr(W, "datetime", _FrozenDatetime)
    db = tmp_path / "master.db"
    db.write_bytes(b"DB-v1")
    first = W.backup_master_db(str(db))
    db.write_bytes(b"DB-v2")
    second = W.backup_master_db(str(db))

    assert set(first) != set(second)
    assert [Path(b).read_bytes() for b in first] == [b"DB-v1"]  # not overwritten
    assert [Path(b).read_bytes() for b in second] == [b"DB-v2"]

    db.write_bytes(b"DB-broken")
    assert W.restore_master_db(str(db)) == 1
    assert db.read_bytes() == b"DB-v2"  # the newer set still sorts last


# ── restore ───────────────────────────────────────────────────────────────


@pytest.fixture
def _rekordbox_closed(monkeypatch):
    monkeypatch.setattr(W, "_rekordbox_running", lambda: False)


def _snapshot(tmp_path: Path, db_bytes: bytes, wal_bytes: bytes | None) -> list[str]:
    db = tmp_path / "master.db"
    wal = tmp_path / "master.db-wal"
    db.write_bytes(db_bytes)
    if wal_bytes is None:
        wal.unlink(missing_ok=True)
    else:
        wal.write_bytes(wal_bytes)
    return W.backup_master_db(str(db))


def test_restore_restores_the_newest_set(tmp_path, _rekordbox_closed):
    _snapshot(tmp_path, b"DB-v1", b"WAL-v1")
    time.sleep(0.01)
    _snapshot(tmp_path, b"DB-v2", b"WAL-v2")
    (tmp_path / "master.db").write_bytes(b"DB-broken")

    assert W.restore_master_db(str(tmp_path / "master.db")) == 2
    assert (tmp_path / "master.db").read_bytes() == b"DB-v2"
    assert (tmp_path / "master.db-wal").read_bytes() == b"WAL-v2"


def test_restore_never_mixes_generations(tmp_path, _rekordbox_closed):
    """A db from T2 beside a -wal from T1 = silent page-level corruption."""
    _snapshot(tmp_path, b"DB-v1", b"WAL-v1")
    time.sleep(0.01)
    _snapshot(tmp_path, b"DB-v2", None)  # checkpointed: no wal in this set
    (tmp_path / "master.db-wal").write_bytes(b"WAL-v3")

    assert W.restore_master_db(str(tmp_path / "master.db")) == 1
    assert (tmp_path / "master.db").read_bytes() == b"DB-v2"
    assert not (tmp_path / "master.db-wal").exists()


def test_restore_removes_orphan_sidecars(tmp_path, _rekordbox_closed):
    _snapshot(tmp_path, b"DB-v1", None)
    (tmp_path / "master.db-wal").write_bytes(b"WAL-after-backup")
    (tmp_path / "master.db-shm").write_bytes(b"SHM-after-backup")

    W.restore_master_db(str(tmp_path / "master.db"))
    assert not (tmp_path / "master.db-wal").exists()
    assert not (tmp_path / "master.db-shm").exists()


def test_restore_accepts_an_explicit_set(tmp_path, _rekordbox_closed):
    first = _snapshot(tmp_path, b"DB-v1", b"WAL-v1")
    time.sleep(0.01)
    _snapshot(tmp_path, b"DB-v2", b"WAL-v2")

    assert W.restore_master_db(str(tmp_path / "master.db"), backups=first) == 2
    assert (tmp_path / "master.db").read_bytes() == b"DB-v1"
    assert (tmp_path / "master.db-wal").read_bytes() == b"WAL-v1"


def test_restore_rejects_a_path_without_the_backup_marker(tmp_path, _rekordbox_closed):
    """Declared in the docstring's Raises block — an unmarked path is not a snapshot."""
    stray = tmp_path / "random.db"
    stray.write_bytes(b"NOT-A-BACKUP")
    (tmp_path / "master.db").write_bytes(b"LIVE")

    with pytest.raises(ValueError, match="not a phrase backup file"):
        W.restore_master_db(str(tmp_path / "master.db"), backups=[str(stray)])
    assert (tmp_path / "master.db").read_bytes() == b"LIVE"


def test_restore_refuses_a_set_without_the_main_db(tmp_path, _rekordbox_closed):
    (tmp_path / "master.db").write_bytes(b"LIVE")
    (tmp_path / "master.db-wal.phrasebak-20260101-010101-000001").write_bytes(b"WAL-only")

    with pytest.raises(RuntimeError, match="incomplete backup set"):
        W.restore_master_db(str(tmp_path / "master.db"))
    assert (tmp_path / "master.db").read_bytes() == b"LIVE"


def test_restore_returns_zero_when_no_backups(tmp_path, _rekordbox_closed):
    db = tmp_path / "master.db"
    db.write_bytes(b"LIVE")
    (tmp_path / "master.db-wal").write_bytes(b"WAL")

    assert W.restore_master_db(str(db)) == 0
    assert db.read_bytes() == b"LIVE"
    assert (tmp_path / "master.db-wal").exists()  # untouched, nothing was rolled back


def test_restore_refuses_while_rekordbox_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(W, "_rekordbox_running", lambda: True)
    _snapshot(tmp_path, b"DB-v1", None)
    (tmp_path / "master.db").write_bytes(b"LIVE")

    with pytest.raises(RuntimeError, match="Rekordbox is running"):
        W.restore_master_db(str(tmp_path / "master.db"))
    assert (tmp_path / "master.db").read_bytes() == b"LIVE"


# ── structural invariants ─────────────────────────────────────────────────


class TestMasterDbWriteLock:
    """Snapshot and restore are master.db writers — they hold the global lock."""

    def test_db_lock_is_the_global_write_lock(self):
        import app.database as db_mod

        assert W.db_lock is db_mod.db_lock
        with W.db_lock():
            assert db_mod._db_write_lock._is_owned()

    def test_snapshot_is_taken_under_the_lock(self):
        """Outside it, another writer can commit between copy and write."""
        tree = _module_tree()
        sites = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "backup_master_db"
        ]
        assert sites, "no backup_master_db call site — did it get renamed?"
        unguarded = [ln for ln in sites if not _inside_with(tree, ln, "db_lock")]
        assert not unguarded, f"backup_master_db called outside db_lock at line(s) {unguarded}"

    def test_restore_mutations_are_under_the_lock(self):
        tree = _module_tree()
        restore = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "restore_master_db"
        )
        sites = [
            n.lineno
            for n in ast.walk(restore)
            if isinstance(n, ast.Call) and getattr(n.func, "attr", None) in ("copy2", "unlink")
        ]
        assert sites, "restore no longer copies/unlinks — update this test"
        unguarded = [ln for ln in sites if not _inside_with(tree, ln, "db_lock")]
        assert not unguarded, f"restore mutates master.db outside db_lock at line(s) {unguarded}"


def test_pyrekordbox_is_imported_quietly():
    """A bare import drops the root logger to NOTSET — see pyrekordbox_compat."""
    tree = _module_tree()
    imports = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.level == 0
        and (node.module or "").split(".")[0] == "pyrekordbox"
    ]
    assert imports, "no pyrekordbox import found — update this test"
    unguarded = [ln for ln in imports if not _inside_with(tree, ln, "quiet_import")]
    assert not unguarded, f"pyrekordbox imported outside quiet_import at line(s) {unguarded}"
