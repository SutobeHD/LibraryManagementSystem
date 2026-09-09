"""Artist-Hub background sync + idle signal (T-17 — app/artist_store/sync.py).

The contracts that matter, all of them things this feature could get quietly wrong:

* **Idle fails closed.** A running phrase batch, SoundCloud download, local import or an
  unloaded library each mean "not idle", and a probe that raises means "not idle" too.
  ``is_idle()`` reports *which* signal blocked it, so a run that did not happen can say
  why instead of looking like a no-op.
* **``off`` is never fetched.** Not "fetched and discarded" — never called at all.
* **``review`` is fetched and queues nothing.** Neither does ``auto``: the background
  pass never downloads, and ``downloads_queued`` stays 0 so that is observable.
* **One CallBudget for the whole run**, not one per artist, and the run stops when it
  is spent.
* **The run stops mid-way** the moment idle goes false, and says so in
  ``reason_stopped``.
* **``record_sync`` is stamped** on success and carries the error text on failure,
  without clobbering the artist's mode.

No network, no keyring, no ``master.db``: every tracker is monkeypatched, the refresher
is a local callable, and the sidecar is a throwaway file in ``tmp_path``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app import import_tracker, main
from app import soundcloud_api as sc_api
from app.artist_store import catalogue as catalogue_mod
from app.artist_store import schema, sync

SYNC_SOURCE = Path(sync.__file__)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _close_thread_conn() -> None:
    conn = getattr(schema._local, "conn", None)
    if conn is not None:
        conn.close()
        del schema._local.conn


@pytest.fixture
def store(tmp_path, monkeypatch):
    db_file = tmp_path / "artists.db"
    monkeypatch.setattr(schema, "_db_path", lambda: db_file)
    monkeypatch.setattr(schema, "_initialised", False)
    _close_thread_conn()
    schema.init_db()
    yield schema
    _close_thread_conn()


class _LoadedDb:
    loaded = True


class _LoadingDb:
    loaded = False


@pytest.fixture(autouse=True)
def quiet_app(monkeypatch):
    """Every observable tracker reports nothing running."""
    import app.database as database_mod
    from app.soundcloud_downloader import sc_downloader

    monkeypatch.setattr(database_mod, "db", _LoadedDb())
    monkeypatch.setattr(main, "_phrase_jobs", {})
    monkeypatch.setattr(main, "_artist_jobs", {})
    monkeypatch.setattr(main, "_dup_jobs", {})
    monkeypatch.setattr(sc_downloader, "tasks", {})
    monkeypatch.setattr(import_tracker, "get_all", dict)
    # Swap the registry out rather than draining it: app/main.py registers a live
    # analyze-batch probe at import time, and unregistering it here left it gone for
    # every later test in the session. The suite only stayed green because the file
    # names happened to sort in a forgiving order.
    monkeypatch.setattr(sync, "_extra_probes", {})
    yield


def _favourite(name: str, mode: str) -> str:
    collection_id = schema.create_collection(name)
    schema.add_favourite(collection_id)
    schema.set_sync_mode(collection_id, mode)
    return collection_id


def _ok_view(*, missing: int = 1, queueable: int = 1) -> dict:
    """A minimal `_artist_catalogue_view` success payload with countable buckets."""
    tracks = []
    for i in range(missing):
        tracks.append(
            {
                "sc_id": f"m{i}",
                "in_library": False,
                "auto_queue_allowed": i < queueable,
            }
        )
    return {
        "status": "ok",
        "collection_id": "",
        catalogue_mod.BUCKET_THEIR_TRACKS: tracks,
        catalogue_mod.BUCKET_MIXES: [{"sc_id": "mix1", "in_library": None}],
    }


class _Recorder:
    """A refresher that records the ids and budget objects it was handed."""

    def __init__(self, view=None, spend: int = 0):
        self.calls: list[str] = []
        self.budgets: list[int] = []
        self._view = view or (lambda cid: _ok_view())
        self._spend = spend

    def __call__(self, collection_id: str, *, budget) -> dict:
        self.calls.append(collection_id)
        self.budgets.append(id(budget))
        for _ in range(self._spend):
            budget.try_spend()
        return self._view(collection_id)


def _budget(limit: int = 60) -> sc_api.CallBudget:
    return sc_api.CallBudget(limit=limit, label="test")


# ---------------------------------------------------------------------------
# The idle signal
# ---------------------------------------------------------------------------


def test_idle_true_only_when_every_tracker_is_quiet():
    idle, reason = sync.is_idle()
    assert idle is True
    assert reason == sync.STOP_IDLE
    report = sync.idle_report()
    assert set(report["probes"].values()) == {"quiet"}
    # The streaming analyse route keeps no job record — say so, never imply coverage.
    assert report["unobservable"]


def test_not_idle_while_a_phrase_batch_runs(monkeypatch):
    monkeypatch.setattr(main, "_phrase_jobs", {"j1": {"status": "running"}})
    idle, reason = sync.is_idle()
    assert idle is False
    assert reason.startswith("phrase_batch:")


def test_not_idle_while_a_soundcloud_download_runs(monkeypatch):
    from app.soundcloud_downloader import sc_downloader

    monkeypatch.setattr(sc_downloader, "tasks", {"t1": {"status": "Downloading"}})
    idle, reason = sync.is_idle()
    assert idle is False
    assert reason.startswith("sc_download:")


def test_not_idle_while_a_local_import_runs(monkeypatch):
    monkeypatch.setattr(import_tracker, "get_all", lambda: {"i1": {"status": "Analyzing"}})
    idle, reason = sync.is_idle()
    assert idle is False
    assert reason.startswith("local_import:")


def test_not_idle_while_the_library_is_loading(monkeypatch):
    import app.database as database_mod

    monkeypatch.setattr(database_mod, "db", _LoadingDb())
    idle, reason = sync.is_idle()
    assert idle is False
    assert reason == "library_not_loaded"


def test_finished_jobs_do_not_block(monkeypatch):
    monkeypatch.setattr(main, "_phrase_jobs", {"j1": {"status": "done"}})
    monkeypatch.setattr(main, "_dup_jobs", {"d1": {"status": "error"}})
    monkeypatch.setattr(import_tracker, "get_all", lambda: {"i1": {"status": "Completed"}})
    assert sync.is_idle()[0] is True


def test_unknown_job_status_counts_as_busy(monkeypatch):
    monkeypatch.setattr(main, "_artist_jobs", {"a1": {"status": "hoovering"}})
    idle, reason = sync.is_idle()
    assert idle is False
    assert reason == "artist_job:hoovering"


def test_a_probe_that_raises_counts_as_busy(monkeypatch):
    def _boom():
        raise RuntimeError("tracker unreadable")

    sync.register_probe("explodes", _boom)
    idle, reason = sync.is_idle()
    assert idle is False
    assert reason.startswith("probe_error:")
    assert sync.idle_report()["probes"]["explodes"].startswith("probe_error:")


def test_a_registered_probe_can_report_busy(monkeypatch):
    monkeypatch.setattr(sync, "_extra_probes", {})
    sync.register_probe("analyze_batch", lambda: "analyze_batch:2 running")
    idle, reason = sync.is_idle()
    assert idle is False
    assert reason == "analyze_batch:2 running"
    assert sync.unregister_probe("analyze_batch") is True
    assert sync.is_idle()[0] is True


def test_an_abandoned_task_is_ignored_but_reported(monkeypatch):
    import time as time_mod

    from app.soundcloud_downloader import sc_downloader

    stale_start = time_mod.time() - sync.STALE_TASK_S - 60
    monkeypatch.setattr(
        sc_downloader, "tasks", {"t1": {"status": "Downloading", "start_time": stale_start}}
    )
    report = sync.idle_report()
    assert report["idle"] is True
    assert report["stale_ignored"] == ["sc_download:t1"]


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------


def test_off_artist_is_never_fetched(store):
    off = _favourite("Off Artist", schema.SYNC_OFF)
    auto = _favourite("Auto Artist", schema.SYNC_AUTO)
    refresher = _Recorder()

    run = sync.run_sync(refresher=refresher, budget=_budget(), force=True, remember=False)

    assert refresher.calls == [auto]
    assert off not in refresher.calls
    assert run.artists_synced == 1
    assert schema.get_sync_state(off) is not None  # the mode row survives
    assert schema.get_sync_state(off)["last_sync_at"] is None


def test_review_artist_is_fetched_and_queues_nothing(store):
    review = _favourite("Review Artist", schema.SYNC_REVIEW)
    refresher = _Recorder(view=lambda cid: _ok_view(missing=3, queueable=2))

    run = sync.run_sync(refresher=refresher, budget=_budget(), force=True, remember=False)

    assert refresher.calls == [review]
    assert run.downloads_queued == 0
    result = run.results[0]
    assert (result.mode, result.status) == (schema.SYNC_REVIEW, "ok")
    # The candidates are counted, not acted on — a download is user-initiated.
    assert (result.missing, result.auto_queue_candidates) == (3, 2)


def test_auto_artist_also_queues_nothing(store):
    _favourite("Auto Artist", schema.SYNC_AUTO)
    run = sync.run_sync(
        refresher=_Recorder(view=lambda cid: _ok_view(missing=5, queueable=5)),
        budget=_budget(),
        force=True,
        remember=False,
    )
    assert run.downloads_queued == 0
    assert run.artists_synced == 1


def test_sync_module_never_calls_a_download_or_queue():
    """Structural guard: the pass reads the downloader's task dict and nothing else.

    A regression here would be one line — `sc_downloader.download_track(...)` inside the
    loop — and no assertion about counts would catch it, because the count would then be
    honest.
    """
    tree = ast.parse(SYNC_SOURCE.read_text(encoding="utf-8"))
    called: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            called.add(func.attr)
        elif isinstance(func, ast.Name):
            called.add(func.id)
    forbidden = {name for name in called if "download" in name or "queue" in name}
    assert not forbidden, forbidden


def test_run_stops_mid_way_when_idle_goes_false(store):
    first = _favourite("A Artist", schema.SYNC_AUTO)
    _favourite("B Artist", schema.SYNC_AUTO)
    _favourite("C Artist", schema.SYNC_AUTO)
    refresher = _Recorder()
    verdicts = iter([(True, "idle"), (True, "idle"), (False, "sc_download:Downloading")])

    run = sync.run_sync(
        refresher=refresher,
        budget=_budget(),
        idle=lambda: next(verdicts),
        force=True,
        remember=False,
    )

    assert refresher.calls == [first]
    assert run.artists_synced == 1
    assert run.artists_skipped == 2
    assert run.reason_stopped == "busy:sc_download:Downloading"


def test_a_busy_app_runs_nothing_at_all(store):
    _favourite("A Artist", schema.SYNC_AUTO)
    refresher = _Recorder()

    run = sync.run_sync(
        refresher=refresher,
        budget=_budget(),
        idle=lambda: (False, "library_not_loaded"),
        force=True,
        remember=False,
    )

    assert refresher.calls == []
    assert run.reason_stopped == "busy:library_not_loaded"
    assert run.artists_synced == 0


def test_one_budget_is_shared_across_the_whole_run(store):
    _favourite("A Artist", schema.SYNC_AUTO)
    _favourite("B Artist", schema.SYNC_AUTO)
    _favourite("C Artist", schema.SYNC_AUTO)
    budget = _budget(limit=10)
    refresher = _Recorder(spend=2)

    run = sync.run_sync(refresher=refresher, budget=budget, force=True, remember=False)

    assert len(refresher.calls) == 3
    assert len(set(refresher.budgets)) == 1  # the same object every time
    assert budget.used == 6
    assert run.calls_used == 6
    assert run.call_budget == 10


def test_the_run_stops_when_the_shared_budget_is_spent(store):
    _favourite("A Artist", schema.SYNC_AUTO)
    _favourite("B Artist", schema.SYNC_AUTO)
    _favourite("C Artist", schema.SYNC_AUTO)
    refresher = _Recorder(spend=4)

    run = sync.run_sync(refresher=refresher, budget=_budget(limit=4), force=True, remember=False)

    assert len(refresher.calls) == 1
    assert run.reason_stopped == sync.STOP_CALL_BUDGET
    assert run.artists_skipped == 2


def test_oldest_last_synced_goes_first(store):
    old = _favourite("Old Artist", schema.SYNC_AUTO)
    new = _favourite("New Artist", schema.SYNC_AUTO)
    never = _favourite("Never Artist", schema.SYNC_AUTO)
    schema.record_sync(old)
    schema.record_sync(new)
    # `record_sync` stamps "now" for both, so age them by hand — second-resolution
    # timestamps would otherwise tie.
    conn = schema._ensure_schema()
    conn.execute(
        "UPDATE sync_state SET last_sync_at = ? WHERE collection_id = ?",
        ("2020-01-01T00:00:00+00:00", old),
    )
    conn.execute(
        "UPDATE sync_state SET last_sync_at = ? WHERE collection_id = ?",
        ("2024-01-01T00:00:00+00:00", new),
    )
    conn.commit()
    refresher = _Recorder()

    sync.run_sync(
        refresher=refresher, budget=_budget(), force=True, min_interval_s=0.0, remember=False
    )

    assert refresher.calls == [never, old, new]


def test_a_freshly_synced_artist_is_left_alone(store):
    fresh = _favourite("Fresh Artist", schema.SYNC_AUTO)
    schema.record_sync(fresh)
    refresher = _Recorder()

    run = sync.run_sync(refresher=refresher, budget=_budget(), force=True, remember=False)

    assert refresher.calls == []
    assert run.artists_skipped == 1
    assert run.results[0].status == "fresh"


def test_record_sync_stamps_success_and_stores_the_error(store):
    good = _favourite("Good Artist", schema.SYNC_AUTO)
    bad = _favourite("Bad Artist", schema.SYNC_AUTO)

    def _refresh(collection_id: str, *, budget):
        if collection_id == bad:
            raise RuntimeError("SoundCloud said no")
        return _ok_view()

    run = sync.run_sync(refresher=_refresh, budget=_budget(), force=True, remember=False)

    good_state = schema.get_sync_state(good)
    assert good_state["last_sync_at"]
    assert good_state["last_error"] is None
    assert good_state["mode"] == schema.SYNC_AUTO  # the stamp must not reset the mode

    bad_state = schema.get_sync_state(bad)
    assert bad_state["last_sync_at"]
    assert "SoundCloud said no" in bad_state["last_error"]
    assert run.artists_synced == 1
    assert run.errors[0]["collection_id"] == bad


def test_a_signed_out_session_ends_the_run(store):
    _favourite("A Artist", schema.SYNC_AUTO)
    _favourite("B Artist", schema.SYNC_AUTO)
    calls: list[str] = []

    def _refresh(collection_id: str, *, budget):
        calls.append(collection_id)
        return {"status": "not_connected", "detail": "SoundCloud is not connected."}

    run = sync.run_sync(refresher=_refresh, budget=_budget(), force=True, remember=False)

    assert len(calls) == 1
    assert run.reason_stopped == sync.STOP_NOT_CONNECTED
    assert run.artists_synced == 0


def test_a_non_ok_state_is_not_counted_as_a_sync(store):
    _favourite("Gone Artist", schema.SYNC_AUTO)
    other = _favourite("Fine Artist", schema.SYNC_AUTO)

    def _refresh(collection_id: str, *, budget):
        if collection_id != other:
            return {"status": "artist_gone", "detail": "deleted or private"}
        return _ok_view()

    run = sync.run_sync(refresher=_refresh, budget=_budget(), force=True, remember=False)

    assert run.artists_synced == 1
    assert [r.status for r in run.results].count("artist_gone") == 1


def test_a_payload_without_buckets_prints_no_count(store):
    _favourite("A Artist", schema.SYNC_AUTO)
    run = sync.run_sync(
        refresher=lambda cid, *, budget: {"status": "ok"},
        budget=_budget(),
        force=True,
        remember=False,
    )
    result = run.results[0]
    assert result.status == "ok"
    assert result.missing is None  # never measured, never printed as 0
    assert result.auto_queue_candidates is None


def test_artist_cap_bounds_one_pass(store):
    for i in range(4):
        _favourite(f"Artist {i}", schema.SYNC_AUTO)
    refresher = _Recorder()

    run = sync.run_sync(
        refresher=refresher, budget=_budget(), force=True, max_artists=2, remember=False
    )

    assert len(refresher.calls) == 2
    assert run.reason_stopped == sync.STOP_ARTIST_CAP
    assert run.artists_skipped == 2


def test_the_setting_is_opt_in(store, monkeypatch):
    _favourite("A Artist", schema.SYNC_AUTO)
    refresher = _Recorder()
    monkeypatch.setattr("app.services.SettingsManager.load", classmethod(lambda cls: {}))

    run = sync.run_sync(refresher=refresher, budget=_budget(), remember=False)

    assert sync.background_sync_enabled() is False
    assert refresher.calls == []
    assert run.reason_stopped == sync.STOP_DISABLED


def test_the_setting_switches_the_run_on(store, monkeypatch):
    _favourite("A Artist", schema.SYNC_AUTO)
    refresher = _Recorder()
    monkeypatch.setattr(
        "app.services.SettingsManager.load",
        classmethod(lambda cls: {sync.SETTING_KEY: True}),
    )

    run = sync.run_sync(refresher=refresher, budget=_budget(), remember=False)

    assert sync.background_sync_enabled() is True
    assert refresher.calls
    assert run.reason_stopped == sync.STOP_COMPLETED


def test_a_refresher_without_a_shared_budget_is_refused(store):
    _favourite("A Artist", schema.SYNC_AUTO)

    def _own_budget(collection_id: str):  # no `budget=` — would cap per artist
        return _ok_view()

    run = sync.run_sync(refresher=_own_budget, budget=_budget(), force=True, remember=False)

    assert run.reason_stopped == sync.STOP_NO_REFRESHER
    assert run.artists_synced == 0
    assert "budget" in run.errors[0]["detail"]


def test_the_run_record_round_trips(store):
    _favourite("A Artist", schema.SYNC_AUTO)
    run = sync.run_sync(refresher=_Recorder(), budget=_budget(), force=True)

    stored = sync.last_run()
    assert stored is not None
    assert stored["artists_synced"] == 1
    assert stored["reason_stopped"] == sync.STOP_COMPLETED
    assert stored["downloads_queued"] == 0
    assert stored["started"] == run.started
