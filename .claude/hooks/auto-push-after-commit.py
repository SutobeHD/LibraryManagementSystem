#!/usr/bin/env python3
"""
PostToolUse hook — auto-push to origin after a successful `git commit`.

Wired in `.claude/settings.json` → hooks.PostToolUse[matcher="Bash"].
Fires for every Bash tool call but exits early unless the command was
a `git commit`. Defense-in-depth pairing with the soft-rule in
`.claude/rules/commit-and-git.md` ("Push Policy — autonomous + auto").

Behaviour:
- Commit succeeded → fetch + check drift → `git push origin <branch>`.
- Local is behind origin → abort with a stderr note. User pulls manually.
  Hook never rebases or merges autonomously (would break the Revertable
  rule).
- Commit message contains `[skip-push]` / `[no-push]` → skip silently.
- Detached HEAD → skip (no upstream branch).
- Push failure → log to stderr but never revert the commit.

Exit codes (Claude Code convention):
- 0 → success / non-applicable / soft-skip
- 1 → soft error (drift, push failed) — visible to user, non-blocking
- 2 → hard block — never used here; auto-push failures must not break
      the agent's commit flow.

Bypass for the next commit: include `[skip-push]` or `[no-push]` in
the commit message body. The hook reads HEAD's message and respects it.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys


def _run(cmd: list[str], timeout: int = 30) -> tuple[int, str, str]:
    """Run a subprocess. Return (rc, stdout, stderr)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s running: {' '.join(cmd)}"
    except FileNotFoundError:
        return 127, "", f"executable not found: {cmd[0]}"


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    tool_input = payload.get("tool_input") or {}
    cmd = (tool_input.get("command") or "").strip()

    # Match `git commit ...` — not `git commit-tree`, not other git verbs.
    if not re.match(r"^git\s+commit(\s|$)", cmd):
        return 0

    # The amend variant would re-push history; agent shouldn't reach here
    # because it's in the deny list of settings.json, but guard anyway.
    if "--amend" in cmd:
        return 0

    # Verify the tool call itself returned 0. If `tool_response` carries an
    # exit code, respect it; otherwise assume the commit landed (which it
    # almost always did, since we're PostToolUse).
    tool_response = payload.get("tool_response")
    if isinstance(tool_response, dict):
        exit_code = tool_response.get("exit_code")
        if exit_code is not None and exit_code != 0:
            return 0

    # Read HEAD's commit message — that's the commit we'd be pushing.
    rc, last_msg, _ = _run(["git", "log", "-1", "--pretty=%B"])
    if rc != 0:
        # No commits at all? Bail.
        return 0

    # Honour the explicit opt-out.
    if re.search(r"\[(skip|no)[-_]push\]", last_msg, re.IGNORECASE):
        print("[hook] auto-push skipped: commit message opts out", file=sys.stderr)
        return 0

    # Current branch (skip on detached HEAD).
    rc, branch_out, _ = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    if rc != 0:
        return 0
    branch = branch_out.strip()
    if branch == "HEAD":
        print("[hook] detached HEAD — skipping auto-push", file=sys.stderr)
        return 0

    # Pre-push hygiene — refresh tracking refs, surface drift.
    rc, _, _ = _run(["git", "fetch", "--quiet"], timeout=15)
    if rc != 0:
        # Network/auth failure on fetch. Don't push blindly without knowing
        # the remote state; will retry on next commit.
        print("[hook] git fetch failed — skipping auto-push (will retry next commit)", file=sys.stderr)
        return 1

    # Read ahead/behind.
    rc, status, _ = _run(["git", "status", "-sb"])
    if rc == 0 and status:
        first_line = status.splitlines()[0]
        m = re.search(r"behind\s+(\d+)", first_line)
        if m:
            n = m.group(1)
            print(
                f"[hook] push aborted: local is {n} commit(s) behind origin/{branch}. "
                f"Pull --ff-only first, then push manually.",
                file=sys.stderr,
            )
            return 1

    # Push.
    rc, out, err = _run(["git", "push", "origin", branch], timeout=60)
    if rc != 0:
        # GitHub rejection (e.g. GH007 private-email), network, auth — never silent.
        print(f"[hook] git push origin {branch} failed (rc={rc}):", file=sys.stderr)
        for line in (out + err).splitlines()[-6:]:
            print(f"[hook]   {line}", file=sys.stderr)
        return 1

    # Success — surface the canonical "a..b main -> main" line.
    output_lines = (err + out).strip().splitlines()
    canonical = next(
        (ln for ln in reversed(output_lines) if "->" in ln),
        f"pushed to origin/{branch}",
    )
    print(f"[hook] auto-pushed: {canonical.strip()}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
