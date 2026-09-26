"""SoundCloud OAuth token store + silent refresh (persistent login, Option A).

The sidecar owns the token lifecycle. Callers ask `get_access_token()` for a
token that is good for at least `min_ttl_s` more seconds; the store refreshes
behind that call when needed. Nothing here ever talks to `api.soundcloud.com` —
only to the token endpoint, and only with `grant_type=refresh_token`.

Persistence — OS keyring only, two entries under `KEYRING_SERVICE`:
  - `KEYRING_SC_OAUTH` ("sc_oauth"): one JSON blob
    `{access_token, refresh_token, expires_at, obtained_at, scope}`. One entry =
    one `set_password` = one atomic write. The new blob lands BEFORE the new access
    token is handed out, so a crash never leaves a rotated-but-unsaved refresh token.
  - `KEYRING_SC_TOKEN` ("sc_token"): the legacy bare access token. Mirrored on every
    store so the ten existing `keyring.get_password(..., "sc_token")` readers in
    `app/main.py` keep working during the transition. The blob is canonical when
    both exist; a legacy-only state (user logged in before this module shipped) is
    still honoured so the upgrade never logs anyone out.

Refresh — single-flight behind a module-private `threading.Lock`. SoundCloud
rotates the refresh token on every use (single-use), so concurrent refreshes
would burn each other's token. Every caller re-reads the blob inside the lock
and returns without a POST when someone else already rotated.

Outcomes — exactly two failure classes, deliberately:
  - `AuthExpiredError` (from `soundcloud_api`): the token endpoint rejected the
    refresh token (HTTP 400/401, e.g. `invalid_grant`). Both keyring entries are
    cleared first. This is the ONLY path that sends the user back to the login button.
  - `TransientRefreshError`: network error, 5xx, 429, malformed body, missing
    client credentials. The stored blob is kept untouched; nothing is cleared.

Clock skew — `expires_at` is trusted only up to `min_ttl_s`; a server 401 counts as
expired regardless of the clock (`with_fresh_token`, `refresh(stale_token=...)`).

Never logged, at any level, redacted or not: the access token, the refresh token,
the client secret, the refresh request body, any response body. Log lines carry
`op=` markers with outcome + remaining TTL only.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, NamedTuple, TypeVar

import requests

from .soundcloud_api import AuthExpiredError, _get_proxy, _log_url

logger = logging.getLogger(__name__)


class _KeyringShim:
    """In-memory stand-in when the `keyring` package is missing (mirrors `app/main.py`)."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self._store.get(f"{service}:{username}")

    def set_password(self, service: str, username: str, value: str) -> None:
        self._store[f"{service}:{username}"] = value

    def delete_password(self, service: str, username: str) -> None:
        self._store.pop(f"{service}:{username}", None)


keyring: Any
try:
    import keyring as _keyring_backend

    keyring = _keyring_backend
except ImportError:  # pragma: no cover - exercised only on a machine without keyring
    keyring = _KeyringShim()

# Must equal app.main.KEYRING_SERVICE / KEYRING_SC_TOKEN — tests pin the parity.
KEYRING_SERVICE = "library_management_system"
KEYRING_SC_TOKEN = "sc_token"
KEYRING_SC_OAUTH = "sc_oauth"

# Same value as TOKEN_URL in src-tauri/src/soundcloud_client.rs.
SC_TOKEN_URL = "https://secure.soundcloud.com/oauth/token"
SC_REFRESH_TIMEOUT_S = 15

# A token is "fresh" only while it outlives this margin — absorbs clock skew and
# the duration of the call the token is about to be used for.
DEFAULT_MIN_TTL_S = 120

# SoundCloud documents ~1 h; `expires_in` is optional on the wire. Assuming the
# documented value when it is missing costs at most one harmless early rotation.
DEFAULT_EXPIRES_IN_S = 3600

_REFRESH_HEADERS = {"Accept": "application/json"}
_ERROR_CODE_RE = re.compile(r"^[a-z_]{1,40}$")

_refresh_lock = threading.Lock()

T = TypeVar("T")


class TransientRefreshError(Exception):
    """Refresh could not be completed right now; the stored tokens are untouched."""


