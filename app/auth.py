"""Bearer-token authentication for the FastAPI sidecar.

Phase 1 of the API-auth-hardening rollout. This module owns the
**session token** lifecycle and exposes the FastAPI dependency that
enforces it on every mutating route. The Tauri shell consumes the token
out-of-band: the sidecar prints ``LMS_TOKEN=<value>`` as its very first
stdout line at boot, and the Rust supervisor (``src-tauri/src/main.rs``)
captures + scrubs that line before the rest of the log stream is
forwarded to ``log::info!``. The same token is also written to
``%APPDATA%/MusicLibraryManager/.session-token`` (cross-platform via
``platformdirs``) so the browser-dev path (``vite.config.js``
dev-middleware) can read it without touching the sidecar's stdout.

**This module MUST NOT log the token value at any level, ever.** Not
INFO, not DEBUG, not redacted — the moment the token enters the
``logging`` machinery it lands in ``log/app.log`` and any future
log-aggregation pipeline. See
``docs/research/implement/draftplan_security-api-auth-hardening.md``
(Decisions table + Risks section) for the full rationale.

The token rotates **only** on sidecar process restart (Phase 1 policy).
A stale file from a prior crash / SIGKILL / Tauri force-kill is
expected — ``_write_token_file`` overwrites unconditionally.
"""

from __future__ import annotations

import contextlib
import logging
import multiprocessing as _mp
import secrets
import sys
from pathlib import Path
from typing import Annotated

from fastapi import Header, HTTPException
from platformdirs import user_data_dir

from app.auth_db import paired_token_valid
from app.security_compare import safe_compare

logger = logging.getLogger("APP_AUTH")

_APP_DIRNAME = "MusicLibraryManager"
_TOKEN_FILENAME = ".session-token"


def _token_file_path() -> Path:
    """Resolve the absolute path of the session-token file."""
    base = Path(user_data_dir(_APP_DIRNAME, appauthor=False, roaming=False))
    return base / _TOKEN_FILENAME


def _write_token_file(token: str) -> Path:
    """Persist ``token`` to the user-data dir, overwriting any stale file."""
    path = _token_file_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(token, encoding="utf-8")
        # Windows NTFS rejects POSIX mode bits silently; not fatal.
        with contextlib.suppress(OSError):
            path.chmod(0o600)
    except OSError as exc:
        logger.warning(
            "auth: failed to write session-token file at %s: %s",
            path,
            exc,
        )
        raise
    return path


def _emit_boot_banner(token: str) -> None:
    """Write the ``LMS_TOKEN=<value>`` handshake line to stdout."""
    sys.stdout.write(f"LMS_TOKEN={token}\n")
    sys.stdout.flush()


def _generate_session_token() -> str:
    """Produce a fresh 32-byte URL-safe token via ``secrets``."""
    return secrets.token_urlsafe(32)


if _mp.current_process().name == "MainProcess":
    SESSION_TOKEN: str = _generate_session_token()
    _emit_boot_banner(SESSION_TOKEN)
    try:
        _written_to = _write_token_file(SESSION_TOKEN)
        logger.info("auth: session-token file written at %s", _written_to)
    except OSError:
        raise
else:
    SESSION_TOKEN = ""


def _extract_bearer(authorization: str | None) -> str | None:
    """Parse an ``Authorization: Bearer <token>`` header.

    Returns the bare token, or ``None`` when the header is missing, malformed,
    not a Bearer scheme, or carries an empty credential. Kept separate from
    :func:`require_session` so a future ``require_session_ws`` (WebSocket auth)
    reuses the exact same parsing.
    """
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) != 2:
        return None
    scheme, raw_credentials = parts
    if scheme.lower() != "bearer":
        return None
    candidate = raw_credentials.strip()
    return candidate or None


def require_session(
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """Authenticate one HTTP request against an accepted bearer token.

    Dual-acceptance (Phase 2): a request authenticates if its bearer token is
    EITHER the boot-time ``SESSION_TOKEN`` (constant-time compare) OR a
    non-revoked paired device token (``auth_db``). The device-token branch is a
    no-op until a device is paired, and degrades to a clean 401 if ``auth.db``
    is absent.
    """
    candidate = _extract_bearer(authorization)
    if candidate is None:
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Branch 1 — boot-time session token. Guarded so the empty child-process
    # SESSION_TOKEN ("" in non-MainProcess workers) never spuriously matches.
    if SESSION_TOKEN and safe_compare(candidate, SESSION_TOKEN):
        return

    # Branch 2 — long-lived per-device paired token.
    if paired_token_valid(candidate):
        return

    raise HTTPException(status_code=401, detail="Unauthorized")
