#!/usr/bin/env python3
"""
validate_real_world.py — real-library validation run for the analysis engine.

The synthetic self-test (selftest_analysis.py) proves the engine on generated
audio. This script is the step after it: the user's own tracks, measured
against what Rekordbox analysed for the same files.

    ab         A/B against Rekordbox over N real tracks, in parallel workers.
               Writes a JSON report.
    db-write   Run the app's analysis writer against a COPY of master.db and
               prove it changed only what it should. Rekordbox must be closed.
    checklist  Print the CDJ-3000 checklist for a finished `ab` report (for the
               later hardware test).

The real library is only read. `db-write` copies master.db into a work folder,
points the writer at the copy and its own share/ folder, and checks at the end
that the real master.db and ANLZ files are byte-identical.

    python scripts/validate_real_world.py ab -n 50 --seed 7 --workers 4
    python scripts/validate_real_world.py db-write -n 5
    python scripts/validate_real_world.py checklist tmp/validation/ab_report.json

The summary / threshold / pick helpers carry no I/O and are unit-tested in
tests/test_validate_real_world.py.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from compare_rekordbox import COMPATIBLE_KEY_RELATIONS  # noqa: E402

DEFAULT_REPORT = ROOT / "tmp" / "validation" / "ab_report.json"

# One analysis worker holds the madmom models: ~6-9 GB RSS measured.
DEFAULT_WORKERS = 2
# Generous per-track budget for a worker chunk (decode + madmom + key).
TRACK_TIMEOUT_S = 300
CHUNK_STARTUP_S = 180

# A DJ set keeps two decks in sync for minutes: this is the window the drift
# figure is quoted for.
DRIFT_WINDOW_S = 300.0

# Floors a run must reach to exit 0. Set from the first full run on a real
# library (2026-11-22) with headroom, so they flag a regression, not noise.
DEFAULT_THRESHOLDS: dict[str, float] = {
    "min_bpm_acc2_pct": 95.0,
    "min_bpm_exact_pct": 60.0,
    "max_grid_median_ms": 15.0,
    "min_key_compatible_pct": 70.0,
    "max_error_pct": 5.0,
}

OCTAVE_RELATIONS = frozenset({"half", "double", "third", "triple"})

# djmdContent columns the analysis writer may change on a row it writes. Every
# other column, and every other row, has to come back identical.
WRITER_COLUMNS = frozenset({"bpm", "key_id", "analysed"})
# Bookkeeping rbox touches itself on any row update.
BOOKKEEPING_COLUMNS = frozenset({"updated_at", "rb_local_usn"})
# rbox getters that are not whole-table listings (need an argument or return one row).
_NOT_A_TABLE = re.compile(r"(_by_id|_by_name|_by_path|_by_ids|_children|_tree|_dir|_paths|_usn)$")
# djmdKey may grow: a key name the library never used before gets a new row.
GROWABLE_TABLES = frozenset({"keys"})
# Membership tables rbox only lists per parent row: (parent table, child getter suffix).
MEMBERSHIP_TABLES = (
    ("playlists", "playlist_songs"),
    ("histories", "history_songs"),
    ("my_tags", "my_tag_songs"),
    ("related_tracks", "related_tracks_songs"),
    ("samplers", "sampler_songs"),
    ("hot_cue_banklists", "hot_cue_banklist_songs"),
)
# Rekordbox's change counter: every row update bumps it (rbox does that itself).
USN_COUNTER = ("agent_registries", "localUpdateCount", frozenset({"int_1", "updated_at"}))
# Tables the write test cannot do without.
REQUIRED_TABLES = frozenset({"contents", "keys"})
_CAMELOT_NAME = re.compile(r"^(1[0-2]|[1-9])[AB]$")
ANLZ_SUFFIXES = (".DAT", ".EXT", ".2EX")
REKORDBOX_ANALYSED = 105


# --------------------------------------------------------------------------- #
# Pure helpers (no I/O — unit-tested)
# --------------------------------------------------------------------------- #


def split_chunks(ids: list[str], workers: int) -> list[list[str]]:
    """Deal ids round-robin into at most `workers` non-empty chunks."""
    n = max(1, min(workers, len(ids)))
    chunks: list[list[str]] = [[] for _ in range(n)]
    for i, tid in enumerate(ids):
        chunks[i % n].append(tid)
    return [c for c in chunks if c]


def percentile(values: list[float], q: float) -> float:
    """Linear-interpolated percentile, q in 0..100. NaN for an empty list."""
    if not values:
        return float("nan")
    s = sorted(values)
    pos = (len(s) - 1) * q / 100.0
    lo = math.floor(pos)
    hi = math.ceil(pos)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def drift_ms(rb_bpm: float, our_bpm: float, window_s: float = DRIFT_WINDOW_S) -> float:
    """How far two decks run apart over `window_s` if one plays at our BPM and
    the other at Rekordbox's. inf when either tempo is missing."""
    if rb_bpm <= 0 or our_bpm <= 0:
        return float("inf")
    return abs(our_bpm - rb_bpm) / rb_bpm * window_s * 1000.0