@dataclass(frozen=True, repr=False)
class ScTokens:
    """The stored token set. `repr` deliberately omits every secret."""

    access_token: str
    refresh_token: str | None
    expires_at: float | None
    obtained_at: float
    scope: str | None = None

    def __repr__(self) -> str:
        return (
            f"ScTokens(has_refresh={self.refresh_token is not None}, "
            f"expires_at={self.expires_at}, obtained_at={self.obtained_at})"
        )


class StoreResult(NamedTuple):
    tokens: ScTokens
    persistent: bool
    """False → only the legacy key holds the session (blob write failed); no silent refresh."""


def _now() -> float:
    return time.time()


def _remaining_ttl(tokens: ScTokens) -> float:
    if tokens.expires_at is None:
        return float("inf")
    return tokens.expires_at - _now()


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _coerce_expires_in(value: Any) -> int:
    number = _as_float(value)
    if number is None or number <= 0:
        return DEFAULT_EXPIRES_IN_S
    return int(number)


# ──────────────────────────────────────────────────────────────────────────────
# Keyring I/O
# ──────────────────────────────────────────────────────────────────────────────


def load_tokens() -> ScTokens | None:
    """The blob, validated on read. Corrupt or partial → None (treated as logged out)."""
    try:
        raw = keyring.get_password(KEYRING_SERVICE, KEYRING_SC_OAUTH)
    except Exception as exc:
        logger.warning("op=sc_token_load outcome=keyring_error err=%s", type(exc).__name__)
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        logger.warning("op=sc_token_load outcome=corrupt reason=not_json")
        return None
    if not isinstance(data, dict):
        logger.warning("op=sc_token_load outcome=corrupt reason=not_object")
        return None
    access = data.get("access_token")
    if not isinstance(access, str) or not access:
        logger.warning("op=sc_token_load outcome=corrupt reason=no_access_token")
        return None
    refresh = data.get("refresh_token")
    scope = data.get("scope")
    return ScTokens(
        access_token=access,
        refresh_token=refresh if isinstance(refresh, str) and refresh else None,
        expires_at=_as_float(data.get("expires_at")),
        obtained_at=_as_float(data.get("obtained_at")) or 0.0,
        scope=scope if isinstance(scope, str) and scope else None,
    )


def _read_legacy() -> str | None:
    try:
        return keyring.get_password(KEYRING_SERVICE, KEYRING_SC_TOKEN) or None
    except Exception as exc:
        logger.warning(
            "op=sc_token_load outcome=keyring_error key=legacy err=%s", type(exc).__name__
        )
        return None


def _delete_key(username: str) -> None:
    try:
        keyring.delete_password(KEYRING_SERVICE, username)
    except Exception as exc:
        # Absent entry raises on most backends — that is the state we want anyway.
        logger.debug("op=sc_token_clear key=%s outcome=%s", username, type(exc).__name__)


def _persist(tokens: ScTokens) -> bool:
    """Blob first (canonical, atomic), then the legacy mirror. Returns blob success.

    A failed blob write (Windows Credential Manager caps one entry at 1280 UTF-16
    chars and `keyring` does not chunk) must not leave a stale blob next to a newer
    legacy token: the stale refresh token is single-use and already consumed, so
    the old blob is dropped and the session lives on in the legacy key alone.
    """
    blob = json.dumps(
        {
            "access_token": tokens.access_token,
            "refresh_token": tokens.refresh_token,
            "expires_at": int(tokens.expires_at) if tokens.expires_at is not None else None,
            "obtained_at": int(tokens.obtained_at),
            "scope": tokens.scope,
        },
        separators=(",", ":"),
    )
    blob_ok = True
    try:
        keyring.set_password(KEYRING_SERVICE, KEYRING_SC_OAUTH, blob)
    except Exception as exc:
        blob_ok = False
        logger.warning(
            "op=sc_token_store outcome=blob_write_failed err=%s blob_chars=%d",
            type(exc).__name__,
            len(blob),
        )
        _delete_key(KEYRING_SC_OAUTH)
    try:
        keyring.set_password(KEYRING_SERVICE, KEYRING_SC_TOKEN, tokens.access_token)
    except Exception as exc:
        logger.warning("op=sc_token_store outcome=legacy_mirror_failed err=%s", type(exc).__name__)
    return blob_ok


# ──────────────────────────────────────────────────────────────────────────────
# Public store API
# ──────────────────────────────────────────────────────────────────────────────


