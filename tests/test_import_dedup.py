"""Import dedup — ``/api/library/import-paths``, ``/api/library/scan-folder`` and
the folder watcher's ``_is_known_audio_path`` (app/main.py).

Every file of an import batch is checked against every library path. The check
used to ``resolve()`` each library path anew per file — 30 dropped files over
2,000 tracks were ~75k ``resolve()`` calls, about 12 s on Windows. The resolve
step is memoised now; the contracts pinned here are:

* the batch costs at most one ``resolve()`` per library path plus two per file;
* the helpers still read the LIVE ``db.tracks`` per file. A track another writer
  adds mid-batch (folder watcher, an overlapping scan) counts as known: a
  per-batch snapshot would import it a second time — a duplicate row in XML mode,
  a "Path is not unique" failure in live mode;
* the memo is cleared at batch start, so a stale resolve from earlier never
  decides a new batch;
* ``_track_id_for_path`` keeps first-match when two tracks share a path.

The library is a stub and ``ImportManager.process_import`` is faked: nothing
analyses audio or opens a master.db.
"""

from __future__ import annotations

import asyncio
import pathlib
import threading
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from app import import_tracker, main
from app.main import app

LIBRARY_SIZE = 500


def _post(url: str, body: dict[str, Any], headers: dict[str, str]) -> httpx.Response:
    async def _go() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            return await ac.post(url, json=body, headers=headers)

    return asyncio.run(_go())


def _join_threads(name: str) -> None:
    for t in threading.enumerate():
        if t.name == name and t is not threading.current_thread():
            t.join(timeout=60)
            assert not t.is_alive(), f"{name} did not finish"


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not really audio")
    return path


def _rows_for(library: SimpleNamespace, path: Path) -> list[str]:
    target = str(path.resolve())
    return [tid for tid, t in library.tracks.items() if str(Path(t["path"]).resolve()) == target]


def _tasks_by_path() -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for task in import_tracker.get_all().values():
        out.setdefault(task["file_path"], []).append(task)
    return out


