"""Tests for ``app/downloader/orchestrator.py`` — the Phase-5 fetch pipeline.

Every external touch-point is mocked: providers never hit the network, the
registry is redirected at a tmp SQLite file, AIFF conversion / artwork fetch /
background analysis are stubbed. The two headline cases:

* the happy path — all 9 steps run, the ``JobStatus`` ends ``done`` with a
  ``final_path``;
* a deliberately-failing step — the provider's ``fetch`` raises, and the job
  must end ``failed`` with the error attached (never an escaped exception).

Plus the request-cache (``remember_resolve`` / ``remember_search`` →
``enqueue_fetch`` lookup), the ``KeyError`` / ``RuntimeError`` raise contract,
and dedup short-circuiting.

See ``docs/research/implement/accepted_downloader-unified-multi-source.md``
§ "P5.18".
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from app.downloader import orchestrator as orch
from app.downloader.models import (
    Candidate,
    FetchRequest,
    MatchResult,
    Platform,
    QualityTier,
    ResolveResponse,
    SearchHit,
    SearchResponse,
    TrackMatch,
)

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _claim(
    *,
    platform: Platform = "soundcloud",
    title: str = "Wake Me Up",
    artist: str = "Avicii",
    isrc: str | None = "USUM71304455",
    genre: str | None = "Deep House",
    url: str = "https://soundcloud.com/avicii/wake-me-up",
    fmt: str = "flac",
    tier: QualityTier = QualityTier.CD_LOSSLESS,
) -> TrackMatch:
    """Build a :class:`TrackMatch` claim with sensible defaults."""
    return TrackMatch(
        platform=platform,
        url=url,
        title=title,
        artist=artist,
        duration_s=247.0,
        isrc=isrc,
        album="True",
        year=2013,
        genre=genre,
        cover_url=None,
        claimed_format=fmt,  # type: ignore[arg-type]
        claimed_bit_depth=16,
        claimed_sample_rate_hz=44100,
        claimed_bitrate_kbps=None,
        quality_tier=tier,
    )


def _candidate(match: TrackMatch | None = None) -> Candidate:
    """Wrap a claim in a 100%-match :class:`Candidate`."""
    m = match or _claim()
    return Candidate(
        match=m,
        match_result=MatchResult(is_match=True, confidence=1.0, rule_fired="isrc_equality"),
    )


class _FakeProvider:
    """Mock provider whose ``fetch`` writes a stub file (or raises)."""

    def __init__(self, *, raises: Exception | None = None, content: bytes = b"FAKE-AUDIO") -> None:
        self._raises = raises
        self._content = content
        self.fetch_calls: list[TrackMatch] = []

    async def fetch(self, match: TrackMatch, dest_dir: Path) -> Path:
        self.fetch_calls.append(match)
        if self._raises is not None:
            raise self._raises
        dest_dir.mkdir(parents=True, exist_ok=True)
        out = dest_dir / "downloaded.flac"
        out.write_bytes(self._content)
        return out


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Redirect MUSIC_DIR + the registry DB at a tmp dir; clear caches/jobs.

    Each test gets a pristine job registry, an empty request cache, a tmp
    music dir, and a stubbed background analysis (so no real DSP runs).
    """
    music = tmp_path / "music"
    music.mkdir()
    monkeypatch.setattr(orch, "MUSIC_DIR", music)

    # Registry → its own tmp SQLite file.
    from app import download_registry as reg

    monkeypatch.setattr(reg, "_REGISTRY_DB", tmp_path / "registry.db")
    reg.init_registry()

    # Background analysis is a no-op — no DSP, no master.db.
    monkeypatch.setattr(orch, "_schedule_analysis", lambda _p: None)
    # Artwork fetch never reaches the network.
    monkeypatch.setattr(orch, "_fetch_artwork", lambda _u: None)

    orch._jobs.clear()
    with orch._cache_lock:
        orch._request_cache.clear()