def store_tokens(
    access_token: str,
    refresh_token: str | None = None,
    expires_in: int | float | None = None,
    *,
    scope: str | None = None,
) -> StoreResult:
    """Persist a token set (fresh login or rotation). Missing `expires_in` → 1 h assumed."""
    access = (access_token or "").strip()
    if not access:
        raise ValueError("access_token must be a non-empty string")
    now = _now()
    tokens = ScTokens(
        access_token=access,
        refresh_token=(refresh_token or "").strip() or None,
        expires_at=now + _coerce_expires_in(expires_in),
        obtained_at=now,
        scope=(scope or "").strip() or None,
    )
    persistent = _persist(tokens)
    logger.info(
        "op=sc_token_store outcome=%s has_refresh=%s ttl=%.0f",
        "ok" if persistent else "legacy_only",
        tokens.refresh_token is not None,
        _remaining_ttl(tokens),
    )
    return StoreResult(tokens=tokens, persistent=persistent)


def clear_tokens() -> None:
    """Logout: remove the blob and the legacy key. Missing entries are not an error."""
    _delete_key(KEYRING_SC_OAUTH)
    _delete_key(KEYRING_SC_TOKEN)
    logger.info("op=sc_token_clear outcome=ok")


def token_status() -> dict[str, Any]:
    """Auth state without token material — safe to return from an HTTP route."""
    tokens = load_tokens()
    if tokens is None:
        legacy = _read_legacy()
        return {
            "authenticated": legacy is not None,
            "refreshable": False,
            "source": "legacy" if legacy is not None else None,
            "expires_at": None,
            "remaining_ttl_s": None,
        }
    remaining = _remaining_ttl(tokens)
    return {
        "authenticated": True,
        "refreshable": tokens.refresh_token is not None,
        "source": "oauth",
        "expires_at": tokens.expires_at,
        "remaining_ttl_s": None if remaining == float("inf") else int(remaining),
    }


def get_access_token(*, min_ttl_s: int = DEFAULT_MIN_TTL_S) -> str | None:
    """A token good for ≥ `min_ttl_s` more seconds, refreshing if needed. None = not logged in.

    Raises `AuthExpiredError` when a refresh was attempted and rejected (tokens
    cleared), `TransientRefreshError` when the token is already past expiry and
    the endpoint was unreachable. A token that is inside the safety margin but not
    yet expired is served as-is on a transient failure — the server stays the judge.
    """
    tokens = load_tokens()
    if tokens is None:
        legacy = _read_legacy()
        logger.debug("op=sc_token_get outcome=%s", "legacy" if legacy else "none")
        return legacy

    remaining = _remaining_ttl(tokens)
    if remaining > min_ttl_s:
        return tokens.access_token
    if tokens.refresh_token is None:
        logger.info("op=sc_token_get outcome=unrefreshable remaining_ttl=%.0f", remaining)
        return tokens.access_token
    try:
        return refresh(min_ttl_s=min_ttl_s)
    except TransientRefreshError:
        if remaining > 0:
            logger.warning("op=sc_token_get outcome=stale_served remaining_ttl=%.0f", remaining)
            return tokens.access_token
        raise


def refresh(
    *,
    min_ttl_s: int = DEFAULT_MIN_TTL_S,
    stale_token: str | None = None,
    force: bool = False,
) -> str:
    """Single-flight refresh. Returns the current access token.

    - `stale_token`: the token a server just rejected. If the stored token already
      differs, another caller rotated in the meantime — return theirs, no POST.
    - Without `stale_token`, a blob that is still fresh (> `min_ttl_s`) is returned
      as-is unless `force`.
    """
    with _refresh_lock:
        tokens = load_tokens()
        if tokens is None or tokens.refresh_token is None:
            raise AuthExpiredError("No SoundCloud refresh token stored. Sign in again.")
        if stale_token is not None:
            if tokens.access_token != stale_token:
                logger.info("op=sc_token_refresh outcome=rotated_elsewhere")
                return tokens.access_token
        elif not force:
            remaining = _remaining_ttl(tokens)
            if remaining > min_ttl_s:
                logger.debug(
                    "op=sc_token_refresh outcome=already_fresh remaining_ttl=%.0f", remaining
                )
                return tokens.access_token
        return _refresh_locked(tokens)


