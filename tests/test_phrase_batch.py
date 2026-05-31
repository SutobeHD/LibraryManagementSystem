"""
Tests for the phrase-batch backend (app/main.py):

  * resolve_track_scope — all four scope kinds, de-dupe, key-shape fallbacks
  * _phrase_track_fields — live/xml/raw key shapes
  * _run_phrase_batch — progress, skipped/failed reasons, cancel, ETA, error cap
  * /api/phrase/batch/{start,status,cancel} — auth, validation, 409 single-flight

The blocking phrase_generator calls are monkeypatched in the app.main namespace
so no rbox / real ANLZ is touched. The autouse `auth_token` fixture (conftest)
pins SESSION_TOKEN and yields the Bearer header.
"""

from __future__ import annotations

import asyncio
import contextlib

import httpx
import pytest
from fastapi import HTTPException

from app import main
from app.main import _phrase_track_fields, _run_phrase_batch, app, resolve_track_scope
from app.phrase_generator import PhraseNotAnalysedError


# fastapi 0.109 + httpx 0.28 break starlette TestClient → drive the ASGI app
# directly (same pattern as tests/test_main_security.py).
def _post(url, json=None, *, headers=None):
    async def _go():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            return await ac.post(url, json=json, headers=headers)

    return asyncio.run(_go())


def _get(url, params=None, *, headers=None):
    async def _go():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            return await ac.get(url, params=params, headers=headers)

    return asyncio.run(_go())


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clean_phrase_state():
    """Reset module-global job store + single-flight lock around every test."""
    main._phrase_jobs.clear()
    yield
    main._phrase_jobs.clear()
    # Defensive: a test may have monkeypatched the lock with a stub that lacks
    # release(); suppress so teardown never masks the real assertion.
    with contextlib.suppress(AttributeError, RuntimeError):
        if main._phrase_batch_lock.locked():
            main._phrase_batch_lock.release()


class _DB:
    """Minimal stand-in for the `db` facade used by resolve_track_scope."""

    def __init__(self, *, loaded=True, all_tracks=None, playlist_tracks=None, details=None):
        self.loaded = loaded
        self._all = all_tracks or []
        self._pl = playlist_tracks or []
        self._details = details

    def get_all_tracks(self):
        return self._all

    def get_playlist_tracks(self, _pid):
        return self._pl

    def get_track_details(self, _tid):
        return self._details


def _new_job(total):
    return {
        "status": "running",
        "total": total,
        "done": 0,
        "percent": 0.0,
        "eta_seconds": 0.0,
        "current_track": None,
        "succeeded": 0,
        "skipped": 0,
        "failed": 0,
        "errors": [],
        "errors_truncated": False,
        "cancel_requested": False,
        "scope_kind": "test",
    }


def _drive(
    tracks,
    monkeypatch,
    *,
    beats=(0.0, 0.5, 1.0, 1.5),
    cues=None,
    commit=None,
    align=False,
    cancel=False,
):
    """Run _run_phrase_batch over `tracks` with patched phrase funcs; return job."""
    if cues is None:
        cues = [{"type": "phrase_start", "position_ms": 0, "label": "P1", "color": 0}]
    monkeypatch.setattr(main, "extract_beats_from_db", lambda tid, dbp: list(beats))
    monkeypatch.setattr(main, "generate_phrase_cues", lambda b, phrase_length=16: cues)
    monkeypatch.setattr(main, "detect_first_downbeat", lambda p, b: b[0])
    if commit is None:
        commit = lambda tid, c, dbp, include_bar_markers=False: {"written": len(c)}  # noqa: E731
    monkeypatch.setattr(main, "commit_phrase_cues", commit)
    monkeypatch.setattr(main, "_phrase_db_path", lambda: "X:/master.db")

    job_id = "job-test"
    main._phrase_jobs[job_id] = _new_job(len(tracks))
    if cancel:
        main._phrase_jobs[job_id]["cancel_requested"] = True
    asyncio.run(_run_phrase_batch(job_id, tracks, 16, align, False))
    return main._phrase_jobs[job_id]


def _tracks(n):
    return [{"id": i, "title": f"T{i}", "path": f"p{i}"} for i in range(1, n + 1)]