def bpm_exact(row: dict[str, Any]) -> bool:
    """Same BPM as Rekordbox at the two decimals Rekordbox stores."""
    return round(float(row["rb_bpm"]), 2) == round(float(row["our_bpm"]), 2)


def _pct(part: int, whole: int) -> float:
    return round(part / whole * 100.0, 1) if whole else 0.0


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate compare_rekordbox rows into one report block."""
    ok = [r for r in rows if r.get("status") == "ok"]
    n = len(ok)
    acc1 = sum(1 for r in ok if r["bpm_relation"] == "match")
    octave = sum(1 for r in ok if r["bpm_relation"] in OCTAVE_RELATIONS)
    exact = sum(1 for r in ok if bpm_exact(r))
    key_known = [r for r in ok if r["key_relation"] != "unknown"]
    key_exact = sum(1 for r in key_known if r["key_relation"] == "exact")
    key_ok = sum(1 for r in key_known if r["key_relation"] in COMPATIBLE_KEY_RELATIONS)
    grid = [
        float(r["beatgrid"]["mean_abs_err_ms"])
        for r in ok
        if r["bpm_relation"] == "match" and float(r["beatgrid"]["mean_abs_err_ms"]) >= 0
    ]
    drifts = [drift_ms(r["rb_bpm"], r["our_bpm"]) for r in ok if r["bpm_relation"] == "match"]
    return {
        "tracks": len(rows),
        "compared": n,
        "errors": len(rows) - n,
        "error_pct": _pct(len(rows) - n, len(rows)),
        "bpm_exact": exact,
        "bpm_exact_pct": _pct(exact, n),
        "bpm_acc1": acc1,
        "bpm_acc1_pct": _pct(acc1, n),
        "bpm_acc2": acc1 + octave,
        "bpm_acc2_pct": _pct(acc1 + octave, n),
        "key_compared": len(key_known),
        "key_exact": key_exact,
        "key_exact_pct": _pct(key_exact, len(key_known)),
        "key_compatible": key_ok,
        "key_compatible_pct": _pct(key_ok, len(key_known)),
        "grid_compared": len(grid),
        "grid_median_ms": round(percentile(grid, 50), 1) if grid else None,
        "grid_mean_ms": round(sum(grid) / len(grid), 1) if grid else None,
        "grid_p90_ms": round(percentile(grid, 90), 1) if grid else None,
        "grid_max_ms": round(max(grid), 1) if grid else None,
        "drift_median_ms": round(percentile(drifts, 50), 1) if drifts else None,
        "drift_p90_ms": round(percentile(drifts, 90), 1) if drifts else None,
    }


def check_thresholds(summary: dict[str, Any], thresholds: dict[str, float]) -> list[str]:
    """Return one line per missed floor; empty list = pass."""
    fails: list[str] = []
    if summary["compared"] == 0:
        return ["no track could be compared"]

    def floor(key: str, limit_key: str, label: str) -> None:
        if summary[key] < thresholds[limit_key]:
            fails.append(f"{label}: {summary[key]} % < {thresholds[limit_key]} %")

    floor("bpm_acc2_pct", "min_bpm_acc2_pct", "BPM within tolerance (octave-tolerant)")
    floor("bpm_exact_pct", "min_bpm_exact_pct", "BPM identical to Rekordbox")
    if summary["key_compared"]:
        floor("key_compatible_pct", "min_key_compatible_pct", "key harmonically compatible")
    median = summary["grid_median_ms"]
    if median is not None and median > thresholds["max_grid_median_ms"]:
        fails.append(f"beat grid median error: {median} ms > {thresholds['max_grid_median_ms']} ms")
    if summary["error_pct"] > thresholds["max_error_pct"]:
        fails.append(
            f"tracks that failed to analyse: {summary['error_pct']} % > "
            f"{thresholds['max_error_pct']} %"
        )
    return fails


def pick_cdj_tracks(rows: list[dict[str, Any]], per_group: int = 3) -> dict[str, list[dict]]:
    """Choose the tracks a CDJ check should load.

    agree      — same BPM, tightest grid: these must sit on the kick.
    grid_off   — same tempo, grid furthest from Rekordbox: phase/downbeat suspects.
    bpm_differ — tempo differs from Rekordbox: the ear decides who is right.
    """
    ok = [r for r in rows if r.get("status") == "ok"]

    def grid_err(r: dict[str, Any]) -> float:
        return float(r["beatgrid"]["mean_abs_err_ms"])

    with_grid = [r for r in ok if r["bpm_relation"] == "match" and grid_err(r) >= 0]
    agree = sorted((r for r in with_grid if bpm_exact(r)), key=grid_err)[:per_group]
    taken = {r["id"] for r in agree}
    grid_off = sorted((r for r in with_grid if r["id"] not in taken), key=grid_err, reverse=True)[
        :per_group
    ]
    taken |= {r["id"] for r in grid_off}
    differ = sorted(
        (r for r in ok if not bpm_exact(r) and r["id"] not in taken),
        key=lambda r: drift_ms(r["rb_bpm"], r["our_bpm"]),
        reverse=True,
    )[:per_group]
    return {"agree": agree, "grid_off": grid_off, "bpm_differ": differ}


def is_within(path: Path, root: Path) -> bool:
    """True when `path` resolves to `root` or something below it."""
    try:
        return path.resolve().is_relative_to(root.resolve())
    except OSError:
        return False


def diff_table(
    before: dict[str, dict[str, Any]], after: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Row-level diff of two {row id: column dict} snapshots."""
    changed: dict[str, list[str]] = {}
    for rid in before.keys() & after.keys():
        b, a = before[rid], after[rid]
        cols = sorted(k for k in b.keys() | a.keys() if b.get(k) != a.get(k))
        if cols:
            changed[rid] = cols
    return {
        "added": sorted(after.keys() - before.keys()),
        "removed": sorted(before.keys() - after.keys()),
        "changed": changed,
    }


