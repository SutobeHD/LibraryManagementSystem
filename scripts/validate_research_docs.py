#!/usr/bin/env python3
"""
Validate every doc under docs/research/{research,implement,archived}/.

Checks (per doc):
- Filename matches `<state>_<slug>.md` and the state is a known pipeline state.
- The folder matches the state (research/ vs implement/ vs archived/).
- Frontmatter present with required keys: slug, title, created.
- Frontmatter's slug matches the filename slug (no rename drift).
- `## Original Idea` section exists.
- `## Lifecycle` section exists and has at least one parseable line.
- Lifecycle's latest state matches the filename state (no stale file rename).

Usage:
    python scripts/validate_research_docs.py             # all docs
    python scripts/validate_research_docs.py FILE [...]  # specific files (for pre-commit)
    python scripts/validate_research_docs.py --quiet     # one-line summary only

Exit 0 = all valid; 1 = at least one defect (lists each).

Stdlib only.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RESEARCH_DIR = REPO_ROOT / "docs" / "research"

# Mirrors pipeline_status._KNOWN_STATES — kept in sync by hand. The script
# is intentionally stdlib-only so it works in pre-commit without a sys.path
# dance. Drift between the two lists is caught by --check in CI.
STATES_PER_STAGE: dict[str, set[str]] = {
    "research": {"idea", "drafting", "ideagate", "exploring", "midgate", "evaluated", "parked"},
    "implement": {"draftplan", "review", "plangate", "rework", "accepted", "inprogress", "blocked"},
    "archived": {"implemented", "superseded", "abandoned"},
}
REQUIRED_FRONTMATTER = ("slug", "title", "created")

_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
_LIFECYCLE_LINE_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2})\s*[—\-]+\s*"
    r"(?:`?(research|implement|archived)/)?"
    r"(idea|drafting|ideagate|exploring|midgate|evaluated|parked|"
    r"draftplan|review|plangate|rework|accepted|inprogress|blocked|"
    r"implemented|superseded|abandoned|watchdog)_"
)


def parse_frontmatter(text: str) -> dict[str, str]:
    """Parse the YAML-ish frontmatter at the top of a doc. Returns {} if absent."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 4)
    if end == -1:
        return {}
    block = text[4:end]
    out: dict[str, str] = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if key and not key.startswith("#"):
            out[key] = value
    return out


def section_exists(text: str, heading: str) -> bool:
    """True if `## <heading>` (case-insensitive, after stripping the optional `(verbatim …)` tail) is present as a top-level heading."""
    heading_lc = heading.lower()
    for line in text.splitlines():
        s = line.strip().lower()
        if s.startswith("## ") and (s[3:].startswith(heading_lc)):
            return True
    return False


def latest_lifecycle_state(text: str) -> str | None:
    """Return the state in the latest parseable line under ## Lifecycle, or None."""
    in_section = False
    found: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            in_section = stripped.lower() == "## lifecycle"
            continue
        if not in_section:
            continue
        m = _LIFECYCLE_LINE_RE.search(line)
        if m:
            found = m.group(3)
    return found


def parse_filename(path: Path) -> tuple[str | None, str | None]:
    """Split filename stem into (state, slug). archived/ docs have an extra
    `_YYYY-MM-DD` suffix on the slug — strip it for the comparison."""
    stem = path.stem
    if "_" not in stem:
        return None, None
    state, slug = stem.split("_", 1)
    # Strip trailing `_YYYY-MM-DD` suffix on archived docs.
    if path.parent.name == "archived":
        slug = re.sub(r"_\d{4}-\d{2}-\d{2}$", "", slug)
    return state, slug


