"""Artist-Hub local-attribution routes (T-24 — app/main.py, route half of plan rows T30/T31).

The contracts under test:

* the one write (``POST …/local-tracks/{track_id}``) is behind ``Depends(require_session)``
  (threat T3), and a rejected call stores no collection and no assignment.
* the two reads stay plain reads — and ``GET …/local-tracks`` answers for an id the hub
  derived from a library spelling that nothing has stored yet. A read never stores it.
* every engine refusal surfaces as its HTTP meaning, told apart by ``detail``: unknown
  artist and unknown track are both 404 but never the same sentence, no library is 409,
  a role nobody may assign is 400. Never a 500, never a silent success.
* no loaded library is said out loud (``library_loaded: false``), never "has no tracks" —
  and the routes hand the engine ``None`` then, not the half-empty library object.
* the literal ``candidates`` path is not swallowed by the ``{track_id}`` parameter.

Library: a real ``LiveRekordboxDB`` against a path that does not exist, ``.tracks`` filled
by hand, the real ``_finalize_ui_metadata`` and splitter — the fixture of
``tests/test_artist_attribution.py`` — swapped in for ``app.main.db`` the way the other
route tests swap their stubs in. The sidecar is a throwaway file in a tmp dir.
"""

from __future__ import annotations

import asyncio
import typing
from collections.abc import Callable
from typing import Any

import httpx
import pytest
import requests

pytest.importorskip("rbox", reason="pyrekordbox not installed on this platform")

from app import auth, main
from app.artist_store import attribution, registry, schema
from app.live_database import LiveRekordboxDB
from app.main import app

BOYS = "Boys Noize"

#: Ids are assigned in order, starting at "1".
LIBRARY: tuple[dict[str, Any], ...] = (
    {"Title": "Overdrive", "Artist": BOYS},  # 1 — the Artist field names them: primary
    {"Title": "Sirens (Boys Noize Remix)", "Artist": "Charli XCX"},  # 2 — title credit
    {"Title": "White Label Tool", "Artist": "Unknown Artist"},  # 3 — nobody's; assign target
    {"Title": "Over and Over", "Artist": "Somebody"},  # 4 — a search hit that is not theirs
)

LibraryFactory = Callable[..., LiveRekordboxDB]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _request(
    method: str,
    url: str,
    *,
    json: Any = None,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
) -> httpx.Response:
    async def _go() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            return await ac.request(method, url, json=json, headers=headers, params=params)

    return asyncio.run(_go())


def _cid(name: str = BOYS) -> str:
    """The id the hub and browse hand out for a library spelling — stored or not."""
    return schema.collection_id_for(name)


def _page(cid: str) -> httpx.Response:
    return _request("GET", f"/api/artists/{cid}/local-tracks")


def _candidates(cid: str, **params: Any) -> httpx.Response:
    return _request("GET", f"/api/artists/{cid}/local-tracks/candidates", params=params)


def _write(
    cid: str, track: str, headers: dict[str, str] | None = None, **body: Any
) -> httpx.Response:
    return _request("POST", f"/api/artists/{cid}/local-tracks/{track}", json=body, headers=headers)


def _roles(body: dict[str, Any]) -> dict[str, tuple[str, str, str]]:
    return {
        t["ID"]: (
            t["artist_role"]["role"],
            t["artist_role"]["confidence"],
            t["artist_role"]["source"],
        )
        for t in body["tracks"]
    }


