---
description: Feature map — who builds what where; open the mindmap or look up one feature before touching it
argument-hint: "[<id|path|text>]   empty = construction sites + mindmap"
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

Keep it terse — status glance, not a report.
