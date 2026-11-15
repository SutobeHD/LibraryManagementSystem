---
description: Feature map — who builds what where; open the mindmap or look up one feature before touching it
argument-hint: "[<id|path|text> | roadmap [<version>] | testen]   empty = construction sites + mindmap"
allowed-tools: Bash
---

Show the feature map (`docs/features/*.toml` + live git overlay). Rules: `.claude/rules/feature-map.md`.

## Process

1. **With an argument** — look up that feature, file or text:
   ```bash
   python scripts/feature_map.py --who "$ARGUMENTS"
   ```
   Print the output verbatim. If it reports `!! Mehrere Baustellen` or active work on another branch/worktree, say in one line which branch/worktree and that parallel work there needs the user's call.

2. **Without an argument** — overview + mindmap:
   ```bash
   python scripts/feature_map.py --active
   python scripts/feature_map.py --html --open
   ```
   Print the `--active` output, then the mindmap path. Add one line per real risk you see in it: work that was never pushed, a detached HEAD holding commits, two live sites on the same feature.

3. **`testen` / `getestet <id...>`** as argument — the user's test to-do list, or a confirmed test:
   ```bash
   python scripts/feature_map.py --list --phase testen
   python scripts/feature_map.py --mark getestet <id> [<id> ...]
   ```
   Commit a `--mark` change right away (`docs(docs): mark <id> tested in the feature map`).

4. **`roadmap [<version>]`** as argument — versions plan (0.1 Alpha … 1.0, Später) with progress:
   ```bash
   python scripts/feature_map.py --roadmap                  # all versions
   python scripts/feature_map.py --roadmap --release 0.1    # one version, features by tag
   ```
   Print it verbatim. Then one line: what makes the current version testbar next (which PR to merge, what to build).

Keep it terse — status glance, not a report.
