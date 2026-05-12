"""Tests for the beatgrid save / get sidecar roundtrip added in Slice 3.

The endpoint ``POST /api/track/grid/save`` was previously calling
``db.save_track_beatgrid`` which did not exist (AttributeError on every
call). Slice 3 adds minimal JSON-sidecar persistence so the BeatgridPanel
has a working save path until proper rbox + ANLZ (PQTZ / PQT2) wiring
lands in a later slice.

Run from repo root: ``pytest tests/test_beatgrid_endpoint_roundtrip.py -v``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def tmp_log_dir(monkeypatch, tmp_path):
    """Redirect LOG_DIR so the sidecar lands in an isolated tmp folder."""
    from app import config as cfg

    monkeypatch.setattr(cfg, "LOG_DIR", str(tmp_path), raising=True)
    return tmp_path


def test_save_track_beatgrid_creates_sidecar(tmp_log_dir):
    from app.database import db

    grid = [
        {"beat_number": 1, "time_ms": 0, "tempo": 12800},
        {"beat_number": 2, "time_ms": 468, "tempo": 12800},
        {"beat_number": 3, "time_ms": 937, "tempo": 12800},
        {"beat_number": 4, "time_ms": 1406, "tempo": 12800},
    ]
    assert db.save_track_beatgrid("track-bg", grid) is True

    sidecar = Path(tmp_log_dir) / "beatgrid_overrides.json"
    assert sidecar.exists()
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    assert "track-bg" in data
    assert data["track-bg"] == grid


def test_get_track_beatgrid_returns_override(tmp_log_dir):
    from app.database import db

    grid = [{"beat_number": 1, "time_ms": 100, "tempo": 13000}]
    db.save_track_beatgrid("track-bg2", grid)
    assert db.get_track_beatgrid("track-bg2") == grid


def test_get_track_beatgrid_empty_for_unknown_track(tmp_log_dir):
    from app.database import db

    assert db.get_track_beatgrid("does-not-exist-xyz") == []


def test_save_track_beatgrid_overwrites_previous(tmp_log_dir):
    from app.database import db

    db.save_track_beatgrid("track-x", [{"beat_number": 1, "time_ms": 0}])
    db.save_track_beatgrid("track-x", [{"beat_number": 1, "time_ms": 500, "tempo": 14000}])

    got = db.get_track_beatgrid("track-x")
    assert len(got) == 1
    assert got[0]["time_ms"] == 500
    assert got[0]["tempo"] == 14000


def test_save_track_beatgrid_monotonic_times(tmp_log_dir):
    """Beat times in a saved grid are expected to be monotonically
    increasing. The sidecar does NOT enforce this — that's the writer's
    responsibility — but the roundtrip preserves the order verbatim."""
    from app.database import db

    grid = [{"beat_number": (i % 4) + 1, "time_ms": i * 468} for i in range(16)]
    db.save_track_beatgrid("track-mono", grid)

    got = db.get_track_beatgrid("track-mono")
    times = [b["time_ms"] for b in got]
    assert times == sorted(times)
    assert len(times) == 16
