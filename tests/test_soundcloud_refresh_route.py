"""Route tests for the persistent SoundCloud login (T-19).

Covers the three routes that carry the session across a restart:

* ``POST /api/soundcloud/refresh`` — session-gated, rate-limited, and mapping the two
  failure classes apart: a rejected refresh token is a 401 ("sign in again"), an
  unreachable token endpoint is a 503 ("the stored login is intact"). A 503 answered as
  401 would throw the user at a login button over a dropped connection.
* ``POST /api/soundcloud/auth-token`` — stores the access token, the refresh token and
  the lifetime; an empty token still means logout.
* ``GET /api/soundcloud/auth-status`` — reports whether the session can renew itself and
  how much life the stored access token has left.

No response of any of the three may contain token material — asserted literally against
the raw body text on every case.

**No network, no real keyring, no credentials.** ``app.main.sc_auth`` is patched per test;
the refresh grant itself is exercised in ``tests/test_soundcloud_auth.py``. The app is
driven through ``httpx.ASGITransport`` (TestClient is broken on the installed
fastapi 0.109 / httpx 0.28 pair), the same as ``tests/test_main_security.py``.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from app import main as main_mod
from app import rate_limit as rate_limit_mod
from app.main import app
from app.soundcloud_api import AuthExpiredError
from app.soundcloud_auth import ScTokens, StoreResult, TransientRefreshError
from tests.conftest import TEST_SESSION_TOKEN

ACCESS = "ACCESS-TOKEN-ROUTE-TEST-DO-NOT-LEAK-a1b2c3"
REFRESH = "REFRESH-TOKEN-ROUTE-TEST-DO-NOT-LEAK-d4e5f6"
NEW_ACCESS = "ACCESS-TOKEN-ROTATED-ROUTE-TEST-DO-NOT-LEAK-g7h8i9"
SECRETS = (ACCESS, REFRESH, NEW_ACCESS)

AUTH = {"Authorization": f"Bearer {TEST_SESSION_TOKEN}"}

# Loopback is whitelisted by the rate limiter (app/rate_limit.py), so the bucket only
# exists for a caller that looks remote. TEST-NET-3 (RFC 5737) never routes anywhere.
LOOPBACK_CLIENT = ("127.0.0.1", 12345)
REMOTE_CLIENT = ("203.0.113.9", 44321)

# Mirrors the decorator on the route: @rate_limit(steady=5.0, burst=10).
REFRESH_BURST = 10


def _request(
    method: str,
    url: str,
    *,
    json: Any = None,
    headers: dict[str, str] | None = None,
    client: tuple[str, int] = LOOPBACK_CLIENT,
) -> httpx.Response:
    async def _go() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, client=client, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            return await ac.request(method, url, json=json, headers=headers)

    return asyncio.run(_go())


def _tokens(access: str = ACCESS, refresh: str | None = REFRESH) -> ScTokens:
    return ScTokens(
        access_token=access,
        refresh_token=refresh,
        expires_at=2_000_000_000.0,
        obtained_at=1_999_996_400.0,
        scope=None,
    )


def _assert_no_secrets(resp: httpx.Response) -> None:
    for secret in SECRETS:
        assert secret not in resp.text


@pytest.fixture(autouse=True)
def _no_keyring_no_network(monkeypatch: pytest.MonkeyPatch):
    """Every `sc_auth` entry point the routes touch is replaced.

    Defaults are the signed-out ones: a test that forgets to opt in cannot reach the
    developer's real keyring, and no test can fire a real refresh POST.
    """

    def _refuse(*_a: Any, **_kw: Any):
        raise AssertionError("a test reached the real refresh grant")

    monkeypatch.setattr(main_mod.sc_auth, "load_tokens", lambda: None)
    monkeypatch.setattr(main_mod.sc_auth, "refresh", _refuse)
    monkeypatch.setattr(main_mod.sc_auth, "get_access_token", lambda **_kw: None)
    monkeypatch.setattr(
        main_mod.sc_auth,
        "token_status",
        lambda: {
            "authenticated": False,
            "refreshable": False,
            "source": None,
            "expires_at": None,
            "remaining_ttl_s": None,
        },
    )
    # The limiter's bucket map is process-wide; a leftover bucket would make the
    # rate-limit case order-dependent.
    rate_limit_mod._store._buckets.clear()
    yield
    rate_limit_mod._store._buckets.clear()


# ---------------------------------------------------------------------------
# POST /api/soundcloud/refresh
# ---------------------------------------------------------------------------


def test_refresh_requires_a_session_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unauthenticated callers are refused before any keyring read happens."""

    def _never(*_a: Any, **_kw: Any):
        raise AssertionError("the handler ran without a session token")

    monkeypatch.setattr(main_mod.sc_auth, "load_tokens", _never)

    resp = _request("POST", "/api/soundcloud/refresh")
    assert resp.status_code == 401