def judge_db_diff(diffs: dict[str, dict[str, Any]], written_ids: set[str]) -> list[str]:
    """Turn table diffs into failures. Empty list = the write was non-destructive."""
    fails: list[str] = []
    allowed = WRITER_COLUMNS | BOOKKEEPING_COLUMNS
    for table, d in diffs.items():
        if d["removed"]:
            fails.append(f"{table}: {len(d['removed'])} row(s) vanished, e.g. {d['removed'][:3]}")
        if d["added"] and table not in GROWABLE_TABLES:
            fails.append(f"{table}: {len(d['added'])} unexpected new row(s), e.g. {d['added'][:3]}")
        for rid, cols in sorted(d["changed"].items()):
            if (table, rid) == USN_COUNTER[:2] and set(cols) <= USN_COUNTER[2]:
                continue
            if table != "contents":
                fails.append(f"{table}: row {rid} changed ({', '.join(cols)})")
            elif rid not in written_ids:
                fails.append(f"contents: row {rid} was not written but changed ({', '.join(cols)})")
            else:
                extra = [c for c in cols if c not in allowed]
                if extra:
                    fails.append(
                        f"contents: row {rid} changed beyond the writer's columns: {extra}"
                    )
    return fails


def table_getters(method_names: list[str]) -> list[str]:
    """Table names behind rbox's no-argument listing getters (`get_playlists` -> `playlists`)."""
    return sorted(
        name[4:]
        for name in method_names
        if name.startswith("get_") and not _NOT_A_TABLE.search(name)
    )


def library_key_notation(key_names: list[str | None]) -> str:
    """'camelot' or 'classic': the notation most keyed tracks carry. Tie or none -> classic.

    Rekordbox writes key names in the notation set in its preferences ("8A" or
    "Am") and sorts and filters the key column by that text.
    """
    named = [n for n in key_names if n]
    camelot = sum(1 for n in named if _CAMELOT_NAME.match(n))
    return "camelot" if camelot > len(named) - camelot else "classic"


