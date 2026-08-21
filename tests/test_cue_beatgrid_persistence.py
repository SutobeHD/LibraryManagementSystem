"""Round-trip tests for the cue / beatgrid sidecar persistence.

`POST /api/track/cues/save` and `/api/track/grid/save` called
`db.save_track_cues` / `db.save_track_beatgrid`, which existed on no DB
facade and had no `__getattr__` behind them — every save from the waveform
editor returned HTTP 500. These tests pin the four methods down so the
endpoints can't silently lose their backing again.

The sidecar is a stopgap: it is NOT master.db and NOT the ANLZ files, so
what it stores never reaches Rekordbox or a CDJ. The tests assert the
storage contract only.
"""

from __future__ import annotations

import json

import pytest

from app.database import RekordboxDB

CUES = [
    {"number": 0, "type": "hot_cue", "time_ms": 14777, "name": "Start", "color_id": 1},
    {"number": 1, "type": "hot_cue", "time_ms": 29777, "name": "Verse", "color_id": 2},
    {"type": "memory_cue", "time_ms": 1000, "name": "Intro"},
]
GRID = [{"beat": (i % 4) + 1, "bpm": 128.0, "time_ms": 500 + i * 469} for i in range(8)]


@pytest.fixture
def db(tmp_path, monkeypatch):
    """A facade whose sidecars land in tmp_path instead of the real LOG_DIR."""
    instance = RekordboxDB.__new__(RekordboxDB)
    monkeypatch.setattr(
        type(instance), "_cue_sidecar_path", lambda self: tmp_path / "cue_overrides.json"
    )
    monkeypatch.setattr(
        type(instance),
        "_beatgrid_sidecar_path",
        lambda self: tmp_path / "beatgrid_overrides.json",
    )
    monkeypatch.setattr(type(instance), "get_track_details", lambda self, tid: None)
    return instance


class TestCuePersistence:
    def test_save_then_get_round_trips(self, db):
        assert db.save_track_cues("T1", CUES) is True
        assert db.get_track_cues("T1") == CUES

    def test_unknown_track_returns_empty_list(self, db):
        db.save_track_cues("T1", CUES)
        assert db.get_track_cues("T-does-not-exist") == []

    def test_second_track_does_not_clobber_the_first(self, db):
        db.save_track_cues("T1", CUES)
        db.save_track_cues("T2", [{"type": "memory_cue", "time_ms": 42}])
        assert db.get_track_cues("T1") == CUES
        assert db.get_track_cues("T2") == [{"type": "memory_cue", "time_ms": 42}]

    def test_overwrites_the_same_track(self, db):
        db.save_track_cues("T1", CUES)
        db.save_track_cues("T1", [])
        assert db.get_track_cues("T1") == []

    def test_write_is_atomic_no_tmp_left_behind(self, db, tmp_path):
        db.save_track_cues("T1", CUES)
        assert not list(tmp_path.glob("*.tmp"))
        assert (tmp_path / "cue_overrides.json").exists()

    def test_corrupt_sidecar_does_not_lose_the_new_write(self, db, tmp_path):
        """A truncated sidecar must not make save() fail — it starts fresh."""
        (tmp_path / "cue_overrides.json").write_text("{not json", encoding="utf-8")
        assert db.save_track_cues("T1", CUES) is True
        assert db.get_track_cues("T1") == CUES

    def test_corrupt_sidecar_reads_as_empty(self, db, tmp_path):
        (tmp_path / "cue_overrides.json").write_text("{not json", encoding="utf-8")
        assert db.get_track_cues("T1") == []