def test_refresh_ok_returns_status_only(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def _refresh(**kwargs: Any) -> str:
        seen.update(kwargs)
        return NEW_ACCESS

    monkeypatch.setattr(main_mod.sc_auth, "load_tokens", _tokens)
    monkeypatch.setattr(main_mod.sc_auth, "refresh", _refresh)

    resp = _request("POST", "/api/soundcloud/refresh", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json() == {"status": "refreshed"}
    # The token a caller just had rejected is handed to the single-flight refresh so a
    # racing second caller gets the winner's token instead of burning the rotation.
    assert seen["stale_token"] == ACCESS
    _assert_no_secrets(resp)


def test_refresh_maps_auth_expired_to_401(monkeypatch: pytest.MonkeyPatch) -> None:
    def _rejected(**_kw: Any) -> str:
        raise AuthExpiredError("SoundCloud refused the refresh token (HTTP 401, invalid_grant).")

    monkeypatch.setattr(main_mod.sc_auth, "load_tokens", _tokens)
    monkeypatch.setattr(main_mod.sc_auth, "refresh", _rejected)

    resp = _request("POST", "/api/soundcloud/refresh", headers=AUTH)
    assert resp.status_code == 401
    assert resp.json()["status"] == "expired"
    _assert_no_secrets(resp)


def test_refresh_maps_transient_failure_to_503(monkeypatch: pytest.MonkeyPatch) -> None:
    """A network fault must not read as "signed out" — the stored login is intact."""

    def _unreachable(**_kw: Any) -> str:
        raise TransientRefreshError("SoundCloud token endpoint unreachable (ConnectionError).")

    monkeypatch.setattr(main_mod.sc_auth, "load_tokens", _tokens)
    monkeypatch.setattr(main_mod.sc_auth, "refresh", _unreachable)

    resp = _request("POST", "/api/soundcloud/refresh", headers=AUTH)
    assert resp.status_code == 503
    assert resp.json()["status"] == "unavailable"
    _assert_no_secrets(resp)


def test_refresh_without_stored_tokens_is_401(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nothing stored → `refresh` raises AuthExpiredError; the UI must offer a login."""

    def _nothing(**kwargs: Any) -> str:
        assert kwargs["stale_token"] is None
        raise AuthExpiredError("No SoundCloud refresh token stored. Sign in again.")

    monkeypatch.setattr(main_mod.sc_auth, "refresh", _nothing)

    resp = _request("POST", "/api/soundcloud/refresh", headers=AUTH)
    assert resp.status_code == 401
    assert resp.json()["status"] == "expired"


def test_refresh_is_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same bucket as auth-token: burst 10, then 429."""
    monkeypatch.setattr(main_mod.sc_auth, "load_tokens", _tokens)
    monkeypatch.setattr(main_mod.sc_auth, "refresh", lambda **_kw: NEW_ACCESS)

    codes = [
        _request("POST", "/api/soundcloud/refresh", headers=AUTH, client=REMOTE_CLIENT).status_code
        for _ in range(REFRESH_BURST + 1)
    ]
    assert codes[:REFRESH_BURST] == [200] * REFRESH_BURST
    assert codes[REFRESH_BURST] == 429


# ---------------------------------------------------------------------------
# POST /api/soundcloud/auth-token
# ---------------------------------------------------------------------------


def test_auth_token_stores_the_full_triple(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[Any, ...]] = []

    def _store(access: str, refresh: str | None = None, expires_in: Any = None, **_kw: Any):
        calls.append((access, refresh, expires_in))
        return StoreResult(tokens=_tokens(access, refresh), persistent=True)

    monkeypatch.setattr(main_mod.sc_auth, "store_tokens", _store)

    resp = _request(
        "POST",
        "/api/soundcloud/auth-token",
        json={"token": ACCESS, "refresh_token": REFRESH, "expires_in": 3600},
        headers=AUTH,
    )
    assert resp.status_code == 200
    assert calls == [(ACCESS, REFRESH, 3600)]
    body = resp.json()
    assert body["status"] == "success"
    assert body["persistent"] is True
    assert body["refreshable"] is True
    _assert_no_secrets(resp)


def test_auth_token_without_refresh_half_reports_unrefreshable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An old frontend posts one field. It still works — and must not claim renewal."""
    monkeypatch.setattr(
        main_mod.sc_auth,
        "store_tokens",
        lambda access, refresh=None, expires_in=None, **_kw: StoreResult(
            tokens=_tokens(access, None), persistent=True
        ),
    )

    resp = _request("POST", "/api/soundcloud/auth-token", json={"token": ACCESS}, headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["refreshable"] is False


def test_auth_token_empty_clears_every_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    cleared: list[bool] = []
    monkeypatch.setattr(main_mod.sc_auth, "clear_tokens", lambda: cleared.append(True))

    def _never(*_a: Any, **_kw: Any):
        raise AssertionError("logout must not store anything")

    monkeypatch.setattr(main_mod.sc_auth, "store_tokens", _never)

    resp = _request("POST", "/api/soundcloud/auth-token", json={"token": ""}, headers=AUTH)
    assert resp.status_code == 200
    assert resp.json() == {"status": "success", "persistent": False, "refreshable": False}
    assert cleared == [True]


def test_auth_token_rejects_an_out_of_range_lifetime(monkeypatch: pytest.MonkeyPatch) -> None:
    def _never(*_a: Any, **_kw: Any):
        raise AssertionError("a rejected body must not reach the keyring")

    monkeypatch.setattr(main_mod.sc_auth, "store_tokens", _never)

    resp = _request(
        "POST",
        "/api/soundcloud/auth-token",
        json={"token": ACCESS, "expires_in": 10},
        headers=AUTH,
    )
    assert resp.status_code == 422


def test_auth_token_requires_a_session_token(monkeypatch: pytest.MonkeyPatch) -> None:
    def _never(*_a: Any, **_kw: Any):
        raise AssertionError("the handler ran without a session token")

    monkeypatch.setattr(main_mod.sc_auth, "store_tokens", _never)

    resp = _request("POST", "/api/soundcloud/auth-token", json={"token": ACCESS})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/soundcloud/auth-status
# ---------------------------------------------------------------------------


def test_auth_status_reports_remaining_lifetime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        main_mod.sc_auth,
        "token_status",
        lambda: {
            "authenticated": True,
            "refreshable": True,
            "source": "oauth",
            "expires_at": 2_000_000_000.0,
            "remaining_ttl_s": 2400,
        },
    )

    resp = _request("GET", "/api/soundcloud/auth-status")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data == {
        "authenticated": True,
        "refreshable": True,
        "source": "oauth",
        "expires_in_s": 2400,
    }
    _assert_no_secrets(resp)


def test_auth_status_clamps_a_negative_lifetime(monkeypatch: pytest.MonkeyPatch) -> None:
    """An already-expired token reports 0 s left, never a negative number."""
    monkeypatch.setattr(
        main_mod.sc_auth,
        "token_status",
        lambda: {
            "authenticated": True,
            "refreshable": True,
            "source": "oauth",
            "expires_at": 1.0,
            "remaining_ttl_s": -900,
        },
    )

    resp = _request("GET", "/api/soundcloud/auth-status")
    assert resp.json()["data"]["expires_in_s"] == 0


def test_auth_status_legacy_session_has_no_known_lifetime(monkeypatch: pytest.MonkeyPatch) -> None:
    """A pre-refresh login carries no expiry — `null`, never a made-up number."""
    monkeypatch.setattr(
        main_mod.sc_auth,
        "token_status",
        lambda: {
            "authenticated": True,
            "refreshable": False,
            "source": "legacy",
            "expires_at": None,
            "remaining_ttl_s": None,
        },
    )

    resp = _request("GET", "/api/soundcloud/auth-status")
    data = resp.json()["data"]
    assert data["authenticated"] is True
    assert data["refreshable"] is False
    assert data["expires_in_s"] is None