@pytest.fixture(autouse=True)
def _fresh_state(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(import_tracker, "_TASKS", {})
    main._resolve_cached.cache_clear()
    yield
    main._resolve_cached.cache_clear()


@pytest.fixture
def library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """``LIBRARY_SIZE`` tracks. Only the ``known-*`` ones exist on disk."""
    tracks: dict[str, dict[str, Any]] = {}
    for i in range(LIBRARY_SIZE - 5):
        tracks[f"lib-{i}"] = {"path": str(tmp_path / "library" / f"track_{i:04d}.mp3")}
    for i in range(5):
        tracks[f"known-{i}"] = {"path": str(_touch(tmp_path / "known" / f"known_{i}.mp3"))}
    lib = SimpleNamespace(tracks=tracks)
    monkeypatch.setattr(main, "db", lib)
    return lib


@pytest.fixture
def imports(
    library: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> tuple[list[Path], list[Callable[[Path], None]]]:
    """Fake ``process_import``: records the file and adds it to the library.

    Hooks in the returned list run after each import — that is where a test
    plays the second writer.
    """
    imported: list[Path] = []
    hooks: list[Callable[[Path], None]] = []

    def process_import(fp: Path) -> tuple[str, dict[str, Any]]:
        fp = Path(fp)
        imported.append(fp)
        new_id = f"new-{len(imported)}"
        library.tracks[new_id] = {"path": str(fp.absolute())}
        for hook in hooks:
            hook(fp)
        return new_id, {}

    monkeypatch.setattr(main.ImportManager, "process_import", staticmethod(process_import))
    return imported, hooks


@pytest.fixture
def resolve_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    real_resolve = pathlib.Path.resolve

    def counting_resolve(self: Path, strict: bool = False) -> Path:
        calls.append(str(self))
        return real_resolve(self, strict=strict)

    monkeypatch.setattr(pathlib.Path, "resolve", counting_resolve)
    return calls


# ---------------------------------------------------------------------------
# /api/library/import-paths
# ---------------------------------------------------------------------------


def test_drop_imports_new_files_once_and_skips_known(
    tmp_path: Path,
    library: SimpleNamespace,
    imports: tuple[list[Path], list[Callable[[Path], None]]],
    resolve_calls: list[str],
    auth_token: dict[str, str],
) -> None:
    imported, _ = imports
    drop = tmp_path / "drop"
    new_files = [_touch(drop / f"new_{i:02d}.mp3") for i in range(30)]
    known = sorted((tmp_path / "known").iterdir())
    # The folder, one of its files again (an in-batch duplicate), five known files.
    paths = [str(drop), str(new_files[0]), *(str(k) for k in known)]

    resolve_calls.clear()
    r = _post("/api/library/import-paths", {"paths": paths}, auth_token)
    assert r.status_code == 200, r.text
    assert r.json()["queued_total"] == 36
    _join_threads("drop-import")
    batch_resolves = len(resolve_calls)

    # Old cost: one resolve per library path PER FILE (~18k here).
    assert batch_resolves <= LIBRARY_SIZE + 2 * 36, batch_resolves
    assert sorted(imported) == sorted(new_files)
    tasks = _tasks_by_path()
    for i, k in enumerate(known):
        (task,) = tasks[str(k)]
        assert task["status"] == "Skipped"
        assert task["local_track_id"] == f"known-{i}"
    dup_tasks = tasks[str(new_files[0])]
    assert sorted(t["status"] for t in dup_tasks) == ["Completed", "Skipped"]
    assert len({t["local_track_id"] for t in dup_tasks}) == 1
    assert len(_rows_for(library, new_files[0])) == 1


def test_drop_skips_a_file_another_writer_added_mid_batch(
    tmp_path: Path,
    library: SimpleNamespace,
    imports: tuple[list[Path], list[Callable[[Path], None]]],
    auth_token: dict[str, str],
) -> None:
    """The case a per-batch snapshot gets wrong: f3 lands in the library while
    the batch is still on f0 (folder watcher, overlapping scan)."""
    imported, hooks = imports
    files = [_touch(tmp_path / "drop" / f"f{i}.mp3") for i in range(5)]

    def other_writer(fp: Path) -> None:
        if fp == files[0]:
            library.tracks["other-writer-f3"] = {"path": str(files[3])}

    hooks.append(other_writer)

    r = _post("/api/library/import-paths", {"paths": [str(f) for f in files]}, auth_token)
    assert r.status_code == 200, r.text
    _join_threads("drop-import")

    assert imported == [files[0], files[1], files[2], files[4]]
    (task,) = _tasks_by_path()[str(files[3])]
    assert task["status"] == "Skipped"
    assert task["local_track_id"] == "other-writer-f3"
    assert _rows_for(library, files[3]) == ["other-writer-f3"]


def _store_known_via_detour_with_stale_memo(
    tmp_path: Path, library: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-spell each known row as ``known/sub/../known_N.mp3`` and memoise a
    wrong resolve for that spelling. A fresh resolve maps it onto the file the
    batch sees; the stale memo maps it nowhere."""
    (tmp_path / "known" / "sub").mkdir(exist_ok=True)
    detours = []
    for i in range(5):
        detour = str(tmp_path / "known" / "sub" / ".." / f"known_{i}.mp3")
        library.tracks[f"known-{i}"] = {"path": detour}
        detours.append(detour)
    with monkeypatch.context() as m:
        m.setattr(pathlib.Path, "resolve", lambda self, strict=False: Path("Z:/gone/stale.mp3"))
        for detour in detours:
            main._resolve_cached(detour)


def test_drop_batch_does_not_trust_a_resolve_memoised_before_it(
    tmp_path: Path,
    library: SimpleNamespace,
    imports: tuple[list[Path], list[Callable[[Path], None]]],
    monkeypatch: pytest.MonkeyPatch,
    auth_token: dict[str, str],
) -> None:
    imported, _ = imports
    known = tmp_path / "known" / "known_0.mp3"
    _store_known_via_detour_with_stale_memo(tmp_path, library, monkeypatch)

    r = _post("/api/library/import-paths", {"paths": [str(known)]}, auth_token)
    assert r.status_code == 200, r.text
    _join_threads("drop-import")

    assert imported == []
    (task,) = _tasks_by_path()[str(known)]
    assert task["status"] == "Skipped"
    assert task["local_track_id"] == "known-0"


# ---------------------------------------------------------------------------
# /api/library/scan-folder
# ---------------------------------------------------------------------------


def test_scan_imports_only_unknown_files(
    tmp_path: Path,
    library: SimpleNamespace,
    imports: tuple[list[Path], list[Callable[[Path], None]]],
    resolve_calls: list[str],
    auth_token: dict[str, str],
) -> None:
    imported, _ = imports
    scan = tmp_path / "known"  # holds the five known files
    new_files = [_touch(scan / "sub" / f"new_{i:02d}.mp3") for i in range(10)]

    resolve_calls.clear()
    r = _post("/api/library/scan-folder", {"path": str(scan)}, auth_token)
    assert r.status_code == 200, r.text
    _join_threads(f"scan-{scan.name}")

    assert sorted(imported) == sorted(new_files)
    assert len(resolve_calls) <= LIBRARY_SIZE + 2 * 15, len(resolve_calls)


def test_scan_skips_files_another_writer_added_mid_scan(
    tmp_path: Path,
    library: SimpleNamespace,
    imports: tuple[list[Path], list[Callable[[Path], None]]],
    auth_token: dict[str, str],
) -> None:
    """Whichever file the scan imports first, the other writer adds all the
    rest meanwhile — the scan must import exactly one and duplicate none."""
    imported, hooks = imports
    scan = tmp_path / "scan"
    files = [_touch(scan / f"s{i}.mp3") for i in range(6)]

    def other_writer(fp: Path) -> None:
        if len(imported) == 1:
            for n, f in enumerate(files):
                if f != fp:
                    library.tracks[f"other-{n}"] = {"path": str(f)}

    hooks.append(other_writer)

    r = _post("/api/library/scan-folder", {"path": str(scan)}, auth_token)
    assert r.status_code == 200, r.text
    _join_threads(f"scan-{scan.name}")

    assert len(imported) == 1
    for f in files:
        assert len(_rows_for(library, f)) == 1, f


def test_scan_does_not_trust_a_resolve_memoised_before_it(
    tmp_path: Path,
    library: SimpleNamespace,
    imports: tuple[list[Path], list[Callable[[Path], None]]],
    monkeypatch: pytest.MonkeyPatch,
    auth_token: dict[str, str],
) -> None:
    imported, _ = imports
    scan = tmp_path / "known"
    _store_known_via_detour_with_stale_memo(tmp_path, library, monkeypatch)

    r = _post("/api/library/scan-folder", {"path": str(scan)}, auth_token)
    assert r.status_code == 200, r.text
    _join_threads(f"scan-{scan.name}")

    assert imported == []


# ---------------------------------------------------------------------------
# The helpers themselves (folder-watcher signature)
# ---------------------------------------------------------------------------


def test_is_known_sees_a_track_added_after_an_earlier_call(
    tmp_path: Path, library: SimpleNamespace
) -> None:
    """The folder watcher calls ``_is_known_audio_path(path)`` between batches,
    with no memo clear in between — the library must still be read live."""
    late = _touch(tmp_path / "watched" / "late.mp3")
    assert main._is_known_audio_path(late) is False

    library.tracks["late"] = {"path": str(late)}

    assert main._is_known_audio_path(late) is True
    assert main._track_id_for_path(late) == "late"


def test_track_id_for_path_keeps_the_first_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = _touch(tmp_path / "dup" / "same.mp3")
    (tmp_path / "dup" / "sub").mkdir()
    detour = str(tmp_path / "dup" / "sub" / ".." / "same.mp3")

    monkeypatch.setattr(
        main, "db", SimpleNamespace(tracks={"first": {"path": str(f)}, "second": {"path": detour}})
    )
    assert main._track_id_for_path(f) == "first"

    main._resolve_cached.cache_clear()
    monkeypatch.setattr(
        main, "db", SimpleNamespace(tracks={"second": {"path": detour}, "first": {"path": str(f)}})
    )
    assert main._track_id_for_path(f) == "second"


def test_unresolvable_path_falls_back_to_the_raw_string(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken_resolve(self: Path, strict: bool = False) -> Path:
        raise OSError("device not ready")

    monkeypatch.setattr(pathlib.Path, "resolve", broken_resolve)
    raw = str(Path("X:/unplugged/track.mp3"))
    monkeypatch.setattr(main, "db", SimpleNamespace(tracks={"t1": {"path": raw}}))

    assert main._resolve_cached(raw) == raw
    assert main._is_known_audio_path(Path(raw)) is True
    assert main._track_id_for_path(Path(raw)) == "t1"
    assert main._is_known_audio_path(Path(raw + ".other")) is False