class TestBeatgridPersistence:
    def test_save_then_get_round_trips(self, db):
        assert db.save_track_beatgrid("T1", GRID) is True
        assert db.get_track_beatgrid("T1") == GRID

    def test_kept_in_a_separate_sidecar_from_cues(self, db, tmp_path):
        db.save_track_cues("T1", CUES)
        db.save_track_beatgrid("T1", GRID)
        cue_file = json.loads((tmp_path / "cue_overrides.json").read_text(encoding="utf-8"))
        grid_file = json.loads((tmp_path / "beatgrid_overrides.json").read_text(encoding="utf-8"))
        assert cue_file["T1"] == CUES
        assert grid_file["T1"] == GRID

    def test_unknown_track_returns_empty_list(self, db):
        assert db.get_track_beatgrid("nope") == []


class TestFallbackToActiveDb:
    def test_cues_fall_back_to_track_details(self, tmp_path, monkeypatch):
        """With no sidecar override, whatever the active DB loaded wins."""
        instance = RekordboxDB.__new__(RekordboxDB)
        monkeypatch.setattr(
            type(instance), "_cue_sidecar_path", lambda self: tmp_path / "cue_overrides.json"
        )
        monkeypatch.setattr(
            type(instance), "get_track_details", lambda self, tid: {"Cues": [{"time_ms": 7}]}
        )
        assert instance.get_track_cues("T1") == [{"time_ms": 7}]

    def test_sidecar_override_beats_the_active_db(self, tmp_path, monkeypatch):
        instance = RekordboxDB.__new__(RekordboxDB)
        monkeypatch.setattr(
            type(instance), "_cue_sidecar_path", lambda self: tmp_path / "cue_overrides.json"
        )
        monkeypatch.setattr(
            type(instance), "get_track_details", lambda self, tid: {"Cues": [{"time_ms": 7}]}
        )
        instance.save_track_cues("T1", CUES)
        assert instance.get_track_cues("T1") == CUES


class TestWriteLockCoverage:
    def test_savers_are_serialised(self):
        """Both savers must be in database.py's `_serialised` wrap list —
        they mutate shared on-disk state from FastAPI worker threads."""
        import inspect

        for name in ("save_track_cues", "save_track_beatgrid"):
            fn = getattr(RekordboxDB, name)
            src = inspect.getsource(fn)
            assert "db_lock" in src or fn.__wrapped__ is not None, (
                f"{name} is not wrapped by _serialised"
            )


class TestEndpointsNoLongerFiveHundred:
    """The regression that mattered: both save routes returned HTTP 500
    because the DB facade had no such method.

    Driven over ``httpx.ASGITransport`` rather than ``TestClient`` — the
    installed fastapi/httpx pair breaks starlette's TestClient (it still
    passes ``app=`` to ``httpx.Client``). Same reason as tests/test_auth.py.
    """

    @pytest.fixture
    def request_json(self, tmp_path, monkeypatch):
        import asyncio

        import httpx

        from app import database as db_mod
        from app.main import app as fastapi_app

        monkeypatch.setattr(
            type(db_mod.db), "_cue_sidecar_path", lambda self: tmp_path / "cue_overrides.json"
        )
        monkeypatch.setattr(
            type(db_mod.db),
            "_beatgrid_sidecar_path",
            lambda self: tmp_path / "beatgrid_overrides.json",
        )

        def _go(url, payload, headers=None):
            async def _run():
                transport = httpx.ASGITransport(app=fastapi_app, raise_app_exceptions=False)
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://testserver"
                ) as ac:
                    return await ac.post(url, json=payload, headers=headers)

            return asyncio.run(_run())

        return _go

    def test_cue_save_route(self, request_json, auth_token):
        r = request_json("/api/track/cues/save", {"track_id": "T1", "cues": CUES}, auth_token)
        assert r.status_code != 500, r.text
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "success"

    def test_grid_save_route(self, request_json, auth_token):
        r = request_json("/api/track/grid/save", {"track_id": "T1", "beat_grid": GRID}, auth_token)
        assert r.status_code != 500, r.text
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "success"

    def test_cue_save_still_requires_auth(self, request_json):
        r = request_json("/api/track/cues/save", {"track_id": "T1", "cues": []})
        assert r.status_code in (401, 403), r.text
