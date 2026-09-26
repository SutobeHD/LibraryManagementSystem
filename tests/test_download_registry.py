"""Tests for app/download_registry.py — SoundCloud download dedup/history DB.

Exercises the full lifecycle through the refactored _conn() context manager
(which now commits-or-rolls-back AND closes). The cross-call persistence
checks prove the transaction is committed; the many-call loop exercises the
no-leak path. All writes go to a throwaway DB via _REGISTRY_DB override.
"""

from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import download_registry as dr  # noqa: E402


@pytest.fixture
def registry(tmp_path, monkeypatch):
    monkeypatch.setattr(dr, "_REGISTRY_DB", tmp_path / "reg.db")
    dr.init_registry()
    return dr


def test_register_and_dedup(registry):
    assert registry.is_already_downloaded("sc1") is False
    ok = registry.register_download(
        sc_track_id="sc1", title="Song", artist="DJ", status="downloaded"
    )
    assert ok is True
    assert registry.is_already_downloaded("sc1") is True
    rec = registry.get_record("sc1")
    assert rec["title"] == "Song"
    assert rec["status"] == "downloaded"


def test_upsert_updates_status_keeps_metadata(registry):
    registry.register_download(sc_track_id="sc1", title="Real", artist="A", status="downloading")
    # re-register (UPSERT) with new status — first-seen title is intentionally kept
    registry.register_download(sc_track_id="sc1", title="", artist="", status="downloaded")
    rec = registry.get_record("sc1")
    assert rec["status"] == "downloaded"
    assert rec["title"] == "Real"  # not clobbered with the empty re-register


def test_update_analysis_and_persistence(registry):
    registry.register_download(sc_track_id="sc1", title="S", artist="A")
    assert registry.update_analysis(sc_track_id="sc1", bpm=128.0, key_str="8A", confidence=0.9)
    rec = registry.get_record("sc1")
    assert rec["bpm"] == 128.0
    assert rec["key_str"] == "8A"
    assert rec["status"] == "analyzed"


def test_find_by_hash_and_mark_failed(registry):
    registry.register_download(sc_track_id="sc1", title="S", artist="A", sha256_hash="deadbeef")
    assert registry.find_by_hash("deadbeef")["sc_track_id"] == "sc1"
    assert registry.find_by_hash("nope") is None
    registry.mark_failed("sc1", "boom")
    assert registry.get_record("sc1")["status"] == "failed"
    # failed track is no longer a dedup hit (re-downloadable)
    assert registry.is_already_downloaded("sc1") is False


def test_delete_entry_commits(registry):
    registry.register_download(sc_track_id="sc1", title="S", artist="A")
    assert registry.delete_entry("sc1") is True
    assert registry.get_record("sc1") is None


def test_history_search_and_stats(registry):
    registry.register_download(sc_track_id="sc1", title="Sunset", artist="Aria", status="analyzed")
    registry.register_download(sc_track_id="sc2", title="Nightfall", artist="Beck", status="failed")
    hits = registry.get_history(search="sun")
    assert [h["sc_track_id"] for h in hits] == ["sc1"]
    assert len(registry.get_history(limit=10)) == 2
    stats = registry.get_stats()
    assert isinstance(stats, dict)


def test_many_calls_persist_no_corruption(registry):
    """A burst of open/commit/close cycles must all land (proves _conn closes
    cleanly without losing writes)."""
    for i in range(40):
        registry.register_download(sc_track_id=f"b{i}", title=f"t{i}", artist="A")
    assert len(registry.get_history(limit=100)) == 40
    assert registry.get_record("b39")["title"] == "t39"


def test_local_track_ids_maps_only_imported_rows(registry):
    """The artist catalogue's "downloaded" match (artist hub T-30)."""
    for sc_id in ("11", "12", "13"):
        registry.register_download(sc_track_id=sc_id, title="t", artist="A")
    registry.update_analysis(sc_track_id="11", local_track_id="501")
    # The historical tuple-string bug: never a usable id, so never a link.
    registry.update_analysis(sc_track_id="13", local_track_id="('502', {'bpm': 128.0})")

    assert registry.local_track_ids(["11", "12", "13", "99", ""]) == {"11": "501"}
    assert registry.local_track_ids([]) == {}


def test_local_track_ids_reads_past_the_parameter_ceiling(registry):
    for i in range(1, 1201):
        registry.register_download(sc_track_id=str(i), title="t", artist="A")
        registry.update_analysis(sc_track_id=str(i), local_track_id=f"L{i}")

    found = registry.local_track_ids(str(i) for i in range(1, 1201))

    assert len(found) == 1200
    assert found["1200"] == "L1200"


def test_local_track_ids_never_creates_the_registry(tmp_path, monkeypatch):
    path = tmp_path / "never-downloaded.db"
    monkeypatch.setattr(dr, "_REGISTRY_DB", path)

    assert dr.local_track_ids(["1", "2"]) == {}
    assert not path.exists()
