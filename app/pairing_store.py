"""pairing_store — in-memory one-shot pairing codes (Phase-2 auth, T2).

A pairing code is a short-lived secret the desktop mints
(``POST /api/pairing/start``) and the phone redeems exactly once
(``POST /api/pairing/complete``) to obtain a long-lived device token. Codes are
deliberately **not** persisted: a sidecar restart mid-pairing invalidates them
and the user re-scans (a one-time setup cost, not a runtime path).

Shape mirrors ``app/rate_limit.py:BucketStore`` — a thread-safe ``dict`` guarded
by a single ``Lock`` with lazy TTL purge piggy-backed on ``mint``. One-shot
semantics: the first successful :meth:`consume` flips the entry to ``CONSUMED`` so
a replay is distinguishable (the route maps it to 409) from an expired/unknown
code (410), while the code itself can never be redeemed twice.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass
from enum import Enum

_DEFAULT_TTL_S = 60.0
_PURGE_INTERVAL_S = 60.0  # min wall-clock between lazy purge sweeps
#: ``token_urlsafe(8)`` ≈ 64 bits — brute force infeasible within the TTL even
#: before the ``@rate_limit(5, 10)`` gate on the complete route.
_CODE_NBYTES = 8


class ConsumeStatus(Enum):
    """Outcome of a :meth:`PairingCodeStore.consume` attempt."""

    OK = "ok"
    UNKNOWN = "unknown"
    EXPIRED = "expired"
    CONSUMED = "consumed"


@dataclass
class _Entry:
    expires_at: float  # monotonic clock
    consumed: bool = False


class PairingCodeStore:
    """Process-wide TTL'd map of pairing-code to its one-shot state."""

    def __init__(self) -> None:
        self._codes: dict[str, _Entry] = {}
        self._lock = threading.Lock()
        self._last_purge = time.monotonic()

    def _purge_stale(self, now: float) -> None:
        """Drop expired codes (caller holds the lock)."""
        stale = [c for c, e in self._codes.items() if e.expires_at < now]
        for c in stale:
            self._codes.pop(c, None)
        self._last_purge = now

    def mint(self, ttl_s: float = _DEFAULT_TTL_S) -> str:
        """Create a fresh single-use code valid for ``ttl_s`` seconds."""
        code = secrets.token_urlsafe(_CODE_NBYTES)
        now = time.monotonic()
        with self._lock:
            if now - self._last_purge > _PURGE_INTERVAL_S:
                self._purge_stale(now)
            self._codes[code] = _Entry(expires_at=now + ttl_s)
        return code

    def consume(self, code: str) -> ConsumeStatus:
        """Redeem ``code`` once; report why if it cannot be redeemed."""
        if not code:
            return ConsumeStatus.UNKNOWN
        now = time.monotonic()
        with self._lock:
            entry = self._codes.get(code)
            if entry is None:
                return ConsumeStatus.UNKNOWN
            if entry.consumed:
                return ConsumeStatus.CONSUMED
            if entry.expires_at < now:
                self._codes.pop(code, None)
                return ConsumeStatus.EXPIRED
            entry.consumed = True
            return ConsumeStatus.OK

    def clear(self) -> None:
        """Test helper: drop all codes and reset the purge clock."""
        with self._lock:
            self._codes.clear()
            self._last_purge = time.monotonic()


#: Module-level singleton; exposed so tests can reset state between cases.
_store = PairingCodeStore()


def mint_code(ttl_s: float = _DEFAULT_TTL_S) -> str:
    """Mint a one-shot pairing code on the shared store."""
    return _store.mint(ttl_s)


def consume_code(code: str) -> ConsumeStatus:
    """Redeem a pairing code on the shared store."""
    return _store.consume(code)
