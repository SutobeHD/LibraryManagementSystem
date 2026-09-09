"""Artist-Hub discovery + background-sync route tests (T-16 / T-17).

The contracts under test are the ones this feature has previously broken:

* ``GET /api/artists/discover`` is **never a bare list**. Every answer carries a state
  per source, so a source that failed, hit the call cap or was never queried can never
  be rendered as "nothing found".
* Signed out is not an error: the related hop reports ``not_queried`` and the zero-call
  co-occurrence tier still answers.
* ``POST /api/artists/sync/run`` is session-gated and answers 409 while a pass is
  already in flight.
* ``GET /api/artists/sync/status`` is public, names the probe that is keeping the app
  busy, and reports a run record only when one exists.
* The opt-in setting defaults to **off** and gates the pass — a run without ``force``
  stops at ``disabled`` and never touches the refresher.
* ``_artist_catalogue_view`` accepts the shared ``budget=`` keyword, which is what lets
  one run hold one cap instead of N.
* The streaming ``analyze-batch`` route has a registered idle probe, so the status
  payload no longer lists it as unobservable.

**No network, no keyring, no real library.** ``sc_api.get_related_artists`` is replaced
per test and an autouse fixture pins ``soundcloud_auth.get_access_token`` to ``None`` so
a test that forgets to opt in reads "signed out" instead of the developer's real token.
The sidecar is a throwaway file in a tmp dir, exactly as in
``tests/test_artist_catalogue_routes.py``.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import httpx
import pytest

from app import auth, main
from app import soundcloud_api as sc_api
from app.artist_store import discovery, registry, schema
from app.artist_store import sync as artist_sync
from app.main import app

ARTIST_NAME = "Boys Noize"
ARTIST_URN = "soundcloud:users:4242"
RELATED_NAME = "Djedjotronic"
RELATED_URN = "soundcloud:users:7777"
FAKE_TOKEN = "not-a-real-oauth-token-only-lives-in-this-process"


def _request(
    method: str,
    url: str,
    *,
    json: Any = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    async def _go() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            return await ac.request(method, url, json=json, headers=headers)

    return asyncio.run(_go())


class _LibraryDB:
    """Stand-in for the ``db`` facade: ``loaded``, ``artists`` and ``tracks``."""

    def __init__(self, loaded: bool = True):
        self.loaded = loaded
        self.artists = [{"id": "art_0", "name": ARTIST_NAME, "track_count": 3, "Artwork": ""}]
        self.tracks: dict[str, dict[str, Any]] = {}


class _HeldLock:
    """An `asyncio.Lock` stand-in that is already held.

    A real lock cannot be pre-acquired here: every request runs in its own event loop,
    and an `asyncio.Lock` binds to the loop that first awaits it.
    """

    @staticmethod
    def locked() -> bool:
        return True


_WIPE = (
    "DELETE FROM favourites; DELETE FROM catalogue_cache; DELETE FROM projection; "
    "DELETE FROM sync_state; DELETE FROM links; DELETE FROM aliases; "
    "DELETE FROM collections; DELETE FROM store_meta;"
)


def _close_thread_conn() -> None:
    conn = getattr(schema._local, "conn", None)
    if conn is not None:
        conn.close()
        del schema._local.conn


@pytest.fixture(scope="module", autouse=True)
def _store_file(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    db_file = tmp_path_factory.mktemp("artist_discovery_routes") / "artists.db"
    mp.setattr(schema, "_db_path", lambda: db_file)
    mp.setattr(schema, "_initialised", False)
    _close_thread_conn()
    schema.init_db()
    yield
    _close_thread_conn()
    mp.undo()


@pytest.fixture(autouse=True)
def _clean_store():
    conn = schema._ensure_schema()
    with schema._write_lock:
        conn.executescript(_WIPE)
        conn.commit()
    registry._legacy_migration_done = False
    yield


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """No library, no keyring, no SoundCloud. Every escape hatch closed."""
    monkeypatch.setattr(main, "db", _LibraryDB())
    monkeypatch.setattr(auth, "paired_token_valid", lambda _token: False)
    monkeypatch.setattr(main.sc_auth, "get_access_token", lambda **_kw: None)
    monkeypatch.setattr(main.keyring, "get_password", lambda _service, _user: None)

    def _no_fetch(*_a: Any, **_kw: Any):
        raise AssertionError("a test made a real SoundCloud call")

    monkeypatch.setattr(main.sc_api, "get_related_artists", _no_fetch)
    monkeypatch.setattr(sc_api, "get_related_artists", _no_fetch)
    monkeypatch.setattr(main.sc_api, "get_user_tracks", _no_fetch)
    monkeypatch.setattr(main.sc_api, "search_tracks_many", _no_fetch)

    # The idle probe reads the real facade, not `main.db`. Without this every test would
    # measure "library_not_loaded" instead of the probe it is actually about.
    from app import database as database_module

    monkeypatch.setattr(database_module.db, "loaded", True, raising=False)


@pytest.fixture(autouse=True)
def _quiet_settings(monkeypatch):
    """Settings come from the packaged defaults, never from the developer's file."""
    from app.services import SettingsManager

    monkeypatch.setattr(
        SettingsManager, "load", staticmethod(lambda: dict(SettingsManager.DEFAULT))
    )


