"""Shared `master.db` write-serialisation primitives.

Lives in its own module (not `database.py`) so that BOTH `database.py` and
`live_database.py` can import the lock + decorator without a circular import
(`database.py` imports `LiveRekordboxDB` from `live_database.py`, so the
reverse direction would cycle).

`database.py` re-exports `_db_write_lock`, `db_lock`, `_serialised` so existing
`from app.database import _db_write_lock` / `db_lock` / `_serialised` callers
keep working unchanged.

Pure stdlib — imports nothing from the app, so no module can cycle through it.
"""

import inspect
import threading
from contextlib import contextmanager
from functools import wraps

# Module-level reentrant lock that serialises all mutating operations on the
# global `db` singleton against concurrent FastAPI request threads.
# RLock is used so methods that internally call other mutating methods
# (e.g. `update_tracks_metadata` → `save_xml`) don't deadlock themselves.
_db_write_lock = threading.RLock()


@contextmanager
def db_lock():
    """Acquire `_db_write_lock` for the duration of the `with` block.

    Use this when several mutations must form one atomic transaction
    from a route handler, e.g.::

        with db_lock():
            db.add_track(...)
            db.add_track_to_playlist(...)

    Mutating methods on `RekordboxDB` / `LiveRekordboxDB` are auto-wrapped by
    `@serialise_mutators`, so you only need this for multi-step transactions or
    rbox-direct writers that bypass both facades (e.g. `AnalysisDBWriter`).
    """
    with _db_write_lock:
        yield


def _serialised(method):
    """Decorator: serialise a single method against `_db_write_lock`.

    `functools.wraps` sets `__wrapped__` so the drift guard can detect the
    decoration.
    """

    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with _db_write_lock:
            return method(self, *args, **kwargs)

    return wrapper


# Name prefixes that mark a mutating method. Single source of truth for
# `serialise_mutators`. NOTE: the drift guard (`tests/test_concurrency.py`)
# deliberately does NOT consult this tuple — it detects writers by the rbox
# write-calls they make, so an off-prefix future mutator still fails CI.
_MUTATOR_PREFIXES = (
    "set_",
    "load_",
    "unload_",
    "create_",
    "delete_",
    "remove_",
    "add_",
    "update_",
    "move_",
    "rename_",
    "reorder_",
    "refresh_",
    "save",
    "ensure_",
)


def serialise_mutators(cls):
    """Class decorator: wrap every mutating method of `cls` in `_serialised`.

    A method is wrapped iff it is a plain function (not a property / classmethod
    / staticmethod), is not private/dunder (`_`-prefixed), is not a read accessor
    (`get_*` / `list_*`), and its name starts with one of `_MUTATOR_PREFIXES`.

    Replaces the hand-maintained `setattr` name-list that silently drifted.
    """
    for name, attr in list(vars(cls).items()):
        if name.startswith("_"):
            continue
        if not inspect.isfunction(attr):
            continue
        if name.startswith(("get_", "list_")):
            continue
        if name.startswith(_MUTATOR_PREFIXES):
            setattr(cls, name, _serialised(attr))
    return cls