_WIPE = (
    "DELETE FROM track_assignments; DELETE FROM favourites; DELETE FROM links; "
    "DELETE FROM aliases; DELETE FROM collections;"
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
    db_file = tmp_path_factory.mktemp("artist_local_tracks_routes") / "artists.db"
    mp.setattr(schema, "_db_path", lambda: db_file)
    mp.setattr(schema, "_initialised", False)
    _close_thread_conn()
    schema.init_db()
    yield
    _close_thread_conn()
    mp.undo()


@pytest.fixture(autouse=True)
def _clean_store() -> None:
    conn = schema._ensure_schema()
    with schema._write_lock:
        conn.executescript(_WIPE)
        conn.commit()


@pytest.fixture(autouse=True)
def _sealed(monkeypatch: pytest.MonkeyPatch) -> None:
    """No user file, no network, no device-token lookup.

    The settings and name-mapping stubs are ``test_artist_attribution.py``'s: the real
    ones read the developer's own files and would reshape the library under test. The
    legacy ``app_data.json`` import is marked done so no route can reach that file either.
    """
    import app.services as services

    def _no_http(url: Any, *_a: Any, **_kw: Any) -> Any:
        raise AssertionError(f"a test made a real HTTP call: {url}")

    monkeypatch.setattr(services.SettingsManager, "load", staticmethod(lambda: {}))
    monkeypatch.setattr(
        services.MetadataManager,
        "get_mapped_name",
        classmethod(lambda cls, category, name: name),
    )
    monkeypatch.setattr(requests, "get", _no_http)
    monkeypatch.setattr(auth, "paired_token_valid", lambda _token: False)
    monkeypatch.setattr(registry, "_legacy_migration_done", True)


@pytest.fixture
def use_library(monkeypatch: pytest.MonkeyPatch) -> LibraryFactory:
    """Install a hand-filled library as ``app.main.db``; ``loaded=False`` keeps its tracks.

    Keeping the tracks on an unloaded library is the point: a route that handed the
    engine the object instead of ``None`` would find them and give itself away.
    """

    def _install(*rows: dict[str, Any], loaded: bool = True) -> LiveRekordboxDB:
        library = LiveRekordboxDB("does-not-exist.db")
        library.tracks = {}
        for i, row in enumerate(rows, start=1):
            track = {"ID": str(i), "Title": "", "Artist": "", "Remixer": "", **row}
            library.tracks[str(i)] = track
        library._finalize_ui_metadata()
        library.loaded = loaded
        monkeypatch.setattr(main, "db", library)
        return library

    return _install


@pytest.fixture(autouse=True)
def library(use_library: LibraryFactory) -> LiveRekordboxDB:
    return use_library(*LIBRARY)


@pytest.fixture
def unloaded(use_library: LibraryFactory) -> str:
    """A stored artist, and the same library with ``loaded`` false."""
    cid = schema.create_collection(BOYS)
    use_library(*LIBRARY, loaded=False)
    return cid


# ---------------------------------------------------------------------------
# Auth — threat T3
# ---------------------------------------------------------------------------

_WRITES = [
    {"action": "assign", "role": "remixer", "name": BOYS},
    {"action": "exclude", "name": BOYS},
    {"action": "clear"},
]
_WRITE_IDS = ["assign", "exclude", "clear"]


@pytest.mark.parametrize("body", _WRITES, ids=_WRITE_IDS)
def test_write_requires_session(body: dict[str, Any]) -> None:
    assert _write(_cid(), "3", **body).status_code == 401


@pytest.mark.parametrize("body", _WRITES, ids=_WRITE_IDS)
def test_write_rejects_wrong_bearer(body: dict[str, Any]) -> None:
    headers = {"Authorization": "Bearer not-the-session-token"}
    assert _write(_cid(), "3", headers, **body).status_code == 401


def test_rejected_writes_store_nothing() -> None:
    for body in _WRITES:
        _write(_cid(), "3", **body)
        _write(_cid(), "3", {"Authorization": "Bearer not-the-session-token"}, **body)

    assert schema.list_collections() == []
    assert schema.list_track_assignments(_cid()) == []


def test_the_reads_need_no_session() -> None:
    assert _page(_cid()).status_code == 200
    assert _candidates(_cid(), q="over").status_code == 200


# ---------------------------------------------------------------------------
# GET …/local-tracks
# ---------------------------------------------------------------------------


def test_a_derived_collection_lists_its_artist_field_and_remix_credits() -> None:
    """The hub hands out this id for a library spelling that nothing has stored yet."""
    cid = _cid()

    res = _page(cid)

    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["collection_id"] == cid
    assert body["name"] == BOYS
    assert body["stored"] is False
    assert body["library_loaded"] is True
    assert body["library_names"] == [BOYS]
    assert _roles(body) == {
        "1": ("primary", "high", "artist_field"),
        "2": ("remixer", "medium", "title_remix"),
    }
    assert body["counts"]["total"] == 2
    assert body["excluded"] == []
    assert body["assigned_missing"] == []
    assert schema.get_collection(cid) is None, "a read stored the collection"


def test_an_id_nobody_knows_is_404() -> None:
    res = _page(_cid("Nobody Anyone Knows"))

    assert res.status_code == 404
    assert "Unknown artist collection" in res.json()["detail"]


def test_without_a_loaded_library_a_stored_artist_says_so(unloaded: str) -> None:
    res = _page(unloaded)

    assert res.status_code == 200
    body = res.json()
    assert body["library_loaded"] is False
    assert body["tracks"] == []
    assert body["stored"] is True


# ---------------------------------------------------------------------------
# POST …/local-tracks/{track_id}
# ---------------------------------------------------------------------------


def test_assign_with_the_name_stores_the_artist_and_the_track_turns_manual(
    auth_token: dict[str, str],
) -> None:
    cid = _cid()

    res = _write(cid, "3", auth_token, action="assign", role="remixer", name=BOYS)

    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert (body["collection_id"], body["track_id"], body["action"]) == (cid, "3", "assign")
    assert body["track"]["artist_role"] == {
        "role": "remixer",
        "confidence": "high",
        "source": "manual",
        "detail": "Assigned by you",
    }
    assert body["counts"]["manual"] == 1
    assert schema.get_collection(cid) is not None

    page = _page(cid).json()
    assert page["stored"] is True
    assert _roles(page)["3"] == ("remixer", "high", "manual")


def test_assign_defaults_to_primary(auth_token: dict[str, str]) -> None:
    res = _write(_cid(), "3", auth_token, action="assign", name=BOYS)

    assert res.status_code == 200
    assert res.json()["track"]["artist_role"]["role"] == "primary"


@pytest.mark.parametrize("name", ["Somebody Else", None], ids=["wrong_name", "no_name"])
def test_an_unstored_artist_is_only_stored_under_the_name_that_derives_its_id(
    name: str | None, auth_token: dict[str, str]
) -> None:
    res = _write(_cid(), "3", auth_token, action="assign", name=name)

    assert res.status_code == 404
    detail = res.json()["detail"]
    assert "Unknown artist collection" in detail
    assert "track" not in detail.lower(), "an unknown artist was reported as an unknown track"
    assert schema.list_collections() == []


def test_a_track_the_library_does_not_hold_is_404(auth_token: dict[str, str]) -> None:
    res = _write(_cid(), "999", auth_token, action="assign", name=BOYS)

    assert res.status_code == 404
    assert res.json()["detail"] == "That track is not in the loaded library."
    assert schema.list_collections() == []


def test_clear_on_an_artist_nothing_stored_is_404(auth_token: dict[str, str]) -> None:
    res = _write(_cid(), "1", auth_token, action="clear")

    assert res.status_code == 404
    assert "Unknown artist collection" in res.json()["detail"]


@pytest.mark.parametrize("stray", [KeyError("rows"), LookupError("index"), IndexError(3)])
def test_a_stray_lookup_error_from_a_bug_is_a_500_not_a_404(
    stray: Exception, auth_token: dict[str, str], monkeypatch
) -> None:
    def broken(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise stray

    monkeypatch.setattr(attribution, "set_assignment", broken)

    assert _write(_cid(), "1", auth_token, action="assign", name=BOYS).status_code == 500


def test_exclude_takes_an_automatic_match_out_and_clear_hands_it_back(
    auth_token: dict[str, str],
) -> None:
    cid = _cid()

    excluded = _write(cid, "1", auth_token, action="exclude", name=BOYS)

    assert excluded.status_code == 200
    assert excluded.json()["track"] is None
    assert excluded.json()["excluded_count"] == 1
    page = _page(cid).json()
    assert "1" not in _roles(page)
    assert [(e["track_id"], e["would_be"]["role"]) for e in page["excluded"]] == [("1", "primary")]

    cleared = _write(cid, "1", auth_token, action="clear")

    assert cleared.status_code == 200
    assert cleared.json()["track"]["artist_role"]["source"] == "artist_field"
    page = _page(cid).json()
    assert _roles(page)["1"] == ("primary", "high", "artist_field")
    assert page["excluded"] == []


def test_a_role_nobody_may_assign_is_400(auth_token: dict[str, str]) -> None:
    """``uncertain`` is the classifier's review bucket — nobody assigns "not sure"."""
    res = _write(_cid(), "3", auth_token, action="assign", role="uncertain", name=BOYS)

    assert res.status_code == 400
    assert "uncertain" in res.json()["detail"]
    assert schema.list_collections() == []


def test_an_unknown_action_never_reaches_the_engine(auth_token: dict[str, str]) -> None:
    res = _write(_cid(), "3", auth_token, action="delete", name=BOYS)

    assert res.status_code == 422
    assert schema.list_collections() == []


@pytest.mark.parametrize(
    "body",
    [
        {"action": "assign", "role": "r" * 33, "name": BOYS},
        {"action": "assign", "name": "n" * 513},
    ],
    ids=["role", "name"],
)
def test_oversized_fields_are_refused_before_the_route(
    body: dict[str, Any], auth_token: dict[str, str]
) -> None:
    assert _write(_cid(), "3", auth_token, **body).status_code == 422
    assert schema.list_collections() == []


def test_the_action_vocabulary_is_the_engines() -> None:
    annotation = main.ArtistTrackAssignReq.model_fields["action"].annotation

    assert set(typing.get_args(annotation)) == {
        schema.ASSIGN,
        schema.EXCLUDE,
        attribution.ACTION_CLEAR,
    }


def test_without_a_loaded_library_a_write_is_409(unloaded: str, auth_token: dict[str, str]) -> None:
    res = _write(unloaded, "3", auth_token, action="assign")

    assert res.status_code == 409
    assert "library" in res.json()["detail"].lower()
    assert schema.list_track_assignments(unloaded) == []


def test_clear_needs_no_library(unloaded: str, auth_token: dict[str, str]) -> None:
    """Dropping a row needs no snapshot — only assign / exclude read the library."""
    schema.set_track_assignment(unloaded, "1", schema.EXCLUDE)

    res = _write(unloaded, "1", auth_token, action="clear")

    assert res.status_code == 200
    assert schema.list_track_assignments(unloaded) == []


# ---------------------------------------------------------------------------
# GET …/local-tracks/candidates
# ---------------------------------------------------------------------------


def test_candidates_find_by_title_and_flag_what_is_already_theirs(
    auth_token: dict[str, str],
) -> None:
    cid = _cid()

    res = _candidates(cid, q="over")

    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["total"] == 2
    by_id = {t["id"]: t for t in body["tracks"]}
    assert set(by_id) == {"1", "4"}
    assert by_id["1"]["artist_role"]["role"] == "primary"
    assert by_id["4"]["artist_role"] is None
    assert not by_id["1"]["excluded"]

    _write(cid, "1", auth_token, action="exclude", name=BOYS)
    flagged = {t["id"]: t for t in _candidates(cid, q="over").json()["tracks"]}

    assert flagged["1"]["excluded"] is True
    assert flagged["1"]["artist_role"] is None


def test_candidates_honour_the_limit_but_count_every_hit() -> None:
    body = _candidates(_cid(), q="over", limit=1).json()

    assert len(body["tracks"]) == 1
    assert body["total"] == 2


def test_a_blank_search_returns_nothing() -> None:
    body = _candidates(_cid(), q="   ").json()

    assert body["tracks"] == []
    assert body["total"] == 0


def test_candidates_without_a_loaded_library_find_nothing(unloaded: str) -> None:
    body = _candidates(unloaded, q="over").json()

    assert body["tracks"] == []
    assert body["total"] == 0


def test_candidates_for_an_id_nobody_knows_is_404() -> None:
    res = _candidates(_cid("Nobody At All"), q="over")

    assert res.status_code == 404
    assert "Unknown artist collection" in res.json()["detail"]


# ---------------------------------------------------------------------------
# Routing — the literal segment is not a track id
# ---------------------------------------------------------------------------


def test_the_candidates_path_reaches_the_search_not_the_write(auth_token: dict[str, str]) -> None:
    searched = _candidates(_cid(), q="over")
    assert searched.status_code == 200
    assert searched.json()["query"] == "over"

    written = _write(_cid(), "candidates", auth_token, action="assign", name=BOYS)
    assert written.status_code == 404
    assert written.json()["detail"] == "That track is not in the loaded library."

    assert _request("GET", f"/api/artists/{_cid()}/local-tracks/1").status_code == 405