@pytest.fixture
def signed_in(monkeypatch):
    monkeypatch.setattr(main.sc_auth, "get_access_token", lambda **_kw: FAKE_TOKEN)


@pytest.fixture
def favourite() -> str:
    cid = registry.favourite_artist_by_name(ARTIST_NAME)
    return str(cid)


@pytest.fixture
def linked_favourite(favourite: str) -> str:
    schema.set_link(
        favourite,
        registry.PROVIDER_SOUNDCLOUD,
        ARTIST_URN,
        "https://soundcloud.com/boysnoize",
        1.0,
    )
    return favourite


def _related_payload() -> sc_api.SCResultList:
    return sc_api.SCResultList(
        [
            {
                "urn": RELATED_URN,
                "username": RELATED_NAME,
                "permalink_url": f"https://soundcloud.com/{RELATED_NAME}",
                "track_count": 42,
                "followers_count": 5000,
                "avatar_url": "",
            }
        ],
        truncated=False,
        stop_reason="",
        calls_used=1,
    )


# ---------------------------------------------------------------------------
# GET /api/artists/discover
# ---------------------------------------------------------------------------


def test_discover_is_never_a_bare_list() -> None:
    body = _request("GET", "/api/artists/discover").json()

    assert isinstance(body, dict)
    assert body["status"] == "ok"
    assert set(body["sources"]) == {"related", "co_occurrence"}
    assert set(body["sources_detail"]) == {"related", "co_occurrence"}
    assert set(body["call_budget"]) == {"limit", "used", "remaining"}
    assert set(body["excluded_against"]) == {"local_names", "linked_accounts"}
    assert isinstance(body["suggestions"], list)


def test_signed_out_says_not_queried_never_nothing_found(favourite: str) -> None:
    body = _request("GET", "/api/artists/discover").json()

    assert body["soundcloud"]["connected"] is False
    assert body["soundcloud"]["detail"]
    assert body["sources"]["related"] == discovery.STATE_NOT_QUERIED
    assert body["sources_detail"]["related"]["reason"] == "not_signed_in"
    assert body["suggestions"] == []
    assert body["calls_used"] == 0


def test_no_linked_favourite_reports_the_reason(monkeypatch, signed_in, favourite: str) -> None:
    """A signed-in user with no bound account: nothing was asked, and it says so."""
    body = _request("GET", "/api/artists/discover").json()

    assert body["soundcloud"]["connected"] is True
    assert body["sources"]["related"] == discovery.STATE_NOT_QUERIED
    assert body["sources_detail"]["related"]["reason"] == "no_linked_accounts"
    assert ARTIST_NAME in body["sources_detail"]["related"]["not_linked"]


def test_related_hop_returns_ranked_candidates(
    monkeypatch, signed_in, linked_favourite: str
) -> None:
    seen: list[tuple[str, str]] = []

    def _related(urn: str, token: str, *, budget: Any = None) -> sc_api.SCResultList:
        seen.append((urn, token))
        if budget is not None:
            budget.try_spend()
        return _related_payload()

    monkeypatch.setattr(sc_api, "get_related_artists", _related)

    body = _request("GET", "/api/artists/discover").json()

    assert seen == [(ARTIST_URN, FAKE_TOKEN)]
    assert body["sources"]["related"] == discovery.STATE_OK
    assert body["seeded_from"] == [ARTIST_NAME]
    assert body["calls_used"] == 1
    assert body["call_budget"]["limit"] == discovery.DEFAULT_DISCOVERY_BUDGET

    names = [s["name"] for s in body["suggestions"]]
    assert names == [RELATED_NAME]
    row = body["suggestions"][0]
    assert row["seeds"] == [ARTIST_NAME]
    assert row["track_count"] == 42
    assert row["followers_count"] == 5000
    assert row["urn"] == RELATED_URN


def test_a_failed_hop_is_reported_not_swallowed(
    monkeypatch, signed_in, linked_favourite: str
) -> None:
    def _boom(*_a: Any, **_kw: Any):
        raise sc_api.RateLimitError("429")

    monkeypatch.setattr(sc_api, "get_related_artists", _boom)

    body = _request("GET", "/api/artists/discover").json()

    assert body["sources"]["related"] == discovery.STATE_FAILED
    assert body["sources_detail"]["related"]["reason"] == "rate_limited"
    assert body["suggestions"] == []


