"""Tests for ``app/auth.py`` -- Bearer-token session authentication.

Covers the 14 cases (a) through (n) enumerated in Step 14 of
``docs/research/implement/draftplan_security-api-auth-hardening.md``.

Phase-1-staging note: cases (f) and (g) reference behaviour that ships
in later steps (Step 4 bulk decoration of mutation routes; Step 8
removal of the legacy ``SHUTDOWN_TOKEN`` query-string scheme on
``shutdown`` / ``restart``). Those cases are present as
``pytest.skip(...)`` scaffolding so the next turn can drop the skip
gate without rewriting the test file. Cases (a)-(e), (h)-(n) all pass
today against the freshly-landed ``require_session`` dep and the
existing un-gated routes.

We deliberately avoid ``fastapi.testclient.TestClient`` because the
installed fastapi 0.109 + httpx 0.28 pair is incompatible -- same
reason as ``tests/test_security_hotfixes.py``. All requests go through
``httpx.ASGITransport`` driven by ``asyncio.run``.

The ``require_session`` dep is exercised against a **small embedded
FastAPI app** built per-test rather than the real ``app/main.py``
``app`` instance -- that keeps the auth contract under test cleanly
decoupled from the route-by-route enforcement rollout (Step 4).
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from fastapi import Depends, FastAPI

from app import auth as _auth
from app.auth import require_session
from app.main import app as real_app


def _gated_app() -> FastAPI:
    """Tiny FastAPI app with a single ``require_session``-gated route."""
    test_app = FastAPI()

    @test_app.post("/gated", dependencies=[Depends(require_session)])
    def _gated() -> dict[str, str]:
        return {"status": "ok"}

    @test_app.get("/gated-get", dependencies=[Depends(require_session)])
    def _gated_get() -> dict[str, str]:
        return {"status": "ok"}

    return test_app


def _request(
    app: FastAPI,
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    json: Any = None,
) -> httpx.Response:
    """Drive ``app`` over ``httpx.ASGITransport`` and return the response."""

    async def _go() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as ac:
            return await ac.request(method, url, headers=headers, json=json)

    return asyncio.run(_go())


class TestCaseA_NoHeader:
    def test_post_without_authorization_is_401(self) -> None:
        r = _request(_gated_app(), "POST", "/gated")
        assert r.status_code == 401
        assert r.json() == {"detail": "Unauthorized"}


class TestCaseB_WrongToken:
    def test_post_with_wrong_bearer_is_401(
        self, auth_token: dict[str, str]
    ) -> None:
        wrong = "X" * len(_auth.SESSION_TOKEN)
        r = _request(
            _gated_app(),
            "POST",
            "/gated",
            headers={"Authorization": f"Bearer {wrong}"},
        )
        assert r.status_code == 401

    def test_post_with_wrong_length_is_401(
        self, auth_token: dict[str, str]
    ) -> None:
        r = _request(
            _gated_app(),
            "POST",
            "/gated",
            headers={"Authorization": "Bearer short"},
        )
        assert r.status_code == 401


class TestCaseC_HappyPath:
    def test_post_with_correct_bearer_is_2xx(
        self, auth_token: dict[str, str]
    ) -> None:
        r = _request(
            _gated_app(), "POST", "/gated", headers=auth_token
        )
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


class TestCaseD_HeartbeatTokenLeak:
    def test_heartbeat_response_has_no_token_field(self) -> None:
        r = _request(real_app, "POST", "/api/system/heartbeat")
        assert r.status_code == 200
        body = r.json()
        assert "token" not in body
        assert body["status"] == "alive"


class TestCaseE_InitTokenAbsent:
    def test_post_init_token_is_404(self) -> None:
        r = _request(real_app, "POST", "/api/system/init-token")
        assert r.status_code == 404


class TestCaseF_SoundCloudAuthTokenGated:
    def test_sc_auth_token_without_bearer_is_401(self) -> None:
        r = _request(
            real_app,
            "POST",
            "/api/soundcloud/auth-token",
            json={"token": "anything"},
        )
        assert r.status_code == 401


class TestCaseG_LegacyShutdownTokenRemoved:
    def test_shutdown_without_bearer_is_401(self) -> None:
        r = _request(real_app, "POST", "/api/system/shutdown")
        assert r.status_code == 401

    def test_restart_without_bearer_is_401(self) -> None:
        r = _request(real_app, "POST", "/api/system/restart")
        assert r.status_code == 401


class TestCaseH_BearerWhitespace:
    def test_trailing_whitespace_in_credentials_is_accepted(
        self, auth_token: dict[str, str]
    ) -> None:
        token = _auth.SESSION_TOKEN
        r = _request(
            _gated_app(),
            "POST",
            "/gated",
            headers={"Authorization": f"Bearer {token}   "},
        )
        assert r.status_code == 200

    def test_leading_whitespace_between_scheme_and_token(
        self, auth_token: dict[str, str]
    ) -> None:
        token = _auth.SESSION_TOKEN
        r = _request(
            _gated_app(),
            "POST",
            "/gated",
            headers={"Authorization": f"Bearer    {token}"},
        )
        assert r.status_code == 200


class TestCaseI_SchemeCaseInsensitive:
    @pytest.mark.parametrize("scheme", ["bearer", "BEARER", "BeArEr"])
    def test_scheme_case_insensitive(
        self, scheme: str, auth_token: dict[str, str]
    ) -> None:
        token = _auth.SESSION_TOKEN
        r = _request(
            _gated_app(),
            "POST",
            "/gated",
            headers={"Authorization": f"{scheme} {token}"},
        )
        assert r.status_code == 200


class TestCaseJ_EmptyAuthorizationHeader:
    def test_empty_header_value_is_401(self) -> None:
        r = _request(
            _gated_app(),
            "POST",
            "/gated",
            headers={"Authorization": ""},
        )
        assert r.status_code == 401

    def test_whitespace_only_header_is_401(self) -> None:
        r = _request(
            _gated_app(),
            "POST",
            "/gated",
            headers={"Authorization": "   "},
        )
        assert r.status_code == 401

    def test_scheme_only_no_credentials_is_401(self) -> None:
        r = _request(
            _gated_app(),
            "POST",
            "/gated",
            headers={"Authorization": "Bearer"},
        )
        assert r.status_code == 401


class TestCaseK_ControlCharsRejected:
    def test_vtab_in_token_is_401(
        self, auth_token: dict[str, str]
    ) -> None:
        token = "A" * (len(_auth.SESSION_TOKEN) - 1) + "\x0b"
        r = _request(
            _gated_app(),
            "POST",
            "/gated",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 401

    def test_del_char_in_token_is_401(
        self, auth_token: dict[str, str]
    ) -> None:
        token = "A" * (len(_auth.SESSION_TOKEN) - 1) + "\x7f"
        r = _request(
            _gated_app(),
            "POST",
            "/gated",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 401


class TestCaseL_WrongScheme:
    @pytest.mark.parametrize(
        "header",
        [
            "Basic dXNlcjpwYXNz",
            "Digest username=foo, realm=bar",
            "Token abc123",
            "Bear abc123",
        ],
    )
    def test_non_bearer_scheme_is_401(
        self, header: str, auth_token: dict[str, str]
    ) -> None:
        r = _request(
            _gated_app(),
            "POST",
            "/gated",
            headers={"Authorization": header},
        )
        assert r.status_code == 401


class TestCaseM_OptionsPreflight:
    def test_options_preflight_short_circuits_before_auth(self) -> None:
        from fastapi.middleware.cors import CORSMiddleware

        test_app = _gated_app()
        test_app.add_middleware(
            CORSMiddleware,
            allow_origins=["http://localhost:5173"],
            allow_methods=["*"],
            allow_headers=["*"],
        )
        r = _request(
            test_app,
            "OPTIONS",
            "/gated",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization",
            },
        )
        assert r.status_code == 200
        assert "access-control-allow-origin" in {
            k.lower() for k in r.headers
        }


class TestCaseN_UngatedAcceptsAuthHeader:
    def test_heartbeat_with_bearer_header_still_2xx(
        self, auth_token: dict[str, str]
    ) -> None:
        r = _request(
            real_app, "POST", "/api/system/heartbeat", headers=auth_token
        )
        assert r.status_code == 200
