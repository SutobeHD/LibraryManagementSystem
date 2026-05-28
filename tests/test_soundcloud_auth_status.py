"""Tests for GET /api/soundcloud/auth-status.

Pins the contract:

  - Token present in keyring        -> 200 {authenticated: true}
  - Token absent                    -> 200 {authenticated: false}
  - Keyring backend raises          -> 200 {authenticated: false} + WARN log
                                       (degrade gracefully, never 500)

The endpoint is unauthenticated by design — matches the other read-only
SC GETs (/tasks, /history, /check, /settings). No token material is in
the response, so there's no PII to gate.

Driving the app via httpx ASGITransport (same pattern as
test_main_security.py) — TestClient is broken on the installed
fastapi 0.109 / httpx 0.28 pair.
"""

from __future__ import annotations

import asyncio
import logging

import httpx
import pytest

from app import main as main_mod
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
    """Minimal keyring stand-in: configurable get_password behaviour."""

    def __init__(self, *, value: str | None = None, raises: type | None = None):
        self._value = value
        self._raises = raises

    def get_password(self, service, username):
        if self._raises:
            raise self._raises("keyring stub: simulated failure")
        return self._value

    # the endpoint only calls get_password; the other methods aren't reached
    def set_password(self, *a, **k): ...  # pragma: no cover
    def delete_password(self, *a, **k): ...  # pragma: no cover


@pytest.fixture
def patched_keyring(monkeypatch):
    """Swap out the module-level keyring with one we control per test.

    Returns a callable that installs the stub — test passes
    `(value=..., raises=...)` to configure behaviour.
    """

    def install(*, value=None, raises=None):
        monkeypatch.setattr(main_mod, "keyring", _StubKeyring(value=value, raises=raises))

    return install


def test_authenticated_true_when_token_present(patched_keyring):
    patched_keyring(value="ya29.fake-oauth-token")
    resp = _get("/api/soundcloud/auth-status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["data"]["authenticated"] is True


def test_authenticated_false_when_token_absent(patched_keyring):
    patched_keyring(value=None)
    resp = _get("/api/soundcloud/auth-status")
    assert resp.status_code == 200
    assert resp.json()["data"]["authenticated"] is False


def test_authenticated_false_when_token_empty_string(patched_keyring):
    """Empty-string token is treated as absent — bool('') is False."""
    patched_keyring(value="")
    resp = _get("/api/soundcloud/auth-status")
    assert resp.status_code == 200
    assert resp.json()["data"]["authenticated"] is False


def test_degrades_when_keyring_raises(patched_keyring, caplog):
    """A broken keyring backend (locked session, missing libsecret) must
    return 200 + authenticated=false, not a 500. The UI shows the
    login button instead of an error screen."""
    patched_keyring(raises=RuntimeError)
    with caplog.at_level(logging.WARNING):
        resp = _get("/api/soundcloud/auth-status")
    assert resp.status_code == 200
    assert resp.json()["data"]["authenticated"] is False
    # Confirm the failure was logged (no token material in the log line —
    # only the exception message reaches WARN).
    assert any("auth-status keyring lookup failed" in r.message for r in caplog.records)


def test_response_never_contains_token_material(patched_keyring):
    """Belt-and-suspenders: the response payload must never leak the
    secret value, even when authenticated."""
    secret = "MY-VERY-SECRET-OAUTH-TOKEN-DO-NOT-LEAK"
    patched_keyring(value=secret)
    resp = _get("/api/soundcloud/auth-status")
    assert resp.status_code == 200
    assert secret not in resp.text
