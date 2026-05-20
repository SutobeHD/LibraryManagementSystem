#!/usr/bin/env python3
"""
Show the research pipeline state at a glance.

Scans docs/research/{research,implement,archived}/, groups docs by state,
highlights open user gates (A/B/C), and lists open routine/* PRs.

Usage:
    python scripts/pipeline_status.py            # full report
    python scripts/pipeline_status.py --gates    # only docs waiting at a gate
    python scripts/pipeline_status.py --no-pr    # skip the gh PR lookup

Design:
- No third-party deps — pure stdlib, safe to run without the project's
  runtime installed.
- File system is the source of truth (state = folder + filename prefix).
- The gh PR lookup is best-effort: skipped silently if gh is missing,
  unauthenticated, or offline.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RESEARCH_DIR = REPO_ROOT / "docs" / "research"

# State order per stage (pipeline order).
STAGE_STATES: dict[str, list[str]] = {
    "research": ["idea", "drafting", "ideagate", "exploring", "midgate", "evaluated", "parked"],
    "implement": ["draftplan", "review", "plangate", "rework", "accepted", "inprogress", "blocked"],
    "archived": ["implemented", "superseded", "abandoned"],
}

# Gate states → gate letter. These wait on the user.
GATE_STATES: dict[str, str] = {"ideagate": "A", "midgate": "B", "plangate": "C"}

_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


@dataclass
class Doc:
    stage: str
    state: str
    slug: str
    path: Path
    last_lifecycle: date | None

    @property
    def age_days(self) -> int | None:
        if self.last_lifecycle is None:
            return None
        return (date.today() - self.last_lifecycle).days


def _last_lifecycle_date(path: Path) -> date | None:
    """Return the date of the last line under the doc's ## Lifecycle heading."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    in_section = False
    found: date | None = None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            in_section = stripped.lower() == "## lifecycle"
            continue
        if in_section:
            m = _DATE_RE.search(line)
            if m:
                with contextlib.suppress(ValueError):
                    found = date.fromisoformat(m.group(1))
    return found


def scan() -> list[Doc]:
    """Walk the three stage folders, parse each <state>_<slug>.md doc."""
    docs: list[Doc] = []
    for stage in STAGE_STATES:
        folder = RESEARCH_DIR / stage
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.md")):
            name = path.stem  # filename without .md
            if "_" not in name:
                continue  # skip non-pipeline files
            state, slug = name.split("_", 1)
            docs.append(
                Doc(
                    stage=stage,
                    state=state,
                    slug=slug,
                    path=path,
                    last_lifecycle=_last_lifecycle_date(path),
                )
            )
    return docs


def fetch_routine_prs() -> list[dict] | None:
    """Open PRs from routine/* branches. None if gh is unavailable."""
    try:
        result = subprocess.run(
            ["gh", "pr", "list", "--state", "open", "--json", "number,title,headRefName"],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=REPO_ROOT,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    try:
        prs = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    return [p for p in prs if str(p.get("headRefName", "")).startswith("routine/")]


def _age_str(doc: Doc) -> str:
    if doc.age_days is None:
        return "?"
    if doc.age_days == 0:
        return "today"
    if doc.age_days == 1:
        return "1 day"
    return f"{doc.age_days} days"


def open_gates(docs: list[Doc]) -> list[Doc]:
    return [d for d in docs if d.state in GATE_STATES]


def print_gates(docs: list[Doc]) -> None:
    gates = open_gates(docs)
    if not gates:
        print("No open gates - nothing waiting on you.")
        return
    print(f"WAITING ON YOU ({len(gates)} gate{'s' if len(gates) != 1 else ''})")
    for d in gates:
        letter = GATE_STATES[d.state]
        print(
            f"  GATE {letter}  {d.state}_  {d.slug}  ({_age_str(d)})"
            f"  ->  /gate-pass {d.slug}   |   /gate-reject {d.slug} \"<reason>\""
        )


def print_report(docs: list[Doc], prs: list[dict] | None, pr_checked: bool) -> None:
    print(f"Research pipeline - {date.today().isoformat()}")
    print()
    print_gates(docs)
    print()

    by_state: dict[str, list[Doc]] = {}
    for d in docs:
        by_state.setdefault(d.state, []).append(d)

    for stage, states in STAGE_STATES.items():
        print(f"{stage}/")
        for state in states:
            entries = by_state.get(state, [])
            slugs = ", ".join(d.slug for d in entries) if entries else ""
            print(f"  {state:<12}{len(entries):>3}  {slugs}")
        # surface any unexpected state in this folder
        for state, entries in sorted(by_state.items()):
            if entries and entries[0].stage == stage and state not in states:
                slugs = ", ".join(d.slug for d in entries)
                print(f"  {state:<12}{len(entries):>3}  {slugs}  (UNKNOWN STATE)")
        print()

    if pr_checked:
        if prs is None:
            print("Open routine/* PRs — skipped (gh unavailable)")
        else:
            print(f"Open routine/* PRs ({len(prs)})")
            for p in prs:
                print(f"  #{p['number']}  {p['title']}  [{p['headRefName']}]")


def main() -> int:
    parser = argparse.ArgumentParser(description="Show the research pipeline state.")
    parser.add_argument("--gates", action="store_true", help="only show open gates")
    parser.add_argument("--no-pr", action="store_true", help="skip the gh PR lookup")
    args = parser.parse_args()

    docs = scan()

    if args.gates:
        print_gates(docs)
        return 0

    prs = None if args.no_pr else fetch_routine_prs()
    print_report(docs, prs, pr_checked=not args.no_pr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
