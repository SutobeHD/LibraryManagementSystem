"""Phase-2 pairing-code store tests (T2 — app/pairing_store.py).

Covers one-shot consume semantics (OK → CONSUMED on replay), expiry, the
unknown-code path, and lazy purge.
"""

from __future__ import annotations

import time

from app.pairing_store import ConsumeStatus, PairingCodeStore


def test_mint_returns_distinct_codes():
    store = PairingCodeStore()
    codes = {store.mint() for _ in range(50)}
    assert len(codes) == 50  # no collisions
    assert all(isinstance(c, str) and c for c in codes)


def test_consume_one_shot_then_replay_is_consumed():
    store = PairingCodeStore()
    code = store.mint()
    assert store.consume(code) is ConsumeStatus.OK
    # second redemption of the same code is rejected as a replay
    assert store.consume(code) is ConsumeStatus.CONSUMED
    assert store.consume(code) is ConsumeStatus.CONSUMED


def test_unknown_code_is_unknown():
    store = PairingCodeStore()
    assert store.consume("never-minted") is ConsumeStatus.UNKNOWN
    assert store.consume("") is ConsumeStatus.UNKNOWN


def test_expired_code_is_expired():
    store = PairingCodeStore()
    code = store.mint(ttl_s=-1.0)  # already expired
    assert store.consume(code) is ConsumeStatus.EXPIRED
    # an expired code is dropped, so a follow-up looks unknown
    assert store.consume(code) is ConsumeStatus.UNKNOWN


def test_purge_stale_drops_expired_entries():
    store = PairingCodeStore()
    store.mint(ttl_s=-1.0)
    live = store.mint(ttl_s=60.0)
    store._purge_stale(time.monotonic())
    assert len(store._codes) == 1  # only the live code remains
    assert store.consume(live) is ConsumeStatus.OK


def test_clear_resets_store():
    store = PairingCodeStore()
    code = store.mint()
    store.clear()
    assert store.consume(code) is ConsumeStatus.UNKNOWN