def _run_job_and_wait(job_id: str, timeout_s: float = 5.0) -> object:
    """Poll the job registry until the job leaves the in-flight states."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        job = orch.get_job(job_id)
        if job is not None and job.state in ("done", "failed"):
            return job
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} did not finish within {timeout_s}s")


# ──────────────────────────────────────────────────────────────────────────────
# Request cache + enqueue contract
# ──────────────────────────────────────────────────────────────────────────────


def test_remember_resolve_then_enqueue_finds_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    """A resolve result is cached so enqueue_fetch can resolve request_id+index."""
    fake = _FakeProvider()
    monkeypatch.setattr(orch, "_provider_for_platform", lambda _p: fake)

    resp = ResolveResponse(
        request_id="req-1",
        needle=_claim(),
        candidates=[_candidate()],
        auto_pick_index=0,
        near_misses=[],
    )
    orch.remember_resolve(resp)

    fetch_resp = orch.enqueue_fetch(FetchRequest(request_id="req-1", candidate_index=0))
    assert fetch_resp.job_id
    assert fetch_resp.started_at
    job = _run_job_and_wait(fetch_resp.job_id)
    assert job.state == "done"  # type: ignore[attr-defined]


def test_remember_search_wraps_hits_as_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    """A search result's hits become fetch-ready candidates in the cache."""
    fake = _FakeProvider()
    monkeypatch.setattr(orch, "_provider_for_platform", lambda _p: fake)

    resp = SearchResponse(
        request_id="req-search",
        hits=[
            SearchHit(
                cluster_id="USUM71304455",
                representative=_claim(),
                cross_platform_urls={},
            )
        ],
    )
    orch.remember_search(resp)

    fetch_resp = orch.enqueue_fetch(FetchRequest(request_id="req-search", candidate_index=0))
    job = _run_job_and_wait(fetch_resp.job_id)
    assert job.state == "done"  # type: ignore[attr-defined]


def test_enqueue_unknown_request_id_raises_keyerror() -> None:
    """An unknown request_id is a KeyError (route maps it to 400)."""
    with pytest.raises(KeyError):
        orch.enqueue_fetch(FetchRequest(request_id="does-not-exist", candidate_index=0))


def test_enqueue_index_out_of_range_raises_keyerror() -> None:
    """A candidate_index past the end of the list is a KeyError."""
    resp = ResolveResponse(
        request_id="req-2",
        needle=_claim(),
        candidates=[_candidate()],
        auto_pick_index=0,
        near_misses=[],
    )
    orch.remember_resolve(resp)
    with pytest.raises(KeyError):
        orch.enqueue_fetch(FetchRequest(request_id="req-2", candidate_index=5))


def test_enqueue_when_downloader_disabled_raises_runtimeerror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The unified_downloader.enabled kill-switch makes enqueue raise RuntimeError."""
    monkeypatch.setattr(orch, "_downloader_enabled", lambda: False)
    resp = ResolveResponse(
        request_id="req-3",
        needle=_claim(),
        candidates=[_candidate()],
        auto_pick_index=0,
        near_misses=[],
    )
    orch.remember_resolve(resp)
    with pytest.raises(RuntimeError):
        orch.enqueue_fetch(FetchRequest(request_id="req-3", candidate_index=0))


# ──────────────────────────────────────────────────────────────────────────────
# The 9-step pipeline — happy path
# ──────────────────────────────────────────────────────────────────────────────


def test_pipeline_happy_path_lands_file_and_records(monkeypatch: pytest.MonkeyPatch) -> None:
    """All 9 steps run: file lands in MUSIC_DIR/<artist>/, registry row written."""
    fake = _FakeProvider()
    monkeypatch.setattr(orch, "_provider_for_platform", lambda _p: fake)
    # AIFF conversion is a no-op passthrough (keep the .flac).
    monkeypatch.setattr(orch, "convert_to_aiff", lambda p: None)
    monkeypatch.setattr(orch, "map_genre", lambda _g, **_kw: "Deep House")

    cand = _candidate()
    job_id = "job-happy"
    orch._put_job(_make_queued(job_id))
    orch.execute_fetch(job_id, cand, [cand])

    job = orch.get_job(job_id)
    assert job is not None
    assert job.state == "done"
    assert job.progress_pct == 100
    assert job.final_path is not None
    final = Path(job.final_path)
    assert final.exists()
    assert final.parent.name == "Avicii"
    assert fake.fetch_calls  # provider.fetch ran

    # Step 8 — registry row exists with the unified columns populated.
    from app import download_registry as reg

    sha = reg.compute_sha256(final)
    assert sha is not None
    row = reg.find_by_hash(sha)
    assert row is not None
    assert row["source"] == "soundcloud"
    assert row["isrc"] == "USUM71304455"
    assert row["picked_quality_tier"] == int(QualityTier.CD_LOSSLESS)


def test_pipeline_writes_provenance_into_comment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Step 5/6 — provenance string is handed to write_tags in the COMMENT slot."""
    fake = _FakeProvider()
    monkeypatch.setattr(orch, "_provider_for_platform", lambda _p: fake)
    monkeypatch.setattr(orch, "convert_to_aiff", lambda p: None)

    captured: dict[str, object] = {}

    def _spy_write_tags(path, updates, artwork=None):
        captured["updates"] = updates
        return True

    monkeypatch.setattr(orch.audio_tags, "write_tags", _spy_write_tags)

    cand = _candidate()
    job_id = "job-prov"
    orch._put_job(_make_queued(job_id))
    orch.execute_fetch(job_id, cand, [cand])

    updates = captured["updates"]
    assert isinstance(updates, dict)
    assert updates["ISRC"] == "USUM71304455"
    # The picked URL is the head of the provenance comment (D6 invariant).
    assert updates["Comment"].startswith("https://soundcloud.com/avicii/wake-me-up")


