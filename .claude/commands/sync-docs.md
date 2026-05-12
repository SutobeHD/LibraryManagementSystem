---
description: Sync docs/FILE_MAP.md + index docs against the current codebase
argument-hint: "[optional: subsystem to focus on, e.g. backend, frontend, rust]"
allowed-tools: Read, Edit, Glob, Grep, Bash, Agent
---

Reconcile `docs/FILE_MAP.md`, `docs/backend-index.md`, `docs/frontend-index.md`, and `docs/rust-index.md` against the actual code.

Scope: $ARGUMENTS (default: all four docs)

Process:
1. List the files under the relevant directory (`app/`, `frontend/src/`, `src-tauri/src/`, or all).
2. Diff against the corresponding doc table rows.
3. For each file present in code but missing from the doc, propose a one-line description (read the file header / docstring / module-level comments first — don't invent purpose).
4. For each row present in the doc but missing from code, mark it stale.
5. Show the diff before editing. Wait for user confirmation unless the change is purely additive (new files) AND fewer than 5 rows.

Use the `doc-syncer` subagent for the heavy reading — it keeps the main context clean. After edits, run `git diff docs/` and summarise.
