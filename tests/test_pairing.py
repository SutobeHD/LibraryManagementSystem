"""Phase-2 paired-token store tests (T1 — app/auth_db.py).

Covers the auth_db layer: hashed-at-rest storage, create/validate/revoke,
the throttled last_seen write, and the listing surface. Route + dual-acceptance
tests (T3-T5) land with those tasks.
"""

from __future__ import annotations

import hashlib

import pytest

from app import auth_db


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Point auth_db at a throwaway DB file and reset the thread-local conn."""
    db_file = tmp_path / "auth.db"
    monkeypatch.setattr(auth_db, "_db_path", lambda: db_file)
    if getattr(auth_db._local, "conn", None) is not None:
        auth_db._local.conn.close()
        del auth_db._local.conn
    auth_db.init_db()
    yield auth_db
    if getattr(auth_db._local, "conn", None) is not None:
        auth_db._local.conn.close()
        del auth_db._local.conn


def _raw_token_hash(db, device_id: str) -> str:
    row = (
        db._connect()
        .execute("SELECT token_hash FROM paired_devices WHERE device_id=?", (device_id,))
        .fetchone()
    )
    return row["token_hash"]


def test_create_and_validate(fresh_db):
    dev = fresh_db.create_device("secret-token", "Pixel")
    assert isinstance(dev, str) and len(dev) == 32  # uuid4 hex
    assert fresh_db.paired_token_valid("secret-token") is True
    assert fresh_db.paired_token_valid("wrong-token") is False


def test_token_stored_hashed_not_plaintext(fresh_db):
    dev = fresh_db.create_device("plaintext-secret", "iPhone")
    stored = _raw_token_hash(fresh_db, dev)
    assert stored == hashlib.sha256(b"plaintext-secret").hexdigest()
    assert stored != "plaintext-secret"
    # plaintext appears nowhere in the table
    dump = fresh_db._connect().execute("SELECT * FROM paired_devices").fetchall()
    assert all("plaintext-secret" not in str(tuple(r)) for r in dump)


def test_revoke_flips_and_invalidates(fresh_db):
    dev = fresh_db.create_device("tok", "Tablet")
    assert fresh_db.paired_token_valid("tok") is True
    assert fresh_db.revoke_device(dev) is True
    assert fresh_db.paired_token_valid("tok") is False  # revoked=0 filter excludes it
    # second revoke affects no row (already revoked)
    assert fresh_db.revoke_device(dev) is False
    # row still present (audit trail), flagged revoked
    (entry,) = [d for d in fresh_db.list_devices() if d["device_id"] == dev]
    assert entry["revoked"] is True


def test_revoke_unknown_device_returns_false(fresh_db):
    assert fresh_db.revoke_device("does-not-exist") is False


def test_last_seen_write_throttled(fresh_db):
    dev = fresh_db.create_device("tok", "Phone")
    fresh_db.paired_token_valid("tok")  # first hit: NULL -> writes now
    # pin a recent timestamp, then a second validate must NOT overwrite it
    recent = "2999-01-01T00:00:00+00:00"  # far future => always within throttle window
    fresh_db._connect().execute(
        "UPDATE paired_devices SET last_seen_at=? WHERE device_id=?", (recent, dev)
    )
    fresh_db._connect().commit()
    fresh_db.paired_token_valid("tok")
    (entry,) = [d for d in fresh_db.list_devices() if d["device_id"] == dev]
    assert entry["last_seen_at"] == recent  # throttled: not rewritten


def test_last_seen_refreshes_when_stale(fresh_db):
    dev = fresh_db.create_device("tok", "Phone")
    stale = "2000-01-01T00:00:00+00:00"  # > 60s ago
    fresh_db._connect().execute(
        "UPDATE paired_devices SET last_seen_at=? WHERE device_id=?", (stale, dev)
    )
    fresh_db._connect().commit()
    fresh_db.paired_token_valid("tok")
    (entry,) = [d for d in fresh_db.list_devices() if d["device_id"] == dev]
    assert entry["last_seen_at"] != stale  # refreshed


def test_empty_candidate_is_false(fresh_db):
    assert fresh_db.paired_token_valid("") is False


def test_create_empty_token_raises(fresh_db):
    with pytest.raises(ValueError):
        fresh_db.create_device("", "NoToken")


def test_list_devices_newest_first(fresh_db):
    a = fresh_db.create_device("t1", "First")
    b = fresh_db.create_device("t2", "Second")
    listed = fresh_db.list_devices()
    assert len(listed) == 2
    assert {d["device_id"] for d in listed} == {a, b}


def test_two_devices_independent_validation(fresh_db):
    fresh_db.create_device("tok-a", "A")
    dev_b = fresh_db.create_device("tok-b", "B")
    fresh_db.revoke_device(dev_b)
    assert fresh_db.paired_token_valid("tok-a") is True
    assert fresh_db.paired_token_valid("tok-b") is False