def test_an_artist_you_already_favourited_is_excluded(
    monkeypatch, signed_in, linked_favourite: str
) -> None:
    """The suggestion IS the seed's own account — it must not be offered back."""

    def _related(_urn: str, _token: str, *, budget: Any = None) -> sc_api.SCResultList:
        return sc_api.SCResultList(
            [{"urn": ARTIST_URN, "username": ARTIST_NAME, "permalink_url": "", "track_count": 3}]
        )

    monkeypatch.setattr(sc_api, "get_related_artists", _related)

    body = _request("GET", "/api/artists/discover").json()

    assert body["suggestions"] == []
    assert body["excluded"] == 1
    assert body["excluded_against"]["local_names"] > 0


def test_discover_limit_is_capped(monkeypatch, signed_in) -> None:
    body = _request("GET", "/api/artists/discover?limit=100000").json()

    assert body["limit"] == discovery.DEFAULT_SUGGESTION_LIMIT * 4


# ---------------------------------------------------------------------------
# GET /api/artists/sync/status
# ---------------------------------------------------------------------------


def test_sync_status_needs_no_session() -> None:
    assert _request("GET", "/api/artists/sync/status").status_code == 200


def test_sync_status_reports_the_busy_probe_by_name() -> None:
    artist_sync.register_probe("_pytest_busy", lambda: "sc_download:downloading")
    try:
        body = _request("GET", "/api/artists/sync/status").json()
    finally:
        artist_sync.unregister_probe("_pytest_busy")

    assert body["idle"] is False
    assert body["reason"] == "sc_download:downloading"
    assert body["probes"]["_pytest_busy"] == "sc_download:downloading"


def test_sync_status_defaults_to_off_and_has_no_invented_run_record() -> None:
    body = _request("GET", "/api/artists/sync/status").json()

    assert body["enabled"] is False
    assert body["running"] is False
    assert body["last_run"] is None


def test_sync_status_lists_every_favourite_state(favourite: str) -> None:
    body = _request("GET", "/api/artists/sync/status").json()

    rows = {row["collection_id"]: row for row in body["artists"]}
    assert favourite in rows
    assert rows[favourite]["name"] == ARTIST_NAME
    # Never synced: the payload says None, so the UI cannot print a date.
    assert rows[favourite]["last_sync_at"] is None
    assert rows[favourite]["last_error"] is None


def test_analyze_batch_is_probed_and_no_longer_listed_as_unobservable() -> None:
    body = _request("GET", "/api/artists/sync/status").json()

    assert "analyze_batch" in body["probes"]
    assert body["probes"]["analyze_batch"] == "quiet"
    assert not [u for u in body["unobservable"] if u.startswith("analyze_batch")]
    # The module's own constant is untouched — only the route filters what it covers.
    assert any(u.startswith("analyze_batch") for u in artist_sync.UNOBSERVABLE_LOAD)


def test_analyze_batch_counter_makes_the_app_look_busy(monkeypatch) -> None:
    monkeypatch.setattr(main, "_analyze_batch_active", 2)

    body = _request("GET", "/api/artists/sync/status").json()

    assert body["idle"] is False
    assert body["probes"]["analyze_batch"] == "analyze_batch:2"


# ---------------------------------------------------------------------------
# POST /api/artists/sync/run
# ---------------------------------------------------------------------------


def test_sync_run_requires_session() -> None:
    assert _request("POST", "/api/artists/sync/run", json={"force": True}).status_code == 401


def test_sync_run_rejects_a_wrong_bearer() -> None:
    res = _request(
        "POST",
        "/api/artists/sync/run",
        json={"force": True},
        headers={"Authorization": "Bearer not-the-session-token"},
    )
    assert res.status_code == 401


def test_sync_run_returns_the_run_record(auth_token) -> None:
    res = _request("POST", "/api/artists/sync/run", json={"force": True}, headers=auth_token)

    assert res.status_code == 200
    run = res.json()["data"]
    assert set(run) >= {
        "started",
        "finished",
        "artists_synced",
        "artists_skipped",
        "reason_stopped",
        "calls_used",
        "call_budget",
        "downloads_queued",
        "errors",
        "results",
    }
    # The pass refreshes; it never queues and never downloads.
    assert run["downloads_queued"] == 0


def test_sync_run_without_force_stops_at_the_opt_in_setting(auth_token) -> None:
    res = _request("POST", "/api/artists/sync/run", json={"force": False}, headers=auth_token)

    assert res.json()["data"]["reason_stopped"] == artist_sync.STOP_DISABLED
    assert res.json()["data"]["artists_synced"] == 0


def test_sync_run_409s_while_a_pass_is_in_flight(monkeypatch, auth_token) -> None:
    monkeypatch.setattr(main, "_artist_sync_run_lock", _HeldLock())

    res = _request("POST", "/api/artists/sync/run", json={"force": True}, headers=auth_token)

    assert res.status_code == 409


