"""Decode-once audio measurement runner: Stage E of docs/LIBRARY_ANALYSIS_HANDOVER.md (§3.5).

Loads every track ONCE (native rate, stereo) and runs the engine's building blocks in the order of
app.analysis_engine.run_full_analysis, minus waveforms / PVBR / cues, plus the Stage-E extras
E1-E8 from app.analysis_extras.compute_extras at depth "high" (spectrum / clipping / dynamics /
silence / dc / bass / lowband / fingerprint sub-dicts, see that module).

Read-only towards the library: no AnalysisCache, no master.db, no ANLZ, no backend calls.
Output: one JSON line per track, resumable via track_key = ID|path|mtime|size
("key" is the musical key, as in the engine), plus <out>.summary.json after every run.

Usage:
  python scripts/library_measure_audio.py --limit 50 --seed 1 --workers 10 --depth high
  python scripts/library_measure_audio.py --only-ids 123,456 --out tmp/x.jsonl --inline
"""

from __future__ import annotations

import os

# Must be set before numpy / OpenBLAS load, in the parent AND in every spawned worker (the worker
# re-imports this module as __mp_main__, so the loop below runs there too).
THREAD_ENV_VARS = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMBA_NUM_THREADS",
)
for _var in THREAD_ENV_VARS:
    os.environ.setdefault(_var, "1")

import argparse  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import random  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
import warnings  # noqa: E402
from collections import deque  # noqa: E402
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait  # noqa: E402
from concurrent.futures.process import BrokenProcessPool  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.analysis_extras import compute_extras  # noqa: E402

logger = logging.getLogger("library_measure_audio")

DEFAULT_INPUT = ROOT / "tmp" / "library-analysis" / "tracks.json"
DEFAULT_OUT = ROOT / "tmp" / "library-analysis" / "measure" / "audio.jsonl"
STREAM_PREFIXES = ("soundcloud:", "spotify:")
DEPTHS = ("rekordbox", "high")
ANALYSIS_SR = 44100

MIN_BUDGET_S = 120.0
BUDGET_FACTOR = 10.0
DEFAULT_BUDGET_S = 600.0
MAX_ATTEMPTS = 2
# §3.5.1: madmom peaks at +5 GB per worker, 12 x 7-9 GB exceeded 62 GB only by luck -> 10 workers;
# recycle a worker every 10 tasks to bound leaked RSS.
DEFAULT_WORKERS = 10
DEFAULT_MAX_TASKS_PER_CHILD = 10
DEFAULT_PROGRESS_EVERY = 50

_ENGINE: Any = None


# --------------------------------------------------------------------------- #
# Engine access (lazy: the parent process never pays for librosa / madmom)
# --------------------------------------------------------------------------- #


def _engine() -> Any:
    """Import app.analysis_engine and load its libraries (applies the madmom py3.11 shim)."""
    global _ENGINE
    if _ENGINE is None:
        warnings.filterwarnings("ignore", category=UserWarning)
        from app import analysis_engine as ae

        if not ae._ensure_libs():
            raise RuntimeError("analysis libraries not available (librosa / scipy)")
        _ENGINE = ae
    return _ENGINE


# --------------------------------------------------------------------------- #
# Compact engine fields
# --------------------------------------------------------------------------- #

PHRASE_KEYS = ("label", "mood", "energy", "start_ms", "end_ms")


def compact_phrases(phrases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: p.get(k) for k in PHRASE_KEYS} for p in phrases]


def compact_anchors(anchors: list[dict[str, Any]]) -> dict[str, Any]:
    bpms = [float(a["bpm"]) for a in anchors if a.get("bpm") is not None]
    return {
        "count": len(anchors),
        "bpm_min": round(min(bpms), 3) if bpms else None,
        "bpm_max": round(max(bpms), 3) if bpms else None,
    }


# --------------------------------------------------------------------------- #
# measure_track: decode once, engine order, extras
# --------------------------------------------------------------------------- #


