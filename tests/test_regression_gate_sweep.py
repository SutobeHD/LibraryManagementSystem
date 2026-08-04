"""Named regression pins for the bugs the 2026-08-04 quality-gate sweep found.

Each of these shipped and none of them had a test. They are grouped here
rather than scattered because they share a cause: the gate that would have
caught each one was running with ``|| true`` in CI.

Catalogue + how each was found: docs/QUALITY_GATES.md.
"""

from __future__ import annotations

import ast
import json
import re
import threading
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# ruff F821 — NameError on every format-swap request
# ---------------------------------------------------------------------------


def test_format_swap_can_reach_uuid() -> None:
    """``uuid`` must be importable at ``app.main`` module scope.

    ``POST /api/library/format-swap/execute`` called ``uuid.uuid4()`` while
    ``uuid`` was imported only inside two *other* function bodies, so the
    route raised ``NameError`` on every request. Nothing at import time
    catches that, which is why it survived; ruff's F821 is what found it.
    """
    import app.main as main_mod

    tree = ast.parse((REPO_ROOT / "app" / "main.py").read_text(encoding="utf-8"))
    module_imports = {
        (alias.asname or alias.name).split(".")[0]
        for node in tree.body
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in node.names
    }

    assert "uuid" in module_imports, (
        "app/main.py no longer imports `uuid` at module scope. "
        "format_swap_execute() calls uuid.uuid4() — a function-local import "
        "in some other route does not make it visible there."
    )
    assert hasattr(main_mod, "uuid")

    # The route body itself must still be the caller this protects.
    fn = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) and n.name == "format_swap_execute"
    )
    assert "uuid.uuid4()" in ast.unparse(fn)


# ---------------------------------------------------------------------------
# mypy index — TypeError in live-mode delete_track
# ---------------------------------------------------------------------------


def test_live_delete_track_treats_playlist_entries_as_ids() -> None:
    """``playlists_tracks`` holds content-ID strings, not row objects.

    ``delete_track`` used to evaluate ``str(t["ID"]) for t in tracks``, which
    raises ``TypeError`` on a ``str`` — and did so *outside* the ``try`` a few
    lines below, so ``DELETE /api/track/{tid}`` blew up on the first playlist
    that had any tracks.
    """
    source = (REPO_ROOT / "app" / "live_database.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "LiveRekordboxDB")
    fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "delete_track")
    body = ast.unparse(fn)
    assert 't["ID"]' not in body and "t['ID']" not in body, (
        "delete_track indexes playlist entries again. They are content-ID "
        "strings — indexing a str raises TypeError before the try below can "
        "catch it."
    )
    assert "tid in tracks" in body


def test_live_playlists_tracks_stores_ids_not_dicts() -> None:
    """Pins the assumption the fix above rests on."""
    source = (REPO_ROOT / "app" / "live_database.py").read_text(encoding="utf-8")
    assert "self.playlists_tracks[pid].append(str(s.content_id))" in source, (
        "playlists_tracks no longer stores plain content-ID strings. "
        "delete_track and get_playlist_tracks both assume it does."
    )


# ---------------------------------------------------------------------------
# eslint no-undef — palette drop onto the editor timeline
# ---------------------------------------------------------------------------


def test_timeline_canvas_declares_on_region_drop() -> None:
    """``handleDrop`` calls ``onRegionDrop``; the props list must declare it.

    ``onRegionDrop?.()`` on an *undeclared* identifier throws ReferenceError —
    optional chaining only guards ``undefined`` properties, not missing
    bindings. The throw landed in the surrounding catch and surfaced as a
    "Drop failed" console line, so dragging a region onto the timeline
    silently did nothing.
    """
    src = (REPO_ROOT / "frontend/src/components/editor/TimelineCanvas.jsx").read_text(
        encoding="utf-8"
    )
    props_block = src.split("}) => {", 1)[0]
    assert "onRegionDrop" in props_block, (
        "TimelineCanvas no longer destructures onRegionDrop, but handleDrop "
        "still calls it — every palette drop will throw ReferenceError."
    )
    assert "onRegionDrop?.(" in src


def test_playlist_browser_loads_tree_once() -> None:
    """Only one effect may fetch the playlist tree.

    There were two byte-identical ``useEffect``s, one keyed on
    ``libraryStatus?.loaded`` and one on ``[]``, so every mount with a loaded
    library fetched the tree and the full track list twice.
    """
    src = (REPO_ROOT / "frontend/src/components/PlaylistBrowser.jsx").read_text(encoding="utf-8")
    assert src.count("loadTree();\n            loadAllTracks();") == 1, (
        "PlaylistBrowser has more than one effect calling loadTree() + "
        "loadAllTracks() — that is a duplicate fetch on every mount."
    )


# ---------------------------------------------------------------------------
# B019 — lru_cache on instance methods pinned every loaded library
# ---------------------------------------------------------------------------


def test_group_rollups_are_not_lru_cached() -> None:
    """``@lru_cache`` on a method keys on ``self`` and leaks the instance."""
    source = (REPO_ROOT / "app" / "database.py").read_text(encoding="utf-8")
    assert "@lru_cache" not in source, (
        "database.py uses lru_cache again. On an instance method the cache "
        "keys on `self`, so every RekordboxDB the sidecar ever loaded stays "
        "reachable for the process lifetime. Use the per-instance memo + "
        "_invalidate_group_caches() instead."
    )


