#!/usr/bin/env python3
"""
PostToolUse hook — auto-format files after Edit/Write tool calls.

Wired in `.claude/settings.json` → hooks.PostToolUse[matcher="Edit|Write"].

Behaviour per file type:
- `app/**/*.py`, `tests/**/*.py`  → ruff format + ruff check --fix
- `frontend/src/**/*.{js,jsx}`     → npx prettier --write
- `src-tauri/src/**/*.rs`          → cargo fmt --manifest-path src-tauri/Cargo.toml

Silent on success. Prints a one-line "[hook] ..." note on failure so the
agent sees why and can decide whether to fix manually.

Exit codes:
- 0  → success / non-applicable file
- 1  → soft error (formatter not on PATH, tool stuck) — non-blocking
- 2  → hard block (never used here; we don't want auto-format failures to
       break the agent's commit flow)
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _which(cmd: str) -> str | None:
    """Cross-platform `which`."""
    found = shutil.which(cmd)
    if found:
        return found
    # Windows: also try .exe / .cmd variants
    for ext in (".cmd", ".exe", ".bat"):
        found = shutil.which(cmd + ext)
        if found:
            return found
    return None


def _run(cmd: list[str], cwd: Path) -> tuple[int, str]:
    """Run a subprocess with a sane timeout, return (rc, combined_output)."""
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode, (result.stdout + result.stderr)
    except subprocess.TimeoutExpired:
        return 124, f"timeout after 30s running: {' '.join(cmd)}"
    except FileNotFoundError:
        return 127, f"executable not found: {cmd[0]}"


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        # Nothing useful to do without a payload.
        return 0

    tool_input = payload.get("tool_input") or {}
    file_path = tool_input.get("file_path")
    if not file_path:
        return 0

    repo_root = Path(payload.get("cwd") or os.getcwd())
    try:
        rel = Path(file_path).resolve().relative_to(repo_root.resolve()).as_posix()
    except (ValueError, OSError):
        # File outside the repo or unresolvable — skip.
        return 0

    rc = 0
    out = ""

    # ── Python ────────────────────────────────────────────────────────────
    if rel.startswith(("app/", "tests/")) and rel.endswith(".py"):
        # Skip dev/debug scripts that are excluded in pyproject.toml
        bad_prefixes = (
            "app/brute_force_",
            "app/inspect_",
            "app/debug_",
            "app/diag_",
            "app/check_",
            "app/verify_",
            "app/find_",
            "app/fix_",
            "app/calibrate_",
            "app/final_",
            "app/mass_verify",
            "app/analysis_inspector.py",
        )
        if any(rel.startswith(p) for p in bad_prefixes):
            return 0

        if _which("ruff"):
            rc, out = _run(["ruff", "format", rel], repo_root)
            if rc == 0:
                rc, out = _run(["ruff", "check", "--fix", "--quiet", rel], repo_root)
        else:
            print("[hook] ruff not on PATH — skipping Python format", file=sys.stderr)
            return 1

    # ── Frontend JS/JSX ───────────────────────────────────────────────────
    elif rel.startswith("frontend/src/") and rel.endswith((".js", ".jsx", ".mjs", ".cjs")):
        # Skip test resolver helpers — they're explicitly hand-tuned
        if "dawReducer.test.resolver" in rel:
            return 0

        if _which("npx"):
            rc, out = _run(["npx", "--no-install", "prettier", "--write", rel], repo_root)
            if rc == 0 and _which("npx"):
                # ESLint --fix is best-effort, never blocks
                _run(["npx", "--no-install", "eslint", "--fix", rel], repo_root)
        else:
            print("[hook] npx not on PATH — skipping frontend format", file=sys.stderr)
            return 1

    # ── Rust ──────────────────────────────────────────────────────────────
    elif rel.startswith("src-tauri/src/") and rel.endswith(".rs"):
        if _which("cargo"):
            rc, out = _run(
                ["cargo", "fmt", "--manifest-path", "src-tauri/Cargo.toml"],
                repo_root,
            )
        else:
            print("[hook] cargo not on PATH — skipping Rust format", file=sys.stderr)
            return 1

    # Anything else (markdown, json, configs) → no auto-format
    else:
        return 0

    if rc != 0:
        # Non-blocking: print to stderr so the agent sees it but the edit
        # is not reverted. The agent can decide whether to fix manually.
        snippet = (out or "").strip().splitlines()[-3:]
        print(f"[hook] format failed for {rel} (rc={rc})", file=sys.stderr)
        for line in snippet:
            print(f"[hook]   {line}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
