"""Tests for the cue save / get sidecar roundtrip added in Slice 1.

The endpoints ``POST /api/track/cues/save`` and ``GET /api/track/{tid}/cues``
were previously calling ``db.save_track_cues`` / ``db.get_track_cues`` which
did not exist (would raise AttributeError on first call). Slice 1 adds a
minimal JSON-sidecar so the new CuePanel has a working save path until
the proper rbox + ANLZ wiring lands in a later slice.

Run from repo root: ``pytest tests/test_cue_endpoint_roundtrip.py -v``.
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


def test_save_track_cues_creates_sidecar(tmp_log_dir):
    from app.database import db

    cues = [
        {
            "id": "mem-1",
            "type": "memory_cue",
            "time_ms": 5000,
            "color_id": 5,
            "color_rgb": [79, 203, 107],
            "name": "Drop",
            "status": 0,
        }
    ]
    assert db.save_track_cues("track-42", cues) is True

    sidecar = Path(tmp_log_dir) / "cue_overrides.json"
    assert sidecar.exists()
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    assert "track-42" in data
    assert data["track-42"] == cues


def test_get_track_cues_returns_sidecar_override(tmp_log_dir):
    from app.database import db

    cues = [{"id": "mem-1", "type": "memory_cue", "time_ms": 12345, "name": "X"}]
    db.save_track_cues("track-7", cues)

    got = db.get_track_cues("track-7")
    assert got == cues


def test_get_track_cues_empty_for_unknown_track(tmp_log_dir):
    from app.database import db

    got = db.get_track_cues("does-not-exist-99999")
    assert got == []


def test_save_track_cues_roundtrip_preserves_unicode(tmp_log_dir):
    from app.database import db

    cues = [{"id": "mem-1", "type": "memory_cue", "time_ms": 1000, "name": "Drüss"}]
    assert db.save_track_cues("track-de", cues) is True

    got = db.get_track_cues("track-de")
    assert got[0]["name"] == "Drüss"


def test_save_track_cues_overwrites_previous(tmp_log_dir):
    from app.database import db

    db.save_track_cues("track-9", [{"id": "a", "type": "memory_cue", "time_ms": 100}])
    db.save_track_cues(
        "track-9", [{"id": "b", "type": "hot_cue", "number": 1, "time_ms": 200}]
    )
    got = db.get_track_cues("track-9")
    assert len(got) == 1
    assert got[0]["id"] == "b"