def test_load_xml_invalidates_group_caches() -> None:
    """Reloading must not serve the previous library's rollups.

    The lru_cache version never invalidated on load, so loading a second XML
    into a live instance returned the first library's labels and albums.
    """
    source = (REPO_ROOT / "app" / "database.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "RekordboxXMLDB")
    fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "load_xml")
    assert "_invalidate_group_caches" in ast.unparse(fn), (
        "RekordboxXMLDB.load_xml no longer invalidates the label/album memo — "
        "a second load will serve the first library's rollups."
    )


# ---------------------------------------------------------------------------
# import_tracker — thread binding without monkey-patching threading.Thread
# ---------------------------------------------------------------------------


def test_import_task_binding_is_thread_local() -> None:
    from app import import_tracker

    assert import_tracker.current_task() is None

    import_tracker.bind_current_task("task-a")
    assert import_tracker.current_task() == "task-a"

    seen: list[str | None] = []

    def _worker() -> None:
        # A fresh thread must not inherit the caller's binding.
        seen.append(import_tracker.current_task())
        import_tracker.bind_current_task("task-b")
        seen.append(import_tracker.current_task())

    t = threading.Thread(target=_worker)
    t.start()
    t.join()

    assert seen == [None, "task-b"]
    # The worker's binding must not have leaked back out.
    assert import_tracker.current_task() == "task-a"

    import_tracker.unbind_current_task()
    assert import_tracker.current_task() is None
    # Unbinding twice must not raise — the old `del` form needed a
    # contextlib.suppress(AttributeError) around every call site.
    import_tracker.unbind_current_task()


def test_thread_object_is_not_monkey_patched() -> None:
    for module in ("app/main.py", "app/services.py"):
        source = (REPO_ROOT / module).read_text(encoding="utf-8")
        assert "_lms_import_tid" not in source, (
            f"{module} monkey-patches threading.current_thread() again. Use "
            "import_tracker.bind_current_task()/current_task() — the stdlib "
            "Thread object is shared with every other library in the process."
        )


# ---------------------------------------------------------------------------
# usb_manager — streaming pseudo-path detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("soundcloud:tracks:123", True),
        ("spotify:track:abc", True),
        ("https://example.com/a.mp3", True),
        ("http://example.com/a.mp3", True),
        ("tidal:track:1", True),
        ("beatport:track:1", True),
        # Windows drive letters must never be read as a URI scheme.
        (r"C:\Music\track.mp3", False),
        ("C:/Music/track.mp3", False),
        ("D:/x.wav", False),
        # Plain relative / POSIX paths.
        ("/home/user/music/a.flac", False),
        ("music/a.flac", False),
        ("", False),
        # A colon past the 12-char window is not a scheme.
        ("some/long/dir/name:weird.mp3", False),
    ],
)
def test_streaming_pseudo_path_detection(path: str, expected: bool) -> None:
    """One helper now backs both sync sites that used to inline this."""
    from app.usb_manager import _is_streaming_pseudo_path

    assert _is_streaming_pseudo_path(path) is expected


# ---------------------------------------------------------------------------
# .claude hooks — must survive a non-repo-root working directory
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("hook", ["format-on-edit.py", "auto-push-after-commit.py"])
def test_hooks_are_invoked_by_absolute_path(hook: str) -> None:
    """settings.json must not reference the hooks relatively.

    The Bash tool's cwd persists across calls, so one ``cd frontend`` used to
    break both hooks: auto-push died with ENOENT and format-on-edit silently
    stopped formatting (its relative_to() raised and was swallowed as "file
    outside the repo").
    """
    settings = json.loads((REPO_ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    commands = [
        entry.get("command", "")
        for group in settings["hooks"]["PostToolUse"]
        for entry in group["hooks"]
    ]
    matching = [c for c in commands if hook in c]
    assert matching, f"{hook} is no longer wired in settings.json"
    for cmd in matching:
        assert "$CLAUDE_PROJECT_DIR" in cmd, (
            f"{hook} is invoked without $CLAUDE_PROJECT_DIR: {cmd!r}. "
            "A relative path breaks as soon as a Bash call changes directory."
        )


@pytest.mark.parametrize("hook", ["format-on-edit.py", "auto-push-after-commit.py"])
def test_hooks_anchor_on_their_own_location(hook: str) -> None:
    source = (REPO_ROOT / ".claude" / "hooks" / hook).read_text(encoding="utf-8")
    assert "Path(__file__).resolve().parents[2]" in source, (
        f"{hook} no longer derives the repo root from __file__ — it will "
        "operate on whatever directory the tool call happened to be in."
    )


# ---------------------------------------------------------------------------
# validate_research_docs — lifecycle regex
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("line", "expected_state"),
    [
        ("- 2026-06-09 — `research/idea_` — created from template", "idea"),
        ("- 2026-06-09 — `drafting_` — promoted", "drafting"),
        ("- 2026-06-09 — drafting_ — promoted", "drafting"),
        ("- 2026-06-09 - `implement/inprogress_` - started", "inprogress"),
        ("- 2026-06-09 — `archived/implemented_` — shipped", "implemented"),
    ],
)
def test_lifecycle_regex_parses_both_backtick_forms(line: str, expected_state: str) -> None:
    """The backtick must be optional independently of the folder prefix.

    It used to sit *inside* the optional ``(research|implement|archived)/``
    group, so a line written as ``\\`drafting_\\`` — state in backticks with no
    folder — never matched, and the doc read as still being in its previous
    state. The pre-commit hook was failing on a correct document because of it.
    """
    import sys

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import validate_research_docs as vrd

    m: re.Match | None = vrd._LIFECYCLE_LINE_RE.search(line)
    assert m is not None, f"lifecycle line did not parse at all: {line!r}"
    assert m.group(3) == expected_state
