"""Regression guard: no SoundCloud log record may carry a `client_id`.

`_sc_paginate` follows a SERVER-SUPPLIED `next_href` into `_sc_get`, and the
unauthenticated path puts `client_id` in the params dict. Every error branch in
`_sc_get` used to render one of those verbatim. These tests drive the branches
that leaked and assert on `caplog` — the formatter is bypassed, so this pins the
call sites themselves, not a downstream scrub.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

import pytest
import requests

from app.soundcloud_api import NotFoundError, _log_params, _sc_get, _scrub_secrets

SECRET = "SUPERSECRET32CHARSAAAAAAAAAAAAAA"
CURSOR_URL = f"https://api.soundcloud.com/users/1/tracks?cursor=abc&client_id={SECRET}"


class _FakeResponse:
    def __init__(self, status_code: int, json_data: Any | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._json = json_data
        self.text = text
        self.headers: dict[str, str] = {}

    def json(self) -> Any:
        if self._json is None:
            raise ValueError("No JSON object could be decoded")
        return self._json

    def raise_for_status(self) -> None:
        raise AssertionError("raise_for_status leaks the prepared url — must not be called")


@pytest.fixture(autouse=True)
def _suppress_sleep(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _t: None)


_LEAK_RE = re.compile(r"(client_id|oauth_token|access_token|secret_token)=(?!…)", re.IGNORECASE)


def _assert_clean(caplog: pytest.LogCaptureFixture) -> None:
    for record in caplog.records:
        rendered = record.getMessage()
        assert SECRET not in rendered, f"secret leaked into log: {rendered}"
        assert not _LEAK_RE.search(rendered), f"unredacted credential in log: {rendered}"


def test_non_json_200_does_not_log_client_id(monkeypatch, caplog) -> None:
    monkeypatch.setattr(
        "app.soundcloud_api.requests.get",
        lambda *a, **kw: _FakeResponse(200, text="<html>SC down</html>"),
    )
    with caplog.at_level(logging.DEBUG, logger="app.soundcloud_api"), pytest.raises(ValueError):
        _sc_get(CURSOR_URL, headers={}, params={"client_id": SECRET})
    _assert_clean(caplog)


def test_502_does_not_log_client_id_and_raises_sanitized_http_error(monkeypatch, caplog) -> None:
    monkeypatch.setattr(
        "app.soundcloud_api.requests.get",
        lambda *a, **kw: _FakeResponse(502, text="bad gateway"),
    )
    with (
        caplog.at_level(logging.DEBUG, logger="app.soundcloud_api"),
        pytest.raises(requests.HTTPError) as excinfo,
    ):
        _sc_get(CURSOR_URL, headers={}, params={"client_id": SECRET})
    _assert_clean(caplog)
    assert SECRET not in str(excinfo.value)
    # `response=` must survive — callers read exc.response.status_code
    assert excinfo.value.response is not None
    assert excinfo.value.response.status_code == 502


def test_network_error_does_not_log_client_id(monkeypatch, caplog) -> None:
    def _boom(*_a, **_kw):
        raise requests.ConnectionError(
            f"HTTPSConnectionPool(host='api.soundcloud.com'): Max retries exceeded "
            f"with url: /users/1/tracks?cursor=abc&client_id={SECRET}"
        )

    monkeypatch.setattr("app.soundcloud_api.requests.get", _boom)
    with (
        caplog.at_level(logging.DEBUG, logger="app.soundcloud_api"),
        pytest.raises(requests.ConnectionError),
    ):
        _sc_get(CURSOR_URL, headers={}, params={"client_id": SECRET}, max_retries=1)
    _assert_clean(caplog)


def test_404_does_not_log_client_id(monkeypatch, caplog) -> None:
    monkeypatch.setattr(
        "app.soundcloud_api.requests.get",
        lambda *a, **kw: _FakeResponse(404, text="not found"),
    )
    with caplog.at_level(logging.DEBUG, logger="app.soundcloud_api"), pytest.raises(NotFoundError):
        _sc_get(CURSOR_URL, headers={}, params={"client_id": SECRET}, auth_404=False)
    _assert_clean(caplog)


def test_log_params_redacts_credential_keys_only() -> None:
    out = _log_params({"client_id": SECRET, "oauth_token": SECRET, "limit": 50})
    assert out == {"client_id": "…", "oauth_token": "…", "limit": 50}
    assert _log_params(None) == {}


def test_scrub_secrets_strips_query_credentials() -> None:
    assert SECRET not in _scrub_secrets(f"boom for url: /x?cursor=1&client_id={SECRET}")
    assert "cursor=1" in _scrub_secrets(f"boom for url: /x?cursor=1&client_id={SECRET}")
