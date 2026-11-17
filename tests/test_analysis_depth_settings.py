"""The `analysis_depth` setting ("rekordbox" | "high") and how the analyze routes resolve it.

Settings side: `SettingsManager` default / legacy-key strip (handover B11) /
`analysis_depth()` resolver; `SetReq` accepts only the two literals.
Route side: `POST /api/settings`, `POST /api/audio/analyze`,
`POST /api/track/{tid}/analyze` — the depth from the body wins, otherwise the
stored setting; the analysis itself is stubbed (no DSP, no pool).
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from app import main
from app.main import SetReq, app
from app.services import SettingsManager


def _post(url: str, headers: dict[str, str], body: dict[str, Any] | None = None) -> httpx.Response:
    async def _go() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            return await ac.post(url, json=body if body is not None else {}, headers=headers)

    return asyncio.run(_go())


def _get(url: str) -> httpx.Response:
    async def _go() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            return await ac.get(url)

    return asyncio.run(_go())


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A private settings.json; absent until a test writes it."""
    path = tmp_path / "settings.json"
    monkeypatch.setattr(SettingsManager, "CONFIG", path)
    return path


# --- SettingsManager -------------------------------------------------------------


class TestSettingsManagerDepth:
    def test_default_is_rekordbox(self, cfg: Path) -> None:
        assert SettingsManager.DEFAULT["analysis_depth"] == "rekordbox"
        assert SettingsManager.load()["analysis_depth"] == "rekordbox"  # no file yet
        assert SettingsManager.analysis_depth() == "rekordbox"

    def test_stored_value_is_returned(self, cfg: Path) -> None:
        cfg.write_text(json.dumps({"analysis_depth": "high"}), encoding="utf-8")
        assert SettingsManager.load()["analysis_depth"] == "high"
        assert SettingsManager.analysis_depth() == "high"

    def test_override_wins_over_the_stored_value(self, cfg: Path) -> None:
        cfg.write_text(json.dumps({"analysis_depth": "high"}), encoding="utf-8")
        assert SettingsManager.analysis_depth("rekordbox") == "rekordbox"
        assert SettingsManager.analysis_depth("high") == "high"

    def test_invalid_override_raises(self, cfg: Path) -> None:
        with pytest.raises(ValueError):
            SettingsManager.analysis_depth("fast")

    @pytest.mark.parametrize("stored", [None, "", "fast", "standard", 3, [], {"a": 1}])
    def test_null_or_invalid_stored_value_normalises_to_the_default(
        self, cfg: Path, stored: Any
    ) -> None:
        cfg.write_text(json.dumps({"analysis_depth": stored, "theme": "light"}), encoding="utf-8")
        loaded = SettingsManager.load()
        assert loaded["analysis_depth"] == "rekordbox"
        assert loaded["theme"] == "light"
        assert SettingsManager.analysis_depth() == "rekordbox"

    def test_legacy_analysis_quality_is_dropped_on_load(
        self, cfg: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        cfg.write_text(
            json.dumps({"analysis_quality": "thorough", "theme": "light"}), encoding="utf-8"
        )
        with caplog.at_level(logging.INFO, logger="app.services"):
            loaded = SettingsManager.load()
        assert "analysis_quality" not in loaded
        assert loaded["theme"] == "light"
        assert loaded["analysis_depth"] == "rekordbox"
        assert any(
            "analysis_quality" in r.message and "legacy" in r.message for r in caplog.records
        )

    def test_legacy_key_does_not_survive_a_save_round_trip(self, cfg: Path) -> None:
        cfg.write_text(json.dumps({"analysis_quality": "fast"}), encoding="utf-8")
        SettingsManager.save(SettingsManager.load())
        assert "analysis_quality" not in json.loads(cfg.read_text(encoding="utf-8"))


# --- SetReq ------------------------------------------------------------------------


class TestSetReqDepth:
    def test_accepts_both_levels_and_defaults_to_none(self) -> None:
        assert SetReq().analysis_depth is None
        assert SetReq(analysis_depth="rekordbox").analysis_depth == "rekordbox"
        assert SetReq(analysis_depth="high").analysis_depth == "high"

    @pytest.mark.parametrize("bad", ["fast", "standard", "thorough", "HIGH", "", 1])
    def test_rejects_anything_else(self, bad: Any) -> None:
        with pytest.raises(ValidationError):
            SetReq(analysis_depth=bad)


# --- POST / GET /api/settings --------------------------------------------------------


@pytest.fixture
def quiet_settings_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main.db, "refresh_metadata", lambda: None)
    monkeypatch.setattr(main.folder_watcher, "get_watcher", lambda: None)


def test_settings_post_stores_analysis_depth(
    cfg: Path, quiet_settings_side_effects: None, auth_token: dict[str, str]
) -> None:
    r = _post("/api/settings", auth_token, {"analysis_depth": "high"})
    assert r.status_code == 200, r.text
    assert json.loads(cfg.read_text(encoding="utf-8"))["analysis_depth"] == "high"
    assert _get("/api/settings").json()["analysis_depth"] == "high"