def test_a_busy_app_refuses_the_pass_with_a_reason(auth_token) -> None:
    artist_sync.register_probe("_pytest_busy", lambda: "usb_sync:lock_held")
    try:
        res = _request("POST", "/api/artists/sync/run", json={"force": True}, headers=auth_token)
    finally:
        artist_sync.unregister_probe("_pytest_busy")

    run = res.json()["data"]
    assert run["reason_stopped"] == "busy:usb_sync:lock_held"
    assert run["artists_synced"] == 0
    # A refusal must not overwrite the record of the last pass that did run.
    assert artist_sync.last_run() is None


# ---------------------------------------------------------------------------
# The setting + the shared call budget
# ---------------------------------------------------------------------------


def test_setting_defaults_to_off() -> None:
    from app.services import SettingsManager

    assert SettingsManager.DEFAULT[artist_sync.SETTING_KEY] is False
    assert artist_sync.background_sync_enabled() is False


def test_setting_on_lets_a_pass_run(monkeypatch) -> None:
    from app.services import SettingsManager

    monkeypatch.setattr(
        SettingsManager,
        "load",
        staticmethod(lambda: {**SettingsManager.DEFAULT, artist_sync.SETTING_KEY: True}),
    )

    assert artist_sync.background_sync_enabled() is True
    run = artist_sync.run_sync(idle=lambda: (True, "idle"), remember=False)
    assert run.reason_stopped != artist_sync.STOP_DISABLED


def test_catalogue_view_accepts_one_shared_budget() -> None:
    """Without this keyword `run_sync` refuses outright — N artists would get N caps."""
    assert artist_sync._accepts_budget(main._artist_catalogue_view) is True
    assert artist_sync._resolve_refresher(None) is artist_sync._default_refresher


def test_a_passed_budget_is_used_instead_of_a_fresh_one(monkeypatch, favourite: str) -> None:
    """The caller's cap survives the call — that is what stops N artists getting N caps."""
    budget = sc_api.CallBudget(limit=7, label="shared")
    budget.try_spend()
    budget.try_spend()

    monkeypatch.setattr(main.artist_catalogue, "catalogue", lambda *_a, **_kw: {"from_cache": True})

    view = main._artist_catalogue_view(favourite, refresh=False, allow_fetch=False, budget=budget)

    assert view["call_budget"] == 7
    assert view["calls_used"] == 2

    # Omitted, the same call falls back to the route's own per-run cap.
    fresh = main._artist_catalogue_view(favourite, refresh=False, allow_fetch=False)
    assert fresh["call_budget"] == main.ARTIST_CATALOGUE_CALL_BUDGET
    assert fresh["calls_used"] == 0


def test_the_scheduler_is_wired_and_starts_paused() -> None:
    """The poller exists, waits before its first look, and is gated on the setting."""
    assert main.ARTIST_SYNC_STARTUP_DELAY_S > 0
    assert main.ARTIST_SYNC_POLL_INTERVAL_S > 0
    assert main._artist_sync_task is None  # never started outside the lifespan


# ---------------------------------------------------------------------------
# The scheduler loop
# ---------------------------------------------------------------------------


def _drive_scheduler(seconds: float) -> None:
    """Run the poll loop briefly, then cancel it. Also proves it cancels cleanly."""

    async def _go() -> None:
        task = asyncio.create_task(main._artist_sync_scheduler())
        await asyncio.sleep(seconds)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    asyncio.run(_go())


@pytest.fixture
def fast_scheduler(monkeypatch):
    monkeypatch.setattr(main, "ARTIST_SYNC_STARTUP_DELAY_S", 0.0)
    monkeypatch.setattr(main, "ARTIST_SYNC_POLL_INTERVAL_S", 0.01)
    monkeypatch.setattr(main, "_artist_sync_run_lock", asyncio.Lock())
    calls: list[dict[str, Any]] = []

    def _run(**kwargs: Any) -> artist_sync.SyncRun:
        calls.append(kwargs)
        return artist_sync.SyncRun()

    monkeypatch.setattr(main.artist_sync, "run_sync", _run)
    return calls


def test_scheduler_does_nothing_while_the_setting_is_off(fast_scheduler) -> None:
    _drive_scheduler(0.1)

    assert fast_scheduler == []


def test_scheduler_runs_a_pass_once_the_setting_is_on(monkeypatch, fast_scheduler) -> None:
    monkeypatch.setattr(main.artist_sync, "background_sync_enabled", lambda: True)

    _drive_scheduler(0.1)

    assert fast_scheduler, "the poller never asked for a pass"
    # The scheduled pass never forces: `force` is the manual button's escape hatch.
    assert all("force" not in kwargs for kwargs in fast_scheduler)
