"""Phase-2 require_session dual-acceptance tests (T3 — app/auth.py).

Covers the _extract_bearer parser matrix and the dual-acceptance branch:
SESSION_TOKEN OR a non-revoked paired device token, plus the empty
child-process SESSION_TOKEN edge case.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app import auth, auth_db


@pytest.fixture
def paired(tmp_path, monkeypatch):
    """Throwaway auth.db + a known SESSION_TOKEN for require_session."""
    db_file = tmp_path / "auth.db"
    monkeypatch.setattr(auth_db, "_db_path", lambda: db_file)
    if getattr(auth_db._local, "conn", None) is not None:
        auth_db._local.conn.close()
        del auth_db._local.conn
    auth_db.init_db()
    monkeypatch.setattr(auth, "SESSION_TOKEN", "known-session-token")
    yield auth_db
    if getattr(auth_db._local, "conn", None) is not None:
        auth_db._local.conn.close()
        del auth_db._local.conn


@pytest.mark.parametrize(
    "header,expected",
    [
        (None, None),
        ("", None),
        ("Bearer", None),  # no credential
        ("Bearer ", None),  # empty credential
        ("Basic abc", None),  # wrong scheme
        ("abc", None),  # no scheme
        ("Bearer tok123", "tok123"),
        ("bearer tok123", "tok123"),  # scheme case-insensitive
        ("Bearer   spaced  ", "spaced"),  # trims surrounding whitespace
    ],
)
def test_extract_bearer_matrix(header, expected):
    assert auth._extract_bearer(header) == expected


def test_session_token_authenticates(paired):
    # no raise == authenticated
    assert auth.require_session("Bearer known-session-token") is None


def test_paired_device_token_authenticates(paired):
    paired.create_device("device-tok", "Pixel")
    assert auth.require_session("Bearer device-tok") is None


def test_revoked_device_token_rejected(paired):
    dev = paired.create_device("device-tok", "Pixel")
    paired.revoke_device(dev)
    with pytest.raises(HTTPException) as exc:
        auth.require_session("Bearer device-tok")
    assert exc.value.status_code == 401


def test_unknown_token_rejected(paired):
    with pytest.raises(HTTPException) as exc:
        auth.require_session("Bearer not-a-real-token")
    assert exc.value.status_code == 401


def test_missing_header_rejected(paired):
    with pytest.raises(HTTPException) as exc:
        auth.require_session(None)
    assert exc.value.status_code == 401


def test_child_process_empty_session_token_still_accepts_device(paired, monkeypatch):
    # Non-MainProcess workers carry SESSION_TOKEN == "": branch 1 must be
    # skipped (never match ""), branch 2 must still authenticate a device.
    monkeypatch.setattr(auth, "SESSION_TOKEN", "")
    paired.create_device("device-tok", "Pixel")
    assert auth.require_session("Bearer device-tok") is None
    # ...and an empty/garbage token is still rejected, not silently accepted.
    with pytest.raises(HTTPException):
        auth.require_session("Bearer ")
