"""Concurrency / `_db_write_lock` coverage tests.

Two jobs:

1. **Drift guard** (`test_no_unprotected_master_db_writer`) — the CI gate. It
   enumerates every `master.db` writer by the rbox write-calls it makes (AST
   write-sink detection), NOT by method-name prefix, so a future off-prefix
   mutator (`commit`/`flush`/`import_*`) or a new rbox-direct writer fails CI
   the instant it touches a write sink. Each flagged writer must be either
   `@serialise_mutators`-wrapped (`__wrapped__`) or listed in
   `KNOWN_CALLSITE_PROTECTED` (and that callsite must actually acquire the lock).

2. **Serialisation harness** (`test_*_serialise*`, `@pytest.mark.slow`) — proves
   `@serialise_mutators` actually serialises concurrent callers, with a no-op-lock
   negative control proving the lock is load-bearing.

The drift guard + decorator-coverage tests run without `rbox` (they inspect
source + class objects). Only actual `master.db` writes need `rbox`; the
serialisation harness deliberately uses the lock primitive directly so it is
deterministic and rbox-independent.
"""

import ast
import importlib
import threading
import time
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Drift guard — prefix-INDEPENDENT AST write-sink detection
# ---------------------------------------------------------------------------

_APP = Path(__file__).resolve().parent.parent / "app"

# Modules that reach `master.db` writes. Grep-seeded + asserted below. A future
# NEW module doing rbox-direct writes must be added here — the documented manual
# surface (same class as KNOWN_CALLSITE_PROTECTED). The guard does the rest.
SCANNED_MODULES = {
    "database.py": "app.database",
    "live_database.py": "app.live_database",
    "analysis_db_writer.py": "app.analysis_db_writer",
}

# rbox MasterDb methods that mutate the DB (the write sinks we call today).
RBOX_WRITE_METHODS = frozenset(
    {
        "create_content",
        "update_content",
        "update_content_artist",
        "update_content_genre",
        "update_content_album",
        "update_content_key",
        "rename_playlist",
        "delete_playlist",
        "create_playlist",
        "create_playlist_song",
        "delete_playlist_song",
        "add_track_to_playlist",
        "remove_track_from_playlist",
    }
)
# Catch future rbox write methods we don't yet name explicitly.
_WRITE_VERB_PREFIXES = (
    "create_",
    "update_",
    "delete_",
    "insert_",
    "add_",
    "remove_",
    "rename_",
    "move_",
    "reorder_",
    "set_",
    "save",
)
# Module-level rbox factory writers, e.g. `rbox.OneLibrary.create(...)`.
_RBOX_FACTORY_METHODS = frozenset({"create", "create_content"})

# Writers that bypass both facades (rbox-direct) and acquire the lock at the
# callsite instead of via @serialise_mutators. Explicit + small + reviewed.
KNOWN_CALLSITE_PROTECTED = frozenset({"AnalysisDBWriter._update_db"})


def _attr_chain_root(node: ast.AST) -> str | None:
    """Leftmost `Name.id` of an attribute chain (`a.b.c` -> 'a'), else None."""
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _is_write_sink(call: ast.Call) -> bool:
    func = call.func
    if not isinstance(func, ast.Attribute):
        return False
    attr = func.attr
    # Rule 2: dynamic dispatch helper `self._try_call([...])` (mytag writers).
    if attr == "_try_call":
        return True
    value = func.value
    # Rule 1: `<recv>.db.<rbox-write>(...)`  (e.g. self.live_db.db.update_content).
    if isinstance(value, ast.Attribute) and value.attr == "db":
        if attr.startswith(("get_", "list_", "all_")):
            return False
        if attr in RBOX_WRITE_METHODS or attr.startswith(_WRITE_VERB_PREFIXES):
            return True
    # Rule 3: module-level `rbox.<Class>.<create...>(...)`.
    return attr in _RBOX_FACTORY_METHODS and _attr_chain_root(func) == "rbox"


def _acquires_lock(funcdef: ast.AST) -> bool:
    """True if a function body uses `with db_lock()` or `with _db_write_lock`."""
    for node in ast.walk(funcdef):
        if isinstance(node, ast.With):
            for item in node.items:
                ctx = item.context_expr
                if (
                    isinstance(ctx, ast.Call)
                    and isinstance(ctx.func, ast.Name)
                    and ctx.func.id == "db_lock"
                ):
                    return True
                if isinstance(ctx, ast.Name) and ctx.id == "_db_write_lock":
                    return True
    return False


def _find_writers() -> list[tuple[str, str, ast.AST]]:
    """Return (class_name, method_name, funcdef) for every method that contains
    a write sink, across SCANNED_MODULES."""
    writers: list[tuple[str, str, ast.AST]] = []
    for filename in SCANNED_MODULES:
        tree = ast.parse((_APP / filename).read_text())
        for cls in (n for n in tree.body if isinstance(n, ast.ClassDef)):
            for fn in cls.body:
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if any(isinstance(c, ast.Call) and _is_write_sink(c) for c in ast.walk(fn)):
                    writers.append((cls.name, fn.name, fn))
    return writers


def test_scanned_modules_exist():
    for filename in SCANNED_MODULES:
        assert (_APP / filename).exists(), f"{filename} missing — update SCANNED_MODULES"


def test_drift_guard_finds_the_known_writers():
    """Sanity: the AST guard must surface the writers we know exist, else it is
    silently detecting nothing (a false-green of its own)."""
    found = {f"{c}.{m}" for c, m, _ in _find_writers()}
    for expected in (
        "LiveRekordboxDB.add_track",
        "LiveRekordboxDB.create_mytag",
        "RekordboxDB.ensure_standalone_master_db",
        "AnalysisDBWriter._update_db",
    ):
        assert expected in found, f"drift guard failed to detect writer {expected}"


