"""Tests for GET /api/soundcloud/auth-status.

Pins the contract, now that the route reads the `soundcloud_auth` store instead of a
bare keyring entry:

  - OAuth blob stored          -> 200 {authenticated: true, refreshable: true,
                                       source: "oauth", expires_in_s: <int>}
  - legacy bare token only     -> 200 {authenticated: true, refreshable: false,
                                       source: "legacy", expires_in_s: null}
  - nothing stored             -> 200 {authenticated: false, ...}
  - keyring backend raises     -> 200 {authenticated: false} + WARN log
                                  (degrade gracefully, never 500)

`refreshable` is the one flag that entitles the UI to say the session renews itself;
`expires_in_s` is `null` when no expiry was ever stored — never a guessed number.

The endpoint is unauthenticated by design — matches the other read-only SC GETs
(/tasks, /history, /check, /settings). No token material is in the response.

Driving the app via httpx ASGITransport (same pattern as test_main_security.py) —
TestClient is broken on the installed fastapi 0.109 / httpx 0.28 pair.
"""

from __future__ import annotations

import asyncio
import logging

import httpx
import pytest

from app import main as main_mod
from app import soundcloud_auth as sc_auth
from app.main import app


def _get(url: str) -> httpx.Response:
    async def _go() -> httpx.Response:
        transport = httpx.ASGITransport(
            app=app,
            client=("127.0.0.1", 12345),
            raise_app_exceptions=False,
        )
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            return await ac.get(url)

    return asyncio.run(_go())


class _StubKeyring:
    """Dict-backed keyring stand-in; optionally raises on read."""

    def __init__(self, *, raises: type | None = None):
        self.store: dict[str, str] = {}
        self._raises = raises

    def get_password(self, _service: str, username: str) -> str | None:
        if self._raises:
            raise self._raises("keyring stub: simulated failure")
        return self.store.get(username)

    def set_password(self, _service: str, username: str, value: str) -> None:
        self.store[username] = value

    def delete_password(self, _service: str, username: str) -> None:
        self.store.pop(username, None)


@pytest.fixture
def patched_keyring(monkeypatch: pytest.MonkeyPatch):
    """Install a controllable keyring on `soundcloud_auth` — the module the route reads.

    Returns the stub so a test can seed it directly (legacy key) or via
    `sc_auth.store_tokens` (real blob).
    """

    def install(*, raises: type | None = None) -> _StubKeyring:
        stub = _StubKeyring(raises=raises)
        monkeypatch.setattr(sc_auth, "keyring", stub)
        return stub

    return install


def test_reports_a_renewable_oauth_session(patched_keyring):
    patched_keyring()
    sc_auth.store_tokens("ya29.fake-oauth-token", "fake-refresh-token", 3600)

    resp = _get("/api/soundcloud/auth-status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    data = body["data"]
    assert data["authenticated"] is True
    assert data["refreshable"] is True
    assert data["source"] == "oauth"
    # Stored one second ago at the latest, so the remaining life is just under an hour.
    assert 3500 <= data["expires_in_s"] <= 3600


def test_legacy_token_is_authenticated_but_not_refreshable(patched_keyring):
    """A login stored before the refresh work shipped must not log the user out —
    and must not claim it renews itself either."""
    stub = patched_keyring()
    stub.store[sc_auth.KEYRING_SC_TOKEN] = "ya29.legacy-token"

    data = _get("/api/soundcloud/auth-status").json()["data"]
    assert data["authenticated"] is True
    assert data["refreshable"] is False
    assert data["source"] == "legacy"
    assert data["expires_in_s"] is None


def test_authenticated_false_when_nothing_stored(patched_keyring):
    patched_keyring()
    data = _get("/api/soundcloud/auth-status").json()["data"]
    assert data["authenticated"] is False
    assert data["refreshable"] is False
    assert data["source"] is None
    assert data["expires_in_s"] is None


def test_authenticated_false_when_token_empty_string(patched_keyring):
    """Empty-string legacy token is treated as absent."""
    stub = patched_keyring()
    stub.store[sc_auth.KEYRING_SC_TOKEN] = ""

    assert _get("/api/soundcloud/auth-status").json()["data"]["authenticated"] is False


def test_corrupt_blob_reads_as_signed_out(patched_keyring):
    """Half-written or garbage blob → signed out, never a half-trusted session."""
    stub = patched_keyring()
    stub.store[sc_auth.KEYRING_SC_OAUTH] = "{not-json"

    data = _get("/api/soundcloud/auth-status").json()["data"]
    assert data["authenticated"] is False
    assert data["source"] is None


def test_degrades_when_keyring_raises(patched_keyring, caplog):
    """A broken keyring backend (locked session, missing libsecret) must return
    200 + authenticated=false, not a 500. The UI shows the login button."""
    patched_keyring(raises=RuntimeError)
    with caplog.at_level(logging.WARNING):
        resp = _get("/api/soundcloud/auth-status")
    assert resp.status_code == 200
    assert resp.json()["data"]["authenticated"] is False
    # The failure is logged with the exception *type* only — no token material and no
    # backend message that could carry one.
    assert any("op=sc_token_load outcome=keyring_error" in r.message for r in caplog.records)


def test_route_survives_a_raising_token_status(monkeypatch: pytest.MonkeyPatch, caplog):
    """Belt-and-braces: even if the store itself throws, the route answers 200."""

    def _boom() -> dict[str, object]:
        raise RuntimeError("store exploded")

    monkeypatch.setattr(main_mod.sc_auth, "token_status", _boom)
    with caplog.at_level(logging.WARNING):
        resp = _get("/api/soundcloud/auth-status")
    assert resp.status_code == 200
    assert resp.json()["data"]["authenticated"] is False
    assert any("auth-status keyring lookup failed" in r.message for r in caplog.records)


def test_response_never_contains_token_material(patched_keyring):
    """Belt-and-suspenders: the payload must never leak a stored secret."""
    secret = "MY-VERY-SECRET-OAUTH-TOKEN-DO-NOT-LEAK"
    refresh_secret = "MY-VERY-SECRET-REFRESH-TOKEN-DO-NOT-LEAK"
    patched_keyring()
    sc_auth.store_tokens(secret, refresh_secret, 3600)

    resp = _get("/api/soundcloud/auth-status")
    assert resp.status_code == 200
    assert secret not in resp.text
    assert refresh_secret not in resp.text
