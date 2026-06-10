#!/usr/bin/env python3
"""
compare_rekordbox.py — A/B accuracy harness: our engine vs Rekordbox.

Takes N already-analyzed tracks from a Rekordbox library, re-analyzes the
SAME audio files with our engine, and reports where we agree / disagree on
BPM, musical key, and beat grid. This is the "verify what's better" tool:

  * BPM / key are objective — Rekordbox is a strong reference, so a delta is
    a measurable signal (and half/double + harmonic-neighbour relations are
    classified, so a "miss" that is actually harmonically compatible is not
    counted as a hard error).
  * Beat grid: first-downbeat offset + mean nearest-beat error (ms).
  * Phrases (PSSI): count + nearest-boundary offset — Rekordbox phrases are a
    reference, not ground truth, so treat these as a comparison, not a score.

This script reads the live Rekordbox DB via `rbox` (the Rust-backed package,
`pip install rbox==0.1.7` — distinct from pyrekordbox) — run it on the machine
that has the library, with Rekordbox CLOSED.

Usage:
    python scripts/compare_rekordbox.py --db "<path to master.db>" -n 10
    python scripts/compare_rekordbox.py --ids 12345 67890 --json out.json
    python scripts/compare_rekordbox.py --db ... --seed 1 -n 10   # reproducible sample

The pure comparison helpers (parse_camelot / key_relation / bpm_relation /
beatgrid_metrics) carry no I/O and are unit-tested in
tests/test_compare_rekordbox.py.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# --------------------------------------------------------------------------- #
# Pure comparison helpers (no I/O — unit-tested)
# --------------------------------------------------------------------------- #

_CAMELOT_LETTERS = ("A", "B")


def parse_camelot(value: str | None) -> tuple[int, str] | None:
    """Parse a Camelot code like '8A' / '12B' into (number 1..12, letter).

    Returns None for empty / malformed input.
    """
    if not value:
        return None
    s = str(value).strip().upper()
    if len(s) < 2 or s[-1] not in _CAMELOT_LETTERS:
        return None
    try:
        num = int(s[:-1])
    except ValueError:
        return None
    if not 1 <= num <= 12:
        return None
    return num, s[-1]


def key_relation(rb_camelot: str | None, our_camelot: str | None) -> str:
    """Classify the harmonic relation between two Camelot codes.

    exact        — identical key
    relative     — relative major/minor (same number, A<->B) — mix-compatible
    fifth        — +/-1 on the wheel, same letter (perfect 4th/5th) — compatible
    energy       — same number/letter pair off-by ... (handled by relative)
    clash        — harmonically distant
    unknown      — one side unparseable
    """
    a = parse_camelot(rb_camelot)
    b = parse_camelot(our_camelot)
    if a is None or b is None:
        return "unknown"
    if a == b:
        return "exact"
    (na, la), (nb, lb) = a, b
    if na == nb and la != lb:
        return "relative"
    if la == lb and (abs(na - nb) == 1 or abs(na - nb) == 11):
        return "fifth"
    return "clash"


# A key_relation that counts as a "good" agreement (harmonically usable).
COMPATIBLE_KEY_RELATIONS = frozenset({"exact", "relative", "fifth"})


def bpm_relation(rb: float, ours: float, tol_pct: float = 1.0) -> tuple[str, float]:
    """Classify our BPM vs Rekordbox's, accounting for octave (half/double) errors.

    Returns (relation, best_pct_error) where relation is one of:
      match  — within tol_pct at the SAME tempo
      double — we read ~2x Rekordbox
      half   — we read ~0.5x Rekordbox
      triple/third — 3x or 1/3 metrical confusion
      other  — none of the above
    best_pct_error is the % error at the closest octave/metrical ratio.
    """
    if rb <= 0 or ours <= 0:
        return "other", float("inf")
    ratios = {
        "match": 1.0,
        "double": 2.0,
        "half": 0.5,
        "triple": 3.0,
        "third": 1.0 / 3.0,
    }
    best_rel, best_err = "other", float("inf")
    for rel, r in ratios.items():
        err = abs(ours - rb * r) / (rb * r) * 100.0
        if err < best_err:
            best_rel, best_err = rel, err
    if best_rel == "match" and best_err <= tol_pct:
        return "match", best_err
    # If a non-unity ratio fits tightly, report it; else "other".
    if best_err <= tol_pct:
        return best_rel, best_err
    return "other", best_err


def beatgrid_metrics(rb_beats_ms: list[float], our_beats_ms: list[float]) -> dict[str, float | int]:
    """Compare two beat-grids (lists of beat times in ms).

    Returns:
      first_offset_ms  — |first RB beat - first our beat|
      mean_abs_err_ms  — mean nearest-neighbour distance over the overlap
      max_abs_err_ms   — worst nearest-neighbour distance
      matched          — beats compared
    """
    if not rb_beats_ms or not our_beats_ms:
        return {
            "first_offset_ms": -1.0,
            "mean_abs_err_ms": -1.0,
            "max_abs_err_ms": -1.0,
            "matched": 0,
        }
    rb = sorted(rb_beats_ms)
    ours = sorted(our_beats_ms)
    first_offset = abs(rb[0] - ours[0])
    # nearest-neighbour error: for each RB beat within our grid's span,
    # find the closest of our beats.
    lo, hi = ours[0], ours[-1]
    errs: list[float] = []
    j = 0
    for t in rb:
        if t < lo or t > hi:
            continue
        while j + 1 < len(ours) and abs(ours[j + 1] - t) <= abs(ours[j] - t):
            j += 1
        errs.append(abs(ours[j] - t))
    if not errs:
        return {
            "first_offset_ms": round(first_offset, 1),
            "mean_abs_err_ms": -1.0,
            "max_abs_err_ms": -1.0,
            "matched": 0,
        }
    return {
        "first_offset_ms": round(first_offset, 1),
        "mean_abs_err_ms": round(sum(errs) / len(errs), 1),
        "max_abs_err_ms": round(max(errs), 1),
        "matched": len(errs),
    }


# --------------------------------------------------------------------------- #
# Rekordbox-side reading (needs `rbox` + a real library — run locally)
# --------------------------------------------------------------------------- #


def _read_rb_beats_ms(dat_path: str) -> list[float]:
    """Read beat times (ms) from a Rekordbox ANLZ .DAT PQTZ tag via rbox."""
    import rbox  # type: ignore

    anlz = rbox.Anlz(dat_path)
    pqtz = getattr(anlz, "pqtz", None)
    if not pqtz or not getattr(pqtz, "entries", None):
        return []
    return [float(e.time) for e in pqtz.entries]


def _rb_camelot_from_key_id(key_id: int) -> str:
    """Map a Rekordbox key_id (1..24) to a Camelot code using our engine maps."""
    from app.analysis_engine import _CAMELOT_MAP, _REKORDBOX_KEY_ID

    inv = {v: k for k, v in _REKORDBOX_KEY_ID.items()}  # key_id -> "C major"
    full = inv.get(int(key_id))
    return _CAMELOT_MAP.get(full, "") if full else ""


def _collect_tracks(db, ids: list[str] | None, n: int, seed: int | None) -> list[str]:
    """Pick track ids: explicit --ids, else a random sample of analyzed tracks."""
    if ids:
        return [str(i) for i in ids]
    analyzed: list[str] = []
    for item in db.get_contents():
        tid = str(getattr(item, "id", "") or getattr(item, "ID", ""))
        bpm = getattr(item, "bpm", 0) or 0
        if tid and bpm and bpm > 0:
            analyzed.append(tid)
    if seed is not None:
        random.seed(seed)
    random.shuffle(analyzed)
    return analyzed[:n]


def compare_track(db, tid: str, tol_pct: float = 4.0) -> dict[str, Any]:
    """Read RB analysis for one track and re-run ours; return a comparison row."""
    from app.analysis_engine import run_full_analysis

    item = db.get_content_by_id(tid)
    if not item:
        return {"id": tid, "status": "error", "error": "not found in DB"}
    path = str(getattr(item, "folder_path", "") or getattr(item, "FolderPath", "") or "")
    if not path or not Path(path).exists():
        return {"id": tid, "status": "error", "error": f"audio missing: {path}"}

    rb_bpm = float(getattr(item, "bpm", 0) or 0) / 100.0
    rb_key_id = int(getattr(item, "key_id", 0) or getattr(item, "KeyID", 0) or 0)
    rb_camelot = _rb_camelot_from_key_id(rb_key_id) if rb_key_id else ""

    rb_beats: list[float] = []
    try:
        paths = db.get_content_anlz_paths(tid)
        dat = paths.get("DAT") if paths else None
        if dat and Path(str(dat)).exists():
            rb_beats = _read_rb_beats_ms(str(dat))
    except Exception as e:
        rb_beats = []
        print(f"  [warn] {tid}: RB beatgrid read failed: {e}", file=sys.stderr)

    ours = run_full_analysis(path, use_cache=False)
    if ours.get("status") != "ok":
        return {"id": tid, "status": "error", "error": ours.get("error", "analysis failed")}

    our_bpm = float(ours["bpm"])
    our_camelot = ours.get("camelot", "")
    our_beats = [float(b["time_ms"]) for b in ours.get("beats", [])]

    bpm_rel, bpm_err = bpm_relation(rb_bpm, our_bpm, tol_pct=tol_pct)
    return {
        "id": tid,
        "status": "ok",
        "title": str(getattr(item, "title", "") or getattr(item, "Title", "") or "")[:40],
        "rb_bpm": round(rb_bpm, 2),
        "our_bpm": round(our_bpm, 2),
        "bpm_relation": bpm_rel,
        "bpm_pct_err": round(bpm_err, 2),
        "rb_camelot": rb_camelot,
        "our_camelot": our_camelot,
        "key_relation": key_relation(rb_camelot, our_camelot),
        "beatgrid": beatgrid_metrics(rb_beats, our_beats),
        "rb_beats": len(rb_beats),
        "our_beats": len(our_beats),
    }


def _print_report(rows: list[dict[str, Any]]) -> None:
    ok = [r for r in rows if r.get("status") == "ok"]
    print("\n=== Per-track ===")
    for r in rows:
        if r.get("status") != "ok":
            print(f"  [{r['id']}] ERROR: {r.get('error')}")
            continue
        bg = r["beatgrid"]
        print(
            f"  [{r['id']}] {r['title']:<40} "
            f"BPM rb={r['rb_bpm']:<6} ours={r['our_bpm']:<6} {r['bpm_relation']:<6} "
            f"({r['bpm_pct_err']}%)  "
            f"KEY rb={r['rb_camelot']:<3} ours={r['our_camelot']:<3} {r['key_relation']:<8} "
            f"GRID off={bg['first_offset_ms']}ms mean={bg['mean_abs_err_ms']}ms"
        )
    if not ok:
        print("\nNo successful comparisons.")
        return
    bpm_match = sum(1 for r in ok if r["bpm_relation"] == "match")
    bpm_octave = sum(1 for r in ok if r["bpm_relation"] in ("half", "double", "third", "triple"))
    key_compatible = sum(1 for r in ok if r["key_relation"] in COMPATIBLE_KEY_RELATIONS)
    key_exact = sum(1 for r in ok if r["key_relation"] == "exact")
    grid = [r["beatgrid"]["mean_abs_err_ms"] for r in ok if r["beatgrid"]["mean_abs_err_ms"] >= 0]
    print("\n=== Summary ===")
    print(f"  tracks compared        : {len(ok)}")
    print(f"  BPM Acc-1 (exact octave): {bpm_match}/{len(ok)}")
    print(f"  BPM Acc-2 (octave-tol.) : {bpm_match + bpm_octave}/{len(ok)}  (+half/double/third)")
    print(f"  KEY exact              : {key_exact}/{len(ok)}")
    print(f"  KEY harmonic-compatible: {key_compatible}/{len(ok)}  (exact+relative+fifth)")
    if grid:
        print(
            f"  beatgrid mean err     : {round(sum(grid) / len(grid), 1)} ms (avg of per-track means)"
        )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="A/B accuracy: our engine vs Rekordbox")
    ap.add_argument("--db", help="Path to Rekordbox master.db (default: auto-detect)")
    ap.add_argument("--ids", nargs="*", help="Explicit djmdContent ids (else random sample)")
    ap.add_argument("-n", type=int, default=10, help="Number of tracks to sample (default 10)")
    ap.add_argument("--seed", type=int, default=None, help="Random seed for reproducible sampling")
    ap.add_argument("--tol", type=float, default=4.0, help="BPM tolerance %% (MIREX standard 4.0)")
    ap.add_argument("--json", help="Write full results to this JSON file (golden fixture)")
    args = ap.parse_args(argv)

    try:
        import rbox  # type: ignore
    except ImportError:
        print(
            "ERROR: `rbox` (the Rust-backed package — distinct from pyrekordbox) not "
            "installed. `pip install rbox==0.1.7` and run locally where the library lives.",
            file=sys.stderr,
        )
        return 2

    db = rbox.MasterDb(args.db) if args.db else rbox.MasterDb()
    tids = _collect_tracks(db, args.ids, args.n, args.seed)
    if not tids:
        print("No analyzed tracks found.", file=sys.stderr)
        return 1
    print(f"Comparing {len(tids)} track(s)...")

    rows = []
    for tid in tids:
        try:
            rows.append(compare_track(db, tid, tol_pct=args.tol))
        except Exception as e:
            rows.append({"id": tid, "status": "error", "error": repr(e)})

    _print_report(rows)
    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=2))
        print(f"\nWrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
