"""Facade invariant: every ``db.<method>`` a caller uses must exist.

``app.database.RekordboxDB`` is a hand-written facade over
``RekordboxXMLDB`` and ``LiveRekordboxDB``. It has **no ``__getattr__``**,
so a method that exists on a backing class but was never added to the
facade is not a passthrough — it is an ``AttributeError`` raised at the
call site, at request time, in production.

That is not hypothetical. Eight of them shipped simultaneously
(2026-08-04, see docs/QUALITY_GATES.md):

    db.load_xml                 POST /api/library/upload-xml
    db.save_xml                 analysis save + duplicate merge
    db.get_track_cues           GET  /api/track/{tid}/cues
    db.get_track_beatgrid       GET  /api/track/{tid}/beatgrid
    db.save_track_cues          POST /api/track/cues/save
    db.save_track_beatgrid      POST /api/track/grid/save
    db.get_analysis_writer      POST /api/analysis/write-to-db
    db.get_unanalyzed_track_ids POST /api/analysis/write-to-db

Two of those back the waveform editor's hot-cue save and the region
editor's beatgrid save — user-facing features that returned 500 on every
single use for as long as they existed. A ninth call, ``db.get_tracks()``,
named a method that exists on no class at all (it is ``get_all_tracks``),
and one of its four sites hid the failure behind ``hasattr()`` and
quietly processed an empty list.

``mypy app/`` catches this class now, but mypy is one config edit away
from being non-blocking again. This test is the belt to that suspenders,
and unlike mypy it names the offending file and line.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.database import RekordboxDB

REPO_ROOT = Path(__file__).resolve().parent.parent

# Modules that hold a module-level `db` bound to the RekordboxDB singleton.
CALLER_MODULES = ("app/main.py", "app/services.py")

# Attributes reached on `db` that are set in ``__init__`` rather than
# declared on the class, so ``hasattr(RekordboxDB, …)`` cannot see them.
# Listed explicitly so a typo in a call site still fails the test.
INSTANCE_ATTRS = frozenset(
    {
        "xml_db",
        "live_db",
        "live_db_path",
        "loaded",
        "mode",
    }
)

# Properties on the class. Split from INSTANCE_ATTRS because these *are*
# introspectable, and test_class_level_attrs_still_resolve keeps the list
# from going stale.
CLASS_ATTRS = frozenset(
    {
        "tracks",
        "playlists",
        "artists",
        "genres",
        "xml_path",
        "active_db",
    }
)

KNOWN_NON_METHOD_ATTRS = INSTANCE_ATTRS | CLASS_ATTRS


def _db_attribute_uses(module_path: Path) -> set[tuple[str, int]]:
    """Every ``db.<attr>`` access in the module, as (attr, lineno).

    Deliberately syntactic. Importing the module and poking at it would
    only find the attributes a given code path happens to touch, which is
    exactly the blind spot that let eight of these ship.
    """
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    uses: set[tuple[str, int]] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "db"
        ):
            uses.add((node.attr, node.lineno))
    return uses


@pytest.mark.parametrize("module", CALLER_MODULES)
def test_every_db_attribute_exists_on_the_facade(module: str) -> None:
    """No caller may reach for something RekordboxDB does not define."""
    path = REPO_ROOT / module
    missing = sorted(
        (attr, lineno)
        for attr, lineno in _db_attribute_uses(path)
        if not attr.startswith("_")
        and attr not in KNOWN_NON_METHOD_ATTRS
        and not hasattr(RekordboxDB, attr)
    )
    assert not missing, (
        f"{module} calls attributes RekordboxDB does not define — these raise "
        f"AttributeError at request time, not at import:\n"
        + "\n".join(f"  {module}:{lineno}  db.{attr}" for attr, lineno in missing)
        + "\nAdd a delegation to RekordboxDB (see the '── passthroughs' blocks "
        "in app/database.py), or fix the call site."
    )


def test_class_level_attrs_still_resolve() -> None:
    """Keeps the allowlist above honest as the facade evolves."""
    stale = sorted(a for a in CLASS_ATTRS if not hasattr(RekordboxDB, a))
    assert not stale, (
        f"CLASS_ATTRS lists properties RekordboxDB no longer has: {stale}. "
        "Remove them from the allowlist so real call sites get checked again."
    )


def test_instance_attrs_are_set_by_init() -> None:
    """Every INSTANCE_ATTRS entry must actually be assigned in ``__init__``.

    Without this, a stale allowlist entry would mask a genuinely missing
    attribute at a call site.
    """
    source = (REPO_ROOT / "app" / "database.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    facade = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "RekordboxDB")
    init = next(n for n in facade.body if isinstance(n, ast.FunctionDef) and n.name == "__init__")
    assigned = {
        t.attr
        for node in ast.walk(init)
        if isinstance(node, ast.Assign)
        for t in node.targets
        if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "self"
    }
    stale = sorted(INSTANCE_ATTRS - assigned)
    assert not stale, (
        f"INSTANCE_ATTRS lists attributes RekordboxDB.__init__ no longer assigns: "
        f"{stale}. Remove them from the allowlist."
    )


@pytest.mark.parametrize(
    "name",
    [
        "load_xml",
        "save_xml",
        "get_track_cues",
        "get_track_beatgrid",
        "save_track_cues",
        "save_track_beatgrid",
        "get_analysis_writer",
        "get_unanalyzed_track_ids",
        "get_all_tracks",
    ],
    ids=lambda n: n,
)
def test_previously_missing_methods_are_present(name: str) -> None:
    """Named regression pins for the nine that shipped missing."""
    assert callable(getattr(RekordboxDB, name, None)), (
        f"RekordboxDB.{name} is gone again — the route that calls it will "
        "500 on every request. See docs/QUALITY_GATES.md."
    )


def test_get_tracks_is_not_reintroduced() -> None:
    """``db.get_tracks()`` never existed; the method is ``get_all_tracks``.

    Pinned because one of the four call sites wrote
    ``db.get_tracks() if hasattr(db, "get_tracks") else []``, which turned
    the missing method into a silently empty result set instead of an
    error.
    """
    assert not hasattr(RekordboxDB, "get_tracks"), (
        "A `get_tracks` appeared on RekordboxDB. If that is intentional, "
        "delete this test — but check first that callers are not relying on "
        "it to mean `get_all_tracks`."
    )


# ---------------------------------------------------------------------------
# The same bug class, generalised beyond the db singleton
# ---------------------------------------------------------------------------
#
# `db.update_track_title` was found by the AST scan above. `AudioEngine.
# get_duration` — a `hasattr()`-guarded call to a method that has never
# existed, so the branch was permanently dead — was found by generalising it.
# This test keeps both classes covered for every module-level app.* object
# reached by attribute in the caller modules.


def _module_level_attribute_uses(module_path: Path) -> set[tuple[str, str, int]]:
    """Every ``<Name>.<attr>`` access, as (base, attr, lineno)."""
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    return {
        (node.value.id, node.attr, node.lineno)
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
    }


@pytest.mark.parametrize("module", CALLER_MODULES)
def test_app_owned_objects_expose_every_attribute_used(module: str) -> None:
    """No caller may reach for a method an app.* class does not define.

    Scoped to objects whose ``__module__`` starts with ``app.`` — third-party
    and stdlib names are someone else's contract, and dynamic attributes on
    them would only produce noise.
    """
    import importlib

    mod = importlib.import_module(module.replace("/", ".").removesuffix(".py"))

    missing: list[tuple[str, str, int]] = []
    for base, attr, lineno in _module_level_attribute_uses(REPO_ROOT / module):
        if attr.startswith("_"):
            continue
        obj = getattr(mod, base, None)
        if obj is None:
            continue
        owner = getattr(obj, "__module__", None) or getattr(type(obj), "__module__", "")
        if not str(owner).startswith("app."):
            continue
        if base == "db":
            continue  # covered in full by the dedicated scan above
        if not hasattr(obj, attr):
            missing.append((base, attr, lineno))

    assert not missing, (
        f"{module} uses attributes that do not exist on app.* objects:\n"
        + "\n".join(
            f"  {module}:{ln}  {base}.{attr}"
            for base, attr, ln in sorted(missing, key=lambda t: t[2])
        )
        + "\nA `hasattr()` guard around one of these does not make it correct — "
        "it makes the branch permanently dead."
    )
