"""Shutdown paths flush coalesced XML saves before os._exit / os.execv.

app.database (save-coalescing branch) registers ``flush_pending_saves`` with
atexit; ``_graceful_shutdown`` ends in ``os._exit(0)`` and restart in
``os.execv``, both of which skip atexit. ``_flush_pending_db_saves`` bridges
that, and must be a no-op on a database.py without the function.
"""

from __future__ import annotations

import logging

import pytest

import app.main as main
from app import database


class _Exited(Exception):
    pass


def test_noop_without_flush_function(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(database, "flush_pending_saves", raising=False)
    main._flush_pending_db_saves()


def test_calls_flush_and_logs_failure(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    calls: list[int] = []

    def flush() -> bool:
        calls.append(1)
        return False

    monkeypatch.setattr(database, "flush_pending_saves", flush, raising=False)
    with caplog.at_level(logging.WARNING, logger="APP_MAIN"):
        main._flush_pending_db_saves()
    assert calls == [1]
    assert any("could not be written" in r.getMessage() for r in caplog.records)


def test_flush_exception_never_escapes(monkeypatch: pytest.MonkeyPatch) -> None:
    def flush() -> bool:
        raise RuntimeError("disk full")

    monkeypatch.setattr(database, "flush_pending_saves", flush, raising=False)
    main._flush_pending_db_saves()


def test_graceful_shutdown_flushes_before_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []

    def flush() -> bool:
        order.append("flush")
        return True

    def fake_exit(code: int) -> None:
        order.append(f"exit:{code}")
        raise _Exited

    monkeypatch.setattr(database, "flush_pending_saves", flush, raising=False)
    monkeypatch.setattr(main.os, "_exit", fake_exit)
    monkeypatch.setattr(main.time, "sleep", lambda _s: None)
    monkeypatch.setattr(main.folder_watcher, "shutdown_watcher", lambda: None)
    try:
        with pytest.raises(_Exited):
            main._graceful_shutdown()
    finally:
        main._shutdown_event.clear()
    assert order == ["flush", "exit:0"]
