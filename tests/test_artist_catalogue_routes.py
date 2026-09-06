"""Artist-Hub SoundCloud route tests — binding, catalogue, batch download (T-13/T-15).

Six contracts, all of them things this feature has previously got wrong:

* every **mutation** is behind ``Depends(require_session)`` (threat T3), and a rejected
  call writes no link row.
* an artist with no SoundCloud binding gets a **typed** ``not_linked`` payload that
  carries no bucket keys at all — an empty ``definitely_theirs`` would render as "this
  artist has released nothing", which is a claim about data nobody fetched.
* no token, no cache ⇒ ``not_connected``, again with no bucket keys. Never an empty
  success, never a fabricated count.
* ``download-missing`` hands back a job id and refuses a second concurrent run with 409.
* the per-run cap (``ARTIST_DOWNLOAD_MAX_TRACKS``) is refused, not silently trimmed.
* the auto-queue path may only pick ``definitely_theirs``; a remix uploaded by another
  account has to be named explicitly (threat T11). And no queued download inherits
  ``sc_aggressive_mode`` (ToU guardrail).

**No network, no real credentials, no real library.** ``sc_api.get_user_tracks`` /
``resolve_user`` and ``sc_downloader.download_track`` are replaced per test; an autouse
fixture pins ``keyring.get_password`` to ``None`` so a test that forgets to opt in reads
"signed out" instead of the developer's real OAuth token. The sidecar is a throwaway file
in a tmp dir and the ``db`` facade is a stub, exactly as in ``tests/test_artist_routes.py``.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

import httpx
import pytest

from app import auth, main
from app import soundcloud_api as sc_api
from app.artist_store import registry, schema
from app.main import app

ARTIST_URN = "soundcloud:users:4242"
OTHER_URN = "soundcloud:users:9999"
ARTIST_NAME = "Boys Noize"
FAKE_TOKEN = "not-a-real-oauth-token-only-lives-in-this-process"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def _sc_track(
    number: int,
    title: str,
    *,
    uploader_urn: str = ARTIST_URN,
    uploader_name: str = ARTIST_NAME,
    **over: Any,
) -> dict[str, Any]:
    """One track in the shape ``soundcloud_api.get_user_tracks`` returns."""
    return {
        "sc_id": f"soundcloud:tracks:{number}",
        "title": title,
        "permalink_url": f"https://soundcloud.com/{uploader_name}/{number}",
        "duration_ms": 300_000,
        "uploader_urn": uploader_urn,
        "uploader_name": uploader_name,
        "genre": "techno",
        "tag_list": "",
        "access": "playable",
        "streamable": True,
        "sharing": "public",
        "downloadable": True,
        "created_at": "2026-01-01T00:00:00Z",
        "artwork_url": "",
        **over,
    }


OWN_TRACK = _sc_track(101, "Overdrive")
OWN_TRACK_2 = _sc_track(102, "Kill The Beat")
REMIX_TRACK = _sc_track(
    201,
    "Someone Else — Track (Boys Noize Remix)",
    uploader_urn=OTHER_URN,
    uploader_name="Someone Else",
)
CATALOGUE = [OWN_TRACK, OWN_TRACK_2, REMIX_TRACK]


class _LibraryDB:
    """Stand-in for the ``db`` facade: ``loaded``, ``artists`` and ``tracks``."""

    def __init__(self, tracks: dict[str, dict[str, Any]] | None = None, loaded: bool = True):
        self.loaded = loaded
        self.artists = [{"id": "art_0", "name": ARTIST_NAME, "track_count": 3, "Artwork": ""}]
        self.tracks = tracks or {}


_WIPE = (
    "DELETE FROM favourites; DELETE FROM catalogue_cache; DELETE FROM projection; "
    "DELETE FROM sync_state; DELETE FROM links; DELETE FROM aliases; "
    "DELETE FROM collections; "
    "DELETE FROM store_meta WHERE key = 'legacy_sc_links_migrated';"
)


def _close_thread_conn() -> None:
    conn = getattr(schema._local, "conn", None)
    if conn is not None:
        conn.close()
        del schema._local.conn


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", autouse=True)
def _store_file(tmp_path_factory):
    """One throwaway ``artists.db`` for the module — see ``tests/test_artist_routes.py``."""
    mp = pytest.MonkeyPatch()
    db_file = tmp_path_factory.mktemp("artist_catalogue_routes") / "artists.db"
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
    main._artist_jobs.clear()
    yield


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """No library, no keyring, no SoundCloud, no downloader — every escape hatch closed.

    ``keyring.get_password`` defaults to ``None`` on purpose: a test that forgets to opt
    into a token must read "signed out", never the developer's real OAuth token.
    """
    monkeypatch.setattr(main, "db", _LibraryDB())
    monkeypatch.setattr(auth, "paired_token_valid", lambda _token: False)
    monkeypatch.setattr(main.keyring, "get_password", lambda _service, _user: None)

    def _no_fetch(*_a: Any, **_kw: Any):
        raise AssertionError("a test made a real SoundCloud call")

    monkeypatch.setattr(main.sc_api, "get_user_tracks", _no_fetch)
    monkeypatch.setattr(main.sc_api, "get_user_reposts", _no_fetch)
    monkeypatch.setattr(main.sc_api, "resolve_user", _no_fetch)
    monkeypatch.setattr(main.sc_downloader, "download_track", _no_fetch)


@pytest.fixture
def signed_in(monkeypatch):
    monkeypatch.setattr(main.keyring, "get_password", lambda _service, _user: FAKE_TOKEN)


@pytest.fixture
def collection_id() -> str:
    return schema.create_collection(ARTIST_NAME, schema.KIND_ARTIST)


@pytest.fixture
def linked(collection_id: str) -> str:
    schema.set_link(
        collection_id, registry.PROVIDER_SOUNDCLOUD, ARTIST_URN, "https://soundcloud.com/bnr", 1.0
    )
    return collection_id


@pytest.fixture
def fetched(monkeypatch, linked: str, signed_in) -> str:
    """A linked artist whose catalogue is already in the TTL cache."""
    monkeypatch.setattr(
        main.sc_api,
        "get_user_tracks",
        lambda _urn, _token, **_kw: sc_api.SCResultList(list(CATALOGUE)),
    )
    # The route fetches own uploads AND reposts — the remixes bucket can only ever be
    # filled from the second path, so a fixture that stubs only the first would make
    # "no remixes missing" look true when it was simply never queried.
    monkeypatch.setattr(
        main.sc_api, "get_user_reposts", lambda _urn, _token, **_kw: sc_api.SCResultList([])
    )
    res = _request("GET", f"/api/artists/{linked}/catalogue")
    assert res.json()["status"] == "ok"
    return linked


@pytest.fixture
def downloads(monkeypatch) -> list[dict[str, Any]]:
    """Record every ``download_track`` call and complete it immediately."""
    calls: list[dict[str, Any]] = []

    def _stub(**kwargs: Any) -> str:
        calls.append(kwargs)
        task_id = f"task-{len(calls)}"
        callback = kwargs.get("on_complete")
        if callback is not None:
            callback(task_id, True, None)
        return task_id

    monkeypatch.setattr(main.sc_downloader, "download_track", _stub)
    return calls


_BUCKET_KEYS = {"definitely_theirs", "remixes_by_others", "mixes_and_sets"}


def _assert_no_buckets(body: dict[str, Any]) -> None:
    """A non-catalogue answer must not carry a bucket key, empty or otherwise."""
    assert _BUCKET_KEYS.isdisjoint(body), f"typed state leaked bucket keys: {sorted(body)}"
    assert body["detail"]


# ---------------------------------------------------------------------------
# Auth — threat T3
# ---------------------------------------------------------------------------

_MUTATIONS = [
    ("POST", "/api/artists/{cid}/link", {"url_or_permalink": "https://soundcloud.com/bnr"}),
    ("DELETE", "/api/artists/{cid}/link", None),
    ("POST", "/api/artists/{cid}/download-missing", {"auto_queue": True}),
    ("POST", "/api/artist/soundcloud", {"artist_name": ARTIST_NAME, "link": "bnr"}),
]


@pytest.mark.parametrize(("method", "url", "body"), _MUTATIONS)
def test_mutations_require_session(method, url, body, collection_id) -> None:
    assert _request(method, url.format(cid=collection_id), json=body).status_code == 401


@pytest.mark.parametrize(("method", "url", "body"), _MUTATIONS)
def test_mutations_reject_wrong_bearer(method, url, body, collection_id) -> None:
    headers = {"Authorization": "Bearer not-the-session-token"}
    res = _request(method, url.format(cid=collection_id), json=body, headers=headers)
    assert res.status_code == 401


def test_rejected_mutation_writes_no_link(collection_id, auth_token) -> None:
    for method, url, body in _MUTATIONS:
        _request(method, url.format(cid=collection_id), json=body)

    assert schema.get_link(collection_id, registry.PROVIDER_SOUNDCLOUD) is None


def test_catalogue_read_needs_no_session(linked: str) -> None:
    assert _request("GET", f"/api/artists/{linked}/catalogue").status_code == 200


# ---------------------------------------------------------------------------
# GET catalogue — the typed states
# ---------------------------------------------------------------------------


def test_unlinked_artist_returns_typed_not_linked(collection_id: str) -> None:
    body = _request("GET", f"/api/artists/{collection_id}/catalogue").json()

    assert body["status"] == "not_linked"
    assert body["collection_id"] == collection_id
    _assert_no_buckets(body)


def test_unknown_collection_is_404() -> None:
    assert _request("GET", "/api/artists/a_deadbeef/catalogue").status_code == 404


def test_missing_credentials_return_not_connected(linked: str) -> None:
    """No token and nothing cached — say so, never hand back an empty catalogue."""
    body = _request("GET", f"/api/artists/{linked}/catalogue").json()

    assert body["status"] == "not_connected"
    assert "not connected" in body["detail"].lower()
    _assert_no_buckets(body)


def test_expired_session_returns_not_connected(monkeypatch, linked: str, signed_in) -> None:
    def _expired(*_a: Any, **_kw: Any):
        raise sc_api.AuthExpiredError("token rejected")

    monkeypatch.setattr(main.sc_api, "get_user_tracks", _expired)
    body = _request("GET", f"/api/artists/{linked}/catalogue").json()

    assert body["status"] == "not_connected"
    _assert_no_buckets(body)


def test_deleted_soundcloud_account_returns_artist_gone(
    monkeypatch, linked: str, signed_in
) -> None:
    """A dead artist 404s legitimately — that is not a "please log in again"."""

    def _gone(*_a: Any, **_kw: Any):
        raise sc_api.NotFoundError("gone")

    monkeypatch.setattr(main.sc_api, "get_user_tracks", _gone)
    body = _request("GET", f"/api/artists/{linked}/catalogue").json()

    assert body["status"] == "artist_gone"
    _assert_no_buckets(body)


def test_catalogue_splits_into_buckets_and_reports_the_budget(fetched: str) -> None:
    body = _request("GET", f"/api/artists/{fetched}/catalogue").json()

    assert body["status"] == "ok"
    assert [t["sc_id"] for t in body["definitely_theirs"]] == [
        OWN_TRACK["sc_id"],
        OWN_TRACK_2["sc_id"],
    ]
    assert [t["sc_id"] for t in body["remixes_by_others"]] == [REMIX_TRACK["sc_id"]]
    assert body["from_cache"] is True  # the fixture already warmed it
    assert body["call_budget"] == main.ARTIST_CATALOGUE_CALL_BUDGET
    assert body["calls_used"] == 0


def test_catalogue_fetch_carries_a_call_budget(monkeypatch, linked: str, signed_in) -> None:
    seen: dict[str, Any] = {}

    def _fetch(urn: str, token: str, **kwargs: Any):
        seen["urn"] = urn
        seen["budget"] = kwargs.get("budget")
        return sc_api.SCResultList(list(CATALOGUE))

    monkeypatch.setattr(main.sc_api, "get_user_tracks", _fetch)
    body = _request("GET", f"/api/artists/{linked}/catalogue").json()

    assert seen["urn"] == ARTIST_URN
    assert isinstance(seen["budget"], sc_api.CallBudget)
    assert seen["budget"].limit == main.ARTIST_CATALOGUE_CALL_BUDGET
    assert body["from_cache"] is False


def test_truncated_fetch_is_reported_not_hidden(monkeypatch, linked: str, signed_in) -> None:
    monkeypatch.setattr(
        main.sc_api,
        "get_user_tracks",
        lambda *_a, **_kw: sc_api.SCResultList(
            list(CATALOGUE), truncated=True, stop_reason="budget"
        ),
    )
    body = _request("GET", f"/api/artists/{linked}/catalogue").json()

    assert body["truncated"] is True


# ---------------------------------------------------------------------------
# Binding
# ---------------------------------------------------------------------------


def test_link_stores_urn_permalink_and_confidence(
    monkeypatch, collection_id: str, signed_in, auth_token
) -> None:
    monkeypatch.setattr(
        main.sc_api,
        "resolve_user",
        lambda *_a, **_kw: {
            "urn": ARTIST_URN,
            "username": ARTIST_NAME,
            "permalink_url": "https://soundcloud.com/boysnoize",
            "track_count": 3,
            "followers_count": 1,
            "avatar_url": "",
        },
    )
    res = _request(
        "POST",
        f"/api/artists/{collection_id}/link",
        json={"url_or_permalink": "https://soundcloud.com/boysnoize"},
        headers=auth_token,
    )

    assert res.status_code == 200
    stored = schema.get_link(collection_id, registry.PROVIDER_SOUNDCLOUD)
    assert stored["remote_id"] == ARTIST_URN
    assert stored["permalink"] == "https://soundcloud.com/boysnoize"
    assert stored["confidence"] == pytest.approx(1.0)  # exact name match


def test_link_without_a_token_is_refused(collection_id: str, auth_token) -> None:
    res = _request(
        "POST",
        f"/api/artists/{collection_id}/link",
        json={"url_or_permalink": "bnr"},
        headers=auth_token,
    )

    assert res.status_code == 400
    assert "not connected" in res.json()["detail"].lower()
    assert schema.get_link(collection_id, registry.PROVIDER_SOUNDCLOUD) is None


def test_link_refuses_an_unresolvable_profile(
    monkeypatch, collection_id: str, signed_in, auth_token
) -> None:
    monkeypatch.setattr(main.sc_api, "resolve_user", lambda *_a, **_kw: None)
    res = _request(
        "POST",
        f"/api/artists/{collection_id}/link",
        json={"url_or_permalink": "https://soundcloud.com/ghost"},
        headers=auth_token,
    )

    assert res.status_code == 404
    assert schema.get_link(collection_id, registry.PROVIDER_SOUNDCLOUD) is None


def test_unlink_removes_the_binding(linked: str, auth_token) -> None:
    res = _request("DELETE", f"/api/artists/{linked}/link", headers=auth_token)

    assert res.status_code == 200
    assert res.json()["removed"] is True
    assert schema.get_link(linked, registry.PROVIDER_SOUNDCLOUD) is None
    assert schema.get_collection(linked) is not None  # collection survives


def test_legacy_json_links_migrate_once_and_stay_unresolved(monkeypatch) -> None:
    """``app_data.json`` held a URL but no URN — import it, flag it, never claim it works."""
    from app import sidecar

    monkeypatch.setattr(
        sidecar.storage, "data", {"artists": {ARTIST_NAME: {"soundcloud": "sc.com/bnr"}}}
    )
    cid = schema.collection_id_for(ARTIST_NAME, schema.KIND_ARTIST)

    body = _request("GET", f"/api/artists/{cid}/catalogue").json()

    assert body["status"] == "link_unresolved"
    assert body["permalink"] == "sc.com/bnr"
    _assert_no_buckets(body)
    assert registry.migrate_legacy_artist_links()["already_done"] is True


# ---------------------------------------------------------------------------
# Batch download
# ---------------------------------------------------------------------------


def test_download_missing_returns_a_job_id(fetched: str, downloads, auth_token) -> None:
    res = _request(
        "POST",
        f"/api/artists/{fetched}/download-missing",
        json={"auto_queue": True},
        headers=auth_token,
    )

    assert res.status_code == 200
    data = res.json()["data"]
    assert data["total"] == 2
    status = _request("GET", f"/api/artists/download/status?job_id={data['job_id']}")
    assert status.status_code == 200
    job = status.json()["data"]
    assert job["status"] == "done"
    assert job["succeeded"] == 2
    assert job["percent"] == 100.0


def test_download_status_404s_on_an_unknown_job() -> None:
    assert _request("GET", "/api/artists/download/status?job_id=nope").status_code == 404


def test_batch_never_inherits_aggressive_mode(fetched: str, downloads, auth_token) -> None:
    _request(
        "POST",
        f"/api/artists/{fetched}/download-missing",
        json={"auto_queue": True},
        headers=auth_token,
    )

    assert downloads
    assert all(call["allow_aggressive"] is False for call in downloads)


def test_auto_queue_takes_only_definitely_theirs(fetched: str, downloads, auth_token) -> None:
    """The server may not queue a foreign uploader's remix on the user's behalf (T11)."""
    _request(
        "POST",
        f"/api/artists/{fetched}/download-missing",
        json={"auto_queue": True},
        headers=auth_token,
    )

    assert [call["sc_track_id"] for call in downloads] == ["101", "102"]


def test_a_remix_must_be_requested_explicitly(fetched: str, downloads, auth_token) -> None:
    res = _request(
        "POST",
        f"/api/artists/{fetched}/download-missing",
        json={"sc_ids": [REMIX_TRACK["sc_id"]]},
        headers=auth_token,
    )

    assert res.status_code == 200
    assert res.json()["data"]["total"] == 1
    assert [call["sc_track_id"] for call in downloads] == ["201"]


def test_auto_queue_and_explicit_ids_are_mutually_exclusive(
    fetched: str, downloads, auth_token
) -> None:
    res = _request(
        "POST",
        f"/api/artists/{fetched}/download-missing",
        json={"auto_queue": True, "sc_ids": [OWN_TRACK["sc_id"]]},
        headers=auth_token,
    )

    assert res.status_code == 400
    assert downloads == []


def test_unknown_track_ids_are_refused_not_skipped(fetched: str, downloads, auth_token) -> None:
    res = _request(
        "POST",
        f"/api/artists/{fetched}/download-missing",
        json={"sc_ids": ["soundcloud:tracks:999999"]},
        headers=auth_token,
    )

    assert res.status_code == 400
    assert downloads == []


def test_download_without_a_fetched_catalogue_is_409(linked: str, downloads, auth_token) -> None:
    """The job reads the cache only — it must never open its own SoundCloud session."""
    res = _request(
        "POST",
        f"/api/artists/{linked}/download-missing",
        json={"auto_queue": True},
        headers=auth_token,
    )

    assert res.status_code == 409
    assert downloads == []


def test_download_for_an_unlinked_artist_is_409(collection_id: str, downloads, auth_token) -> None:
    res = _request(
        "POST",
        f"/api/artists/{collection_id}/download-missing",
        json={"auto_queue": True},
        headers=auth_token,
    )

    assert res.status_code == 409
    assert downloads == []


def test_per_run_cap_is_refused_not_trimmed(
    monkeypatch, linked: str, signed_in, downloads, auth_token
) -> None:
    over_cap = main.ARTIST_DOWNLOAD_MAX_TRACKS + 1
    big = [_sc_track(1000 + i, f"Track {i}") for i in range(over_cap)]
    monkeypatch.setattr(main.sc_api, "get_user_tracks", lambda *_a, **_kw: sc_api.SCResultList(big))
    assert _request("GET", f"/api/artists/{linked}/catalogue").json()["status"] == "ok"

    res = _request(
        "POST",
        f"/api/artists/{linked}/download-missing",
        json={"auto_queue": True},
        headers=auth_token,
    )

    assert res.status_code == 400
    assert str(main.ARTIST_DOWNLOAD_MAX_TRACKS) in res.json()["detail"]
    assert downloads == []


def test_second_concurrent_run_is_409(monkeypatch, fetched: str, auth_token) -> None:
    """A real second start while the first job is mid-flight, not a simulated lock."""
    gate = threading.Event()
    calls: list[dict[str, Any]] = []

    def _stub(**kwargs: Any) -> str:
        calls.append(kwargs)

        def _finish() -> None:
            gate.wait(10)
            kwargs["on_complete"](f"task-{len(calls)}", True, None)

        threading.Thread(target=_finish, daemon=True).start()
        return f"task-{len(calls)}"

    monkeypatch.setattr(main.sc_downloader, "download_track", _stub)
    url = f"/api/artists/{fetched}/download-missing"

    async def _go() -> tuple[httpx.Response, httpx.Response]:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            first = asyncio.create_task(ac.post(url, json={"auto_queue": True}, headers=auth_token))
            for _ in range(100):  # let the first request acquire the single-flight lock
                await asyncio.sleep(0.02)
                if calls:
                    break
            second = await ac.post(url, json={"auto_queue": True}, headers=auth_token)
            gate.set()
            return await first, second

    first_res, second_res = asyncio.run(_go())

    assert first_res.status_code == 200
    assert second_res.status_code == 409
    assert "already running" in second_res.json()["detail"]


def test_lock_is_released_so_the_next_run_starts(fetched: str, downloads, auth_token) -> None:
    url = f"/api/artists/{fetched}/download-missing"
    first = _request("POST", url, json={"auto_queue": True}, headers=auth_token)
    second = _request("POST", url, json={"auto_queue": True}, headers=auth_token)

    assert first.status_code == 200
    assert second.status_code == 200
    assert main._artist_download_lock.locked() is False


# ---------------------------------------------------------------------------
# ToU guardrail: aggressive_mode stops at the downloader boundary
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.status_code = 200
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


@pytest.fixture
def snipped_only_track(monkeypatch):
    """A track SoundCloud exposes to this account as a 30 s preview only.

    Plus `sc_aggressive_mode = true`, i.e. the hidden per-track opt-in is ON. All HTTP is
    replaced; nothing here reaches SoundCloud.
    """
    from app import services, soundcloud_api
    from app import soundcloud_downloader as sc_dl

    metadata = {
        "media": {
            "transcodings": [
                {
                    "snipped": True,
                    "quality": "sq",
                    "url": "https://api-v2.soundcloud.com/media/x/stream/progressive",
                    "format": {"protocol": "progressive", "mime_type": "audio/mpeg"},
                }
            ]
        },
        "track_authorization": "ta",
    }

    def _fake_get(url: str, **_kw: Any) -> _FakeResponse:
        if "/media/" in url:
            return _FakeResponse({"url": "https://cf-media.sndcdn.com/signed.mp3"})
        return _FakeResponse(metadata)

    monkeypatch.setattr(sc_dl.requests, "get", _fake_get)
    monkeypatch.setattr(soundcloud_api, "get_sc_client_id", lambda: "test-client-id")
    monkeypatch.setattr(
        services.SettingsManager, "load", staticmethod(lambda: {"sc_aggressive_mode": True})
    )
    return sc_dl


def test_aggressive_mode_still_applies_to_a_hand_picked_track(snipped_only_track) -> None:
    """Control case: with the opt-in on, the single-track path does accept the preview."""
    source = snipped_only_track._resolve_stream_via_transcodings("101", None)

    assert source is not None


def test_batch_path_refuses_the_preview_aggressive_mode_would_accept(snipped_only_track) -> None:
    """`allow_aggressive=False` makes the setting unreachable — a batch never inherits it."""
    source = snipped_only_track._resolve_stream_via_transcodings(
        "101", None, allow_aggressive=False
    )

    assert source is None


class TestRepostsPathIsQueriedAndReported:
    """Regression: only own uploads were fetched, so remixes_by_others could never fill.

    ``/users/{urn}/tracks`` is own-uploads-only. With nothing else fetched, every row
    satisfied ``uploader_urn == artist_urn`` and the remixes bucket was structurally
    empty — while the UI still printed "No remix by another uploader is missing from
    your library", a positive claim about data nobody had asked SoundCloud for.
    """

    def test_the_route_actually_queries_reposts(self, monkeypatch, linked, signed_in) -> None:
        calls: list[str] = []

        def _own(_urn, _token, **_kw):
            calls.append("tracks")
            return sc_api.SCResultList(list(CATALOGUE))

        def _reposts(_urn, _token, **_kw):
            calls.append("reposts")
            return sc_api.SCResultList([])

        monkeypatch.setattr(main.sc_api, "get_user_tracks", _own)
        monkeypatch.setattr(main.sc_api, "get_user_reposts", _reposts)

        body = _request("GET", f"/api/artists/{linked}/catalogue").json()

        assert calls == ["tracks", "reposts"]
        assert body["reposts_status"] == "ok"

    def test_a_reposts_failure_does_not_sink_the_catalogue(
        self, monkeypatch, linked, signed_in
    ) -> None:
        """Own uploads are the half that matters — a reposts error must degrade, not fail."""

        def _boom(_urn, _token, **_kw):
            raise RuntimeError("reposts endpoint exploded")

        monkeypatch.setattr(
            main.sc_api,
            "get_user_tracks",
            lambda _urn, _token, **_kw: sc_api.SCResultList(list(CATALOGUE)),
        )
        monkeypatch.setattr(main.sc_api, "get_user_reposts", _boom)

        body = _request("GET", f"/api/artists/{linked}/catalogue").json()

        assert body["status"] == "ok"
        assert body["reposts_status"] == "failed"
        assert body["definitely_theirs"], "own uploads must still be reported"

    def test_a_cached_read_does_not_claim_the_reposts_half(self, fetched) -> None:
        """A cache hit fetched nothing, so it may not assert anything about reposts."""
        body = _request("GET", f"/api/artists/{fetched}/catalogue").json()

        assert body["from_cache"] is True
        assert body["reposts_status"] == "not_queried"
