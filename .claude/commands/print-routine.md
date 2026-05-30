---
description: Print a claude.ai/code routine prompt (paste-ready) — extracts the block below the `---` divider
argument-hint: "<name>|--all|--list|--check   e.g.  research-draft  ·  --all"
allowed-tools: Bash
---

Print a routine prompt from `docs/research/routines/<name>.md` — the bit below the `---` divider, copy-paste-ready for the claude.ai/code routine.

## Process

1. Run:
   ```bash
   python scripts/print_routine.py $ARGUMENTS
   ```

2. If `$ARGUMENTS` is `--list` → the script lists every routine + cron. Print verbatim.

3. If `$ARGUMENTS` is `--check` → the script verifies every file has a `---` divider. Print result + exit code.

4. If `$ARGUMENTS` is a routine name (e.g. `research-draft`) → the script prints the prompt to stdout.
   - In the chat reply, wrap the prompt in a fenced code block (` ```text ` … ` ``` `) so the user can copy it with one click.
   - Below the block, add a one-liner reminder: "Paste into the matching routine on https://claude.ai/code/routines (cron + permissions in `docs/research/routines/README.md`)."

5. If `$ARGUMENTS` is `--all` → the script prints every routine separated by `===`. Pass the output through verbatim.

6. If the script exits non-zero → surface its stderr in your reply (and don't try to recover — usually a typo'd routine name).

## Don'ts

- Don't paste prompts directly into the chat without a code block — the user wants to copy them with one click.
- Don't edit the prompt before printing — `docs/research/routines/<name>.md` is the source of truth.