def judge_written_row(
    tid: str,
    result: dict[str, Any],
    row: dict[str, Any] | None,
    key_name_db: str | None,
    key_name_expected: str | None,
    anlz_beats: int,
) -> list[str]:
    """Check one written track: what the writer reported is what master.db and the .DAT hold."""
    if result.get("status") != "ok":
        return [f"{tid}: writer returned {result.get('reason') or result.get('status')}"]
    if row is None:
        return [f"{tid}: row missing after the write"]
    fails: list[str] = []
    want_bpm = round(float(result["bpm"]) * 100)
    if row.get("bpm") != want_bpm:
        fails.append(f"{tid}: bpm in master.db is {row.get('bpm')}, writer reported {want_bpm}")
    if row.get("analysed") != REKORDBOX_ANALYSED:
        fails.append(f"{tid}: analysed flag is {row.get('analysed')}, expected 105")
    if key_name_expected and key_name_db != key_name_expected:
        fails.append(f"{tid}: key in master.db is {key_name_db!r}, expected {key_name_expected!r}")
    if anlz_beats <= 0:
        fails.append(f"{tid}: written .DAT holds no beat grid")
    elif anlz_beats != int(result.get("beat_count") or 0):
        fails.append(
            f"{tid}: .DAT holds {anlz_beats} beats, writer reported {result.get('beat_count')}"
        )
    return fails


# --------------------------------------------------------------------------- #
# Runner (needs rbox + the real library — run locally)
# --------------------------------------------------------------------------- #


def usable_ids(mdb: Any, candidates: list[str], n: int, need_anlz: bool = False) -> list[str]:
    """First n candidates whose audio file is on disk (streaming tracks have none).

    need_anlz additionally asks for a recorded AnalysisDataPath.
    """
    out: list[str] = []
    for tid in candidates:
        item = mdb.get_content_by_id(tid)
        if not item or (need_anlz and not item.analysis_data_path):
            continue
        if not Path(str(item.folder_path or "")).is_file():
            continue
        out.append(tid)
        if len(out) == n:
            break
    return out


def _sample_ids(
    db_path: str, ids: list[str] | None, n: int, seed: int | None, min_len: float
) -> list[str]:
    import rbox  # type: ignore
    from compare_rekordbox import _collect_tracks

    mdb = rbox.MasterDb(db_path)
    if ids:
        return [str(i) for i in ids]
    # Oversample: the shuffle also returns streaming tracks without a local file.
    return usable_ids(mdb, _collect_tracks(mdb, None, n * 4, seed, min_len_s=min_len), n)


def run_ab(db_path: str, ids: list[str], workers: int, tol: float) -> list[dict[str, Any]]:
    """Run compare_rekordbox.py over `ids` in parallel worker processes."""
    chunks = split_chunks(ids, workers)
    script = str(ROOT / "scripts" / "compare_rekordbox.py")
    rows: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="lms-validate-") as tmp:
        procs = []
        started = time.monotonic()
        for i, chunk in enumerate(chunks):
            out = Path(tmp) / f"chunk{i}.json"
            log = (Path(tmp) / f"chunk{i}.log").open("w", encoding="utf-8")
            cmd = [sys.executable, script, "--db", db_path, "--tol", str(tol), "--json", str(out)]
            cmd += ["--ids", *chunk]
            procs.append((chunk, out, log, subprocess.Popen(cmd, stdout=log, stderr=log)))
            print(f"  worker {i + 1}/{len(chunks)}: {len(chunk)} track(s)")
        for chunk, out, log, proc in procs:
            budget = CHUNK_STARTUP_S + TRACK_TIMEOUT_S * len(chunk)
            try:
                proc.wait(timeout=max(1.0, budget - (time.monotonic() - started)))
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=30)
            log.close()
            if out.exists():
                rows.extend(json.loads(out.read_text(encoding="utf-8")))
            else:
                tail = Path(log.name).read_text(encoding="utf-8", errors="replace").strip()
                last = tail.splitlines()[-1] if tail else "no output"
                reason = f"worker exited {proc.returncode} without a result: {last}"
                rows.extend({"id": tid, "status": "error", "error": reason} for tid in chunk)
        print(f"  {len(ids)} track(s) in {time.monotonic() - started:.0f} s")
    order = {tid: i for i, tid in enumerate(ids)}
    return sorted(rows, key=lambda r: order.get(str(r.get("id")), len(order)))


def _engine_version() -> int:
    from app.analysis_cache import ANALYSIS_VERSION

    return int(ANALYSIS_VERSION)


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #


