#!/usr/bin/env python3
"""
Show the research pipeline state at a glance.

Scans docs/research/{research,implement,archived}/, groups docs by state,
highlights open user gates (A/B/C), and lists open routine/* PRs.

Usage:
    python scripts/pipeline_status.py            # full report
    python scripts/pipeline_status.py --gates    # only docs waiting at a gate
    python scripts/pipeline_status.py --no-pr    # skip the gh PR lookup
    python scripts/pipeline_status.py --trends   # add avg-days-per-stage trends + throughput

Design:
- No third-party deps — pure stdlib, safe to run without the project's
  runtime installed.
- File system is the source of truth (state = folder + filename prefix).
- The gh PR lookup is best-effort: skipped silently if gh is missing,
  unauthenticated, or offline.
- Trend metrics derive from `## Lifecycle` lines — every state advance
  appends a dated line, so the doc itself is the audit trail.
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

# Known pipeline states (must match STAGE_STATES below) — explicit alternation
# avoids matching arbitrary `WORD_` tokens elsewhere in lifecycle lines
# (e.g. SHUTDOWN_TOKEN in commit-style summaries).
_KNOWN_STATES = (
    "idea",
    "drafting",
    "ideagate",
    "exploring",
    "midgate",
    "evaluated",
    "parked",
    "draftplan",
    "review",
    "plangate",
    "rework",
    "accepted",
    "inprogress",
    "blocked",
    "implemented",
    "superseded",
    "abandoned",
)
# Matches a typical lifecycle line: `YYYY-MM-DD — <stage>/<state>_ — context`
# (em-dash u2014 or plain hyphen separator). Captures (date, stage, state).
_LIFECYCLE_LINE_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2})\s*[—\-]+\s*"
    r"(?:`?(research|implement|archived)/)?"
    rf"({'|'.join(_KNOWN_STATES)})_"
)


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


def _parse_lifecycle_transitions(path: Path) -> list[tuple[date, str]]:
    """Return [(date, state), ...] for every parseable line under ## Lifecycle.

    Lines that mention a state (`research/exploring_`, `exploring_`, etc.) are
    extracted; lines without a recognisable state are skipped. Order preserved.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    in_section = False
    out: list[tuple[date, str]] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            in_section = stripped.lower() == "## lifecycle"
            continue
        if not in_section:
            continue
        m = _LIFECYCLE_LINE_RE.search(line)
        if not m:
            continue
        try:
            d = date.fromisoformat(m.group(1))
        except ValueError:
            continue
        state = m.group(3)
        out.append((d, state))
    return out


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


def compute_trends(docs: list[Doc]) -> dict:
    """Aggregate avg-days-per-state + throughput across the whole pipeline.

    Same-state lifecycle entries (e.g. multiple rework loops while still in
    `drafting_`) are compressed into a single "visit" so iterative
    self-improvements don't pollute the average. Only completed visits
    (followed by a state change) contribute to the average — the doc's
    current state is treated as in-progress and excluded. Throughput counts
    docs reaching implemented_ within the last 30 / 90 days based on their
    final lifecycle line.
    """
    per_state_durations: dict[str, list[int]] = {}
    for doc in docs:
        transitions = _parse_lifecycle_transitions(doc.path)
        # Compress consecutive same-state entries into one visit per state.
        visits: list[tuple[date, str]] = []
        for d, state in transitions:
            if visits and visits[-1][1] == state:
                continue
            visits.append((d, state))
        # Duration for visit i = visit[i+1].date - visit[i].date.
        # Last visit is in-progress — excluded.
        for i in range(len(visits) - 1):
            cur_date, cur_state = visits[i]
            next_date, _ = visits[i + 1]
            days = (next_date - cur_date).days
            if days >= 0:
                per_state_durations.setdefault(cur_state, []).append(days)

    avg_per_state: dict[str, float] = {
        state: sum(days_list) / len(days_list)
        for state, days_list in per_state_durations.items()
        if days_list
    }
    sample_size: dict[str, int] = {state: len(d) for state, d in per_state_durations.items()}

    # Slowest stage among non-gate work states.
    work_states = {s for stage_list in STAGE_STATES.values() for s in stage_list}
    work_states -= set(GATE_STATES)
    slowest_state = None
    slowest_avg = 0.0
    for state, avg in avg_per_state.items():
        if state in work_states and avg > slowest_avg:
            slowest_avg = avg
            slowest_state = state

    today = date.today()
    throughput_30 = 0
    throughput_90 = 0
    for doc in docs:
        if doc.stage != "archived" or doc.state != "implemented":
            continue
        if doc.last_lifecycle is None:
            continue
        age = (today - doc.last_lifecycle).days
        if age <= 30:
            throughput_30 += 1
        if age <= 90:
            throughput_90 += 1

    return {
        "avg_per_state": avg_per_state,
        "sample_size": sample_size,
        "slowest_state": slowest_state,
        "slowest_avg": slowest_avg,
        "throughput_30": throughput_30,
        "throughput_90": throughput_90,
    }


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


def print_trends(trends: dict) -> None:
    avg = trends["avg_per_state"]
    if not avg:
        print("Trends — no completed transitions yet (no history to average).")
        return
    print("Trends (avg days per state, completed transitions only)")
    samples = trends["sample_size"]
    for stage, states in STAGE_STATES.items():
        chunks = []
        for state in states:
            if state in avg:
                chunks.append(f"{state} {avg[state]:.1f}d (n={samples[state]})")
        if chunks:
            print(f"  {stage:<10} " + " · ".join(chunks))
    if trends["slowest_state"]:
        print(
            f"  Slowest work state: {trends['slowest_state']} "
            f"({trends['slowest_avg']:.1f}d avg) — bottleneck candidate"
        )
    print(
        f"  Throughput: {trends['throughput_30']} docs -> implemented_ in last 30 days, "
        f"{trends['throughput_90']} in last 90"
    )


def print_report(
    docs: list[Doc],
    prs: list[dict] | None,
    pr_checked: bool,
    show_trends: bool = False,
) -> None:
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

    if show_trends:
        print_trends(compute_trends(docs))
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
    parser.add_argument(
        "--trends",
        action="store_true",
        help="add avg-days-per-stage trends + throughput",
    )
    args = parser.parse_args()

    docs = scan()

    if args.gates:
        print_gates(docs)
        return 0

    prs = None if args.no_pr else fetch_routine_prs()
    print_report(docs, prs, pr_checked=not args.no_pr, show_trends=args.trends)
    return 0


if __name__ == "__main__":
    sys.exit(main())
