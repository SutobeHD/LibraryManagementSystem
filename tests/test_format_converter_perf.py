"""Performance-budget tests for the format converter (T-12).

The two cheap, deterministic budgets — status-lookup latency (in-memory tracker
get) and dry-run-plan latency (DB enumeration, no per-track probe) — run here
with a tiny fake handle, no FFmpeg/rbox. The throughput + peak-memory budgets
need a real FFmpeg transcode and are skipped unless `ffmpeg` is on PATH (they
remain TODO scaffolding for a full runner).

Bounds are intentionally lenient sanity ceilings (not tight p95s) so they don't
flake on a loaded CI box; they catch accidental O(n^2) / per-call blowups.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

import pytest

import app.format_converter as fc
import app.format_swap_tracker as tracker


class _FakeContent:
    def __init__(self, cid, folder_path, file_size=4_000_000):
        self.id = cid
        self.folder_path = str(folder_path)
        self.file_name_l = Path(folder_path).name
        self.file_type = 4
        self.file_size = file_size
        self.rb_local_deleted = False


class _FakeDb:
    def __init__(self, contents):
        self._contents = contents

    def get_contents(self):
        return list(self._contents)

    def get_playlist_contents(self, pid):
        return []

    def get_playlists(self):
        return []


@pytest.mark.slow
def test_status_lookup_latency(tmp_path):
    """tracker.get() is an in-memory dict read — p95 must stay well under 10ms."""
    tid = tracker.register("user_format_pick", "AIFF", "all m4a", 3041)
    tracker.update(tid, status="Converting", converted=1500)
    samples = []
    for _ in range(200):
        t0 = time.perf_counter()
        tracker.get(tid)
        samples.append(time.perf_counter() - t0)
    samples.sort()
    p95 = samples[int(len(samples) * 0.95)]
    assert p95 < 0.010, f"status lookup p95 {p95 * 1000:.2f}ms exceeds 10ms"


@pytest.mark.slow
def test_dry_run_plan_latency_large_library(tmp_path):
    """Dry-run enumerates the DB + sums file_size (no per-track ffprobe). 5000
    fake m4a rows must plan in well under 2s (sanity ceiling, not a p95)."""
    contents = [_FakeContent(i, tmp_path / f"t{i}.m4a") for i in range(5000)]
    master_db = tmp_path / "master.db"
    master_db.write_bytes(b"x")
    engine = fc.FormatSwapEngine(
        db=_FakeDb(contents), master_db_path=master_db, backup_dir=tmp_path / "bk"
    )
    t0 = time.perf_counter()
    plan = engine.dry_run({"all_m4a": True}, "AIFF")
    elapsed = time.perf_counter() - t0
    assert plan["convertible"] == 5000
    assert elapsed < 2.0, f"dry-run of 5000 rows took {elapsed:.2f}s (>2s)"


@pytest.mark.slow
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs FFmpeg on PATH")
def test_transcode_throughput_placeholder():
    """TODO(full-runner): transcode a real fixture, assert >= ~10x realtime
    (OQ3). Needs an FFmpeg build + a sample audio fixture."""
    pytest.skip("real-audio throughput benchmark — implement on a full runner")


@pytest.mark.slow
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs FFmpeg on PATH")
def test_peak_memory_placeholder():
    """TODO(full-runner): run a batch under tracemalloc / RSS sampling, assert
    peak <= ~150MB over baseline (engine streams one ffmpeg subprocess/track)."""
    pytest.skip("real-audio peak-memory benchmark — implement on a full runner")