def with_fresh_token(fn: Callable[[str], T], *, min_ttl_s: int = DEFAULT_MIN_TTL_S) -> T:
    """Call `fn(token)`; on `AuthExpiredError` refresh once and retry once.

    The reactive backstop for long-running callers (a download that outlives the
    token). A second `AuthExpiredError` propagates — no retry loop.
    """
    token = get_access_token(min_ttl_s=min_ttl_s)
    if token is None:
        raise AuthExpiredError("SoundCloud is not connected.")
    try:
        return fn(token)
    except AuthExpiredError:
        logger.info("op=sc_token_reactive outcome=server_rejected action=refresh_once")
        fresh = refresh(stale_token=token)
        return fn(fresh)


# ──────────────────────────────────────────────────────────────────────────────
# Refresh grant
# ──────────────────────────────────────────────────────────────────────────────


def _client_credentials() -> tuple[str, str]:
    # Read the env directly rather than via `get_sc_client_id()`: its scrape fallback
    # yields the public web-player id, which never pairs with the user's client_secret.
    client_id = os.environ.get("SOUNDCLOUD_CLIENT_ID", "").strip()
    client_secret = os.environ.get("SOUNDCLOUD_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        logger.warning(
            "op=sc_token_refresh outcome=config_missing has_client_id=%s has_client_secret=%s",
            bool(client_id),
            bool(client_secret),
        )
        raise TransientRefreshError(
            "SOUNDCLOUD_CLIENT_ID / SOUNDCLOUD_CLIENT_SECRET are not set; "
            "silent refresh is unavailable until .env is completed and the sidecar restarted."
        )
    return client_id, client_secret


def _error_code(resp: Any) -> str:
    """The OAuth `error` code if it is a plain identifier; never the body itself."""
    try:
        body = resp.json()
    except ValueError:
        return "non_json"
    code = body.get("error") if isinstance(body, dict) else None
    if isinstance(code, str) and _ERROR_CODE_RE.match(code):
        return code
    return "unknown"


def _refresh_locked(tokens: ScTokens) -> str:
    client_id, client_secret = _client_credentials()
    payload = {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": tokens.refresh_token,
    }
    try:
        resp = requests.post(
            SC_TOKEN_URL,
            data=payload,
            headers=_REFRESH_HEADERS,
            timeout=SC_REFRESH_TIMEOUT_S,
            proxies=_get_proxy(),
        )
    except requests.RequestException as exc:
        logger.warning(
            "op=sc_token_refresh outcome=network_error err=%s url=%s",
            type(exc).__name__,
            _log_url(SC_TOKEN_URL),
        )
        raise TransientRefreshError(
            f"SoundCloud token endpoint unreachable ({type(exc).__name__})."
        ) from exc

    status = resp.status_code
    if status in (400, 401):
        code = _error_code(resp)
        clear_tokens()
        logger.warning("op=sc_token_refresh outcome=rejected http=%s error=%s", status, code)
        raise AuthExpiredError(
            f"SoundCloud refused the refresh token (HTTP {status}, {code}). Sign in again."
        )
    if status != 200:
        logger.warning("op=sc_token_refresh outcome=server_error http=%s", status)
        raise TransientRefreshError(f"SoundCloud token endpoint returned HTTP {status}.")

    try:
        data = resp.json()
    except ValueError as exc:
        logger.warning("op=sc_token_refresh outcome=malformed http=200 reason=not_json")
        raise TransientRefreshError("SoundCloud token endpoint returned non-JSON.") from exc
    access = data.get("access_token") if isinstance(data, dict) else None
    if not isinstance(access, str) or not access:
        logger.warning("op=sc_token_refresh outcome=malformed http=200 reason=no_access_token")
        raise TransientRefreshError("SoundCloud token response carried no access_token.")

    new_refresh = data.get("refresh_token")
    # RFC 6749 §6: a response without refresh_token leaves the old one valid.
    rotated = isinstance(new_refresh, str) and bool(new_refresh)
    scope = data.get("scope")
    now = _now()
    fresh = ScTokens(
        access_token=access,
        refresh_token=new_refresh if rotated else tokens.refresh_token,
        expires_at=now + _coerce_expires_in(data.get("expires_in")),
        obtained_at=now,
        scope=scope if isinstance(scope, str) and scope else tokens.scope,
    )
    persistent = _persist(fresh)
    logger.info(
        "op=sc_token_refresh outcome=%s rotated=%s remaining_ttl=%.0f",
        "ok" if persistent else "ok_not_persisted",
        rotated,
        _remaining_ttl(fresh),
    )
    return fresh.access_token
