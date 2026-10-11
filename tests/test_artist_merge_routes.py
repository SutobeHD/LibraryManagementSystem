"""Artist-Hub merge + projection route tests (T-8 rest — app/main.py, plan row T13).

The engines themselves are covered by ``test_artist_merge_apply.py`` /
``test_artist_merge_preview.py`` / ``test_artist_projection.py``. What is asserted here
is the HTTP contract on top of them:

* every **mutation** route is behind ``Depends(require_session)`` — no header and a
  wrong bearer both 401, and a rejected call starts no job and writes nothing (T3);
* ``POST /api/artists/merge/preview`` is a POST for payload size only: no session, no
  ``master.db`` write, no undo-log run, no job;
* ``apply`` / ``revert`` / ``projection/sync`` hand back a job id and the job endpoint
  reports it, in the phrase-batch envelope;
* only one artist-hub job runs at a time — a second start while one is in flight 409s;
* Rekordbox holding the library 409s, matching the analysis routes — except for a
  projection **dry run**, which writes nothing and is therefore allowed.

Nothing here opens Rekordbox: ``main.db`` is replaced by a fake facade exposing only
the slice the engines use, the merge's file/lock/process seams are monkeypatched, and
both sidecars (``artists.db``, ``metadata_fixer_log.db``) are throwaway files.

Driving the app: httpx ``ASGITransport`` on ONE module-scoped event loop — not
``asyncio.run`` per request. ``_artist_job_lock`` is an ``asyncio.Lock``, and an
asyncio primitive binds to the first loop that awaits it; a fresh loop per request
would make the second acquire raise "bound to a different event loop".
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from typing import Any

import httpx
import pytest

from app import auth, main
from app.artist_store import merge
from app.artist_store import projection as artist_projection
from app.artist_store import schema as artist_schema
from app.main import app
from app.metadata_fixer import schema as fixer_log

CANONICAL = "Boys Noize"
VARIANTS = ("boys noize", "BOYS NOIZE")
GROUP = [*VARIANTS, CANONICAL]
XML_PATH = "C:/Pioneer/rekordbox/masterPlaylists6.xml"


# ---------------------------------------------------------------------------
# Fake library facade
# ---------------------------------------------------------------------------


class _Artist:
    def __init__(self, artist_id: str, name: str) -> None:
        self.id = artist_id
        self.name = name


class _Content:
    """A whole ``DjmdContent`` row — ``update_content`` writes all of it, so does this."""

    _COLUMNS = ("id", "artist_id", "bpm", "rb_local_usn")

    def __init__(self, content_id: str, artist_id: str) -> None:
        self.id = content_id
        self.artist_id = artist_id
        self.bpm = 12000
        self.rb_local_usn = 1000

    def snapshot(self) -> _Content:
        clone = _Content(self.id, self.artist_id)
        for column in self._COLUMNS:
            setattr(clone, column, getattr(self, column))
        return clone


class _Facade:
    """The slice of ``RekordboxDB`` the merge, the projection and the hub reach for."""

    def __init__(
        self,
        rows: tuple[tuple[str, str], ...],
        *,
        loaded: bool = True,
        xml_path: str | None = XML_PATH,
    ) -> None:
        self.loaded = loaded
        self._xml_path = xml_path
        self.artists: list[dict[str, Any]] = []
        self.contents: dict[str, _Content] = {}
        self.artist_rows: dict[str, _Artist] = {}
        self.tracks_by_ui_id: dict[str, list[dict[str, Any]]] = {}
        self.update_content_calls: list[str] = []

        names: list[str] = []
        for _cid, name in rows:
            if name not in names:
                names.append(name)
        artist_id_by_name = {name: f"A{i + 1}" for i, name in enumerate(names)}
        for name, artist_id in artist_id_by_name.items():
            self.artist_rows[artist_id] = _Artist(artist_id, name)
        for index, name in enumerate(names):
            owned = [cid for cid, n in rows if n == name]
            self.artists.append({"id": f"art_{index}", "name": name, "track_count": len(owned)})
            self.tracks_by_ui_id[f"art_{index}"] = [
                {"ID": cid, "Artist": name, "path": f"C:/music/{cid}.aiff"} for cid in owned
            ]
        for cid, name in rows:
            self.contents[cid] = _Content(cid, artist_id_by_name[name])

    # --- library reads ----------------------------------------------------
    def get_tracks_by_artist(self, aid: str) -> list[dict[str, Any]]:
        return [dict(t) for t in self.tracks_by_ui_id.get(str(aid), [])]

    def playlist_xml_path(self) -> str | None:
        return self._xml_path

    def get_playlist_by_id(self, pid: str) -> dict[str, Any] | None:
        return None

    # --- rbox passthroughs ------------------------------------------------
    def get_content_by_id(self, tid: str) -> _Content | None:
        row = self.contents.get(str(tid))
        return row.snapshot() if row is not None else None

    def update_content(self, item: _Content) -> bool:
        self.update_content_calls.append(str(item.id))
        stored = item.snapshot()
        stored.rb_local_usn = self.contents[str(item.id)].rb_local_usn + 1
        self.contents[str(item.id)] = stored
        return True

    def get_artist_by_name(self, name: str) -> _Artist | None:
        return next((r for r in self.artist_rows.values() if r.name == name), None)

    def create_artist(self, name: str) -> _Artist:
        artist_id = f"A{len(self.artist_rows) + 90}"
        row = _Artist(artist_id, name)
        self.artist_rows[artist_id] = row
        return row

    def artist_id_of(self, cid: str) -> str:
        return str(self.contents[cid].artist_id)


def _rows() -> tuple[tuple[str, str], ...]:
    return (("t1", VARIANTS[0]), ("t2", VARIANTS[1]), ("t3", CANONICAL))


# ---------------------------------------------------------------------------
# Transport — one loop for the whole module (see the module docstring)
# ---------------------------------------------------------------------------

_LOOP: asyncio.AbstractEventLoop | None = None


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

    assert _LOOP is not None
    return _LOOP.run_until_complete(_go())


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", autouse=True)
def _event_loop():
    global _LOOP
    _LOOP = asyncio.new_event_loop()
    yield _LOOP
    _LOOP.run_until_complete(_LOOP.shutdown_default_executor())
    _LOOP.close()
    _LOOP = None


def _close_conn(module) -> None:
    conn = getattr(module._local, "conn", None)
    if conn is not None:
        conn.close()
        del module._local.conn


@pytest.fixture(scope="module", autouse=True)
def _sidecars(tmp_path_factory):
    """Throwaway ``artists.db`` + undo log for the whole module.

    Module-scoped on purpose: both sidecars cache a connection per thread, and the job
    worker runs in the loop's executor — a per-test file would leave that thread
    holding a connection to a deleted path.
    """
    mp = pytest.MonkeyPatch()
    tmp = tmp_path_factory.mktemp("artist_merge_routes")
    mp.setattr(artist_schema, "_db_path", lambda: tmp / "artists.db")
    mp.setattr(artist_schema, "_initialised", False)
    mp.setattr(fixer_log, "_db_path", lambda: tmp / "metadata_fixer_log.db")
    _close_conn(artist_schema)
    _close_conn(fixer_log)
    artist_schema.init_db()
    fixer_log.init_db()
    yield
    _close_conn(artist_schema)
    _close_conn(fixer_log)
    mp.undo()


@pytest.fixture(autouse=True)
def _clean_log():
    """Empty the undo log around each test — the file is shared, the state must not be."""
    conn = fixer_log._connect()
    with fixer_log._write_lock:
        conn.executescript("DELETE FROM mutations; DELETE FROM runs;")
        conn.commit()
    yield


@pytest.fixture(autouse=True)
def _jobs():
    """No job state leaks between tests, and the single-flight lock never stays stuck."""
    main._artist_jobs.clear()
    yield
    main._artist_jobs.clear()
    if main._artist_job_lock.locked():
        main._artist_job_lock.release()


@pytest.fixture(autouse=True)
def library(monkeypatch) -> _Facade:
    """Fake facade + no device-token lookup, so no real user file is opened."""
    facade = _Facade(_rows())
    monkeypatch.setattr(main, "db", facade)
    monkeypatch.setattr(auth, "paired_token_valid", lambda _token: False)
    return facade


@pytest.fixture(autouse=True)
def _no_rekordbox(monkeypatch):
    """Never scan the real process list — and never fail because the user has RB open."""
    monkeypatch.setattr(main, "_is_rekordbox_running", lambda: False)
    monkeypatch.setattr(merge, "_rekordbox_running", lambda: False)
    monkeypatch.setattr(artist_projection, "_rekordbox_running", lambda: False)


@pytest.fixture(autouse=True)
def tags(monkeypatch):
    """Tag reads/writes and hashing are faked: no route may need a real audio file."""
    written: list[tuple[str, str]] = []

    def _write(path: str, updates: dict[str, Any]) -> bool:
        assert set(updates) == {"Artist"}, f"unexpected tag fields {sorted(updates)}"
        written.append((path, updates["Artist"]))
        return True

    monkeypatch.setattr(merge, "_write_tags", _write)
    monkeypatch.setattr(merge, "_read_tag_artist", lambda p: f"tag:{p}" if p else None)
    monkeypatch.setattr(merge, "_file_sha1", lambda p: f"sha1:{p}" if p else None)
    return written


@pytest.fixture(autouse=True)
def _no_real_lock(monkeypatch):
    """``db_lock()`` stand-in — the real one is exercised in test_artist_merge_apply."""

    @contextmanager
    def _lock():
        yield

    monkeypatch.setattr(merge, "_db_lock", _lock)


def _apply_body(**extra: Any) -> dict[str, Any]:
    return {"names": GROUP, "canonical": CANONICAL, **extra}


def _job(job_id: str) -> dict[str, Any]:
    res = _request("GET", f"/api/artists/jobs/{job_id}")
    assert res.status_code == 200, res.text
    return res.json()["data"]


# ---------------------------------------------------------------------------
# Auth — threat T3
# ---------------------------------------------------------------------------

_MUTATIONS = [
    ("POST", "/api/artists/merge/apply", _apply_body()),
    ("POST", "/api/artists/merge/revert/run-does-not-exist", {"write_tags": False}),
    ("POST", "/api/artists/projection/sync", {"dry_run": True}),
]


@pytest.mark.parametrize(("method", "url", "body"), _MUTATIONS)
def test_all_mutations_require_session(method, url, body) -> None:
    assert _request(method, url, json=body).status_code == 401


@pytest.mark.parametrize(("method", "url", "body"), _MUTATIONS)
def test_all_mutations_reject_wrong_bearer(method, url, body) -> None:
    headers = {"Authorization": "Bearer not-the-session-token"}
    assert _request(method, url, json=body, headers=headers).status_code == 401


def test_rejected_mutation_starts_no_job_and_writes_nothing(library) -> None:
    for method, url, body in _MUTATIONS:
        _request(method, url, json=body)

    assert main._artist_jobs == {}
    assert library.update_content_calls == []
    assert fixer_log.list_runs() == []


# ---------------------------------------------------------------------------
# Reads — candidates, preview, runs, projection status
# ---------------------------------------------------------------------------


def test_candidates_is_a_read_and_groups_the_variants() -> None:
    res = _request("GET", "/api/artists/merge/candidates")

    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    group = body["candidates"][0]
    assert sorted(v["name"] for v in group["variants"]) == sorted(GROUP)


def test_preview_writes_nothing(library) -> None:
    res = _request("POST", "/api/artists/merge/preview", json=_apply_body())

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["canonical"] == CANONICAL
    assert body["tracks_to_rewrite"] == 2
    assert sorted(v["name"] for v in body["absorbing"]) == sorted(VARIANTS)
    # Pure: no master.db write, no undo-log run, no sidecar row, no job.
    assert library.update_content_calls == []
    assert fixer_log.list_runs() == []
    assert artist_schema.list_collections() == []
    assert main._artist_jobs == {}


def test_preview_rejects_an_empty_group() -> None:
    res = _request("POST", "/api/artists/merge/preview", json={"names": ["  "]})

    assert res.status_code == 400


def test_preview_needs_a_loaded_library(monkeypatch) -> None:
    monkeypatch.setattr(main, "db", _Facade(_rows(), loaded=False))

    assert _request("POST", "/api/artists/merge/preview", json=_apply_body()).status_code == 400


def test_projection_status_is_a_read_without_auth() -> None:
    res = _request("GET", "/api/artists/projection/status")

    assert res.status_code == 200
    body = res.json()
    assert body["folder_name"] == "Artists"
    assert body["favourites"] == 0
    assert body["playlist_xml"] == XML_PATH


# ---------------------------------------------------------------------------
# apply — job id, job status, single-flight, Rekordbox guard
# ---------------------------------------------------------------------------


def test_apply_returns_a_job_id_the_status_endpoint_reports(auth_token, library, tags) -> None:
    res = _request("POST", "/api/artists/merge/apply", json=_apply_body(), headers=auth_token)

    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["total"] == 2
    assert data["canonical"] == CANONICAL

    job = _job(data["job_id"])
    assert job["kind"] == main.ARTIST_JOB_MERGE_APPLY
    assert job["status"] == "done"
    assert (job["total"], job["done"], job["percent"]) == (2, 2, 100.0)
    assert job["cancel_requested"] is False
    assert job["error"] is None

    result = job["result"]
    assert result["tracks_rewritten"] == 2
    assert result["revertable"] is True
    assert result["aborted"] is False
    # The two absorbed tracks now point at the canonical artist row; the third was
    # already canonical and is not read at all.
    canonical_id = library.get_artist_by_name(CANONICAL).id
    assert [library.artist_id_of(cid) for cid in ("t1", "t2")] == [canonical_id, canonical_id]
    assert sorted(path for path, _ in tags) == ["C:/music/t1.aiff", "C:/music/t2.aiff"]


def test_unknown_job_id_is_404() -> None:
    assert _request("GET", "/api/artists/jobs/nope").status_code == 404


def test_second_apply_while_one_runs_gets_409(auth_token, library) -> None:
    """Single-flight: the in-flight job holds ``_artist_job_lock`` for its whole run."""
    assert _LOOP is not None
    _LOOP.run_until_complete(main._artist_job_lock.acquire())

    res = _request("POST", "/api/artists/merge/apply", json=_apply_body(), headers=auth_token)

    assert res.status_code == 409
    assert "already running" in res.json()["detail"]
    assert main._artist_jobs == {}
    assert library.update_content_calls == []


def test_apply_409_when_rekordbox_is_running(auth_token, library, monkeypatch) -> None:
    monkeypatch.setattr(main, "_is_rekordbox_running", lambda: True)

    res = _request("POST", "/api/artists/merge/apply", json=_apply_body(), headers=auth_token)

    assert res.status_code == 409
    assert "Rekordbox is running" in res.json()["detail"]
    assert main._artist_jobs == {}
    assert library.update_content_calls == []
    assert fixer_log.list_runs() == []


def test_apply_rejects_a_group_with_nothing_to_absorb(auth_token, library) -> None:
    body = {"names": [CANONICAL], "canonical": CANONICAL}

    res = _request("POST", "/api/artists/merge/apply", json=body, headers=auth_token)

    assert res.status_code == 400
    assert library.update_content_calls == []


# ---------------------------------------------------------------------------
# revert + runs
# ---------------------------------------------------------------------------


def test_revert_unknown_run_is_404(auth_token) -> None:
    res = _request("POST", "/api/artists/merge/revert/no-such-run", headers=auth_token)

    assert res.status_code == 404


def test_revert_refuses_a_metadata_fixer_run(auth_token, library) -> None:
    """The undo log is shared — replaying a fixer run here would restore another field."""
    run_id = fixer_log.create_run([1], note="")

    res = _request("POST", f"/api/artists/merge/revert/{run_id}", headers=auth_token)

    assert res.status_code == 400
    assert library.update_content_calls == []


def test_apply_then_revert_restores_the_artist_link(auth_token, library) -> None:
    before = {cid: library.artist_id_of(cid) for cid in ("t1", "t2")}
    applied = _request(
        "POST", "/api/artists/merge/apply", json=_apply_body(), headers=auth_token
    ).json()["data"]
    run_id = _job(applied["job_id"])["result"]["run_id"]

    res = _request("POST", f"/api/artists/merge/revert/{run_id}", headers=auth_token)

    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["run_id"] == run_id
    assert data["total"] == 2

    job = _job(data["job_id"])
    assert job["kind"] == main.ARTIST_JOB_MERGE_REVERT
    assert job["status"] == "done"
    assert job["result"]["tracks_restored"] == 2
    assert job["result"]["complete"] is True
    assert {cid: library.artist_id_of(cid) for cid in ("t1", "t2")} == before


def test_runs_lists_merge_runs_only(auth_token) -> None:
    fixer_log.create_run([7], note="")  # a metadata-fixer run in the same log
    _request("POST", "/api/artists/merge/apply", json=_apply_body(), headers=auth_token)

    res = _request("GET", "/api/artists/merge/runs")

    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    run = body["runs"][0]
    assert run["note"]["kind"] == merge.MERGE_RUN_KIND
    assert run["note"]["canonical"] == CANONICAL
    assert sorted(run["note"]["absorbing"]) == sorted(VARIANTS)


# ---------------------------------------------------------------------------
# projection sync
# ---------------------------------------------------------------------------


def test_projection_sync_returns_a_job_id(auth_token) -> None:
    res = _request(
        "POST", "/api/artists/projection/sync", json={"dry_run": False}, headers=auth_token
    )

    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["dry_run"] is False

    job = _job(data["job_id"])
    assert job["kind"] == main.ARTIST_JOB_PROJECTION_SYNC
    assert job["status"] == "done"
    assert job["result"]["folder_name"] == "Artists"
    assert job["result"]["artists"] == 0


def test_projection_sync_409_when_rekordbox_is_running(auth_token, monkeypatch) -> None:
    monkeypatch.setattr(main, "_is_rekordbox_running", lambda: True)

    res = _request(
        "POST", "/api/artists/projection/sync", json={"dry_run": False}, headers=auth_token
    )

    assert res.status_code == 409
    assert "Rekordbox is running" in res.json()["detail"]
    assert main._artist_jobs == {}


def test_projection_dry_run_is_allowed_while_rekordbox_runs(auth_token, monkeypatch) -> None:
    """A dry run writes nothing at all, so the process guard does not apply to it."""
    monkeypatch.setattr(main, "_is_rekordbox_running", lambda: True)

    res = _request(
        "POST", "/api/artists/projection/sync", json={"dry_run": True}, headers=auth_token
    )

    assert res.status_code == 200, res.text
    job = _job(res.json()["data"]["job_id"])
    assert job["status"] == "done"
    assert job["result"]["dry_run"] is True


def test_projection_sync_400_without_the_playlist_xml(auth_token, monkeypatch) -> None:
    """rbox drops the masterPlaylists6.xml update when the file is not beside master.db."""
    monkeypatch.setattr(main, "db", _Facade(_rows(), xml_path=None))

    res = _request(
        "POST", "/api/artists/projection/sync", json={"dry_run": False}, headers=auth_token
    )

    assert res.status_code == 400
    assert "masterPlaylists6.xml" in res.json()["detail"]
    assert main._artist_jobs == {}


def test_second_projection_sync_while_one_runs_gets_409(auth_token) -> None:
    assert _LOOP is not None
    _LOOP.run_until_complete(main._artist_job_lock.acquire())

    res = _request(
        "POST", "/api/artists/projection/sync", json={"dry_run": True}, headers=auth_token
    )

    assert res.status_code == 409
