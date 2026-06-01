"""Routing-table invariant: no duplicate (method, path) registrations.

Starlette/FastAPI keep the FIRST matching route, so a second handler
registered on the same (method, path) is silent dead code — and which
one wins depends on source order, which is fragile and confusing.

This bug class has hit the project repeatedly: a duplicate
``POST /api/system/heartbeat`` (see TestNoDuplicateHeartbeatRoute in
tests/test_security_hotfixes.py), a duplicate ``GET /api/library/tracks``
(the dead second def bypassed the hide_streaming filter), and a trio of
duplicate ``GET /api/{artist,label,album}/{id}/tracks`` (dead defs added
unused ArtistName/filename enrichment). All removed.

``test_no_duplicate_method_path`` is the general guard that fails the
moment any (method, path) pair gets two handlers again. The parametrized
test below pins the specific paths cleaned historically as named
regressions.
"""

from __future__ import annotations

from collections import Counter

import pytest

from app.main import app


def _method_path_pairs() -> list[tuple[str, str]]:
    """Every (HTTP method, path) the FastAPI app registers.

    Mounts / WebSocket / lifespan routes carry no ``methods`` and
    contribute nothing (``or set()`` guards the missing attribute).
    """
    pairs: list[tuple[str, str]] = []
    for route in app.routes:
        path = getattr(route, "path", None)
        if path is None:
            continue
        for method in getattr(route, "methods", None) or set():
            pairs.append((method, path))
    return pairs


def test_no_duplicate_method_path() -> None:
    counts = Counter(_method_path_pairs())
    dupes = {pair: n for pair, n in counts.items() if n > 1}
    assert not dupes, (
        "Duplicate (method, path) route registrations found — the second "
        f"handler is dead code (Starlette serves the first): {dupes!r}"
    )


# Paths that previously carried a shadowed duplicate handler. Each must
# resolve to exactly one route now and forever.
_HISTORICALLY_DEDUPED = [
    ("POST", "/api/system/heartbeat"),
    ("GET", "/api/library/tracks"),
    ("GET", "/api/artist/{aid}/tracks"),
    ("GET", "/api/label/{aid}/tracks"),
    ("GET", "/api/album/{aid}/tracks"),
]


@pytest.mark.parametrize(("method", "path"), _HISTORICALLY_DEDUPED)
def test_deduplicated_path_has_single_handler(method: str, path: str) -> None:
    matches = [
        r
        for r in app.routes
        if getattr(r, "path", None) == path and method in (getattr(r, "methods", None) or set())
    ]
    assert len(matches) == 1, (
        f"Expected exactly one {method} {path}, found {len(matches)}: "
        f"{[getattr(r.endpoint, '__name__', '?') for r in matches]!r}"
    )
