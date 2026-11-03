"""Vendor a slim snapshot of the genre-atlas repo into app/data/genre_atlas.json.

The genre atlas (sibling repo `genre-atlas`) builds `dist/genres.json` (~3 MB, every note body).
LMS only needs what genre suggestions use: genre ids, names, aliases, parents and BPM windows,
the tags (labels in the wild) with their resolution tests, and the scenes (labels, clubs,
platforms) with SoundCloud permalinks. This script extracts that subset (~320 KB, under the
pre-commit 500 KB limit) and records the source commit in the snapshot.

Usage:
  python scripts/sync_genre_atlas.py                      # source = ../genre-atlas or $GENRE_ATLAS_DIR
  python scripts/sync_genre_atlas.py --source <path>      # explicit checkout of the atlas repo
  python scripts/sync_genre_atlas.py --check              # exit 1 if the snapshot is out of date
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path

logger = logging.getLogger("sync_genre_atlas")

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_FILE = REPO_ROOT / "app" / "data" / "genre_atlas.json"
DEFAULT_SOURCE = REPO_ROOT.parent / "genre-atlas"

_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:\|([^\]]*))?\]\]")
_RESOLUTION_RE = re.compile(r"^- \[\[([^\]|#]+)(?:\|[^\]]*)?\]\]:\s*(.+)$")

GENRE_KEYS = ("id", "name", "aliases", "family", "parent", "level", "bpm", "status")
TAG_KEYS = ("id", "name", "aliases", "seen_on", "period", "resolves_to", "status")
SCENE_KEYS = (
    "id",
    "name",
    "kind",
    "city",
    "country",
    "founded",
    "active",
    "soundcloud",
    "genres",
    "tags_used",
    "status",
)


def _plain(text: str) -> str:
    """Replace Obsidian wikilinks with their display text."""
    return _WIKILINK_RE.sub(lambda m: m.group(2) or m.group(1), text or "").strip()


def _source_commit(source: Path) -> str | None:
    start = time.monotonic()
    try:
        out = subprocess.run(
            ["git", "-C", str(source), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning("op=sync_genre_atlas step=rev-parse err=%s", e)
        return None
    finally:
        logger.debug("op=sync_genre_atlas step=rev-parse elapsed=%.2fs", time.monotonic() - start)
    return out.stdout.strip() or None


def slim(dist: dict, commit: str | None) -> dict:
    genres = []
    for n in dist.get("nodes", []):
        g = {k: n.get(k) for k in GENRE_KEYS}
        g["definition"] = _plain((n.get("sections") or {}).get("definition", ""))
        genres.append(g)

    tags = []
    for t in dist.get("tags", []):
        entry = {k: t.get(k) for k in TAG_KEYS}
        sections = t.get("sections") or {}
        entry["meaning"] = _plain(sections.get("meaning", ""))
        resolution: dict[str, str] = {}
        for line in (sections.get("resolution") or "").splitlines():
            m = _RESOLUTION_RE.match(line.strip())
            if m:
                resolution[m.group(1).strip()] = _plain(m.group(2))
        entry["resolution"] = resolution
        tags.append(entry)

    scenes = [{k: s.get(k) for k in SCENE_KEYS} for s in dist.get("scenes", [])]

    return {
        "schema_version": dist.get("schema_version"),
        "source": {"repo": "genre-atlas", "commit": commit},
        "genres": sorted(genres, key=lambda x: x["id"]),
        "tags": sorted(tags, key=lambda x: x["id"]),
        "scenes": sorted(scenes, key=lambda x: x["id"]),
    }


def render(snapshot: dict) -> str:
    return json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=1) + "\n"


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--source", type=Path, default=Path(os.environ.get("GENRE_ATLAS_DIR", DEFAULT_SOURCE))
    )
    ap.add_argument(
        "--check", action="store_true", help="exit 1 when the snapshot differs from the source"
    )
    args = ap.parse_args(argv)

    dist_file = args.source / "dist" / "genres.json"
    if not dist_file.is_file():
        logger.error(
            "genre-atlas build not found at %s (set --source or GENRE_ATLAS_DIR)", dist_file
        )
        return 2
    dist = json.loads(dist_file.read_text(encoding="utf-8"))
    new = render(slim(dist, _source_commit(args.source)))

    if args.check:
        old = OUT_FILE.read_text(encoding="utf-8") if OUT_FILE.exists() else ""
        if old != new:
            logger.error(
                "app/data/genre_atlas.json is out of date: run python scripts/sync_genre_atlas.py"
            )
            return 1
        logger.info("app/data/genre_atlas.json is up to date")
        return 0

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(new, encoding="utf-8", newline="\n")
    snap = json.loads(new)
    logger.info(
        "wrote %s: %d genres, %d tags, %d scenes, %d KB (source %s)",
        OUT_FILE.relative_to(REPO_ROOT).as_posix(),
        len(snap["genres"]),
        len(snap["tags"]),
        len(snap["scenes"]),
        len(new.encode("utf-8")) // 1024,
        (snap["source"]["commit"] or "unknown")[:10],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
