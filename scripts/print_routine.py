#!/usr/bin/env python3
"""
Extract the deploy-ready prompt from a routine .md file.

Each `docs/research/routines/<name>.md` holds metadata above a `---` divider
and the actual claude.ai/code routine prompt below it. This script prints
just the prompt — copy-paste ready into the routine on claude.ai/code.

Usage:
    python scripts/print_routine.py <name>          # one routine
    python scripts/print_routine.py --all           # all routines, separated
    python scripts/print_routine.py --list          # list routine names + cron
    python scripts/print_routine.py --check         # verify every file has a divider (CI)

Examples:
    python scripts/print_routine.py research-draft | clip       # Windows clipboard
    python scripts/print_routine.py research-draft | pbcopy     # macOS clipboard
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ROUTINES_DIR = REPO_ROOT / "docs" / "research" / "routines"
DIVIDER = "---"
# Cron is encoded in the routine .md header — match the literal line we use
# ("**Cron:** `0 5 * * *` (05:00 Berlin)") to surface it in --list.
_CRON_RE = re.compile(r"\*\*Cron:\*\*\s*`([^`]+)`\s*\(([^)]+)\)")


def list_routines() -> list[Path]:
    """All routine prompt files, sorted alphabetically. Excludes the README."""
    return sorted(
        p
        for p in ROUTINES_DIR.glob("*.md")
        if p.stem.lower() != "readme"
    )


def split_prompt(path: Path) -> tuple[str, str] | None:
    """Return (header, prompt) split at the first standalone `---` divider.

    Returns None if the file has no divider — that means it isn't a
    routine prompt file (or it is malformed).
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"error reading {path}: {exc}", file=sys.stderr)
        return None
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == DIVIDER:
            header = "\n".join(lines[:i])
            # Skip the divider and any single blank line that follows.
            start = i + 1
            if start < len(lines) and lines[start].strip() == "":
                start += 1
            prompt = "\n".join(lines[start:]).rstrip() + "\n"
            return header, prompt
    return None


def cron_summary(header: str) -> str:
    m = _CRON_RE.search(header)
    if not m:
        return "?"
    return f"{m.group(1)}  ({m.group(2)})"


def cmd_list() -> int:
    routines = list_routines()
    if not routines:
        print(f"No routines under {ROUTINES_DIR}.", file=sys.stderr)
        return 1
    print(f"{'routine':<28} cron")
    print("-" * 60)
    for path in routines:
        split = split_prompt(path)
        cron = cron_summary(split[0]) if split else "(no divider)"
        print(f"{path.stem:<28} {cron}")
    return 0


def cmd_check() -> int:
    routines = list_routines()
    bad: list[Path] = []
    for path in routines:
        if split_prompt(path) is None:
            bad.append(path)
    if bad:
        print(f"FAIL — {len(bad)} routine file(s) missing a `---` divider:", file=sys.stderr)
        for p in bad:
            print(f"  {p.relative_to(REPO_ROOT)}", file=sys.stderr)
        return 1
    print(f"OK — {len(routines)} routine files all have a `---` divider.")
    return 0


def cmd_print_one(name: str) -> int:
    path = ROUTINES_DIR / f"{name}.md"
    if not path.is_file():
        avail = ", ".join(p.stem for p in list_routines())
        print(f"No routine named '{name}'. Available: {avail}", file=sys.stderr)
        return 1
    split = split_prompt(path)
    if split is None:
        print(f"{path.name} has no `---` divider — not a routine prompt file.", file=sys.stderr)
        return 1
    _header, prompt = split
    sys.stdout.write(prompt)
    return 0


def cmd_print_all() -> int:
    routines = list_routines()
    if not routines:
        print(f"No routines under {ROUTINES_DIR}.", file=sys.stderr)
        return 1
    for path in routines:
        split = split_prompt(path)
        if split is None:
            continue
        _header, prompt = split
        sys.stdout.write(f"\n{'=' * 78}\n# {path.stem}\n{'=' * 78}\n\n")
        sys.stdout.write(prompt)
    return 0


def main() -> int:
    # Routine prompts contain em-dashes, ⛔, etc. — force UTF-8 stdout so the
    # script works under Windows cp1252 consoles + pipes equally.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        description="Extract claude.ai/code-ready prompts from routine .md files."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("name", nargs="?", help="routine name (e.g. research-draft)")
    group.add_argument("--all", action="store_true", help="print every routine, separated")
    group.add_argument("--list", action="store_true", help="list routines + cron schedule")
    group.add_argument("--check", action="store_true", help="verify every file has a divider")
    args = parser.parse_args()

    if args.list:
        return cmd_list()
    if args.check:
        return cmd_check()
    if args.all:
        return cmd_print_all()
    return cmd_print_one(args.name)


if __name__ == "__main__":
    sys.exit(main())
