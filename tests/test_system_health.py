"""Contract tests for ``GET /api/system/health`` -- unauth'd liveness probe.

The route is polled by tooling *before* a Bearer token exists
(``.claude/launch.json`` readiness check, ``/dev-full``, ``e2e-tester``),
so three properties are load-bearing:

1. reachable with no ``Authorization`` header (and with a bogus one)
2. leaks nothing -- no path, no DB location, no token, no user data
3. no side effects -- must not touch ``db.active_db``, whose property
   getter lazily constructs ``LiveRekordboxDB``

Driving the app: httpx ``ASGITransport`` against the live FastAPI graph;
no ``TestClient`` because the installed fastapi 0.109 + httpx 0.28 pair
mishandles the deprecated ``app=`` kwarg (same note as
``tests/test_main_security.py``).
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.database import db
from app.main import app


def _get(url: str, headers: dict[str, str] | None = None) -> httpx.Response:
    async def _go() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            return await ac.get(url, headers=headers)

    return asyncio.run(_go())


class TestHealthIsUnauthenticated:
    @pytest.mark.no_auth
    def test_no_header_is_200(self) -> None:
        r = _get("/api/system/health")
        assert r.status_code == 200, r.text

    @pytest.mark.no_auth
    def test_bogus_bearer_is_still_200(self) -> None:
        """Tooling may send a stale token; the probe must not 401."""
        r = _get("/api/system/health", headers={"Authorization": "Bearer bogus"})
        assert r.status_code == 200, r.text


class TestHealthPayloadShape:
    def test_exact_field_set(self) -> None:
        body = _get("/api/system/health").json()
        assert set(body) == {"status", "library_loaded"}

    def test_status_is_constant_ok(self) -> None:
        """Liveness != readiness: always ``ok`` while the process serves.

        Readiness rides in ``library_loaded`` -- a non-200/non-ok while
        the ANLZ scan runs would blow ``readyTimeoutMs`` in launch.json.
        """
        assert _get("/api/system/health").json()["status"] == "ok"

    def test_library_loaded_is_bool_and_tracks_db(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(db, "loaded", True, raising=False)
        assert _get("/api/system/health").json()["library_loaded"] is True
        monkeypatch.setattr(db, "loaded", False, raising=False)
        assert _get("/api/system/health").json()["library_loaded"] is False


class TestHealthLeaksNothing:
    def test_body_has_no_sensitive_substrings(self) -> None:
        body = _get("/api/system/health").text
        for needle in ("C:\\", "/Users/", "master.db", "rekordbox", "token", "Token"):
            assert needle not in body, f"health leaked {needle!r}: {body}"

    def test_response_model_filters_undeclared_fields(self) -> None:
        """``response_model`` pins the schema so future edits can't leak."""
        from app.main import HealthResponse

        assert set(HealthResponse.model_fields) == {"status", "library_loaded"}


class TestHealthHasNoSideEffects:
    def test_does_not_lazily_build_live_db(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``db.active_db`` constructs ``LiveRekordboxDB`` on first touch."""
        monkeypatch.setattr(db, "live_db", None, raising=False)
        _get("/api/system/health")
        assert db.live_db is None, "health probe constructed LiveRekordboxDB"