def validate(path: Path) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) for the doc at `path`. Empty lists = valid.

    - **Errors** block CI / pre-commit (structural — file would confuse the
      routines or break pipeline_status.py).
    - **Warnings** print but don't block (style — Original Idea section
      missing on legacy docs predating the multi-agent template).
    """
    errors: list[str] = []
    warnings: list[str] = []
    rel = path.relative_to(REPO_ROOT)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"{rel}: cannot read ({exc})"], []

    state, slug = parse_filename(path)
    if not state or not slug:
        errors.append(f"{rel}: filename does not match <state>_<slug>.md")
        return errors, warnings

    stage = path.parent.name
    if stage not in STATES_PER_STAGE:
        errors.append(f"{rel}: parent folder '{stage}/' is not a pipeline stage")
        return errors, warnings

    if state not in STATES_PER_STAGE[stage]:
        errors.append(
            f"{rel}: state '{state}_' is not valid in '{stage}/' "
            f"(valid: {', '.join(sorted(STATES_PER_STAGE[stage]))})"
        )

    fm = parse_frontmatter(text)
    for key in REQUIRED_FRONTMATTER:
        if key not in fm:
            warnings.append(f"{rel}: frontmatter missing recommended key '{key}'")
    if "slug" in fm and fm["slug"] != slug:
        errors.append(
            f"{rel}: frontmatter slug '{fm['slug']}' does not match filename slug '{slug}'"
        )

    if not section_exists(text, "Original Idea"):
        warnings.append(
            f"{rel}: missing '## Original Idea' section "
            f"(required for docs created on/after 2026-05-28 — legacy docs may omit)"
        )
    if not section_exists(text, "Lifecycle"):
        errors.append(f"{rel}: missing '## Lifecycle' section")
        return errors, warnings

    last_state = latest_lifecycle_state(text)
    if last_state is None:
        errors.append(f"{rel}: ## Lifecycle section has no parseable dated entry")
        return errors, warnings
    # Lifecycle "watchdog" + "implemented" line both can be latest on an
    # archived doc — accept either for archived/implemented_ docs.
    if state == "implemented" and last_state in ("implemented", "watchdog"):
        return errors, warnings
    if last_state != state:
        errors.append(
            f"{rel}: latest Lifecycle state '{last_state}_' does not match "
            f"filename state '{state}_' (rename drift — `git mv` without a "
            f"Lifecycle line?)"
        )

    return errors, warnings


def collect_docs(paths: list[Path] | None) -> list[Path]:
    """Either the explicit list (filtered to .md under docs/research/) or
    every doc in the three stage folders."""
    if paths:
        out: list[Path] = []
        for p in paths:
            ap = p.resolve()
            if (
                ap.suffix == ".md"
                and RESEARCH_DIR in ap.parents
                and ap.parent.name in STATES_PER_STAGE
                and "_" in ap.stem
            ):
                out.append(ap)
        return out
    out = []
    for stage in STATES_PER_STAGE:
        folder = RESEARCH_DIR / stage
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.md")):
            if "_" in path.stem:
                out.append(path)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate research-pipeline docs.")
    parser.add_argument("paths", nargs="*", type=Path, help="optional specific files")
    parser.add_argument("--quiet", action="store_true", help="one-line summary only")
    args = parser.parse_args()

    docs = collect_docs(args.paths or None)
    if not docs:
        if args.paths:
            # Pre-commit gave us non-research files — silently skip, exit 0.
            return 0
        print("No research docs found.", file=sys.stderr)
        return 0

    all_errors: list[str] = []
    all_warnings: list[str] = []
    for path in docs:
        errors, warnings = validate(path)
        all_errors.extend(errors)
        all_warnings.extend(warnings)

    if args.quiet:
        if all_errors:
            print(
                f"FAIL — {len(all_errors)} error(s), {len(all_warnings)} warning(s) "
                f"across {len(docs)} doc(s)."
            )
            return 1
        print(f"OK — {len(docs)} doc(s) valid. {len(all_warnings)} warning(s).")
        return 0

    if all_warnings:
        print("WARNINGS:", file=sys.stderr)
        for w in all_warnings:
            print(f"  {w}", file=sys.stderr)
    if all_errors:
        print("\nERRORS:", file=sys.stderr)
        for e in all_errors:
            print(f"  {e}", file=sys.stderr)
        print(
            f"\nFAIL — {len(all_errors)} error(s), {len(all_warnings)} warning(s) "
            f"across {len(docs)} doc(s).",
            file=sys.stderr,
        )
        return 1

    print(f"OK — {len(docs)} doc(s) valid. {len(all_warnings)} warning(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