# ── _phrase_track_fields ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ({"ID": 5, "Title": "T", "path": "p"}, {"id": 5, "title": "T", "path": "p"}),
        ({"id": 7, "Title": "X", "path": "q"}, {"id": 7, "title": "X", "path": "q"}),
        ({"TrackID": 9, "Name": "N", "Location": "L"}, {"id": 9, "title": "N", "path": "L"}),
        ({"Title": "no id"}, None),
        ({"ID": "not-int"}, None),
    ],
)
def test_phrase_track_fields(raw, expected):
    assert _phrase_track_fields(raw) == expected


# ── resolve_track_scope ──────────────────────────────────────────────────────


def test_scope_single(monkeypatch):
    monkeypatch.setattr(main, "db", _DB(details={"ID": 42, "Title": "One", "path": "a"}))
    out = resolve_track_scope(main.PhraseScope(kind="single", track_id=42))
    assert out == [{"id": 42, "title": "One", "path": "a"}]


def test_scope_single_missing_returns_empty(monkeypatch):
    monkeypatch.setattr(main, "db", _DB(details=None))
    assert resolve_track_scope(main.PhraseScope(kind="single", track_id=99)) == []


def test_scope_single_without_id_raises(monkeypatch):
    monkeypatch.setattr(main, "db", _DB())
    with pytest.raises(HTTPException) as e:
        resolve_track_scope(main.PhraseScope(kind="single"))
    assert e.value.status_code == 400


def test_scope_playlist(monkeypatch):
    pl = [{"ID": 1, "Title": "A", "path": "a"}, {"ID": 2, "Title": "B", "path": "b"}]
    monkeypatch.setattr(main, "db", _DB(playlist_tracks=pl))
    out = resolve_track_scope(main.PhraseScope(kind="playlist", playlist_id="p1"))
    assert [t["id"] for t in out] == [1, 2]


def test_scope_selection_filters(monkeypatch):
    allt = [{"ID": i, "Title": str(i), "path": str(i)} for i in (1, 2, 3, 4)]
    monkeypatch.setattr(main, "db", _DB(all_tracks=allt))
    out = resolve_track_scope(main.PhraseScope(kind="selection", track_ids=[2, 4]))
    assert sorted(t["id"] for t in out) == [2, 4]


def test_scope_collection_all(monkeypatch):
    allt = [{"ID": i, "Title": str(i), "path": str(i)} for i in (1, 2, 3)]
    monkeypatch.setattr(main, "db", _DB(all_tracks=allt))
    out = resolve_track_scope(main.PhraseScope(kind="collection"))
    assert len(out) == 3


def test_scope_dedupes_by_id(monkeypatch):
    allt = [{"ID": 1, "Title": "a", "path": "x"}, {"ID": 1, "Title": "dup", "path": "y"}]
    monkeypatch.setattr(main, "db", _DB(all_tracks=allt))
    out = resolve_track_scope(main.PhraseScope(kind="collection"))
    assert len(out) == 1 and out[0]["id"] == 1


def test_scope_unknown_kind_raises(monkeypatch):
    monkeypatch.setattr(main, "db", _DB())
    with pytest.raises(HTTPException) as e:
        resolve_track_scope(main.PhraseScope(kind="bogus"))
    assert e.value.status_code == 400


# ── _run_phrase_batch worker ─────────────────────────────────────────────────


def test_worker_all_succeed(monkeypatch):
    job = _drive(_tracks(3), monkeypatch)
    assert job["status"] == "done"
    assert (job["succeeded"], job["skipped"], job["failed"]) == (3, 0, 0)
    assert job["done"] == 3 and job["percent"] == 100.0
    assert job["eta_seconds"] == 0.0
    assert job["current_track"] is None


def test_worker_skips_no_beatgrid(monkeypatch):
    job = _drive(_tracks(2), monkeypatch, beats=())
    assert (job["succeeded"], job["skipped"], job["failed"]) == (0, 2, 0)
    assert all(e["reason"] == "no beatgrid" for e in job["errors"])


def test_worker_skips_no_phrase_cues(monkeypatch):
    only_bars = [{"type": "bar_start", "position_ms": 0, "label": "B1", "color": 0}]
    job = _drive(_tracks(1), monkeypatch, cues=only_bars)
    assert job["skipped"] == 1
    assert job["errors"][0]["reason"] == "no phrase cues"


def test_worker_skips_not_analysed(monkeypatch):
    def _raise(tid, c, dbp, include_bar_markers=False):
        raise PhraseNotAnalysedError("no anlz")

    job = _drive(_tracks(2), monkeypatch, commit=_raise)
    assert (job["succeeded"], job["skipped"], job["failed"]) == (0, 2, 0)
    assert all(e["reason"] == "not analysed" for e in job["errors"])