def print_summary(summary: dict[str, Any], fails: list[str]) -> None:
    s = summary
    print("\n=== Summary ===")
    print(f"  tracks                    : {s['compared']} compared, {s['errors']} failed")
    print(
        f"  BPM identical to Rekordbox: {s['bpm_exact']}/{s['compared']} ({s['bpm_exact_pct']} %)"
    )
    print(f"  BPM within tolerance      : {s['bpm_acc1']}/{s['compared']} ({s['bpm_acc1_pct']} %)")
    print(f"  ... octave-tolerant       : {s['bpm_acc2']}/{s['compared']} ({s['bpm_acc2_pct']} %)")
    print(
        f"  key exact / compatible    : {s['key_exact']} / {s['key_compatible']} "
        f"of {s['key_compared']} ({s['key_exact_pct']} % / {s['key_compatible_pct']} %)"
    )
    if s["grid_compared"]:
        print(
            f"  grid error vs Rekordbox   : median {s['grid_median_ms']} ms, "
            f"mean {s['grid_mean_ms']} ms, p90 {s['grid_p90_ms']} ms, max {s['grid_max_ms']} ms "
            f"({s['grid_compared']} tracks)"
        )
        print(
            f"  deck drift over 5 min     : median {s['drift_median_ms']} ms, "
            f"p90 {s['drift_p90_ms']} ms"
        )
    print("\n=== Verdict ===")
    if fails:
        for line in fails:
            print(f"  FAIL  {line}")
    else:
        print("  PASS  every floor reached")


def _row_line(r: dict[str, Any]) -> str:
    return (
        f"    [{r['id']}] {r['title']:<40} BPM rb={r['rb_bpm']} ours={r['our_bpm']}  "
        f"grid {r['beatgrid']['mean_abs_err_ms']} ms"
    )


CHECKLIST = (
    "Tempo and length on the deck match the app",
    "Cover art and waveform (overview + zoomed) show",
    "Grid lines sit on the kick at the start, the middle and the end of the track",
    "Hot cues and memory cues land where they were set",
    "Two of the 'agree' tracks beat-synced stay together for 5 minutes",
    "For 'bpm_differ' tracks: which tempo holds against a second deck, ours or Rekordbox's?",
)


