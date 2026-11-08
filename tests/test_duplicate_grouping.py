"""Duplicate finder: O(n) digest grouping, parallel fingerprinting, location index.

``_legacy_group_duplicates`` is the pre-2026-11-08 implementation verbatim
(nested i/j loop). The new ``_group_duplicates`` must return the same groups,
in the same order, for every input — only faster for bytes digests.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import random
import threading
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

import app.main as main


def _legacy_group_duplicates(
    fingerprints: dict[str, Any],
    similarity_threshold: float = 0.85,
) -> list[dict[str, Any]]:
    paths = list(fingerprints.keys())
    visited: set[int] = set()
    groups: list[dict] = []

    def hamming_sim_py(a: list, b: list) -> float:
        length = min(len(a), len(b))
        if length < 4:
            return 0.0
        diff = sum(bin(x ^ y).count("1") for x, y in zip(a[:length], b[:length]))  # noqa: B905
        return 1.0 - diff / (length * 32)

    for i, p1 in enumerate(paths):
        if i in visited:
            continue
        group_members = [p1]
        group_sims = []
        fp1 = fingerprints[p1]

        for j, p2 in enumerate(paths):
            if j <= i or j in visited:
                continue
            fp2 = fingerprints[p2]
            if isinstance(fp1, list) and isinstance(fp2, list):
                sim = hamming_sim_py(fp1, fp2)
            elif isinstance(fp1, bytes) and isinstance(fp2, bytes):
                sim = 1.0 if fp1 == fp2 else 0.0
            else:
                sim = 0.0

            if sim >= similarity_threshold:
                group_members.append(p2)
                group_sims.append(sim)
                visited.add(j)

        if len(group_members) > 1:
            avg_sim = sum(group_sims) / len(group_sims) if group_sims else 1.0
            groups.append(
                {
                    "master": p1,
                    "members": group_members,
                    "similarity": round(avg_sim, 3),
                }
            )
            visited.add(i)

    return groups


def _digest(n: int) -> bytes:
    return hashlib.md5(str(n).encode()).digest()


def _mixed_fixture(seed: int, n: int = 400) -> dict[str, Any]:
    """bytes digests (with repeats), near-matching u32 vectors, junk types."""
    rng = random.Random(seed)
    bases = [[rng.getrandbits(32) for _ in range(16)] for _ in range(12)]
    fps: dict[str, Any] = {}
    for i in range(n):
        kind = rng.random()
        if kind < 0.55:
            fp: Any = _digest(rng.randrange(60))
        elif kind < 0.9:
            base = rng.choice(bases)
            fp = [x ^ (1 << rng.randrange(32)) if rng.random() < 0.4 else x for x in base]
            if rng.random() < 0.1:
                fp = fp[:3]  # too short -> similarity 0.0
        elif kind < 0.95:
            fp = "not-a-fingerprint"
        else:
            fp = bytearray(_digest(rng.randrange(5)))
        fps[f"C:/music/track_{seed}_{i:05d}.mp3"] = fp
    return fps


@pytest.mark.parametrize("seed", [1, 2, 3])
@pytest.mark.parametrize("threshold", [0.85, 0.95, 0.5, 1.0, 0.0, -0.5, 1.5])
def test_grouping_equals_legacy_on_mixed_input(seed: int, threshold: float) -> None:
    fps = _mixed_fixture(seed)
    assert main._group_duplicates(fps, threshold) == _legacy_group_duplicates(fps, threshold)


def test_grouping_equals_legacy_on_5k_digests() -> None:
    rng = random.Random(42)
    fps = {f"C:/lib/{i:05d}.flac": _digest(rng.randrange(3500)) for i in range(5000)}
    new = main._group_duplicates(fps)
    assert new == _legacy_group_duplicates(fps)
    assert new, "fixture must contain duplicate groups"


class _CountingDigest(bytes):
    eq_calls = 0
    hash_calls = 0

    def __eq__(self, other: object) -> bool:
        type(self).eq_calls += 1
        return bytes.__eq__(self, other)

    def __hash__(self) -> int:
        type(self).hash_calls += 1
        return bytes.__hash__(self)


def test_digest_grouping_is_linear_on_5k_paths() -> None:
    n = 5000
    rng = random.Random(7)
    fps = {f"C:/lib/{i:05d}.mp3": _CountingDigest(_digest(rng.randrange(3500))) for i in range(n)}
    _CountingDigest.eq_calls = _CountingDigest.hash_calls = 0

    t0 = time.perf_counter()
    groups = main._group_duplicates(fps)
    elapsed = time.perf_counter() - t0

    # Pairwise compare would be ~n^2/2 = 12.5M __eq__ calls.
    assert _CountingDigest.eq_calls + _CountingDigest.hash_calls <= 3 * n
    assert elapsed < 1.0
    assert groups


# --- parallel fingerprinting ---


def test_fingerprint_paths_preserves_input_order_and_bounds_inflight() -> None:
    paths = [f"p{i:03d}" for i in range(60)]
    active = 0
    peak = 0
    lock = threading.Lock()
    progress: list[int] = []

    def fake_fp(path: str) -> bytes | None:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(random.random() * 0.01)
        with lock:
            active -= 1
        return None if path.endswith("7") else path.encode()

    async def _go() -> dict[str, Any]:
        with ThreadPoolExecutor(max_workers=16) as ex:
            return await main._fingerprint_paths(
                paths, ex, 4, lambda: progress.append(1), fingerprint_fn=fake_fp
            )

    out = asyncio.run(_go())
    assert list(out) == [p for p in paths if not p.endswith("7")]
    assert all(out[p] == p.encode() for p in out)
    assert len(progress) == len(paths)
    assert 1 < peak <= 4


def test_worker_count_bounds() -> None:
    assert main._dup_scan_worker_count(1) == 1
    assert 1 <= main._dup_scan_worker_count(10_000) <= main._DUP_SCAN_MAX_WORKERS
    assert main._dup_scan_worker_count(10_000) <= max(1, (os.cpu_count() or 2) - 1)


def _write_wav(path: Path, seed: int) -> None:
    rng = random.Random(seed)
    frames = bytes(rng.getrandbits(8) for _ in range(11025 * 2))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(11025)
        w.writeframes(frames)


@pytest.mark.slow
def test_run_duplicate_scan_end_to_end_real_decode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real librosa decode on the scan's thread pool, grouping + enrichment."""
    a, b, c = tmp_path / "a.wav", tmp_path / "b.wav", tmp_path / "c.wav"
    _write_wav(a, 1)
    _write_wav(c, 2)
    b.write_bytes(a.read_bytes())
    monkeypatch.setattr(main.db, "loaded", False, raising=False)

    job_id = "test-dup-e2e"
    try:
        asyncio.run(main._run_duplicate_scan(job_id, [str(a), str(b), str(c)]))
        job = main._dup_jobs[job_id]
        assert job["status"] == "done", job.get("error")
        assert job["done"] == 3
        assert [g["master"] for g in job["groups"]] == [str(a)]
        assert [d["path"] for d in job["groups"][0]["duplicates"]] == [str(a), str(b)]
        assert job["groups"][0]["duplicates"][0]["format"] == "WAV"
    finally:
        main._dup_jobs.pop(job_id, None)