def test_worker_records_failure(monkeypatch):
    def _boom(tid, c, dbp, include_bar_markers=False):
        raise ValueError("kaboom")

    job = _drive(_tracks(1), monkeypatch, commit=_boom)
    assert job["failed"] == 1
    assert "kaboom" in job["errors"][0]["reason"]


def test_worker_cancel_before_first(monkeypatch):
    job = _drive(_tracks(5), monkeypatch, cancel=True)
    assert job["status"] == "cancelled"
    assert job["succeeded"] == 0 and job["done"] == 0


def test_worker_error_cap(monkeypatch):
    def _boom(tid, c, dbp, include_bar_markers=False):
        raise ValueError("x")

    job = _drive(_tracks(250), monkeypatch, commit=_boom)
    assert job["failed"] == 250
    assert len(job["errors"]) == 200
    assert job["errors_truncated"] is True


def test_worker_eta_positive_mid_run(monkeypatch):
    # 2 tracks: assert eta math stays a non-negative number through completion.
    job = _drive(_tracks(2), monkeypatch)
    assert isinstance(job["eta_seconds"], float) and job["eta_seconds"] >= 0.0


# ── Endpoints ────────────────────────────────────────────────────────────────


def test_start_requires_auth():
    r = _post("/api/phrase/batch/start", json={"scope": {"kind": "collection"}})
    assert r.status_code == 401


def test_start_library_not_loaded(monkeypatch, auth_token):
    monkeypatch.setattr(main, "db", _DB(loaded=False))
    r = _post(
        "/api/phrase/batch/start",
        json={"scope": {"kind": "collection"}},
        headers=auth_token,
    )
    assert r.status_code == 400


def test_start_bad_phrase_length(monkeypatch, auth_token):
    monkeypatch.setattr(main, "db", _DB(all_tracks=[{"ID": 1, "Title": "a", "path": "p"}]))
    r = _post(
        "/api/phrase/batch/start",
        json={"scope": {"kind": "collection"}, "phrase_length": 7},
        headers=auth_token,
    )
    assert r.status_code == 400


def test_start_empty_scope(monkeypatch, auth_token):
    monkeypatch.setattr(main, "db", _DB(all_tracks=[]))
    r = _post(
        "/api/phrase/batch/start",
        json={"scope": {"kind": "collection"}},
        headers=auth_token,
    )
    assert r.status_code == 400


def test_start_conflict_when_locked(monkeypatch, auth_token):
    class _Locked:
        def locked(self):
            return True

    monkeypatch.setattr(main, "db", _DB(all_tracks=[{"ID": 1, "Title": "a", "path": "p"}]))
    monkeypatch.setattr(main, "_phrase_batch_lock", _Locked())
    r = _post(
        "/api/phrase/batch/start",
        json={"scope": {"kind": "collection"}},
        headers=auth_token,
    )
    assert r.status_code == 409


def test_start_happy_returns_job(monkeypatch, auth_token):
    monkeypatch.setattr(main, "db", _DB(all_tracks=[{"ID": 1, "Title": "a", "path": "p"}]))

    async def _stub(job_id, *a, **k):
        main._phrase_jobs[job_id]["status"] = "done"
        if main._phrase_batch_lock.locked():
            main._phrase_batch_lock.release()

    monkeypatch.setattr(main, "_run_phrase_batch", _stub)
    r = _post(
        "/api/phrase/batch/start",
        json={"scope": {"kind": "collection"}, "phrase_length": 16},
        headers=auth_token,
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["total"] == 1 and "job_id" in data


def test_status_unknown_404():
    r = _get("/api/phrase/batch/status", params={"job_id": "nope"})
    assert r.status_code == 404


def test_status_returns_job():
    main._phrase_jobs["abc"] = _new_job(3)
    r = _get("/api/phrase/batch/status", params={"job_id": "abc"})
    assert r.status_code == 200
    assert r.json()["data"]["total"] == 3


def test_cancel_unknown_404(auth_token):
    r = _post("/api/phrase/batch/cancel", json={"job_id": "nope"}, headers=auth_token)
    assert r.status_code == 404


def test_cancel_sets_flag(auth_token):
    main._phrase_jobs["abc"] = _new_job(3)
    r = _post("/api/phrase/batch/cancel", json={"job_id": "abc"}, headers=auth_token)
    assert r.status_code == 200
    assert main._phrase_jobs["abc"]["cancel_requested"] is True