def measure_track(
    path: str, depth: str = "high", sample_rate_meta: int | None = None
) -> dict[str, Any]:
    """Decode once; run the engine blocks in run_full_analysis order; add E1-E8 at depth 'high'
    (app.analysis_extras.compute_extras; its sub-dicts land at the top level of the row).

    Raises on unreadable audio (the pool wrapper turns that into an error row).
    """
    if depth not in DEPTHS:
        raise ValueError(f"depth must be one of {DEPTHS}, got {depth!r}")
    ae = _engine()
    librosa = ae.librosa
    t_stage: dict[str, float] = {}
    cpu0, wall0 = time.process_time(), time.perf_counter()

    def stage(name: str, start: float) -> None:
        t_stage[name] = round(time.process_time() - start, 3)

    t = time.process_time()
    y_native, sr_native = librosa.load(path, sr=None, mono=False)
    y_native = np.asarray(y_native, dtype=np.float32)
    sr_native = int(sr_native)
    stage("load", t)
    if y_native.size == 0:
        raise ValueError("empty or unreadable audio")
    channels = int(y_native.shape[0]) if y_native.ndim == 2 else 1

    t = time.process_time()
    stereo = ae.compute_stereo_features(y_native, sr_native) if y_native.ndim == 2 else None
    y_mono = librosa.to_mono(y_native) if y_native.ndim == 2 else y_native
    stage("stereo", t)

    t = time.process_time()
    if sr_native != ANALYSIS_SR:
        y = librosa.resample(y_mono, orig_sr=sr_native, target_sr=ANALYSIS_SR)
        sr = ANALYSIS_SR
    else:
        y, sr = y_mono, sr_native
    stage("resample", t)
    duration = len(y) / sr

    t = time.process_time()
    encoder_delay = float(ae.get_encoder_delay(path))
    first_signal_t = float(ae.find_first_signal_onset(y, sr))
    stage("onset", t)

    t = time.process_time()
    beat = ae.detect_beats(y, sr, encoder_delay=encoder_delay, first_signal_t=first_signal_t)
    stage("beats", t)
    t = time.process_time()
    key = ae.detect_key(y, sr)
    stage("key", t)
    t = time.process_time()
    phrases = ae.detect_phrases(y, sr, beat["bpm"], duration)
    stage("phrases", t)
    t = time.process_time()
    anchors = ae.detect_tempo_changes(y, sr, beat["bpm"])
    stage("tempo_grid", t)

    result: dict[str, Any] = {
        "depth": depth,
        "duration": round(duration, 3),
        "sample_rate": sr,
        "sample_rate_native": sr_native,
        "channels": channels,
        "encoder_delay_ms": round(encoder_delay * 1000.0, 2),
        "first_signal_ms": round(first_signal_t * 1000.0, 2),
        "bpm": beat.get("bpm"),
        "bpm_raw": beat.get("bpm_raw"),
        "beat_count": beat.get("beat_count"),
        "downbeat_index": beat.get("downbeat_index"),
        "beat_method": beat.get("method", "unknown"),
        "grid_confidence": beat.get("grid_confidence", 0.0),
        "tempo_anchors": compact_anchors(anchors),
        "key": key.get("key"),
        "camelot": key.get("camelot"),
        "key_confidence": key.get("confidence"),
        "key_method": key.get("method", "unknown"),
        "phrases": compact_phrases(phrases),
        "stereo": stereo,
    }

    if depth == "high":
        t = time.process_time()
        if y_native.ndim == 2:
            lufs = float(ae.calculate_lufs(y_native, sr_native))
        else:
            lufs = float(ae.calculate_lufs(y, sr))
        replay_gain = float(ae.calculate_replay_gain(lufs))
        stage("lufs", t)

        t = time.process_time()
        mood = ae.detect_mood(y, sr, beat["bpm"], lufs)
        genre_hint = ae.hint_genre(beat["bpm"], mood["brightness"], mood["texture"])
        stage("mood", t)

        extras = compute_extras(
            y_native,
            sr_native,
            y,
            sr,
            lufs=lufs,
            first_signal_ms=round(first_signal_t * 1000.0, 2),
            file_path=path,
            sample_rate_meta=sample_rate_meta,
        )
        t_stage.update(extras.pop("t_stage", {}))

        result.update(
            {
                "lufs": lufs,
                "replay_gain": replay_gain,
                "peak": round(float(np.max(np.abs(y))), 4),
                "mood": mood,
                "genre_hint": genre_hint,
            }
        )
        result.update(extras)

    result["t_stage"] = t_stage
    result["t_cpu_s"] = round(time.process_time() - cpu0, 3)
    result["t_wall_s"] = round(time.perf_counter() - wall0, 3)
    return result


# --------------------------------------------------------------------------- #
# Rows, keys, planning
# --------------------------------------------------------------------------- #


