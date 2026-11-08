"""Scan an audio library with ffprobe, aggregate codec/bitrate/sample-rate.

Usage:
    python scripts/dev/scan_audio_quality.py <root-dir>
    python scripts/dev/scan_audio_quality.py <root-dir> --out report.json
    python scripts/dev/scan_audio_quality.py <root-dir> --workers 4

Writes JSON with per-file rows + aggregate buckets useful for judging
club-playback readiness (lossless / 320 MP3 / 256 AAC / lower).

Needs ffprobe (FFmpeg) on PATH.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import shutil
import subprocess
import sys
from pathlib import Path

AUDIO_EXTS = {
    ".mp3",
    ".wav",
    ".flac",
    ".aiff",
    ".aif",
    ".m4a",
    ".ogg",
    ".wma",
    ".alac",
    ".aac",
    ".opus",
}


def default_workers() -> int:
    """ffprobe is seek-bound, not CPU-bound; >8 thrashes an external USB/HDD."""
    return max(2, min(8, os.cpu_count() or 4))


def require_ffprobe() -> None:
    """Fail before spawning one process per track - see CLAUDE.md, External deps."""
    if shutil.which("ffprobe") is None:
        sys.exit("ffprobe not on PATH - install FFmpeg (see CLAUDE.md, External deps)")


def probe(path: str) -> dict:
    try:
        out = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                "-select_streams",
                "a:0",
                path,
            ],
            capture_output=True,
            timeout=15,
        )
        err = (out.stderr or b"").decode("utf-8", errors="replace").strip()
        data = json.loads((out.stdout or b"").decode("utf-8", errors="replace") or "{}")
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as e:
        return {"path": path, "error": type(e).__name__, "detail": str(e)[:200]}

    streams = data.get("streams", [])
    fmt = data.get("format", {})
    if not streams:
        # ffprobe exits non-zero with an empty JSON body for every real failure:
        # locked by Rekordbox, corrupt, moved. rc + stderr are the only way to
        # tell those apart from a genuine video-only container, which exits 0.
        return {
            "path": path,
            "error": f"ffprobe-rc-{out.returncode}" if out.returncode else "no-audio-stream",
            "detail": err[:200],
        }
    s = streams[0]
    row = {
        "path": path,
        "ext": Path(path).suffix.lower(),
        "codec": s.get("codec_name"),
        "sample_rate": int(s.get("sample_rate") or 0),
        "channels": int(s.get("channels") or 0),
        "bits_per_sample": int(s.get("bits_per_raw_sample") or s.get("bits_per_sample") or 0),
        "stream_bit_rate": int(s.get("bit_rate") or 0),
        "format_bit_rate": int(fmt.get("bit_rate") or 0),
        "duration": float(fmt.get("duration") or 0.0),
        "size": int(fmt.get("size") or 0),
    }
    if err:
        # rc 0 but ffprobe complained ("Header missing") - readable, still worth seeing.
        row["warn"] = err[:200]
    return row


def classify(row: dict) -> str:
    """Bucket per club-readiness tier."""
    if row.get("error"):
        return "unreadable"
    codec = (row.get("codec") or "").lower()
    if codec in {
        "flac",
        "alac",
        "pcm_s16le",
        "pcm_s24le",
        "pcm_s32le",
        "pcm_f32le",
        "pcm_f64le",
        "wavpack",
    }:
        return "lossless"
    br = max(row.get("stream_bit_rate", 0), row.get("format_bit_rate", 0))
    kbps = br // 1000
    if codec == "aac" and kbps >= 256:
        return "aac_256plus"
    if codec == "mp3" and kbps >= 320:
        return "mp3_320"
    if codec == "mp3" and kbps >= 256:
        return "mp3_256_319"
    if codec == "mp3" and kbps >= 192:
        return "mp3_192_255"
    if codec == "mp3" and kbps >= 128:
        return "mp3_128_191"
    if codec == "mp3":
        return "mp3_under128"
    if codec == "aac" and kbps >= 192:
        return "aac_192_255"
    if codec == "aac" and kbps >= 128:
        return "aac_128_191"
    if codec == "aac":
        return "aac_under128"
    return f"other_{codec or 'unknown'}"


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("root", type=Path, help="library root to walk recursively")
    ap.add_argument("--out", type=Path, default=Path("audio_report.json"))
    ap.add_argument("--workers", type=int, default=default_workers())
    args = ap.parse_args()
    if args.workers < 1:
        ap.error("--workers must be >= 1")

    require_ffprobe()
    if not args.root.is_dir():
        sys.exit(f"no such directory: {args.root}")

    files = [str(p) for p in args.root.rglob("*") if p.suffix.lower() in AUDIO_EXTS and p.is_file()]
    print(f"found {len(files)} audio files under {args.root}", file=sys.stderr)
    if not files:
        return 1

    with mp.Pool(args.workers) as pool:
        rows = []
        for i, row in enumerate(pool.imap_unordered(probe, files, chunksize=32), 1):
            row["tier"] = classify(row)
            rows.append(row)
            if i % 500 == 0:
                print(f"  {i}/{len(files)}", file=sys.stderr)

    by_tier: dict[str, dict] = {}
    by_codec: dict[str, dict] = {}
    by_ext: dict[str, int] = {}
    total_bytes = 0
    total_seconds = 0.0
    errors = 0

    for r in rows:
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
        t["seconds"] = t.get("seconds", 0.0) + dur
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
        "root": str(args.root),
        "files_total": len(rows),
        "errors": errors,
        "total_bytes": total_bytes,
        "total_gb": round(total_bytes / 1_073_741_824, 2),
        "total_hours": round(total_seconds / 3600, 1),
        "by_extension": dict(sorted(by_ext.items(), key=lambda kv: -kv[1])),
        "by_tier": dict(sorted(by_tier.items(), key=lambda kv: -kv[1]["count"])),
        "by_codec": dict(sorted(by_codec.items(), key=lambda kv: -kv[1]["count"])),
    }

    args.out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
