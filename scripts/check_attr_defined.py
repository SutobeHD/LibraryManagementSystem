#!/usr/bin/env python3
"""Fail if mypy reports any `attr-defined` error in app/.

Full mypy is still gradual (~148 errors), so it cannot gate a commit. This
one error code can: it means "this attribute does not exist on this object",
which at runtime is an AttributeError. Six such bugs shipped to `main` while
the CI mypy step ran with `|| true`:

    db.get_tracks()                 -> HTTP 500 on duplicates merge
    db.save_track_cues()            -> HTTP 500 on every cue save
    db.save_track_beatgrid()        -> HTTP 500 on every beatgrid save
    db.save_xml() / db.load_xml()   -> HTTP 500 on XML upload + export
    db.get_unanalyzed_track_ids()   -> HTTP 500 on batch analysis

mypy had flagged all of them. Used by .pre-commit-config.yaml and mirrored by
the "Type-check — no missing attributes" step in .github/workflows/ci.yml.

KNOWN LIMIT: pyproject.toml sets `check_untyped_defs = false`, so mypy does
not look inside functions that carry no annotations at all. A bad attribute
in an unannotated `def foo():` slips through this gate. It tightens
automatically as type-hint coverage grows — which is the point of requiring
hints on new code.

Exit 0 = clean. Exit 1 = at least one attr-defined error (printed).
Exit 0 with a warning if mypy is not installed — a missing dev tool should
not block a commit; CI is the backstop.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run_mypy(platform: str | None) -> str | None:
    """mypy output for one target platform, or None if mypy is unavailable."""
    cmd = [sys.executable, "-m", "mypy", "app/", "--no-error-summary"]
    if platform:
        cmd += ["--platform", platform]
    try:
        proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, timeout=300)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    out = proc.stdout.decode("utf-8", "replace") + proc.stderr.decode("utf-8", "replace")
    return None if "No module named mypy" in out else out


def main() -> int:
    # Both the native platform AND linux: ctypes.windll type-checks fine on
    # Windows and does not exist at all on linux, so a Windows-only run passes
    # while CI (ubuntu) fails. Checking both catches that before the push.
    targets = ["linux"] if sys.platform.startswith("linux") else [None, "linux"]

    offenders: list[str] = []
    ran = False
    for target in targets:
        output = _run_mypy(target)
        if output is None:
            continue
        ran = True
        label = target or sys.platform
        offenders += [f"[{label}] {ln}" for ln in output.splitlines() if "attr-defined" in ln]

    if not ran:
        print("check_attr_defined: mypy unavailable — skipping (CI still gates this)")
        return 0
    if not offenders:
        return 0

    print("mypy found missing-attribute errors:\n")
    for line in offenders:
        print(f"  {line}")
    # ASCII only: Windows consoles default to cp1252 and mangle em-dashes.
    print(
        "\nEither the attribute is genuinely missing (a runtime AttributeError\n"
        "waiting to happen, so fix it), or it is a third-party stub gap, in\n"
        "which case annotate the line:\n"
        "    # type: ignore[attr-defined]  # <reason>"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