def test_settings_post_rejects_an_unknown_depth(
    cfg: Path, quiet_settings_side_effects: None, auth_token: dict[str, str]
) -> None:
    r = _post("/api/settings", auth_token, {"analysis_depth": "fast"})
    assert r.status_code == 422
    assert not cfg.exists()


def test_settings_get_reports_the_default_without_a_file(cfg: Path) -> None:
    assert _get("/api/settings").json()["analysis_depth"] == "rekordbox"


def test_settings_post_without_the_key_still_reads_back_a_valid_depth(
    cfg: Path, quiet_settings_side_effects: None, auth_token: dict[str, str]
) -> None:
    """SetReq dumps undeclared Literal fields as null; GET must still hand out a level."""
    r = _post("/api/settings", auth_token, {"theme": "light"})
    assert r.status_code == 200, r.text
    assert _get("/api/settings").json()["analysis_depth"] == "rekordbox"
    assert SettingsManager.analysis_depth() == "rekordbox"


# --- POST /api/audio/analyze ------------------------------------------------------------


@pytest.fixture
def audio_file(tmp_path: Path) -> Path:
    f = tmp_path / "t.wav"
    f.write_bytes(b"RIFF" + b"\x00" * 64)
    return f


@pytest.fixture
def analyze_track_stub(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []

    def fake(cls, task_id: str, file_path: str, depth: str = "rekordbox"):
        seen.append(depth)
        return {"task_id": task_id, "status": "processing"}

    monkeypatch.setattr(main.AudioAnalyzer, "analyze_track", classmethod(fake))
    return seen


def test_audio_analyze_passes_the_body_depth(
    cfg: Path, audio_file: Path, analyze_track_stub: list[str], auth_token: dict[str, str]
) -> None:
    r = _post("/api/audio/analyze", auth_token, {"file_path": str(audio_file), "depth": "high"})
    assert r.status_code == 200, r.text
    assert analyze_track_stub == ["high"]


def test_audio_analyze_falls_back_to_the_stored_depth(
    cfg: Path, audio_file: Path, analyze_track_stub: list[str], auth_token: dict[str, str]
) -> None:
    cfg.write_text(json.dumps({"analysis_depth": "high"}), encoding="utf-8")
    r = _post("/api/audio/analyze", auth_token, {"file_path": str(audio_file)})
    assert r.status_code == 200, r.text
    assert analyze_track_stub == ["high"]


def test_audio_analyze_ignores_the_retired_mode_knob(
    cfg: Path, audio_file: Path, analyze_track_stub: list[str], auth_token: dict[str, str]
) -> None:
    """B9: a legacy client sending `mode` gets the stored depth, no 422, no 120 s cap."""
    r = _post("/api/audio/analyze", auth_token, {"file_path": str(audio_file), "mode": "speed"})
    assert r.status_code == 200, r.text
    assert analyze_track_stub == ["rekordbox"]


def test_audio_analyze_rejects_an_unknown_depth(
    cfg: Path, audio_file: Path, analyze_track_stub: list[str], auth_token: dict[str, str]
) -> None:
    r = _post("/api/audio/analyze", auth_token, {"file_path": str(audio_file), "depth": "fast"})
    assert r.status_code == 422
    assert analyze_track_stub == []


# --- POST /api/track/{tid}/analyze ----------------------------------------------------------


@pytest.fixture
def beat_analyze_stub(monkeypatch: pytest.MonkeyPatch, audio_file: Path) -> list[str]:
    seen: list[str] = []

    def fake(path: str, depth: str = "rekordbox"):
        seen.append(depth)
        return {"bpm": 120.0, "beats": [], "totalTime": 1.0, "dropTime": 0.5}

    track: dict[str, Any] = {"path": str(audio_file), "positionMarks": []}
    monkeypatch.setattr(main.db, "get_track_details", lambda tid: track)
    monkeypatch.setattr(main.db, "save", lambda: None)
    monkeypatch.setattr(main.BeatAnalyzer, "analyze", staticmethod(fake))
    # None -> the loop's default thread pool, so the stub runs in-process.
    monkeypatch.setattr(main.AudioAnalyzer, "get_executor", classmethod(lambda cls: None))
    return seen


def test_track_analyze_passes_the_body_depth(
    cfg: Path, beat_analyze_stub: list[str], auth_token: dict[str, str]
) -> None:
    r = _post("/api/track/1/analyze", auth_token, {"depth": "high"})
    assert r.status_code == 200, r.text
    assert r.json()["bpm"] == 120.0
    assert beat_analyze_stub == ["high"]


def test_track_analyze_without_a_body_uses_the_stored_depth(
    cfg: Path, beat_analyze_stub: list[str], auth_token: dict[str, str]
) -> None:
    cfg.write_text(json.dumps({"analysis_depth": "high"}), encoding="utf-8")
    r = _post("/api/track/1/analyze", auth_token, {})
    assert r.status_code == 200, r.text
    assert beat_analyze_stub == ["high"]


def test_track_analyze_rejects_an_unknown_depth(
    cfg: Path, beat_analyze_stub: list[str], auth_token: dict[str, str]
) -> None:
    r = _post("/api/track/1/analyze", auth_token, {"depth": "thorough"})
    assert r.status_code == 422
    assert beat_analyze_stub == []