def test_pipeline_dedup_hit_short_circuits(monkeypatch: pytest.MonkeyPatch) -> None:
    """Step 2 — a SHA-256 already in the registry returns the existing path, no convert."""
    fake = _FakeProvider(content=b"DEDUP-ME")
    monkeypatch.setattr(orch, "_provider_for_platform", lambda _p: fake)

    convert_called: list[bool] = []
    monkeypatch.setattr(orch, "convert_to_aiff", lambda p: convert_called.append(True) or None)

    # Pre-seed the registry with this content hash.
    import hashlib

    from app import download_registry as reg

    sha = hashlib.sha256(b"DEDUP-ME").hexdigest()
    reg.record_unified_download(
        sha256_hash=sha,
        title="Old Copy",
        artist="Avicii",
        file_path="/already/on/disk/old.flac",
        source="tidal",
    )

    cand = _candidate()
    job_id = "job-dedup"
    orch._put_job(_make_queued(job_id))
    orch.execute_fetch(job_id, cand, [cand])

    job = orch.get_job(job_id)
    assert job is not None
    assert job.state == "done"
    assert job.final_path == "/already/on/disk/old.flac"
    assert not convert_called  # short-circuited before AIFF step


# ──────────────────────────────────────────────────────────────────────────────
# The 9-step pipeline — failing step
# ──────────────────────────────────────────────────────────────────────────────


def test_pipeline_failing_fetch_marks_job_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Step 1 fails — the job ends 'failed' with the error, no exception escapes."""
    boom = _FakeProvider(raises=RuntimeError("no stream available"))
    monkeypatch.setattr(orch, "_provider_for_platform", lambda _p: boom)

    cand = _candidate()
    job_id = "job-fail"
    orch._put_job(_make_queued(job_id))
    # Must NOT raise — execute_fetch swallows everything into the JobStatus.
    orch.execute_fetch(job_id, cand, [cand])

    job = orch.get_job(job_id)
    assert job is not None
    assert job.state == "failed"
    assert job.error is not None
    assert "no stream available" in job.error
    assert job.final_path is None


def test_pipeline_failing_tag_write_step_marks_job_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failure deeper in the pipeline (step 6) still ends the job 'failed'."""
    fake = _FakeProvider()
    monkeypatch.setattr(orch, "_provider_for_platform", lambda _p: fake)
    monkeypatch.setattr(orch, "convert_to_aiff", lambda p: None)

    def _explode(*_a: object, **_kw: object) -> bool:
        raise OSError("disk full during tag write")

    monkeypatch.setattr(orch.audio_tags, "write_tags", _explode)

    cand = _candidate()
    job_id = "job-tagfail"
    orch._put_job(_make_queued(job_id))
    orch.execute_fetch(job_id, cand, [cand])

    job = orch.get_job(job_id)
    assert job is not None
    assert job.state == "failed"
    assert "disk full" in (job.error or "")


def test_get_job_unknown_returns_none() -> None:
    """get_job for an id that was never enqueued is None (route maps to 404)."""
    assert orch.get_job("never-existed") is None


# ──────────────────────────────────────────────────────────────────────────────
# Small helper
# ──────────────────────────────────────────────────────────────────────────────


def _make_queued(job_id: str) -> object:
    """A fresh queued JobStatus to register before driving execute_fetch directly."""
    from app.downloader.models import JobStatus

    return JobStatus(job_id=job_id, state="queued", progress_pct=0)
