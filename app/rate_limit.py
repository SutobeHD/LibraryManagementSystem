"""In-process token-bucket rate limiter for the FastAPI sidecar.

Phase-1 deliverable from
``docs/research/research/evaluated_security-rate-limit-design.md``
(Option B - custom token-bucket, ~50 LOC).

Shape mirrors the proven ``_format_tokens`` pattern at
``app/main.py:2375-2384``: thread-safe ``dict`` keyed by a derived
identity string, ``threading.RLock`` for mutation, lazy TTL eviction
piggy-backed on the next ``take`` call.

Public surface:

* :func:`rate_limit` - decorator applied to FastAPI handlers.
* ``_store`` - module-level :class:`BucketStore` singleton; exposed for
  tests that need to reset state between cases.

Whitelist policy: ``make_key`` short-circuits any loopback request
(``127.0.0.1`` / ``::1``) to the sentinel ``"__whitelist__"``, which
:meth:`BucketStore.take` recognises and returns ``(True, 0.0)`` without
allocating a bucket.  Phase-2 LAN bind (gated on the
``trust_proxy_headers`` flag - currently parked) will widen the
whitelist; the Phase-1 sidecar binds to ``127.0.0.1`` so every real
request hits the sentinel.

Concurrency: ``BucketStore`` holds an ``RLock`` for the dict-mutation
path (get-or-create + refill + decrement) so a thundering herd against a
hot key cannot over-spend the bucket.  ``TokenBucket._refill_to`` is
pure-CPU and assumes its caller holds the lock.
"""

from __future__ import annotations

import functools
import hashlib
import logging
import threading
import time
from typing import Any, Awaitable, Callable, Literal

from fastapi import HTTPException, Request

logger = logging.getLogger("APP_RATE_LIMIT")

_WHITELIST_SENTINEL = "__whitelist__"
_WHITELIST_IPS: frozenset[str] = frozenset({"127.0.0.1", "::1"})
_PURGE_INTERVAL_S = 60.0  # min wall-clock between lazy purge sweeps
_PURGE_TTL_S = 600.0  # drop fully-refilled buckets idle this long


class TokenBucket:
    """Single-key token bucket with monotonic-clock refill."""

    __slots__ = ("steady_per_sec", "capacity", "tokens", "last_refill")

    def __init__(self, steady_per_min: float, burst: int) -> None:
        self.steady_per_sec: float = steady_per_min / 60.0
        self.capacity: int = burst
        self.tokens: float = float(burst)
        self.last_refill: float = time.monotonic()

    def _refill_to(self, now: float) -> None:
        """Add tokens earned since ``last_refill`` (caller holds the lock)."""
        elapsed = now - self.last_refill
        if elapsed > 0:
            self.tokens = min(
                float(self.capacity), self.tokens + elapsed * self.steady_per_sec
            )
            self.last_refill = now

    def take(self) -> tuple[bool, float]:
        """Spend one token; return ``(allowed, retry_after_s)``."""
        self._refill_to(time.monotonic())
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return (True, 0.0)
        deficit = 1.0 - self.tokens
        retry_after_s = deficit / self.steady_per_sec if self.steady_per_sec > 0 else 0.0
        return (False, retry_after_s)


class BucketStore:
    """Process-wide TTL'd map of bucket-key to :class:`TokenBucket`."""

    def __init__(self) -> None:
        self._buckets: dict[str, TokenBucket] = {}
        self._lock: threading.RLock = threading.RLock()
        self._last_purge: float = time.monotonic()

    def _purge_stale(self, now: float, ttl: float = _PURGE_TTL_S) -> None:
        """Evict fully-refilled buckets idle for ``ttl`` seconds."""
        cutoff = now - ttl
        stale = [
            k
            for k, b in self._buckets.items()
            if b.last_refill < cutoff and b.tokens >= float(b.capacity)
        ]
        for k in stale:
            self._buckets.pop(k, None)
        self._last_purge = now

    def take(self, key: str, *, steady: float, burst: int) -> tuple[bool, float]:
        """Spend one token for ``key`` (creating the bucket on first hit)."""
        if key == _WHITELIST_SENTINEL:
            return (True, 0.0)
        with self._lock:
            now = time.monotonic()
            if now - self._last_purge > _PURGE_INTERVAL_S:
                self._purge_stale(now)
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = TokenBucket(steady_per_min=steady, burst=burst)
                self._buckets[key] = bucket
            return bucket.take()


_store: BucketStore = BucketStore()


def make_key(request: Request, *, mode: Literal["ip", "bearer", "both"]) -> str:
    """Derive the bucket-key for ``request`` under ``mode``."""
    client_ip = request.client.host if request.client else "unknown"
    if client_ip in _WHITELIST_IPS:
        return _WHITELIST_SENTINEL

    if mode == "ip":
        return f"ip:{client_ip}"

    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        bearer_hash = hashlib.sha256(auth_header[7:].encode()).hexdigest()[:16]
    else:
        bearer_hash = "none"

    if mode == "bearer":
        return f"b:{bearer_hash}"
    return f"ip:{client_ip}|b:{bearer_hash}"


def rate_limit(
    steady: float,
    burst: int,
    key_mode: Literal["ip", "bearer", "both"] = "both",
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """Decorate an async FastAPI handler with a per-key token-bucket gate."""

    def _decorator(
        func: Callable[..., Awaitable[Any]],
    ) -> Callable[..., Awaitable[Any]]:
        @functools.wraps(func)
        async def _wrapper(*args: Any, **kwargs: Any) -> Any:
            request: Request | None = kwargs.get("request")
            if request is None:
                for arg in args:
                    if isinstance(arg, Request):
                        request = arg
                        break
            if request is None:
                # No Request injected - fail-open rather than 500 the route.
                logger.warning(
                    "rate_limit: no Request param on %s; skipping limit", func.__name__
                )
                return await func(*args, **kwargs)

            key = make_key(request, mode=key_mode)
            allowed, retry_after_s = _store.take(key, steady=steady, burst=burst)
            if not allowed:
                raise HTTPException(
                    status_code=429,
                    detail={
                        "error": "rate_limited",
                        "retry_after_s": int(retry_after_s),
                    },
                    headers={"Retry-After": str(max(1, int(retry_after_s)))},
                )
            return await func(*args, **kwargs)

        return _wrapper

    return _decorator
