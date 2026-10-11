"""Artist-Hub profile-link routes (T-22 / T-23 — app/main.py, plan test row T36).

The contracts under test:

* every **mutation**, and the SoundCloud account search, is behind
  ``Depends(require_session)`` (threat T3) — a rejected call changes nothing and asks
  nobody. ``GET …/links`` stays a plain read, like ``/identities``.
* a hostile URL never becomes a row: the manual add runs the same classifier as a
  fetched link (threat T13), and oversized fields are refused before the route.
* a refresh is honest per source — ``not_linked`` / ``not_connected`` /
  ``not_queried`` instead of an empty success — and an artist with nothing to ask
  costs no call, not even a token renewal.
* the SoundCloud token reaches the SoundCloud layer and nothing else: not the payload,
  not a log line at any level.
* a MusicBrainz *name* match never binds on its own, and the SoundCloud account search
  never links (threat T15). Both only suggest; the user's click decides.

**No network, no real credentials.** ``requests.get`` — the one door both the
SoundCloud and the MusicBrainz client go through — raises and records every attempt,
the entry points a test needs are replaced per test, and the token getter defaults to
"signed out". The sidecar is a throwaway file in a tmp dir, exactly as in
``tests/test_artist_routes.py``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
import pytest
import requests

from app import auth, main
from app import musicbrainz_client as mb_client
from app import soundcloud_api as sc_api
from app import soundcloud_auth as sc_auth
from app.artist_store import links, registry, schema
from app.main import app

ARTIST_NAME = "Boys Noize"
ARTIST_URN = "soundcloud:users:4242"
ARTIST_PERMALINK = "https://soundcloud.com/boysnoize"
MBID = "7d7a3e3f-4d1c-4a3b-9f1e-0123456789ab"
#: Distinctive on purpose: a leak check on a short string such as "tok" also hits
#: "tiktok" and "token", and then proves nothing either way.
SC_TOKEN = "sc-oauth-sentinel-5b1f0c7e-lives-only-in-this-test"

INSTAGRAM_URL = "https://www.instagram.com/boysnoize/"
INSTAGRAM_KEY = "instagram:boysnoize"

#: `soundcloud_api.get_user`'s shape (`SC_PROFILE_FIELDS`).
SC_PROFILE: dict[str, Any] = {
    "urn": ARTIST_URN,
    "username": ARTIST_NAME,
    "permalink_url": ARTIST_PERMALINK,
    "track_count": 120,
    "followers_count": 500_000,
    "avatar_url": "",
    "permalink": "boysnoize",
    "full_name": "Alex Ridha",
    "city": "Berlin",
    "country": "Germany",
    "description": "Boysnoize Records. TikTok: @boysnoize",
    "website": "https://www.boysnoize.com/",
    "website_title": "Official site",
}

#: `soundcloud_api.get_user_web_profiles`' shape — what the artist put on their own page.
SC_WEB_PROFILES: list[dict[str, Any]] = [
    {"service": "instagram", "title": "", "url": "https://instagram.com/boysnoize", "username": ""},
    {"service": "bandcamp", "title": "", "url": "https://boysnoize.bandcamp.com/", "username": ""},
]

#: `musicbrainz_client.artist_with_urls`' `relations`. Instagram overlaps the SoundCloud
#: page on purpose: the artist's own page must keep the row.
MB_RELATIONS: list[dict[str, Any]] = [
    {"type": "social network", "url": INSTAGRAM_URL, "ended": False},
    {"type": "discogs", "url": "https://www.discogs.com/artist/123456-Boys-Noize", "ended": False},
    {
        "type": "other databases",
        "url": "https://www.residentadvisor.net/dj/boysnoize",
        "ended": False,
    },
]


def _mb_summary(mbid: str = MBID) -> dict[str, Any]:
    """One artist in `musicbrainz_client`'s summary shape."""
    return {
        "mbid": mbid,
        "name": ARTIST_NAME,
        "sort_name": "Noize, Boys",
        "disambiguation": "German DJ and producer",
        "country": "DE",
        "type": "Person",
    }


def _mb_artist_with_urls(mbid: str) -> dict[str, Any]:
    return {**_mb_summary(mbid), "relations": list(MB_RELATIONS)}


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


def _sources_by_key(body: dict[str, Any]) -> dict[str, str]:
    return {row["url_key"]: row["source"] for row in body["links"]}


