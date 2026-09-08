"""Tests for `app/soundcloud_auth.py` — token store + silent refresh.

Pins the persistent-login contract (docs/research/research/evaluated_soundcloud-persistent-login.md,
Option A): one atomic blob write, legacy-key mirror, single-flight refresh, the
two failure classes (rejected → cleared + AuthExpiredError; transient → blob kept),
the legacy-only fallback, and the never-log rule for every secret.

No real keyring (a dict-backed stand-in is installed on the module), no network
(`requests.post` is replaced by a scripted recorder; the default stub refuses every
call), no credentials (env vars are set to obvious fakes), and a controllable clock.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

import pytest
import requests

from app import soundcloud_auth as sc_auth
from app.soundcloud_api import AuthExpiredError

ACCESS = "ACCESS-TOKEN-ORIGINAL-DO-NOT-LOG-a1b2c3d4"
REFRESH = "REFRESH-TOKEN-ORIGINAL-DO-NOT-LOG-e5f6g7h8"
NEW_ACCESS = "ACCESS-TOKEN-ROTATED-DO-NOT-LOG-i9j0k1l2"
NEW_REFRESH = "REFRESH-TOKEN-ROTATED-DO-NOT-LOG-m3n4o5p6"
CLIENT_ID = "fake-client-id-0123456789abcdef"
CLIENT_SECRET = "FAKE-CLIENT-SECRET-DO-NOT-LOG-q7r8s9t0"
SECRETS = (ACCESS, REFRESH, NEW_ACCESS, NEW_REFRESH, CLIENT_SECRET)

T0 = 1_700_000_000.0

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class FakeKeyring:
    """Dict-backed keyring that records every write and can refuse long values."""

    def __init__(self, *, max_len: int | None = None) -> None:
        self.store: dict[str, str] = {}
        self.set_calls: list[tuple[str, str]] = []
        self.delete_calls: list[str] = []
        self.max_len = max_len

    def get_password(self, service: str, username: str) -> str | None:
        assert service == sc_auth.KEYRING_SERVICE
        return self.store.get(username)

    def set_password(self, service: str, username: str, value: str) -> None:
        assert service == sc_auth.KEYRING_SERVICE
        self.set_calls.append((username, value))
        if self.max_len is not None and len(value) > self.max_len:
            raise OSError("CredWrite: The stub received bad data.")
        self.store[username] = value

    def delete_password(self, service: str, username: str) -> None:
        assert service == sc_auth.KEYRING_SERVICE
        self.delete_calls.append(username)
        if username not in self.store:
            raise KeyError(username)
        del self.store[username]


_NO_JSON = object()


class FakeResponse:
    def __init__(self, status_code: int, json_data: Any = _NO_JSON) -> None:
        self.status_code = status_code
        self._json = json_data
        self.text = "" if json_data is _NO_JSON else json.dumps(json_data)

    def json(self) -> Any:
        if self._json is _NO_JSON:
            raise ValueError("No JSON object could be decoded")
        return self._json


class PostRecorder:
    """Scripted `requests.post`: returns responses in order, records every call."""

    def __init__(self, responses: list[Any], *, delay_s: float = 0.0) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []
        self.delay_s = delay_s
        self._lock = threading.Lock()

    def __call__(self, url, data=None, headers=None, timeout=None, proxies=None):
        with self._lock:
            self.calls.append({"url": url, "data": data, "headers": headers, "timeout": timeout})
            if not self._responses:
                raise AssertionError(f"unscripted POST to {url}")
            nxt = self._responses.pop(0)
        if self.delay_s:
            time.sleep(self.delay_s)
        if isinstance(nxt, BaseException):
            raise nxt
        return nxt


def _ok_rotation(
    *, refresh_token: str | None = NEW_REFRESH, expires_in: Any = 3600
) -> FakeResponse:
    body: dict[str, Any] = {
        "access_token": NEW_ACCESS,
        "token_type": "bearer",
        "expires_in": expires_in,
        "scope": "",
    }
    if refresh_token is not None:
        body["refresh_token"] = refresh_token
    return FakeResponse(200, body)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def clock(monkeypatch):
    state = {"t": T0}
    monkeypatch.setattr(sc_auth, "_now", lambda: state["t"])
    return state


@pytest.fixture
def kr(monkeypatch, clock):
    fake = FakeKeyring()
    monkeypatch.setattr(sc_auth, "keyring", fake)
    monkeypatch.setenv("SOUNDCLOUD_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("SOUNDCLOUD_CLIENT_SECRET", CLIENT_SECRET)
    monkeypatch.setattr(sc_auth, "_get_proxy", lambda: None)
    # No network by default — any unexpected refresh fails the test loudly.
    monkeypatch.setattr(sc_auth.requests, "post", PostRecorder([]))
    return fake


@pytest.fixture
def post(monkeypatch):
    def install(responses: list[Any], *, delay_s: float = 0.0) -> PostRecorder:
        recorder = PostRecorder(responses, delay_s=delay_s)
        monkeypatch.setattr(sc_auth.requests, "post", recorder)
        return recorder

    return install


def _blob(kr: FakeKeyring) -> dict[str, Any]:
    return json.loads(kr.store[sc_auth.KEYRING_SC_OAUTH])


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


def test_store_writes_one_blob_and_mirrors_legacy(kr):
    result = sc_auth.store_tokens(ACCESS, REFRESH, 3600, scope="non-expiring")

    assert result.persistent is True
    assert [name for name, _ in kr.set_calls] == [
        sc_auth.KEYRING_SC_OAUTH,
        sc_auth.KEYRING_SC_TOKEN,
    ]
    blob = _blob(kr)
    assert blob == {
        "access_token": ACCESS,
        "refresh_token": REFRESH,
        "expires_at": int(T0 + 3600),
        "obtained_at": int(T0),
        "scope": "non-expiring",
    }
    assert kr.store[sc_auth.KEYRING_SC_TOKEN] == ACCESS
    assert result.tokens.expires_at == T0 + 3600


def test_store_without_expires_in_assumes_documented_hour(kr):
    sc_auth.store_tokens(ACCESS, REFRESH)
    assert _blob(kr)["expires_at"] == int(T0 + sc_auth.DEFAULT_EXPIRES_IN_S)


def test_store_rejects_empty_access_token(kr):
    with pytest.raises(ValueError):
        sc_auth.store_tokens("   ")
    assert kr.set_calls == []


def test_blob_too_large_for_backend_keeps_session_in_legacy_key(kr, caplog):
    """Windows Credential Manager caps one entry at 1280 UTF-16 chars and keyring
    does not chunk. A refused blob must not crash, must not leave a stale blob,
    and must still mirror the access token so the current session works."""
    kr.max_len = 1280
    big_access = "A" * 900
    big_refresh = "R" * 900
    with caplog.at_level(logging.DEBUG, logger=sc_auth.__name__):
        result = sc_auth.store_tokens(big_access, big_refresh, 3600)

    assert result.persistent is False
    assert sc_auth.KEYRING_SC_OAUTH not in kr.store
    assert kr.store[sc_auth.KEYRING_SC_TOKEN] == big_access
    assert any("outcome=blob_write_failed" in r.getMessage() for r in caplog.records)
    assert sc_auth.get_access_token() == big_access
    assert sc_auth.token_status()["refreshable"] is False


def test_clear_removes_both_keys_and_tolerates_missing(kr):
    sc_auth.store_tokens(ACCESS, REFRESH, 3600)
    sc_auth.clear_tokens()
    assert kr.store == {}
    sc_auth.clear_tokens()  # second call: nothing to delete, must not raise
    assert sc_auth.get_access_token() is None


def test_constants_match_main_keyring_names():
    from app import main as main_mod

    assert sc_auth.KEYRING_SERVICE == main_mod.KEYRING_SERVICE
    assert sc_auth.KEYRING_SC_TOKEN == main_mod.KEYRING_SC_TOKEN


# ---------------------------------------------------------------------------
# get_access_token — proactive path
# ---------------------------------------------------------------------------


def test_get_returns_without_refresh_when_ttl_ample(kr, clock):
    sc_auth.store_tokens(ACCESS, REFRESH, 3600)
    clock["t"] = T0 + 3600 - sc_auth.DEFAULT_MIN_TTL_S - 1
    assert sc_auth.get_access_token() == ACCESS  # default stub would raise on any POST


def test_get_refreshes_inside_min_ttl(kr, clock, post):
    sc_auth.store_tokens(ACCESS, REFRESH, 3600)
    recorder = post([_ok_rotation()])
    clock["t"] = T0 + 3600 - 60

    token = sc_auth.get_access_token()

    assert token == NEW_ACCESS
    assert len(recorder.calls) == 1
    call = recorder.calls[0]
    assert call["url"] == sc_auth.SC_TOKEN_URL == "https://secure.soundcloud.com/oauth/token"
    assert call["data"] == {
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": REFRESH,
    }
    assert call["timeout"] == sc_auth.SC_REFRESH_TIMEOUT_S
    blob = _blob(kr)
    assert blob["access_token"] == NEW_ACCESS
    assert blob["refresh_token"] == NEW_REFRESH
    assert blob["expires_at"] == int(clock["t"] + 3600)
    assert kr.store[sc_auth.KEYRING_SC_TOKEN] == NEW_ACCESS


def test_refresh_writes_blob_before_mirroring_legacy(kr, clock, post):
    sc_auth.store_tokens(ACCESS, REFRESH, 3600)
    kr.set_calls.clear()
    post([_ok_rotation()])
    clock["t"] = T0 + 3600

    sc_auth.get_access_token()

    assert [name for name, _ in kr.set_calls] == [
        sc_auth.KEYRING_SC_OAUTH,
        sc_auth.KEYRING_SC_TOKEN,
    ]


def test_refresh_keeps_old_refresh_token_when_response_omits_it(kr, clock, post):
    sc_auth.store_tokens(ACCESS, REFRESH, 3600)
    post([_ok_rotation(refresh_token=None, expires_in=None)])
    clock["t"] = T0 + 3600

    assert sc_auth.get_access_token() == NEW_ACCESS
    blob = _blob(kr)
    assert blob["refresh_token"] == REFRESH
    assert blob["expires_at"] == int(clock["t"] + sc_auth.DEFAULT_EXPIRES_IN_S)


def test_get_returns_none_when_nothing_stored(kr):
    assert sc_auth.get_access_token() is None
    assert sc_auth.token_status() == {
        "authenticated": False,
        "refreshable": False,
        "source": None,
        "expires_at": None,
        "remaining_ttl_s": None,
    }


# ---------------------------------------------------------------------------
# Single-flight
# ---------------------------------------------------------------------------


def test_ten_concurrent_callers_trigger_exactly_one_refresh(kr, clock, post):
    sc_auth.store_tokens(ACCESS, REFRESH, 3600)
    recorder = post([_ok_rotation()], delay_s=0.05)
    clock["t"] = T0 + 3600 + 10  # expired

    n = 10
    barrier = threading.Barrier(n)
    results: list[str | None] = [None] * n
    errors: list[BaseException] = []

    def worker(i: int) -> None:
        try:
            barrier.wait(timeout=5)
            results[i] = sc_auth.get_access_token()
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert errors == []
    assert results == [NEW_ACCESS] * n
    assert len(recorder.calls) == 1


def test_refresh_with_stale_token_skips_post_when_already_rotated(kr, clock, post):
    sc_auth.store_tokens(NEW_ACCESS, NEW_REFRESH, 3600)  # someone else already rotated
    assert sc_auth.refresh(stale_token=ACCESS) == NEW_ACCESS  # default stub: any POST raises


def test_refresh_with_stale_token_posts_even_when_clock_says_fresh(kr, clock, post):
    """A server 401 outranks the local clock."""
    sc_auth.store_tokens(ACCESS, REFRESH, 3600)
    recorder = post([_ok_rotation()])
    assert sc_auth.refresh(stale_token=ACCESS) == NEW_ACCESS
    assert len(recorder.calls) == 1


# ---------------------------------------------------------------------------
# Rejected refresh → cleared + AuthExpiredError
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "response",
    [
        FakeResponse(400, {"error": "invalid_grant", "error_description": "expired"}),
        FakeResponse(401, {"error": "invalid_client"}),
        FakeResponse(400),  # non-JSON body
    ],
)
def test_rejected_refresh_clears_both_keys_and_raises(kr, clock, post, response):
    sc_auth.store_tokens(ACCESS, REFRESH, 3600)
    post([response])
    clock["t"] = T0 + 3600

    with pytest.raises(AuthExpiredError):
        sc_auth.get_access_token()

    assert sc_auth.KEYRING_SC_OAUTH not in kr.store
    assert sc_auth.KEYRING_SC_TOKEN not in kr.store
    assert sc_auth.get_access_token() is None


def test_refresh_without_refresh_token_raises_auth_expired_without_clearing_legacy(kr):
    kr.store[sc_auth.KEYRING_SC_TOKEN] = ACCESS
    with pytest.raises(AuthExpiredError):
        sc_auth.refresh()
    assert kr.store[sc_auth.KEYRING_SC_TOKEN] == ACCESS


# ---------------------------------------------------------------------------
# Transient failures → blob kept
# ---------------------------------------------------------------------------


def test_network_error_keeps_blob_and_raises_transient(kr, clock, post):
    sc_auth.store_tokens(ACCESS, REFRESH, 3600)
    before = dict(kr.store)
    post([requests.ConnectionError("boom")])
    clock["t"] = T0 + 3600 + 5  # past expiry → nothing usable to serve

    with pytest.raises(sc_auth.TransientRefreshError):
        sc_auth.get_access_token()

    assert kr.store == before
    assert kr.delete_calls == []


def test_transient_failure_inside_margin_serves_stale_token(kr, clock, post, caplog):
    sc_auth.store_tokens(ACCESS, REFRESH, 3600)
    post([requests.Timeout("slow")])
    clock["t"] = T0 + 3600 - 30  # inside min_ttl, not yet expired

    with caplog.at_level(logging.WARNING, logger=sc_auth.__name__):
        assert sc_auth.get_access_token() == ACCESS
    assert any("outcome=stale_served" in r.getMessage() for r in caplog.records)
    assert _blob(kr)["access_token"] == ACCESS


@pytest.mark.parametrize(
    "response",
    [
        FakeResponse(500, {"error": "server_error"}),
        FakeResponse(429, {"errors": [{"meta": {"rate_limit": 1, "reset_time": "x"}}]}),
        FakeResponse(200),  # 200 but not JSON
        FakeResponse(200, {"token_type": "bearer"}),  # 200 without access_token
    ],
)
def test_server_side_problems_are_transient(kr, clock, post, response):
    sc_auth.store_tokens(ACCESS, REFRESH, 3600)
    before = dict(kr.store)
    post([response])
    clock["t"] = T0 + 3600

    with pytest.raises(sc_auth.TransientRefreshError):
        sc_auth.refresh()
    assert kr.store == before


def test_missing_client_secret_is_transient_not_logout(kr, clock, monkeypatch):
    sc_auth.store_tokens(ACCESS, REFRESH, 3600)
    monkeypatch.delenv("SOUNDCLOUD_CLIENT_SECRET")
    clock["t"] = T0 + 3600

    with pytest.raises(sc_auth.TransientRefreshError):
        sc_auth.refresh()
    assert _blob(kr)["refresh_token"] == REFRESH


# ---------------------------------------------------------------------------
# Legacy compatibility
# ---------------------------------------------------------------------------


def test_legacy_only_state_still_yields_token(kr):
    kr.store[sc_auth.KEYRING_SC_TOKEN] = ACCESS
    assert sc_auth.get_access_token() == ACCESS
    status = sc_auth.token_status()
    assert status["authenticated"] is True
    assert status["source"] == "legacy"
    assert status["refreshable"] is False
    assert ACCESS not in json.dumps(status)


def test_corrupt_blob_falls_back_to_legacy(kr, caplog):
    kr.store[sc_auth.KEYRING_SC_OAUTH] = "{not json"
    kr.store[sc_auth.KEYRING_SC_TOKEN] = ACCESS
    with caplog.at_level(logging.WARNING, logger=sc_auth.__name__):
        assert sc_auth.get_access_token() == ACCESS
    assert any("outcome=corrupt" in r.getMessage() for r in caplog.records)


def test_blob_without_access_token_is_treated_as_absent(kr):
    kr.store[sc_auth.KEYRING_SC_OAUTH] = json.dumps({"refresh_token": REFRESH})
    assert sc_auth.load_tokens() is None
    assert sc_auth.get_access_token() is None


def test_blob_without_refresh_token_is_served_unrefreshed_after_expiry(kr, clock):
    sc_auth.store_tokens(ACCESS)  # no refresh token → nothing to refresh with
    clock["t"] = T0 + 3600 + 600
    assert sc_auth.get_access_token() == ACCESS  # server stays the judge; no POST


def test_token_status_reports_expiry_without_material(kr, clock):
    sc_auth.store_tokens(ACCESS, REFRESH, 3600)
    clock["t"] = T0 + 100
    status = sc_auth.token_status()
    assert status == {
        "authenticated": True,
        "refreshable": True,
        "source": "oauth",
        "expires_at": T0 + 3600,
        "remaining_ttl_s": 3500,
    }


# ---------------------------------------------------------------------------
# Reactive backstop
# ---------------------------------------------------------------------------


def test_with_fresh_token_retries_once_after_server_401(kr, clock, post):
    sc_auth.store_tokens(ACCESS, REFRESH, 3600)
    recorder = post([_ok_rotation()])
    seen: list[str] = []

    def call(token: str) -> str:
        seen.append(token)
        if len(seen) == 1:
            raise AuthExpiredError("HTTP 401")
        return f"ok:{token}"

    assert sc_auth.with_fresh_token(call) == f"ok:{NEW_ACCESS}"
    assert seen == [ACCESS, NEW_ACCESS]
    assert len(recorder.calls) == 1
    assert _blob(kr)["access_token"] == NEW_ACCESS


def test_with_fresh_token_does_not_loop_on_second_401(kr, clock, post):
    sc_auth.store_tokens(ACCESS, REFRESH, 3600)
    recorder = post([_ok_rotation()])
    calls = 0

    def always_401(token: str) -> None:
        nonlocal calls
        calls += 1
        raise AuthExpiredError("HTTP 401")

    with pytest.raises(AuthExpiredError):
        sc_auth.with_fresh_token(always_401)
    assert calls == 2
    assert len(recorder.calls) == 1


def test_with_fresh_token_raises_when_not_connected(kr):
    with pytest.raises(AuthExpiredError):
        sc_auth.with_fresh_token(lambda token: token)


def test_with_fresh_token_concurrent_401s_share_one_refresh(kr, clock, post):
    sc_auth.store_tokens(ACCESS, REFRESH, 3600)
    recorder = post([_ok_rotation()], delay_s=0.05)
    n = 5
    barrier = threading.Barrier(n)
    results: list[str | None] = [None] * n
    errors: list[BaseException] = []

    def call(token: str) -> str:
        if token == ACCESS:
            barrier.wait(timeout=5)  # every worker holds the stale token before any refresh
            raise AuthExpiredError("HTTP 401")
        return token

    def worker(i: int) -> None:
        try:
            results[i] = sc_auth.with_fresh_token(call)
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert errors == []
    assert results == [NEW_ACCESS] * n
    assert len(recorder.calls) == 1


# ---------------------------------------------------------------------------
# Never-log rule
# ---------------------------------------------------------------------------


def test_no_secret_reaches_the_log_at_debug(kr, clock, post, caplog):
    with caplog.at_level(logging.DEBUG):
        sc_auth.store_tokens(ACCESS, REFRESH, 3600, scope="s")
        assert sc_auth.get_access_token() == ACCESS  # fresh path
        post([_ok_rotation()])
        clock["t"] = T0 + 3600  # proactive refresh path
        assert sc_auth.get_access_token() == NEW_ACCESS
        post([requests.ConnectionError("net")])
        clock["t"] += 3600 + 1  # transient path
        with pytest.raises(sc_auth.TransientRefreshError):
            sc_auth.get_access_token()
        post([FakeResponse(400, {"error": "invalid_grant"})])
        with pytest.raises(AuthExpiredError):  # rejected path
            sc_auth.get_access_token()
        kr.store[sc_auth.KEYRING_SC_TOKEN] = ACCESS
        assert sc_auth.get_access_token() == ACCESS  # legacy path
        sc_auth.clear_tokens()

    assert caplog.records, "expected op= markers at DEBUG"
    for record in caplog.records:
        text = record.getMessage() + " " + repr(record.args)
        for secret in SECRETS:
            assert secret not in text, f"secret leaked into log line: {record.getMessage()}"


def test_repr_of_token_set_hides_secrets(kr):
    tokens = sc_auth.store_tokens(ACCESS, REFRESH, 3600).tokens
    text = repr(tokens) + str(tokens)
    for secret in SECRETS:
        assert secret not in text


def test_exception_messages_carry_no_secrets(kr, clock, post):
    sc_auth.store_tokens(ACCESS, REFRESH, 3600)
    clock["t"] = T0 + 3600
    post([FakeResponse(400, {"error": "invalid_grant", "error_description": REFRESH})])
    with pytest.raises(AuthExpiredError) as info:
        sc_auth.refresh()
    for secret in SECRETS:
        assert secret not in str(info.value)
