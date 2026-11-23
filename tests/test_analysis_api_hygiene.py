"""POST /api/audio/analyze sandbox + path-free analyze-batch / analyze-full bodies.

``/api/audio/analyze`` accepted any existing path (no ``validate_audio_path``), and
every ``analyze-batch`` NDJSON line carried the writer's raw result: absolute ANLZ paths
and error texts with the track's audio path. Lines now keep ids, counters, status and
results only; ``anlz_paths`` becomes the list of kinds written.

No real library and no real analysis: the facade's live backend and ``AudioAnalyzer`` are
stubs, every file lives in ``tmp_path``.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from app import main
from app.main import app

_SECRET = r"C:\Users\someone\Music\private"


def _post(url: str, headers: dict[str, str], body: dict[str, Any] | None = None) -> httpx.Response:
    async def _go() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            return await ac.post(url, json=body or {}, headers=headers)

    return asyncio.run(_go())


# --- /api/audio/analyze -------------------------------------------------------------


@pytest.fixture
def sandbox_root(tmp_path: Path) -> Iterator[Path]:
    root = (tmp_path / "lib").resolve()
    root.mkdir()
    main.ALLOWED_AUDIO_ROOTS.append(root)
    try:
        yield root
    finally:
        with contextlib.suppress(ValueError):
            main.ALLOWED_AUDIO_ROOTS.remove(root)


@pytest.fixture
def submitted(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    paths: list[str] = []

    def _analyze_track(task_id: str, file_path: str, mode: str = "accuracy") -> dict[str, Any]:
        paths.append(file_path)
        return {"status": "queued", "task_id": task_id}

    monkeypatch.setattr(main.AudioAnalyzer, "analyze_track", staticmethod(_analyze_track))
    return paths


def test_analyze_inside_the_sandbox_is_queued(
    sandbox_root: Path, submitted: list[str], auth_token: dict[str, str]
) -> None:
    f = sandbox_root / "a.mp3"
    f.write_bytes(b"ID3" + bytes(64))
    r = _post("/api/audio/analyze", auth_token, {"file_path": str(f)})
    assert r.status_code == 200, r.text
    assert submitted == [str(f.resolve())]


def test_analyze_outside_the_sandbox_is_403(
    tmp_path: Path, sandbox_root: Path, submitted: list[str], auth_token: dict[str, str]
) -> None:
    outside = tmp_path / "outside.mp3"
    outside.write_bytes(b"ID3" + bytes(64))
    r = _post("/api/audio/analyze", auth_token, {"file_path": str(outside)})
    assert r.status_code == 403, r.text
    assert submitted == []


def test_analyze_non_audio_extension_is_400(
    sandbox_root: Path, submitted: list[str], auth_token: dict[str, str]
) -> None:
    f = sandbox_root / "notes.txt"
    f.write_text("x", encoding="utf-8")
    r = _post("/api/audio/analyze", auth_token, {"file_path": str(f)})
    assert r.status_code == 400, r.text
    assert submitted == []


def test_analyze_missing_file_stays_404(
    sandbox_root: Path, submitted: list[str], auth_token: dict[str, str]
) -> None:
    r = _post("/api/audio/analyze", auth_token, {"file_path": str(sandbox_root / "gone.mp3")})
    assert r.status_code == 404, r.text
    assert submitted == []


# --- analyze-batch / analyze-full bodies ---------------------------------------------


_OK = {
    "status": "ok",
    "track_id": "1",
    "bpm": 124.0,
    "key": "Am",
    "camelot": "8A",
    "anlz_paths": {
        "dat": rf"{_SECRET}\USBANLZ\abc\ANLZ0000.DAT",
        "ext": rf"{_SECRET}\USBANLZ\abc\ANLZ0000.EXT",
    },
    "db_updated": True,
}
_RESULTS: dict[str, dict[str, Any]] = {
    "1": _OK,
    "2": {
        "status": "error",
        "reason": "audio_missing",
        "error": rf"Audio file not found: {_SECRET}\b.mp3",
    },
    "3": {"status": "error", "error": rf"decoder crashed on {_SECRET}\c.mp3"},  # exception branch
    "4": {"status": "skipped", "reason": "already_analyzed", "bpm": 128.0},
}


class _PathLeakingWriter:
    """Yields what ``AnalysisDBWriter`` yields: counters merged with the raw result."""

    def analyze_and_save(self, tid: str, force: bool = False) -> dict[str, Any]:
        return dict(_RESULTS[tid])

    def analyze_batch(self, track_ids: list[str], force: bool = False) -> Iterator[dict[str, Any]]:
        for i, tid in enumerate(track_ids):
            yield {"track_id": tid, "index": i + 1, "total": len(track_ids), **_RESULTS[tid]}


class _LiveDB:
    loaded = True

    def __init__(self) -> None:
        self.writer = _PathLeakingWriter()

    def get_analysis_writer(self) -> _PathLeakingWriter:
        return self.writer


@pytest.fixture
def live(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main.db, "mode", "live")
    monkeypatch.setattr(main.db, "live_db", _LiveDB())
    monkeypatch.setattr(main, "_is_rekordbox_running", lambda: False)


def test_batch_lines_carry_no_paths(live: None, auth_token: dict[str, str]) -> None:
    r = _post("/api/library/analyze-batch", auth_token, {"track_ids": ["1", "2", "3", "4"]})
    assert r.status_code == 200, r.text
    assert "Users" not in r.text and "ANLZ0000" not in r.text and ".mp3" not in r.text

    lines = [json.loads(line) for line in r.text.splitlines()]
    assert [(ln["track_id"], ln["index"], ln["status"]) for ln in lines] == [
        ("1", 1, "ok"),
        ("2", 2, "error"),
        ("3", 3, "error"),
        ("4", 4, "skipped"),
    ]
    ok, missing, crashed, skipped = lines
    assert ok["anlz_files"] == ["dat", "ext"]
    assert "anlz_paths" not in ok
    assert (ok["bpm"], ok["key"], ok["camelot"], ok["db_updated"]) == (124.0, "Am", "8A", True)
    assert missing["reason"] == "audio_missing"
    assert missing["error"] == "The track's audio file is missing on disk"
    assert crashed["error"] == "Analysis failed. Check logs for details."
    assert skipped == {
        "track_id": "4",
        "index": 4,
        "total": 4,
        "status": "skipped",
        "reason": "already_analyzed",
        "bpm": 128.0,
    }


def test_analyze_full_ok_body_carries_no_paths(live: None, auth_token: dict[str, str]) -> None:
    r = _post("/api/track/1/analyze-full", auth_token)
    assert r.status_code == 200, r.text
    assert "Users" not in r.text
    data = r.json()["data"]
    assert data["anlz_files"] == ["dat", "ext"]
    assert "anlz_paths" not in data
    assert data["bpm"] == 124.0