def test_no_unprotected_master_db_writer():
    """THE CI GATE. Every detected master.db writer is either wrapped by
    @serialise_mutators (`__wrapped__`) or in KNOWN_CALLSITE_PROTECTED (and that
    callsite actually acquires the lock). 0 flagged-but-unprotected writers."""
    unprotected: list[str] = []
    for cls_name, method_name, funcdef in _find_writers():
        key = f"{cls_name}.{method_name}"
        if key in KNOWN_CALLSITE_PROTECTED:
            assert _acquires_lock(funcdef), (
                f"{key} is in KNOWN_CALLSITE_PROTECTED but its body does not "
                "acquire db_lock()/_db_write_lock — the manifest entry is a lie."
            )
            continue
        module = importlib.import_module(SCANNED_MODULES[_module_file_of(cls_name)])
        method = getattr(getattr(module, cls_name), method_name)
        if getattr(method, "__wrapped__", None) is None:
            unprotected.append(key)
    assert not unprotected, (
        "unprotected master.db writer(s) — wrap with @serialise_mutators "
        f"or add to KNOWN_CALLSITE_PROTECTED (with a callsite lock): {unprotected}"
    )


def _module_file_of(cls_name: str) -> str:
    """Map a class name to its SCANNED_MODULES key by parsing each module."""
    for filename in SCANNED_MODULES:
        tree = ast.parse((_APP / filename).read_text())
        if any(isinstance(n, ast.ClassDef) and n.name == cls_name for n in tree.body):
            return filename
    raise AssertionError(f"class {cls_name} not found in scanned modules")


# ---------------------------------------------------------------------------
# Decorator coverage (rbox-independent — inspects class objects)
# ---------------------------------------------------------------------------

# No `importorskip("rbox")` — app.database/live_database/analysis_db_writer all
# soft-import rbox (every rbox call sits in a method body), so class objects +
# AST + the lock primitive are all inspectable without rbox installed.


def test_decorator_wraps_all_rekordboxdb_mutators():
    from app.database import RekordboxDB

    mutators = [
        "set_mode",
        "load_library",
        "unload_library",
        "create_new_library",
        "refresh_metadata",
        "add_track",
        "delete_track",
        "rename_playlist",
        "move_playlist",
        "delete_playlist",
        "reorder_playlist_track",
        "create_folder",
        "create_smart_playlist",
        "update_smart_playlist",
        "create_playlist",
        "add_track_to_playlist",
        "remove_track_from_playlist",
        "save",
        "update_tracks_metadata",
        "update_track_comment",
        "update_track_path",
        "ensure_standalone_master_db",
    ]
    missing = [m for m in mutators if not hasattr(getattr(RekordboxDB, m), "__wrapped__")]
    assert not missing, f"unwrapped RekordboxDB mutators: {missing}"


def test_decorator_wraps_live_mutators():
    from app.live_database import LiveRekordboxDB

    mutators = [
        "add_track",
        "delete_track",
        "update_track_comment",
        "update_track_metadata",
        "create_mytag",
        "delete_mytag",
        "set_track_mytags",
        "rename_playlist",
        "move_playlist",
        "delete_playlist",
        "create_playlist",
        "add_track_to_playlist",
        "remove_track_from_playlist",
        "reorder_playlist_track",
    ]
    missing = [m for m in mutators if not hasattr(getattr(LiveRekordboxDB, m), "__wrapped__")]
    assert not missing, f"unwrapped LiveRekordboxDB mutators: {missing}"


def test_read_paths_not_wrapped():
    from app.database import RekordboxDB

    reads = [
        "get_all_tracks",
        "get_track_details",
        "get_playlist_tracks",
        "evaluate_smart_playlist",
    ]
    wrongly = [m for m in reads if hasattr(getattr(RekordboxDB, m), "__wrapped__")]
    assert not wrongly, f"read methods wrongly serialised: {wrongly}"


def test_live_db_property_preserved():
    from app.live_database import LiveRekordboxDB

    assert isinstance(LiveRekordboxDB.__dict__["db"], property)


# ---------------------------------------------------------------------------
# Serialisation harness + negative control (lock-mechanism, deterministic)
# ---------------------------------------------------------------------------


def _run_concurrency_probe(n_threads: int = 8, hold_s: float = 0.01) -> int:
    """Run n_threads through a @serialise_mutators-wrapped mutator that records
    peak concurrency inside its critical section. Returns the observed peak."""
    from app._db_lock import serialise_mutators

    counter_lock = threading.Lock()
    state = {"inside": 0, "peak": 0, "calls": 0}

    @serialise_mutators
    class _Writer:
        def update_thing(self):
            with counter_lock:
                state["inside"] += 1
                state["peak"] = max(state["peak"], state["inside"])
            time.sleep(hold_s)
            with counter_lock:
                state["inside"] -= 1
                state["calls"] += 1

    w = _Writer()
    threads = [threading.Thread(target=w.update_thing) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert state["calls"] == n_threads
    return state["peak"]


@pytest.mark.slow
def test_wrapped_mutator_serialises():
    """With the real RLock, peak concurrency inside a wrapped mutator is 1."""
    assert _run_concurrency_probe() == 1


@pytest.mark.slow
def test_noop_lock_negative_control(monkeypatch):
    """Negative control: monkeypatch the lock to a no-op → callers overlap
    (peak > 1), proving the lock is load-bearing, not decorative."""
    import app._db_lock as dbl

    class _NoOpLock:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(dbl, "_db_write_lock", _NoOpLock())
    peak = _run_concurrency_probe()
    assert peak > 1, "no-op lock should let callers overlap — lock not load-bearing?"
