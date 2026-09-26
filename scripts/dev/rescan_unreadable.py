"""Re-scan only the rows marked unreadable in an audio_report.json.

Usage:
    python scripts/dev/rescan_unreadable.py [report.json]
    python scripts/dev/rescan_unreadable.py report.json --out rescanned.json
    python scripts/dev/rescan_unreadable.py report.json --workers 4

Re-probes every row carrying an "error", merges the results back into the
report and rewrites it (in place unless --out is given). Use it after
unlocking files Rekordbox held open or fixing a path.

Needs ffprobe (FFmpeg) on PATH.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scan_audio_quality import classify, default_workers, probe, require_ffprobe


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "report",
        type=Path,
        nargs="?",
        default=Path("audio_report.json"),
        help="audio_report.json produced by scan_audio_quality.py",
    )
    ap.add_argument(
        "--out", type=Path, default=None, help="write here instead of overwriting the input"
    )
    ap.add_argument("--workers", type=int, default=default_workers())
    args = ap.parse_args()
    if args.workers < 1:
        ap.error("--workers must be >= 1")

    require_ffprobe()
    if not args.report.is_file():
        sys.exit(f"no report at {args.report} - run scan_audio_quality.py first")

    try:
        data = json.loads(args.report.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(f"cannot read {args.report}: {e}")
    if not isinstance(data, dict) or "rows" not in data:
        sys.exit(f"{args.report} is not a scan report (no 'rows' key)")
    prev_summary = data.get("summary")
    if not isinstance(prev_summary, dict):
        prev_summary = {}

    bad = [r["path"] for r in data["rows"] if r.get("error")]
    print(f"re-scanning {len(bad)} previously-failed files", file=sys.stderr)

    fixed = []
    still_bad = []
    with mp.Pool(args.workers) as pool:
        for row in pool.imap_unordered(probe, bad, chunksize=8):
            row["tier"] = classify(row)
            if row.get("error"):
                still_bad.append(row)
            else:
                fixed.append(row)

    print(f"fixed: {len(fixed)}", file=sys.stderr)
    print(f"still unreadable: {len(still_bad)}", file=sys.stderr)

    rows_new = [r for r in data["rows"] if not r.get("error")] + fixed + still_bad

    by_tier: dict[str, dict] = {}
    by_codec: dict[str, dict] = {}
    by_ext: dict[str, int] = {}
    total_bytes = 0
    total_seconds = 0.0
    errors = 0
    for r in rows_new:
        tier = r["tier"]
        codec = r.get("codec") or "unknown"
        ext = r.get("ext") or "?"
        by_ext[ext] = by_ext.get(ext, 0) + 1
        if r.get("error"):
            errors += 1
            by_tier.setdefault(tier, {"count": 0, "bytes": 0})["count"] += 1
            continue
        size = r.get("size", 0)
        dur = r.get("duration", 0.0)
        total_bytes += size
        total_seconds += dur
        t = by_tier.setdefault(tier, {"count": 0, "bytes": 0, "seconds": 0.0})
        t["count"] += 1
        t["bytes"] += size
        t["seconds"] += dur
        c = by_codec.setdefault(codec, {"count": 0, "sample_rates": {}, "bitrates_kbps": []})
        c["count"] += 1
        sr = r.get("sample_rate", 0)
        c["sample_rates"][str(sr)] = c["sample_rates"].get(str(sr), 0) + 1
        br = max(r.get("stream_bit_rate", 0), r.get("format_bit_rate", 0)) // 1000
        if br > 0:
            c["bitrates_kbps"].append(br)

    for info in by_codec.values():
        bitrates = info.pop("bitrates_kbps")
        if bitrates:
            bitrates.sort()
            info["bitrate_min"] = bitrates[0]
            info["bitrate_max"] = bitrates[-1]
            info["bitrate_median"] = bitrates[len(bitrates) // 2]
            info["bitrate_avg"] = round(sum(bitrates) / len(bitrates), 1)

    summary = {
        # keep scanner-only keys ("root", ...) - the in-place rewrite is the only copy
        **prev_summary,
        "files_total": len(rows_new),
        "errors": errors,
        "total_bytes": total_bytes,
        "total_gb": round(total_bytes / 1_073_741_824, 2),
        "total_hours": round(total_seconds / 3600, 1),
        "by_extension": dict(sorted(by_ext.items(), key=lambda kv: -kv[1])),
        "by_tier": dict(sorted(by_tier.items(), key=lambda kv: -kv[1]["count"])),
        "by_codec": dict(sorted(by_codec.items(), key=lambda kv: -kv[1]["count"])),
    }
    (args.out or args.report).write_text(
        json.dumps({"summary": summary, "rows": rows_new}, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