_WIPE = (
    "DELETE FROM web_links; DELETE FROM link_fetch; DELETE FROM links; "
    "DELETE FROM favourites; DELETE FROM aliases; DELETE FROM collections;"
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
    db_file = tmp_path_factory.mktemp("artist_links_routes") / "artists.db"
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
def network_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every escape hatch closed, and every attempt on the one door recorded.

    The stub raises AssertionError, not a ``RequestException``: the engine files a
    network error under ``failed`` and carries on, which would hide a stray call.
    Signed out by default, so a test that forgets to opt in never reads the
    developer's real OAuth token. The legacy ``app_data.json`` import is marked done —
    it would otherwise read the developer's real sidecar file on the first 404 check.
    """
    attempts: list[str] = []

    def _no_http(url: Any, *_a: Any, **_kw: Any) -> Any:
        attempts.append(str(url))
        raise AssertionError(f"a test made a real HTTP call: {url}")

    monkeypatch.setattr(requests, "get", _no_http)
    monkeypatch.setattr(main.sc_auth, "get_access_token", lambda **_kw: None)
    monkeypatch.setattr(main.keyring, "get_password", lambda _service, _user: None)
    monkeypatch.setattr(auth, "paired_token_valid", lambda _token: False)
    monkeypatch.setattr(registry, "_legacy_migration_done", True)
    return attempts


@pytest.fixture
def signed_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main.sc_auth, "get_access_token", lambda **_kw: SC_TOKEN)


@pytest.fixture
def collection_id() -> str:
    return schema.create_collection(ARTIST_NAME, schema.KIND_ARTIST)


@pytest.fixture
def linked(collection_id: str) -> str:
    schema.set_link(collection_id, registry.PROVIDER_SOUNDCLOUD, ARTIST_URN, ARTIST_PERMALINK, 1.0)
    return collection_id


# ---------------------------------------------------------------------------
# Auth — threat T3
# ---------------------------------------------------------------------------

_GATED = [
    ("POST", "/api/artists/{cid}/links/refresh", {"musicbrainz": False}),
    ("POST", "/api/artists/{cid}/links", {"url": INSTAGRAM_URL}),
    ("POST", "/api/artists/{cid}/links/remove", {"url_key": INSTAGRAM_KEY}),
    ("POST", "/api/artists/{cid}/links/restore", None),
    ("POST", "/api/artists/{cid}/links/musicbrainz", {"mbid": MBID}),
    ("DELETE", "/api/artists/{cid}/links/musicbrainz", None),
    # A read by shape only: it spends the user's SoundCloud quota, so it is gated too.
    ("GET", "/api/artists/{cid}/soundcloud/candidates", None),
]


@pytest.mark.parametrize(("method", "url", "body"), _GATED)
def test_gated_routes_require_session(method: str, url: str, body: Any, collection_id: str) -> None:
    assert _request(method, url.format(cid=collection_id), json=body).status_code == 401


@pytest.mark.parametrize(("method", "url", "body"), _GATED)
def test_gated_routes_reject_wrong_bearer(
    method: str, url: str, body: Any, collection_id: str
) -> None:
    headers = {"Authorization": "Bearer not-the-session-token"}
    res = _request(method, url.format(cid=collection_id), json=body, headers=headers)
    assert res.status_code == 401


def test_rejected_calls_change_nothing_and_ask_nobody(
    collection_id: str, signed_in: None, network_calls: list[str]
) -> None:
    links.add_manual_link(collection_id, INSTAGRAM_URL)
    links.confirm_musicbrainz(collection_id, MBID)
    before = links.list_links(collection_id)

    for method, url, body in _GATED:
        _request(method, url.format(cid=collection_id), json=body)

    assert links.list_links(collection_id) == before
    assert schema.get_link_fetch(collection_id) is None, "a rejected refresh still ran"
    assert network_calls == []


def test_links_read_needs_no_session_and_starts_empty(
    collection_id: str, network_calls: list[str]
) -> None:
    res = _request("GET", f"/api/artists/{collection_id}/links")

    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["collection_id"] == collection_id
    assert body["links"] == []
    assert body["hidden_count"] == 0
    # Never refreshed must not read as "refreshed and found nothing".
    assert body["last_fetch"] is None
    assert body["musicbrainz"] is None
    assert network_calls == []


@pytest.mark.parametrize(
    ("method", "url", "body"), [("GET", "/api/artists/{cid}/links", None), *_GATED]
)
def test_unknown_collection_is_404_before_anything_else(
    method: str,
    url: str,
    body: Any,
    auth_token: dict[str, str],
    signed_in: None,
    network_calls: list[str],
) -> None:
    res = _request(method, url.format(cid="a_deadbeef"), json=body, headers=auth_token)

    assert res.status_code == 404
    assert network_calls == []


# ---------------------------------------------------------------------------
# Manual add / remove / restore — threat T13
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "file:///etc/passwd",
        "https://user:secret@www.instagram.com/boysnoize",
        "http://127.0.0.1:8000/api/system/health",
        "\\\\fileserver\\share\\bio.txt",
        "",
    ],
)
def test_add_refuses_what_is_not_a_web_profile(
    url: str, collection_id: str, auth_token: dict[str, str]
) -> None:
    res = _request(
        "POST", f"/api/artists/{collection_id}/links", json={"url": url}, headers=auth_token
    )

    assert res.status_code == 400
    assert res.json()["detail"]
    assert schema.list_web_links(collection_id, include_hidden=True) == []


def test_add_stores_the_canonical_profile_and_the_read_lists_it(
    collection_id: str, auth_token: dict[str, str]
) -> None:
    res = _request(
        "POST",
        f"/api/artists/{collection_id}/links",
        json={"url": INSTAGRAM_URL},
        headers=auth_token,
    )

    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["collection_id"] == collection_id
    assert body["link"]["url"] == "https://www.instagram.com/boysnoize"
    assert body["link"]["source"] == "manual"

    listed = _request("GET", f"/api/artists/{collection_id}/links").json()["links"]
    assert [(row["url_key"], row["service"], row["source"]) for row in listed] == [
        (INSTAGRAM_KEY, "instagram", "manual")
    ]


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("links", {"url": "https://example.com/" + "a" * 2100}),
        ("links/remove", {"url_key": "web:" + "a" * 600}),
        ("links/musicbrainz", {"mbid": "a" * 65}),
    ],
)
def test_oversized_fields_are_refused_before_the_route(
    path: str, body: dict[str, str], collection_id: str, auth_token: dict[str, str]
) -> None:
    res = _request("POST", f"/api/artists/{collection_id}/{path}", json=body, headers=auth_token)

    assert res.status_code == 422
    assert schema.list_web_links(collection_id, include_hidden=True) == []
    assert schema.get_link(collection_id, links.PROVIDER_MUSICBRAINZ) is None


def test_remove_deletes_a_manual_link(collection_id: str, auth_token: dict[str, str]) -> None:
    added = _request(
        "POST",
        f"/api/artists/{collection_id}/links",
        json={"url": INSTAGRAM_URL},
        headers=auth_token,
    )
    key = added.json()["link"]["url_key"]

    res = _request(
        "POST",
        f"/api/artists/{collection_id}/links/remove",
        json={"url_key": key},
        headers=auth_token,
    )

    assert res.status_code == 200
    assert res.json() == {"status": "ok", "collection_id": collection_id, "outcome": "deleted"}
    assert schema.get_web_link(collection_id, key) is None


def test_remove_hides_a_fetched_link_until_restore(
    collection_id: str, auth_token: dict[str, str]
) -> None:
    """Deleting a fetched link would last one refresh — the hide has to live in the row."""
    fetched = links.classify_url("https://www.residentadvisor.net/dj/boysnoize")
    assert fetched is not None
    schema.merge_fetched_web_links(
        collection_id,
        [fetched.entry(schema.LINK_SOURCE_MUSICBRAINZ)],
        [schema.LINK_SOURCE_MUSICBRAINZ],
    )

    removed = _request(
        "POST",
        f"/api/artists/{collection_id}/links/remove",
        json={"url_key": fetched.url_key},
        headers=auth_token,
    )
    assert removed.json()["outcome"] == "hidden"
    hidden = _request("GET", f"/api/artists/{collection_id}/links").json()
    assert hidden["links"] == []
    assert hidden["hidden_count"] == 1

    restored = _request("POST", f"/api/artists/{collection_id}/links/restore", headers=auth_token)
    assert restored.status_code == 200
    assert restored.json() == {"status": "ok", "collection_id": collection_id, "restored": 1}
    back = _request("GET", f"/api/artists/{collection_id}/links").json()
    assert [row["url_key"] for row in back["links"]] == [fetched.url_key]
    assert back["hidden_count"] == 0

    again = _request("POST", f"/api/artists/{collection_id}/links/restore", headers=auth_token)
    assert again.json()["restored"] == 0


def test_remove_an_unknown_link_is_404(collection_id: str, auth_token: dict[str, str]) -> None:
    res = _request(
        "POST",
        f"/api/artists/{collection_id}/links/remove",
        json={"url_key": INSTAGRAM_KEY},
        headers=auth_token,
    )

    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Refresh — per-source honesty, no stray calls, no token leak
# ---------------------------------------------------------------------------


def test_refresh_without_link_or_musicbrainz_asks_nobody(
    monkeypatch: pytest.MonkeyPatch,
    collection_id: str,
    auth_token: dict[str, str],
    network_calls: list[str],
) -> None:
    token_lookups: list[str] = []

    def _token(**_kw: Any) -> str:
        token_lookups.append("lookup")
        return SC_TOKEN

    monkeypatch.setattr(main.sc_auth, "get_access_token", _token)

    res = _request(
        "POST",
        f"/api/artists/{collection_id}/links/refresh",
        json={"musicbrainz": False},
        headers=auth_token,
    )

    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["sources"] == {"soundcloud": "not_linked", "musicbrainz": "not_queried"}
    assert body["links"] == []
    assert body["musicbrainz_candidates"] == []
    assert body["calls_used"] == 0
    assert network_calls == []
    # A renewal is an HTTPS round-trip too, and an unlinked artist has nothing to spend it on.
    assert token_lookups == []
    # The pass is still recorded, so the UI can say what was not asked.
    assert body["last_fetch"]["sources"] == body["sources"]


def test_refresh_body_is_optional(
    monkeypatch: pytest.MonkeyPatch,
    collection_id: str,
    auth_token: dict[str, str],
    network_calls: list[str],
) -> None:
    """No body = the default click: MusicBrainz is asked."""
    monkeypatch.setattr(mb_client, "search_artists", lambda _name, limit=5: [])

    res = _request("POST", f"/api/artists/{collection_id}/links/refresh", headers=auth_token)

    assert res.status_code == 200
    assert res.json()["sources"] == {"soundcloud": "not_linked", "musicbrainz": "no_match"}
    assert network_calls == []


@pytest.mark.parametrize(
    "failure",
    [
        None,
        sc_api.AuthExpiredError("refresh token rejected"),
        sc_auth.TransientRefreshError("token endpoint unreachable"),
    ],
    ids=["signed_out", "login_expired", "renewal_unreachable"],
)
def test_refresh_without_a_usable_login_says_not_connected(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception | None,
    linked: str,
    auth_token: dict[str, str],
    network_calls: list[str],
) -> None:
    """Not an error: the SoundCloud source says why it was skipped, the call still answers."""

    def _token(**_kw: Any) -> str | None:
        if failure is not None:
            raise failure
        return None

    monkeypatch.setattr(main.sc_auth, "get_access_token", _token)

    res = _request(
        "POST",
        f"/api/artists/{linked}/links/refresh",
        json={"musicbrainz": False},
        headers=auth_token,
    )

    assert res.status_code == 200
    assert res.json()["sources"] == {"soundcloud": "not_connected", "musicbrainz": "not_queried"}
    assert network_calls == []


def test_refresh_folds_both_sources_and_never_leaks_the_token(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    linked: str,
    signed_in: None,
    auth_token: dict[str, str],
    network_calls: list[str],
) -> None:
    caplog.set_level(logging.DEBUG)
    seen: dict[str, Any] = {}

    def _get_user(urn: str, token: str, *, budget: sc_api.CallBudget | None = None) -> Any:
        assert budget is not None and budget.try_spend()
        seen["user"] = (urn, token, budget.limit)
        return dict(SC_PROFILE)

    def _web_profiles(urn: str, token: str, *, budget: sc_api.CallBudget | None = None) -> Any:
        assert budget is not None and budget.try_spend()
        seen["web_profiles"] = (urn, token)
        return sc_api.SCResultList([dict(p) for p in SC_WEB_PROFILES], calls_used=1)

    def _artists_for_url(url: str) -> list[dict[str, Any]]:
        seen["anchor_url"] = url
        return [_mb_summary()]

    monkeypatch.setattr(sc_api, "get_user", _get_user)
    monkeypatch.setattr(sc_api, "get_user_web_profiles", _web_profiles)
    monkeypatch.setattr(mb_client, "artists_for_url", _artists_for_url)
    monkeypatch.setattr(mb_client, "artist_with_urls", _mb_artist_with_urls)

    res = _request("POST", f"/api/artists/{linked}/links/refresh", json={}, headers=auth_token)

    assert res.status_code == 200
    body = res.json()
    assert body["sources"] == {"soundcloud": "ok", "musicbrainz": "ok"}
    expected = {
        INSTAGRAM_KEY: "soundcloud_profile",  # MusicBrainz lists it too; the artist's page wins
        "bandcamp:boysnoize": "soundcloud_profile",
        "tiktok:boysnoize": "soundcloud_bio",
        "discogs:123456": "musicbrainz",
        "resident_advisor:boysnoize": "musicbrainz",
    }
    assert expected.items() <= _sources_by_key(body).items()
    # The MusicBrainz binding came from the linked SoundCloud URL, not from a name.
    assert seen["anchor_url"] == ARTIST_PERMALINK
    assert body["musicbrainz"] == {
        "mbid": MBID,
        "url": f"https://musicbrainz.org/artist/{MBID}",
        "anchored": True,
    }
    # The token reached the SoundCloud layer, under the links budget...
    assert seen["user"] == (ARTIST_URN, SC_TOKEN, links.LINKS_CALL_BUDGET)
    assert seen["web_profiles"] == (ARTIST_URN, SC_TOKEN)
    assert body["calls_used"] == 2
    # ...and nowhere else.
    assert SC_TOKEN not in res.text
    assert SC_TOKEN not in caplog.text
    assert network_calls == []


# ---------------------------------------------------------------------------
# MusicBrainz — threat T15
# ---------------------------------------------------------------------------


def test_mb_name_match_never_autobinds(
    monkeypatch: pytest.MonkeyPatch,
    collection_id: str,
    auth_token: dict[str, str],
    network_calls: list[str],
) -> None:
    """An exact name at score 100 is still only a candidate — the confirm click binds."""
    read: list[str] = []

    def _artist_with_urls(mbid: str) -> dict[str, Any]:
        read.append(mbid)
        return _mb_artist_with_urls(mbid)

    monkeypatch.setattr(
        mb_client, "search_artists", lambda _name, limit=5: [{**_mb_summary(), "score": 100}]
    )
    monkeypatch.setattr(mb_client, "artist_with_urls", _artist_with_urls)

    res = _request(
        "POST",
        f"/api/artists/{collection_id}/links/refresh",
        json={"musicbrainz": True},
        headers=auth_token,
    )

    assert res.status_code == 200
    body = res.json()
    assert body["sources"]["musicbrainz"] == "needs_confirmation"
    assert [c["mbid"] for c in body["musicbrainz_candidates"]] == [MBID]
    assert body["musicbrainz"] is None
    assert body["links"] == []
    assert schema.get_link(collection_id, links.PROVIDER_MUSICBRAINZ) is None
    assert read == [], "an unconfirmed candidate's links were fetched"

    confirmed = _request(
        "POST",
        f"/api/artists/{collection_id}/links/musicbrainz",
        json={"mbid": MBID},
        headers=auth_token,
    )

    assert confirmed.status_code == 200
    body = confirmed.json()
    assert body["status"] == "ok"
    assert body["musicbrainz"] == {
        "mbid": MBID,
        "url": f"https://musicbrainz.org/artist/{MBID}",
        "anchored": False,
    }
    assert body["sources"]["musicbrainz"] == "ok"
    assert body["musicbrainz_candidates"] == []
    assert _sources_by_key(body)["discogs:123456"] == "musicbrainz"
    assert read == [MBID]
    assert network_calls == []


@pytest.mark.parametrize("mbid", ["not-an-mbid", "../../artist/x", ""])
def test_confirm_refuses_a_malformed_mbid(
    mbid: str, collection_id: str, auth_token: dict[str, str], network_calls: list[str]
) -> None:
    res = _request(
        "POST",
        f"/api/artists/{collection_id}/links/musicbrainz",
        json={"mbid": mbid},
        headers=auth_token,
    )

    assert res.status_code == 400
    assert schema.get_link(collection_id, links.PROVIDER_MUSICBRAINZ) is None
    assert network_calls == []


def test_drop_musicbrainz_unbinds_and_takes_its_links(
    monkeypatch: pytest.MonkeyPatch,
    collection_id: str,
    auth_token: dict[str, str],
    network_calls: list[str],
) -> None:
    monkeypatch.setattr(mb_client, "artist_with_urls", _mb_artist_with_urls)
    confirmed = _request(
        "POST",
        f"/api/artists/{collection_id}/links/musicbrainz",
        json={"mbid": MBID},
        headers=auth_token,
    )
    assert "musicbrainz" in _sources_by_key(confirmed.json()).values()

    dropped = _request(
        "DELETE", f"/api/artists/{collection_id}/links/musicbrainz", headers=auth_token
    )

    assert dropped.status_code == 200
    body = dropped.json()
    assert body["status"] == "ok"
    assert body["collection_id"] == collection_id
    assert body["removed"] is True
    assert body["musicbrainz"] is None
    assert "musicbrainz" not in _sources_by_key(body).values()
    again = _request(
        "DELETE", f"/api/artists/{collection_id}/links/musicbrainz", headers=auth_token
    )
    assert again.json()["removed"] is False
    assert network_calls == []


# ---------------------------------------------------------------------------
# SoundCloud account suggestions — threat T15
# ---------------------------------------------------------------------------

REAL_URN = ARTIST_URN
LOOKALIKE_URN = "soundcloud:users:77"
FAN_URN = "soundcloud:users:88"


def _sc_user(urn: str, username: str, permalink: str, followers: int) -> dict[str, Any]:
    return {
        "urn": urn,
        "username": username,
        "permalink_url": f"https://soundcloud.com/{permalink}",
        "track_count": 1,
        "followers_count": followers,
        "avatar_url": "",
        "permalink": permalink,
        "full_name": "",
        "city": "",
        "country": "",
        "description": "",
        "website": "",
        "website_title": "",
    }


def test_sc_candidates_never_link(
    monkeypatch: pytest.MonkeyPatch,
    collection_id: str,
    signed_in: None,
    auth_token: dict[str, str],
    network_calls: list[str],
) -> None:
    """Ranked by name, not by reach — and a suggestion stays a suggestion."""
    seen: dict[str, Any] = {}
    bound: list[Any] = []

    def _search(
        query: str, token: str, *, limit: int = 20, budget: sc_api.CallBudget | None = None
    ) -> Any:
        assert budget is not None and budget.try_spend()
        seen.update(query=query, token=token, cap=budget.limit)
        return sc_api.SCResultList(
            [
                _sc_user(FAN_URN, "Boys Noize Fanpage", "bnfans", 900_000),
                _sc_user(LOOKALIKE_URN, "boysnoize", "boysnoize-official", 10),
                _sc_user(REAL_URN, ARTIST_NAME, "boysnoize", 500),
            ],
            calls_used=1,
        )

    monkeypatch.setattr(sc_api, "search_users", _search)
    monkeypatch.setattr(registry, "set_provider_link", lambda *a, **kw: bound.append((a, kw)))

    res = _request("GET", f"/api/artists/{collection_id}/soundcloud/candidates", headers=auth_token)

    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["query"] == ARTIST_NAME
    assert [(c["urn"], c["match"]) for c in body["candidates"]] == [
        (REAL_URN, "exact"),
        (LOOKALIKE_URN, "close"),
        (FAN_URN, "weak"),
    ]
    assert seen == {
        "query": ARTIST_NAME,
        "token": SC_TOKEN,
        "cap": main.ARTIST_SC_CANDIDATES_CALL_BUDGET,
    }
    assert bound == []
    assert registry.get_provider_link(collection_id) is None
    assert schema.list_web_links(collection_id, include_hidden=True) == []
    assert SC_TOKEN not in res.text
    assert network_calls == []


def test_sc_candidates_signed_out_is_400_and_searches_nothing(
    collection_id: str, auth_token: dict[str, str], network_calls: list[str]
) -> None:
    res = _request("GET", f"/api/artists/{collection_id}/soundcloud/candidates", headers=auth_token)

    assert res.status_code == 400
    assert "not connected" in res.json()["detail"].lower()
    assert network_calls == []


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (sc_api.RateLimitError("SoundCloud rate limit exceeded."), 429),
        (sc_api.AuthExpiredError("token rejected"), 401),
    ],
    ids=["rate_limited", "login_expired"],
)
def test_sc_candidates_map_soundcloud_failures(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    status: int,
    collection_id: str,
    signed_in: None,
    auth_token: dict[str, str],
) -> None:
    def _search(*_a: Any, **_kw: Any) -> Any:
        raise error

    monkeypatch.setattr(sc_api, "search_users", _search)

    res = _request("GET", f"/api/artists/{collection_id}/soundcloud/candidates", headers=auth_token)

    assert res.status_code == status
    assert registry.get_provider_link(collection_id) is None