# --- library location index (enrichment + merge) ---


def test_location_index_first_match_wins_and_keeps_all() -> None:
    tracks = [
        {"TrackID": "1", "path": "C:/Music/A.mp3", "Name": "first"},
        {"TrackID": "2", "path": "C:/Music/A.mp3", "Name": "second"},
        {"TrackID": "3", "Location": "C:/Music/B.mp3", "Name": "b"},
        {"TrackID": "4", "Name": "no location"},
    ]
    index = main._dup_location_index(tracks)
    key = main._dup_location_key("C:/Music/A.mp3")
    assert [t["TrackID"] for t in index[key]] == ["1", "2"]
    assert main._dup_member_info("C:/Music/A.mp3", index)["title"] == "first"
    assert main._dup_member_info("C:/Music/B.mp3", index)["title"] == "b"
    assert main._dup_member_info("C:/Music/missing.mp3", index)["title"] == ""


@pytest.mark.skipif(os.name != "nt", reason="Path equality is case-insensitive on Windows only")
def test_location_index_matches_like_windows_path_equality() -> None:
    index = main._dup_location_index([{"TrackID": "1", "path": "C:/Music/Track.MP3", "Name": "t"}])
    assert main._dup_member_info("c:\\music\\track.mp3", index)["title"] == "t"


def test_member_info_survives_bad_numeric_metadata() -> None:
    index = main._dup_location_index(
        [{"path": "C:/Music/A.mp3", "Name": "a", "BitRate": "320kbps", "PlayCount": "7"}]
    )
    info = main._dup_member_info("C:/Music/A.mp3", index)
    assert info["title"] == "a"
    assert info["bitrate"] == 0