def print_checklist(rows: list[dict[str, Any]]) -> None:
    picks = pick_cdj_tracks(rows)
    print("\n=== CDJ-3000 check ===")
    print("  Export these to a stick with the app, then load them on the player.")
    labels = {
        "agree": "agree (same BPM, tightest grid) — expected to be right",
        "grid_off": "grid_off (same tempo, grid furthest from Rekordbox) — check the kick",
        "bpm_differ": "bpm_differ (tempo differs from Rekordbox) — the ear decides",
    }
    for group, label in labels.items():
        print(f"\n  {label}")
        if not picks[group]:
            print("    (none)")
        for r in picks[group]:
            print(_row_line(r))
    print("\n  Per track:")
    for item in CHECKLIST:
        print(f"    [ ] {item}")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def cmd_ab(args: argparse.Namespace) -> int:
    from compare_rekordbox import default_master_db

    db_path = args.db or default_master_db()
    if not db_path:
        print("ERROR: no master.db under %APPDATA%/Pioneer/rekordbox — pass --db.", file=sys.stderr)
        return 2
    ids = _sample_ids(db_path, args.ids, args.n, args.seed, args.min_len)
    if not ids:
        print("No analysed tracks found.", file=sys.stderr)
        return 1
    print(f"A/B against Rekordbox: {len(ids)} track(s), {args.workers} worker(s)")
    rows = run_ab(db_path, ids, args.workers, args.tol)
    summary = summarise(rows)
    fails = check_thresholds(summary, DEFAULT_THRESHOLDS)
    report = {
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "analysis_version": _engine_version(),
        "sample": {"n": len(ids), "seed": args.seed, "min_len_s": args.min_len, "ids": ids},
        "thresholds": DEFAULT_THRESHOLDS,
        "summary": summary,
        "failures": fails,
        "rows": rows,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    for r in rows:
        if r.get("status") != "ok":
            print(f"  [{r['id']}] ERROR: {r.get('error')}")
    print_summary(summary, fails)
    print(f"\nReport: {out}")
    return 1 if fails else 0


def rekordbox_running() -> bool:
    """rbox refuses every write while Rekordbox runs — on a copy too."""
    import psutil

    for proc in psutil.process_iter(["name"]):
        if (proc.info.get("name") or "").lower().startswith("rekordbox"):
            return True
    return False


def file_fingerprint(path: Path) -> tuple[int, str] | None:
    """(size, sha256) of a file, None when it does not exist."""
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return path.stat().st_size, h.hexdigest()


def copy_library(src: Path, work: Path) -> Path:
    """Copy master.db with its WAL files into `work` next to an empty share/. Returns the copy."""
    work.mkdir(parents=True, exist_ok=False)
    for suffix in ("", "-wal", "-shm"):
        part = Path(str(src) + suffix)
        if part.exists():
            shutil.copy2(part, work / part.name)
    (work / "share").mkdir()
    return work / src.name


def _plain(value: Any) -> Any:
    return value if isinstance(value, (str, int, float, bool, type(None))) else repr(value)


def snapshot_tables(mdb: Any) -> tuple[dict[str, dict[str, dict[str, Any]]], dict[str, str]]:
    """Every table rbox can list: ({table: {row id: column dict}}, {table: why it was skipped}).

    rbox cannot read every table of every library (djmdCue fails on rows with a
    NULL it does not expect); such a table is reported, not silently dropped.
    """
    snap: dict[str, dict[str, dict[str, Any]]] = {}
    skipped: dict[str, str] = {}
    for table in table_getters(dir(mdb)):
        try:
            rows = getattr(mdb, f"get_{table}")()
        except TypeError:
            continue  # needs a parent id: a per-parent listing, see MEMBERSHIP_TABLES
        except Exception as e:
            skipped[table] = f"{type(e).__name__}: {e}"[:120]
            continue
        if not isinstance(rows, list):
            continue
        try:
            snap[table] = _rows_by_id(rows)
        except Exception as e:
            skipped[table] = f"{type(e).__name__}: {e}"[:120]

    for parent, child in MEMBERSHIP_TABLES:
        getter = getattr(mdb, f"get_{child}", None)
        if getter is None or parent not in snap:
            continue
        rows: list[Any] = []
        unreadable = 0
        for parent_id in snap[parent]:
            try:
                rows.extend(getter(parent_id))
            except Exception:
                unreadable += 1
        snap[child] = _rows_by_id(rows)
        if unreadable:
            skipped[child] = (
                f"{unreadable} of {len(snap[parent])} {parent} unreadable, rest compared"
            )
    return snap, skipped


def _rows_by_id(rows: list[Any]) -> dict[str, dict[str, Any]]:
    return {
        str(getattr(r, "id", None) or getattr(r, "registry_id", None) or i): {
            k: _plain(v) for k, v in r.to_dict().items()
        }
        for i, r in enumerate(rows)
    }


def run_db_write(
    src: Path, work: Path, ids: list[str] | None, n: int, seed: int, min_len: float
) -> tuple[list[str], dict[str, Any]]:
    """Write analysis results for a few tracks into a copy of master.db and audit the copy.

    Returns (failures, details). Leaves `work` in place; the caller removes it.
    """
    import rbox  # type: ignore
    from compare_rekordbox import _collect_tracks, _read_rb_beats_ms

    real_share = src.parent / "share"
    real_before = {str(p): file_fingerprint(p) for p in (src, Path(str(src) + "-wal"))}
    copy = copy_library(src, work)

    # From here on nothing may resolve the real library: the app's DB singleton
    # reads %APPDATA% at import, app.config creates folders in the cwd.
    sandbox = work / "appdata"
    sandbox.mkdir()
    old_env = {k: os.environ.get(k) for k in ("APPDATA", "LOCALAPPDATA")}
    old_cwd = Path.cwd()
    os.environ["APPDATA"] = os.environ["LOCALAPPDATA"] = str(sandbox)
    os.chdir(work)
    details: dict[str, Any] = {"work": str(work), "tracks": [], "tables": {}}
    fails: list[str] = []
    try:
        from app.analysis_db_writer import AnalysisDBWriter, rekordbox_key_name
        from app.analysis_engine import AnalysisEngine
        from app.live_database import LiveRekordboxDB

        live = LiveRekordboxDB(str(copy))
        share = Path(str(live.db.share_directory() or ""))
        if not is_within(share, work):
            raise RuntimeError(f"copy resolves its share folder outside the work dir: {share}")

        candidates = _collect_tracks(live.db, ids, n * 6, seed, min_len_s=min_len)
        picked = usable_ids(live.db, candidates, n, need_anlz=True)
        if not picked:
            raise RuntimeError("no track with audio on disk and a recorded AnalysisDataPath")

        # Bring each track's real ANLZ files into the copy's share, so the writer
        # overwrites (and backs up) existing files like it would in the real library.
        real_anlz: dict[str, tuple[int, str] | None] = {}
        had_dat: dict[str, bool] = {}
        for tid in picked:
            item = live.db.get_content_by_id(tid)
            rel = str(item.analysis_data_path).lstrip("/\\")
            # The two fields the writer reads from the loaded library.
            live.tracks[tid] = {"path": str(item.folder_path), "BPM": (item.bpm or 0) / 100.0}
            for suffix in ANLZ_SUFFIXES:
                real = (real_share / rel).with_suffix(suffix)
                real_anlz[str(real)] = file_fingerprint(real)
                if real.is_file():
                    target = (share / rel).with_suffix(suffix)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(real, target)
            had_dat[tid] = (share / rel).with_suffix(".DAT").is_file()

        before, skipped = snapshot_tables(live.db)
        missing = REQUIRED_TABLES - before.keys()
        if missing:
            raise RuntimeError(f"rbox cannot list {sorted(missing)}: {skipped}")
        names_before = {rid: row.get("name") for rid, row in before["keys"].items()}
        notation = library_key_notation(
            [names_before.get(str(r.get("key_id"))) for r in before["contents"].values()]
        )
        details["key_notation"] = notation
        details["skipped_tables"] = skipped
        writer = AnalysisDBWriter(live)
        results: dict[str, dict[str, Any]] = {}
        try:
            for tid in picked:
                started = time.monotonic()
                res = results[tid] = writer.analyze_and_save(tid, force=True)
                print(
                    f"  [{tid}] {res.get('status')} bpm={res.get('bpm')} key={res.get('key')} "
                    f"({time.monotonic() - started:.0f} s)"
                )
        finally:
            writer.shutdown()
            AnalysisEngine.shutdown()
        live._local.conn = None

        fresh = rbox.MasterDb(str(copy))
        after, _ = snapshot_tables(fresh)
        diffs = {t: diff_table(before[t], after[t]) for t in before if t in after}
        fails += judge_db_diff(diffs, set(picked))

        key_names = {rid: row.get("name") for rid, row in after.get("keys", {}).items()}
        for tid in picked:
            res = results[tid]
            row = after["contents"].get(tid)
            beats = 0
            if res.get("status") == "ok":
                dat = Path(str(res["anlz_paths"].get("dat", "")))
                for path in res["anlz_paths"].values():
                    if not is_within(Path(path), work):
                        fails.append(f"{tid}: ANLZ file written outside the work dir: {path}")
                beats = len(_read_rb_beats_ms(str(dat))) if dat.is_file() else 0
                if had_dat[tid] and not list(dat.parent.glob(f"{dat.name}.bak-*")):
                    fails.append(f"{tid}: existing .DAT was overwritten without a backup")
            key_after = key_names.get(str(row.get("key_id"))) if row else None
            classic = rekordbox_key_name(res.get("key_id", 0))
            camelot = str(res.get("camelot") or "")
            expected = (
                camelot if notation == "camelot" and _CAMELOT_NAME.match(camelot) else classic
            )
            fails += judge_written_row(tid, res, row, key_after, expected, beats)
            details["tracks"].append(
                {
                    "id": tid,
                    "status": res.get("status"),
                    "bpm": res.get("bpm"),
                    "key_before": names_before.get(str(before["contents"][tid].get("key_id"))),
                    "key_after": key_after,
                    "beats_in_dat": beats,
                    "changed_columns": diffs["contents"]["changed"].get(tid, []),
                }
            )
        details["tables"] = {
            t: {"rows": len(after[t]), "added": len(d["added"]), "changed": len(d["changed"])}
            for t, d in diffs.items()
        }
        del fresh

        for path, fp in real_anlz.items():
            if file_fingerprint(Path(path)) != fp:
                fails.append(f"REAL library file changed during the run: {path}")
    finally:
        os.chdir(old_cwd)
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    for path, fp in real_before.items():
        if file_fingerprint(Path(path)) != fp:
            fails.append(f"REAL library file changed during the run: {path}")
    return fails, details


def cmd_db_write(args: argparse.Namespace) -> int:
    from compare_rekordbox import default_master_db

    src_str = args.db or default_master_db()
    if not src_str:
        print("ERROR: no master.db under %APPDATA%/Pioneer/rekordbox — pass --db.", file=sys.stderr)
        return 2
    src = Path(src_str).resolve()
    if rekordbox_running():
        print("ERROR: Rekordbox is running. Close it — rbox refuses writes, on a copy too.")
        return 2
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    default_parent = ROOT / "tmp" / "validation"
    # A run that died (rbox can abort the process) leaves a copy of the library behind.
    for stale in default_parent.glob("db-*"):
        shutil.rmtree(stale, ignore_errors=True)
    work = Path(args.work).resolve() if args.work else default_parent / f"db-{stamp}"
    if is_within(work, src.parent):
        print(f"ERROR: work dir {work} lies inside the Rekordbox folder.", file=sys.stderr)
        return 2
    print(f"Write test on a copy of {src.name}: {args.n} track(s)\n  work dir: {work}")
    details: dict[str, Any] = {}
    try:
        fails, details = run_db_write(src, work, args.ids, args.n, args.seed, args.min_len)
    except RuntimeError as e:
        fails = [str(e)]
    finally:
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)
            if work.exists():
                print(f"  [warn] could not remove {work} — it holds a copy of your library")

    tables = details.get("tables", {})
    skipped = details.get("skipped_tables", {})
    print(f"\n=== Tables in the copy: {len(tables)} compared row by row ===")
    for table, t in tables.items():
        if t["changed"] or t["added"]:
            print(f"  {table:<24} {t['rows']:>6} rows  {t['changed']} changed  {t['added']} added")
    print(f"  untouched: {sum(1 for t in tables.values() if not t['changed'] and not t['added'])}")
    for table, why in skipped.items():
        print(f"  NOT COMPARED {table}: {why}")
    print(f"\n=== Written tracks (library key notation: {details.get('key_notation')}) ===")
    for t in details.get("tracks", []):
        print(
            f"  [{t['id']}] {t['status']} bpm={t['bpm']} key {t['key_before']} -> {t['key_after']} "
            f"beats in .DAT={t['beats_in_dat']} changed={t['changed_columns']}"
        )
    print("\n=== Verdict ===")
    if fails:
        for line in fails:
            print(f"  FAIL  {line}")
        return 1
    print("  PASS  only the written rows changed, only in the writer's columns;")
    print("        the real master.db and ANLZ files are byte-identical")
    if skipped:
        print(f"        not covered: {', '.join(sorted(skipped))} (rbox cannot read them here)")
    return 0


