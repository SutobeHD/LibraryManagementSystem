"""Artist-Hub route tests (T-8 — app/main.py, plan test row T13).

Four contracts:

* every **mutation** route is behind ``Depends(require_session)`` — no header and a
  wrong bearer both 401, and the sidecar stays untouched (threat T3).
* ``GET /api/artists/hub`` stays a plain read: no header needed, always the two keys
  the frontend destructures, and the Tier-1 backlog is owned-track-count descending.
* ``GET /api/artists/browse`` is the same read for the *whole* list: favourites stay in
  and carry ``is_favourite``, search and sort run before paging, and hostile paging is
  clamped instead of erroring.
* favouriting round-trips through the API — POST moves an artist out of the backlog
  into ``favourites``, DELETE moves it back — and the sync mode set through the route
  is the one the hub reports back.

No Rekordbox is opened: the ``db`` facade is replaced by a stub exposing the only two
attributes the hub reads (``loaded`` / ``artists``), so nothing here can reach the real
``master.db`` or the developer's settings. The sidecar is a throwaway file in a tmp dir.

Driving the app: httpx ``ASGITransport`` against the live FastAPI graph, same as
``tests/test_main_security.py`` — the installed fastapi 0.109 + httpx 0.28 pair
mishandles ``TestClient``'s deprecated ``app=`` kwarg.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from app import auth, main
from app.artist_store import schema
from app.main import app

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


class _LibraryDB:
    """Stand-in for the ``db`` facade — the hub reads ``loaded`` and ``artists``, nothing else.

    ``art_{i}`` ids are handed out exactly like ``_finalize_ui_metadata`` does, to keep the
    fixture honest about what the route sees; the store must never key on them.
    """

    def __init__(self, artists: tuple[tuple[str, int], ...] = (), loaded: bool = True) -> None:
        self.loaded = loaded
        self.artists = [
            {"id": f"art_{i}", "name": name, "track_count": count, "Artwork": ""}
            for i, (name, count) in enumerate(artists)
        ]


_LIBRARY = (("Boys Noize", 12), ("Helena Hauff", 30), ("Skee Mask", 1))

_WIPE = (
    "DELETE FROM favourites; DELETE FROM catalogue_cache; DELETE FROM projection; "
    "DELETE FROM sync_state; DELETE FROM links; DELETE FROM aliases; "
    "DELETE FROM collections;"
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
    """One throwaway ``artists.db`` for the whole module.

    Module-scoped on purpose: ``schema._connect`` caches its connection per thread and
    FastAPI runs sync handlers on worker threads, so a per-test DB file would leave those
    threads holding a connection to a deleted path.
    """
    mp = pytest.MonkeyPatch()
    db_file = tmp_path_factory.mktemp("artist_routes") / "artists.db"
    mp.setattr(schema, "_db_path", lambda: db_file)
    mp.setattr(schema, "_initialised", False)
    _close_thread_conn()
    schema.init_db()
    yield
    _close_thread_conn()
    mp.undo()


@pytest.fixture(autouse=True)
def _clean_store():
    """Empty every table around each test — the file is shared, the state must not be."""
    conn = schema._ensure_schema()
    with schema._write_lock:
        conn.executescript(_WIPE)
        conn.commit()
    yield


@pytest.fixture(autouse=True)
def _library(monkeypatch):
    """Stub library + no device-token lookup, so no real user file is opened."""
    monkeypatch.setattr(main, "db", _LibraryDB(_LIBRARY))
    monkeypatch.setattr(auth, "paired_token_valid", lambda _token: False)


# ---------------------------------------------------------------------------
# Auth — threat T3
# ---------------------------------------------------------------------------

_MUTATIONS = [
    ("POST", "/api/artists/favourites", {"name": "Boys Noize"}),
    ("DELETE", "/api/artists/favourites/a_deadbeef", None),
    ("POST", "/api/artists/a_deadbeef/sync-mode", {"mode": "auto"}),
]


@pytest.mark.parametrize(("method", "url", "body"), _MUTATIONS)
def test_all_mutations_require_session(method, url, body) -> None:
    assert _request(method, url, json=body).status_code == 401


@pytest.mark.parametrize(("method", "url", "body"), _MUTATIONS)
def test_all_mutations_reject_wrong_bearer(method, url, body) -> None:
    headers = {"Authorization": "Bearer not-the-session-token"}
    assert _request(method, url, json=body, headers=headers).status_code == 401


def test_rejected_mutation_writes_nothing(auth_token) -> None:
    for method, url, body in _MUTATIONS:
        _request(method, url, json=body)

    assert schema.list_favourites() == []
    assert schema.list_collections() == []


def test_valid_bearer_is_accepted(auth_token) -> None:
    res = _request(
        "POST", "/api/artists/favourites", json={"name": "Boys Noize"}, headers=auth_token
    )

    assert res.status_code == 200


# ---------------------------------------------------------------------------
# GET /api/artists/hub
# ---------------------------------------------------------------------------


def test_hub_returns_both_keys_without_auth() -> None:
    res = _request("GET", "/api/artists/hub")

    assert res.status_code == 200
    assert set(res.json()) == {"favourites", "backlog", "backlog_total", "backlog_query"}


def test_hub_backlog_is_track_count_descending() -> None:
    body = _request("GET", "/api/artists/hub").json()

    assert body["favourites"] == []
    assert [row["name"] for row in body["backlog"]] == ["Helena Hauff", "Boys Noize", "Skee Mask"]
    assert [row["track_count"] for row in body["backlog"]] == [30, 12, 1]


def test_hub_backlog_honours_limit() -> None:
    body = _request("GET", "/api/artists/hub", json=None).json()
    limited = _request("GET", "/api/artists/hub?limit=1").json()

    assert len(body["backlog"]) == 3
    assert [row["name"] for row in limited["backlog"]] == ["Helena Hauff"]


def test_hub_renders_before_the_library_loads(monkeypatch) -> None:
    monkeypatch.setattr(main, "db", _LibraryDB(_LIBRARY, loaded=False))

    body = _request("GET", "/api/artists/hub").json()

    assert body == {"favourites": [], "backlog": [], "backlog_total": 0, "backlog_query": ""}


# ---------------------------------------------------------------------------
# Favourites round-trip
# ---------------------------------------------------------------------------


def test_favourite_by_name_round_trips(auth_token) -> None:
    added = _request(
        "POST", "/api/artists/favourites", json={"name": "Helena Hauff"}, headers=auth_token
    )
    assert added.status_code == 200
    assert added.json()["added"] is True
    cid = added.json()["collection_id"]

    hub = _request("GET", "/api/artists/hub").json()
    favourite = hub["favourites"][0]
    assert favourite["collection_id"] == cid
    assert favourite["name"] == "Helena Hauff"
    assert favourite["track_count"] == 30
    assert favourite["sync_mode"] == "review"
    assert "Helena Hauff" not in [row["name"] for row in hub["backlog"]]

    removed = _request("DELETE", f"/api/artists/favourites/{cid}", headers=auth_token)
    assert removed.status_code == 200
    assert removed.json()["removed"] is True

    after = _request("GET", "/api/artists/hub").json()
    assert after["favourites"] == []
    assert [row["name"] for row in after["backlog"]] == ["Helena Hauff", "Boys Noize", "Skee Mask"]


def test_favourite_by_name_is_idempotent(auth_token) -> None:
    first = _request(
        "POST", "/api/artists/favourites", json={"name": "Boys Noize"}, headers=auth_token
    ).json()
    second = _request(
        "POST", "/api/artists/favourites", json={"name": "Boys Noize"}, headers=auth_token
    ).json()

    assert second["collection_id"] == first["collection_id"]
    assert first["added"] is True
    assert second["added"] is False
    assert len(_request("GET", "/api/artists/hub").json()["favourites"]) == 1


def test_favourite_by_collection_id(auth_token) -> None:
    cid = schema.create_collection("Helena Hauff")
    schema.add_alias(cid, "Helena Hauff", source="library")

    res = _request(
        "POST", "/api/artists/favourites", json={"collection_id": cid}, headers=auth_token
    )

    assert res.status_code == 200
    assert res.json() == {"status": "success", "collection_id": cid, "added": True}
    assert [
        row["collection_id"] for row in _request("GET", "/api/artists/hub").json()["favourites"]
    ] == [cid]


def test_favourite_unknown_collection_id_is_404(auth_token) -> None:
    res = _request(
        "POST", "/api/artists/favourites", json={"collection_id": "a_deadbeef"}, headers=auth_token
    )

    assert res.status_code == 404
    assert schema.list_favourites() == []


@pytest.mark.parametrize("body", [{}, {"name": "   "}, {"name": None, "collection_id": None}])
def test_favourite_without_name_or_id_is_400(body, auth_token) -> None:
    assert (
        _request("POST", "/api/artists/favourites", json=body, headers=auth_token).status_code
        == 400
    )


def test_unfavourite_unknown_id_is_a_no_op(auth_token) -> None:
    res = _request("DELETE", "/api/artists/favourites/a_deadbeef", headers=auth_token)

    assert res.status_code == 200
    assert res.json()["removed"] is False


# ---------------------------------------------------------------------------
# Sync mode
# ---------------------------------------------------------------------------


def test_sync_mode_round_trips(auth_token) -> None:
    cid = _request(
        "POST", "/api/artists/favourites", json={"name": "Boys Noize"}, headers=auth_token
    ).json()["collection_id"]

    res = _request(
        "POST", f"/api/artists/{cid}/sync-mode", json={"mode": "auto"}, headers=auth_token
    )

    assert res.status_code == 200
    assert res.json()["mode"] == "auto"
    assert _request("GET", "/api/artists/hub").json()["favourites"][0]["sync_mode"] == "auto"


def test_sync_mode_rejects_unknown_mode(auth_token) -> None:
    cid = _request(
        "POST", "/api/artists/favourites", json={"name": "Boys Noize"}, headers=auth_token
    ).json()["collection_id"]

    res = _request(
        "POST", f"/api/artists/{cid}/sync-mode", json={"mode": "sometimes"}, headers=auth_token
    )

    assert res.status_code == 400
    assert schema.get_sync_mode(cid) == "review"


def test_sync_mode_unknown_collection_is_404(auth_token) -> None:
    res = _request(
        "POST", "/api/artists/a_deadbeef/sync-mode", json={"mode": "auto"}, headers=auth_token
    )

    assert res.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/artists/browse
# ---------------------------------------------------------------------------


def test_browse_returns_the_contract_shape_without_auth() -> None:
    res = _request("GET", "/api/artists/browse")

    assert res.status_code == 200
    body = res.json()
    assert set(body) == {"artists", "total", "limit", "offset", "query", "sort"}
    assert body["total"] == 3
    assert body["limit"] == 100
    assert body["offset"] == 0
    assert body["sort"] == "name"
    assert set(body["artists"][0]) == {
        "collection_id",
        "name",
        "track_count",
        "artwork",
        "is_favourite",
        "sync_mode",
        "sc_linked",
        "library_names",
    }


def test_browse_lists_every_artist_name_sorted() -> None:
    body = _request("GET", "/api/artists/browse").json()

    assert [row["name"] for row in body["artists"]] == [
        "Boys Noize",
        "Helena Hauff",
        "Skee Mask",
    ]
    assert all(row["is_favourite"] is False for row in body["artists"])


def test_browse_keeps_favourites_in_the_list_and_flags_them(auth_token) -> None:
    _request("POST", "/api/artists/favourites", json={"name": "Helena Hauff"}, headers=auth_token)

    body = _request("GET", "/api/artists/browse").json()

    assert {row["name"]: row["is_favourite"] for row in body["artists"]} == {
        "Boys Noize": False,
        "Helena Hauff": True,
        "Skee Mask": False,
    }
    hub = _request("GET", "/api/artists/hub").json()
    assert "Helena Hauff" not in [row["name"] for row in hub["backlog"]], "backlog changed shape"


def test_browse_toggle_round_trips_through_the_favourite_routes(auth_token) -> None:
    row = _request("GET", "/api/artists/browse?q=skee").json()["artists"][0]
    assert row["is_favourite"] is False

    added = _request(
        "POST", "/api/artists/favourites", json={"name": row["name"]}, headers=auth_token
    ).json()
    assert added["collection_id"] == row["collection_id"], "favouriting minted a different id"
    on = _request("GET", "/api/artists/browse?q=skee").json()["artists"][0]
    assert on["is_favourite"] is True

    _request("DELETE", f"/api/artists/favourites/{row['collection_id']}", headers=auth_token)
    off = _request("GET", "/api/artists/browse?q=skee").json()["artists"][0]
    assert off["is_favourite"] is False


def test_browse_row_id_is_derived_until_a_resolve_pass_registers_it(auth_token) -> None:
    """Favourite a browse row by `name`: its `collection_id` need not exist in the store yet.

    `browse` is a read, so it derives the id from the folded name instead of creating a
    row. POSTing that id straight back therefore 404s until something has written the
    collection — the name path (`favourite_artist_by_name`) is the one that always works,
    and it lands on the very same id.
    """
    row = _request("GET", "/api/artists/browse?q=skee").json()["artists"][0]

    by_id = _request(
        "POST",
        "/api/artists/favourites",
        json={"collection_id": row["collection_id"]},
        headers=auth_token,
    )
    assert by_id.status_code == 404

    by_name = _request(
        "POST", "/api/artists/favourites", json={"name": row["name"]}, headers=auth_token
    )
    assert by_name.status_code == 200
    assert by_name.json()["collection_id"] == row["collection_id"]


def test_browse_sorts_by_track_count() -> None:
    body = _request("GET", "/api/artists/browse?sort=tracks").json()

    assert [row["name"] for row in body["artists"]] == [
        "Helena Hauff",
        "Boys Noize",
        "Skee Mask",
    ]
    assert body["sort"] == "tracks"


def test_browse_unknown_sort_falls_back_instead_of_erroring() -> None:
    res = _request("GET", "/api/artists/browse?sort=whatever")

    assert res.status_code == 200
    assert res.json()["sort"] == "name"
    assert [row["name"] for row in res.json()["artists"]] == [
        "Boys Noize",
        "Helena Hauff",
        "Skee Mask",
    ]


def test_browse_query_filters_before_pagination(monkeypatch) -> None:
    """An artist past the first page must still be findable by search."""
    many = (*((f"Artist {i:02d}", 30 - i) for i in range(29)), ("Zeta Rare", 1))
    monkeypatch.setattr(main, "db", _LibraryDB(many))

    page_one = _request("GET", "/api/artists/browse?limit=5").json()
    assert "Zeta Rare" not in [row["name"] for row in page_one["artists"]]
    assert page_one["total"] == 30

    found = _request("GET", "/api/artists/browse?limit=5&q=zeta").json()
    assert [row["name"] for row in found["artists"]] == ["Zeta Rare"]
    assert found["total"] == 1
    assert found["query"] == "zeta"


def test_browse_offset_pages_the_list(monkeypatch) -> None:
    many = tuple((f"Artist {i:02d}", 1) for i in range(10))
    monkeypatch.setattr(main, "db", _LibraryDB(many))

    seen = []
    for offset in (0, 4, 8):
        page = _request("GET", f"/api/artists/browse?limit=4&offset={offset}").json()
        assert page["total"] == 10
        assert page["offset"] == offset
        seen.extend(row["name"] for row in page["artists"])

    assert seen == [f"Artist {i:02d}" for i in range(10)]


def test_browse_caps_the_limit(monkeypatch) -> None:
    many = tuple((f"Artist {i:04d}", 1) for i in range(505))
    monkeypatch.setattr(main, "db", _LibraryDB(many))

    body = _request("GET", "/api/artists/browse?limit=10000").json()

    assert body["limit"] == 500
    assert len(body["artists"]) == 500
    assert body["total"] == 505


@pytest.mark.parametrize("qs", ["limit=0", "limit=-3", "offset=-10", "limit=-1&offset=-1"])
def test_browse_survives_hostile_paging(qs) -> None:
    res = _request("GET", f"/api/artists/browse?{qs}")

    assert res.status_code == 200
    body = res.json()
    assert body["limit"] >= 0
    assert body["offset"] == 0
    assert body["total"] == 3, "the count stays honest whatever the paging"


def test_browse_degrades_when_the_library_is_not_loaded(monkeypatch) -> None:
    monkeypatch.setattr(main, "db", _LibraryDB(_LIBRARY, loaded=False))

    res = _request("GET", "/api/artists/browse")

    assert res.status_code == 200
    assert res.json() == {
        "artists": [],
        "total": 0,
        "limit": 100,
        "offset": 0,
        "query": "",
        "sort": "name",
    }