def make_key(track: dict[str, Any], st: os.stat_result | None) -> str:
    mtime = int(st.st_mtime) if st is not None else 0
    size = int(st.st_size) if st is not None else 0
    return f"{track.get('ID')}|{track.get('path')}|{mtime}|{size}"


def base_row(track: dict[str, Any], depth: str) -> dict[str, Any]:
    return {
        "track_key": track.get("_key") or make_key(track, None),
        "id": track.get("ID"),
        "path": track.get("path"),
        "title": track.get("Title"),
        "artist": track.get("Artist"),
        "mtime": track.get("_mtime"),
        "size": track.get("_size"),
        "depth": depth,
        "snapshot": {
            "bpm": track.get("BPM"),
            "key": track.get("Key"),
            "total_time_s": track.get("TotalTime"),
            "bitrate": track.get("Bitrate"),
            "sample_rate": track.get("SampleRate"),
        },
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def error_row(track: dict[str, Any], depth: str, exc: BaseException, status: str = "error") -> dict:
    row = base_row(track, depth)
    row.update(
        {
            "status": status,
            "error_type": type(exc).__name__,
            "error_message": (str(exc) or repr(exc))[:500],
        }
    )
    return row


def _peak_rss() -> tuple[float | None, str | None]:
    """(peak RSS in MB, source). Windows exposes peak_wset; elsewhere current rss; None w/o psutil."""
    try:
        import psutil
    except ImportError:
        return None, None
    info = psutil.Process().memory_info()
    peak = getattr(info, "peak_wset", None)
    if peak is not None:
        return round(peak / 2**20, 1), "peak_wset"
    return round(info.rss / 2**20, 1), "rss"


def measure_task(track: dict[str, Any], depth: str) -> dict[str, Any]:
    """Pool entry point. Never raises: every outcome is a row."""
    cpu0, wall0 = time.process_time(), time.perf_counter()
    row = base_row(track, depth)
    try:
        meta_sr = track.get("SampleRate")
        row.update(
            measure_track(
                str(track.get("path")),
                depth,
                sample_rate_meta=int(meta_sr) if meta_sr else None,
            )
        )
        row["status"] = "ok"
    except Exception as exc:  # any decode / DSP failure becomes a row
        row.update(error_row(track, depth, exc))
    row["t_cpu_s"] = round(time.process_time() - cpu0, 3)
    row["t_wall_s"] = round(time.perf_counter() - wall0, 3)
    row["worker_pid"] = os.getpid()
    row["rss_peak_mb"], row["rss_source"] = _peak_rss()
    return row


def summary_path_for(out_path: Path) -> Path:
    """audio.jsonl -> audio.summary.json, next to the JSONL."""
    return out_path.with_name(out_path.stem + ".summary.json")


def _percentiles(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    arr = np.asarray(values, dtype=np.float64)
    return {
        "min": round(float(arr.min()), 3),
        "p10": round(float(np.percentile(arr, 10)), 3),
        "median": round(float(np.median(arr)), 3),
        "p90": round(float(np.percentile(arr, 90)), 3),
        "max": round(float(arr.max()), 3),
    }


def summarize_rows(out_path: Path) -> dict[str, Any]:
    """Aggregate every row in the JSONL (all runs so far): status / tier / flag / fingerprint
    counts and a few distributions. Rows from the pre-extras schema (``cutoff`` instead of
    ``spectrum``) are counted under ``legacy_rows``."""
    status: dict[str, int] = {}
    tiers: dict[str, int] = {}
    reasons: dict[str, int] = {}
    flags: dict[str, int] = {}
    lame: dict[str, int] = {}
    fp = {"available": 0, "unavailable": 0, "error": 0, "skipped": 0}
    cpu: list[float] = []
    cutoff_edge: list[float] = []
    legacy = 0
    extras_errors = 0
    if not out_path.exists():
        return {"total": 0}
    with out_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            st = str(row.get("status"))
            status[st] = status.get(st, 0) + 1
            if st != "ok":
                continue
            if row.get("t_cpu_s") is not None:
                cpu.append(float(row["t_cpu_s"]))
            if row.get("depth") != "high":
                continue
            spectrum = row.get("spectrum")
            if spectrum is None:
                if "cutoff" in row:
                    legacy += 1
                continue
            for block in ("spectrum", "clipping", "dynamics", "silence", "dc", "bass", "lowband"):
                if isinstance(row.get(block), dict) and "error" in row[block]:
                    extras_errors += 1
            if "error" in spectrum:
                continue
            tier = str(spectrum.get("tier"))
            tiers[tier] = tiers.get(tier, 0) + 1
            reason = str(spectrum.get("tier_reason"))
            reasons[reason] = reasons.get(reason, 0) + 1
            for flag in spectrum.get("flags") or []:
                flags[flag] = flags.get(flag, 0) + 1
            if spectrum.get("lame_estimate_kbps"):
                k = str(spectrum["lame_estimate_kbps"])
                lame[k] = lame.get(k, 0) + 1
            if spectrum.get("cutoff_edge_hz") is not None:
                cutoff_edge.append(float(spectrum["cutoff_edge_hz"]))
            fingerprint = row.get("fingerprint")
            if fingerprint is None:
                fp["skipped"] += 1
            elif not fingerprint.get("available"):
                fp["unavailable"] += 1
            elif fingerprint.get("error"):
                fp["error"] += 1
            else:
                fp["available"] += 1
    return {
        "total": sum(status.values()),
        "status": status,
        "tiers": dict(sorted(tiers.items())),
        "tier_reasons": reasons,
        "flags": flags,
        "lame_estimate_kbps": dict(sorted(lame.items(), key=lambda kv: int(kv[0]))),
        "fingerprint": fp,
        "extras_block_errors": extras_errors,
        "legacy_rows": legacy,
        "t_cpu_s": _percentiles(cpu),
        "cutoff_edge_hz": _percentiles(cutoff_edge),
    }


def load_done_keys(out_path: Path) -> set[str]:
    keys: set[str] = set()
    if not out_path.exists():
        return keys
    with out_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                key = json.loads(line).get("track_key")
            except json.JSONDecodeError:
                continue
            if key:
                keys.add(key)
    return keys


@dataclass
class Plan:
    todo: list[dict[str, Any]] = field(default_factory=list)
    skipped: int = 0
    streams: list[dict[str, Any]] = field(default_factory=list)
    missing: list[dict[str, Any]] = field(default_factory=list)
    candidates: int = 0


def plan_tracks(
    tracks: list[dict[str, Any]],
    done_keys: set[str],
    limit: int | None = None,
    seed: int | None = None,
    only_ids: set[str] | None = None,
) -> Plan:
    """Split the snapshot into streams / missing / local; sample; drop rows already measured.

    The sample (limit + seed) is drawn before the done-filter so a re-run with the same
    arguments sees the same tracks and skips the finished ones.
    """
    plan = Plan()
    local: list[dict[str, Any]] = []
    for track in tracks:
        path = str(track.get("path") or "")
        if not path or path.startswith(STREAM_PREFIXES):
            plan.streams.append(track)
            continue
        if only_ids is not None and str(track.get("ID")) not in only_ids:
            continue
        try:
            st = os.stat(path)
        except OSError:
            plan.missing.append(track)
            continue
        item = dict(track)
        item["_key"] = make_key(track, st)
        item["_mtime"] = int(st.st_mtime)
        item["_size"] = int(st.st_size)
        item["_attempts"] = 0
        local.append(item)
    plan.candidates = len(local)
    if limit is not None and limit < len(local):
        local = random.Random(seed).sample(local, limit) if seed is not None else local[:limit]
    plan.todo = [t for t in local if t["_key"] not in done_keys]
    plan.skipped = len(local) - len(plan.todo)
    return plan


def track_budget_s(track: dict[str, Any]) -> float:
    total = track.get("TotalTime")
    try:
        seconds = float(total) if total is not None else 0.0
    except (TypeError, ValueError):
        seconds = 0.0
    if seconds <= 0:
        return DEFAULT_BUDGET_S
    return max(MIN_BUDGET_S, BUDGET_FACTOR * seconds)


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #


@dataclass
class RunStats:
    total: int = 0
    done: int = 0
    ok: int = 0
    errors: int = 0
    timeouts: int = 0
    cpu_sum_s: float = 0.0
    wall_s: float = 0.0
    recycles: int = 0
    rss_by_pid: dict[int, float] = field(default_factory=dict)
    rss_source: str | None = None

    def as_dict(self) -> dict[str, Any]:
        rss = sorted(self.rss_by_pid.values())
        return {
            "total": self.total,
            "done": self.done,
            "ok": self.ok,
            "errors": self.errors,
            "timeouts": self.timeouts,
            "recycles": self.recycles,
            "cpu_sum_s": round(self.cpu_sum_s, 1),
            "wall_s": round(self.wall_s, 1),
            "tracks_per_min": round(self.done / self.wall_s * 60.0, 2) if self.wall_s else None,
            "cpu_per_track_s": round(self.cpu_sum_s / self.ok, 1) if self.ok else None,
            "workers_seen": len(self.rss_by_pid),
            "rss_peak_mb_max": rss[-1] if rss else None,
            "rss_peak_mb_median": rss[len(rss) // 2] if rss else None,
            "rss_source": self.rss_source,
        }


def _worker_init() -> None:
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger().setLevel(logging.WARNING)
    _engine()


def _kill_pool(executor: ProcessPoolExecutor) -> None:
    procs = list(getattr(executor, "_processes", {}).values())
    for proc in procs:
        proc.kill()
    for proc in procs:
        proc.join(timeout=5)
    executor.shutdown(wait=False, cancel_futures=True)


def _progress(stats: RunStats, start: float) -> str:
    stats.wall_s = time.perf_counter() - start
    rate = stats.done / stats.wall_s * 60.0 if stats.wall_s > 0 else 0.0
    remaining = stats.total - stats.done
    eta_min = remaining / rate if rate > 0 else float("inf")
    return (
        f"[{stats.done}/{stats.total}] ok={stats.ok} err={stats.errors} to={stats.timeouts} "
        f"rate={rate:.2f}/min cpu_sum={stats.cpu_sum_s:.0f}s wall={stats.wall_s:.0f}s "
        f"eta={eta_min:.1f}min"
    )


def _record(row: dict[str, Any], stats: RunStats, fh: Any) -> None:
    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    fh.flush()
    stats.done += 1
    status = row.get("status")
    if status == "ok":
        stats.ok += 1
    elif status == "timeout":
        stats.timeouts += 1
    else:
        stats.errors += 1
    stats.cpu_sum_s += float(row.get("t_cpu_s") or 0.0)
    pid, rss = row.get("worker_pid"), row.get("rss_peak_mb")
    if pid is not None and rss is not None:
        stats.rss_by_pid[int(pid)] = max(stats.rss_by_pid.get(int(pid), 0.0), float(rss))
        stats.rss_source = row.get("rss_source")


def run_inline(todo: list[dict[str, Any]], depth: str, out_path: Path, every: int) -> RunStats:
    stats = RunStats(total=len(todo))
    start = time.perf_counter()
    with out_path.open("a", encoding="utf-8") as fh:
        for track in todo:
            _record(measure_task(track, depth), stats, fh)
            if stats.done % every == 0 or stats.done == stats.total:
                print(_progress(stats, start), flush=True)
    stats.wall_s = time.perf_counter() - start
    return stats


def run_pool(
    todo: list[dict[str, Any]],
    depth: str,
    workers: int,
    out_path: Path,
    every: int = DEFAULT_PROGRESS_EVERY,
    max_tasks_per_child: int = DEFAULT_MAX_TASKS_PER_CHILD,
) -> RunStats:
    """Submit one task per worker, watch deadlines, recycle the whole pool on a timeout or a
    broken worker (a running task cannot be cancelled individually)."""
    stats = RunStats(total=len(todo))
    pending: deque[dict[str, Any]] = deque(todo)
    start = time.perf_counter()
    with out_path.open("a", encoding="utf-8") as fh:
        while pending:
            # kwargs dict: max_tasks_per_child is py3.11+, mypy runs with python_version 3.10
            pool_kwargs: dict[str, Any] = {
                "max_workers": workers,
                "initializer": _worker_init,
                "max_tasks_per_child": max_tasks_per_child,
            }
            executor = ProcessPoolExecutor(**pool_kwargs)
            running: dict[Future[dict[str, Any]], tuple[dict[str, Any], float]] = {}
            recycle = False
            try:
                while (pending or running) and not recycle:
                    while pending and len(running) < workers:
                        track = pending.popleft()
                        try:
                            fut = executor.submit(measure_task, track, depth)
                        except BrokenProcessPool:
                            pending.appendleft(track)
                            recycle = True
                            break
                        running[fut] = (track, time.perf_counter() + track_budget_s(track))
                    if recycle or not running:
                        break
                    finished, _ = wait(list(running), timeout=1.0, return_when=FIRST_COMPLETED)
                    for fut in finished:
                        track, _deadline = running.pop(fut)
                        try:
                            row = fut.result()
                        except BrokenProcessPool as exc:
                            recycle = True
                            track["_attempts"] += 1
                            if track["_attempts"] < MAX_ATTEMPTS:
                                pending.appendleft(track)
                                continue
                            row = error_row(track, depth, exc)
                        except Exception as exc:  # pickling / unexpected harness failure
                            row = error_row(track, depth, exc)
                        _record(row, stats, fh)
                        if stats.done % every == 0:
                            print(_progress(stats, start), flush=True)
                    now = time.perf_counter()
                    expired = [f for f, (_t, dl) in running.items() if now > dl]
                    if expired:
                        recycle = True
                        for fut in expired:
                            track, _deadline = running.pop(fut)
                            timeout_exc = TimeoutError(
                                f"budget {track_budget_s(track):.0f}s exceeded"
                            )
                            _record(
                                error_row(track, depth, timeout_exc, status="timeout"), stats, fh
                            )
                    if recycle:
                        for _fut, (track, _deadline) in running.items():
                            track["_attempts"] += 1
                            if track["_attempts"] < MAX_ATTEMPTS:
                                pending.appendleft(track)
                            else:
                                lost_exc = RuntimeError("lost twice to a pool recycle")
                                _record(error_row(track, depth, lost_exc), stats, fh)
                        running = {}
            finally:
                if recycle:
                    stats.recycles += 1
                    _kill_pool(executor)
                else:
                    executor.shutdown(wait=True)
    stats.wall_s = time.perf_counter() - start
    print(_progress(stats, start), flush=True)
    return stats


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="tracks.json snapshot")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="JSONL output (appended)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--seed", type=int, default=None, help="reproducible random sample for --limit")
    ap.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    ap.add_argument("--only-ids", default=None, help="comma-separated track IDs")
    ap.add_argument("--depth", choices=DEPTHS, default="high")
    ap.add_argument("--progress-every", type=int, default=DEFAULT_PROGRESS_EVERY)
    ap.add_argument("--max-tasks-per-child", type=int, default=DEFAULT_MAX_TASKS_PER_CHILD)
    ap.add_argument("--inline", action="store_true", help="no pool: run in this process")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    with args.input.open(encoding="utf-8") as fh:
        tracks = json.load(fh)
    if isinstance(tracks, dict):
        tracks = tracks.get("tracks", [])
    only_ids = {s.strip() for s in args.only_ids.split(",") if s.strip()} if args.only_ids else None
    args.out.parent.mkdir(parents=True, exist_ok=True)
    done_keys = load_done_keys(args.out)
    plan = plan_tracks(tracks, done_keys, limit=args.limit, seed=args.seed, only_ids=only_ids)
    full_run = args.limit is None and only_ids is None
    print(
        f"snapshot={len(tracks)} local={plan.candidates} streams={len(plan.streams)} "
        f"missing={len(plan.missing)} already_done={plan.skipped} todo={len(plan.todo)} "
        f"depth={args.depth} workers={args.workers} out={args.out}",
        flush=True,
    )
    if full_run:
        with args.out.open("a", encoding="utf-8") as fh:
            for status, items in (("stream", plan.streams), ("missing", plan.missing)):
                for track in items:
                    row = base_row(track, args.depth)
                    if row["track_key"] in done_keys:
                        continue
                    row["status"] = status
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    if not plan.todo:
        print("nothing to do", flush=True)
        return 0
    if args.inline:
        stats = run_inline(plan.todo, args.depth, args.out, args.progress_every)
    else:
        stats = run_pool(
            plan.todo,
            args.depth,
            args.workers,
            args.out,
            every=args.progress_every,
            max_tasks_per_child=args.max_tasks_per_child,
        )
    summary = {
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "args": {
            "input": str(args.input),
            "out": str(args.out),
            "limit": args.limit,
            "seed": args.seed,
            "workers": args.workers,
            "only_ids": sorted(only_ids) if only_ids else None,
            "depth": args.depth,
            "max_tasks_per_child": args.max_tasks_per_child,
            "inline": args.inline,
        },
        "plan": {
            "snapshot": len(tracks),
            "local": plan.candidates,
            "streams": len(plan.streams),
            "missing": len(plan.missing),
            "already_done": plan.skipped,
            "todo": len(plan.todo),
        },
        "run": stats.as_dict(),
        "rows": summarize_rows(args.out),
    }
    summary_path = summary_path_for(args.out)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"summary": stats.as_dict()}, ensure_ascii=False), flush=True)
    print(f"summary written to {summary_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