def cmd_checklist(args: argparse.Namespace) -> int:
    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    rows = report["rows"] if isinstance(report, dict) else report
    print_summary(summarise(rows), check_thresholds(summarise(rows), DEFAULT_THRESHOLDS))
    print_checklist(rows)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Real-library validation of the analysis engine")
    sub = ap.add_subparsers(dest="cmd", required=True)

    ab = sub.add_parser("ab", help="A/B against Rekordbox over N real tracks")
    ab.add_argument("--db", help="Path to Rekordbox master.db (default: auto-detect)")
    ab.add_argument("--ids", nargs="*", help="Explicit djmdContent ids (else a seeded sample)")
    ab.add_argument("-n", type=int, default=50, help="Tracks to sample (default 50)")
    ab.add_argument("--seed", type=int, default=7, help="Sample seed (default 7)")
    ab.add_argument("--min-len", type=float, default=120.0, help="Skip tracks shorter than this")
    ab.add_argument("--tol", type=float, default=4.0, help="BPM tolerance %% (MIREX 4.0)")
    ab.add_argument(
        "--workers", type=int, default=DEFAULT_WORKERS, help="Parallel analysis workers"
    )
    ab.add_argument("--out", default=str(DEFAULT_REPORT), help="Report path")
    ab.set_defaults(func=cmd_ab)

    dw = sub.add_parser("db-write", help="Run the analysis writer against a copy of master.db")
    dw.add_argument("--db", help="Path to Rekordbox master.db (default: auto-detect)")
    dw.add_argument("--ids", nargs="*", help="Explicit djmdContent ids (else a seeded sample)")
    dw.add_argument("-n", type=int, default=5, help="Tracks to write (default 5)")
    dw.add_argument("--seed", type=int, default=7, help="Sample seed (default 7)")
    dw.add_argument("--min-len", type=float, default=120.0, help="Skip tracks shorter than this")
    dw.add_argument("--work", help="Work folder for the copy (default tmp/validation/db-<time>)")
    dw.add_argument("--keep", action="store_true", help="Keep the copy for inspection")
    dw.set_defaults(func=cmd_db_write)

    cl = sub.add_parser("checklist", help="Print the CDJ checklist for a finished report")
    cl.add_argument("report", nargs="?", default=str(DEFAULT_REPORT))
    cl.set_defaults(func=cmd_checklist)

    args = ap.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
