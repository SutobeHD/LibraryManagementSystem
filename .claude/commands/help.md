---
description: List all available slash commands and subagents for this repo with one-line descriptions
allowed-tools: Bash, Read, Glob
---

Render a discovery view of all repo-local Claude Code capabilities.

## Process

1. **List slash commands** from `.claude/commands/*.md`:
   ```bash
   ls .claude/commands/*.md
   ```
   For each file, read the frontmatter `description` field. Output one line per command:
   ```
   /command-name — description
   ```

2. **List subagents** from `.claude/agents/*.md`:
   ```bash
   ls .claude/agents/*.md
   ```
   For each, read the frontmatter `description` and `name`. Output:
   ```
   <name> — description (tools: <count>)
   ```

3. **List custom rules** from `.claude/rules/*.md` if any:
   ```bash
   ls .claude/rules/*.md 2>/dev/null
   ```
   Show file path + first ~80 chars of body so the user knows what's there.

4. **Print quick reference for hooks and integration files:**
   - `.claude/settings.json` — permission allowlist
   - `.claude/hooks/format-on-edit.py` — PostToolUse auto-format
   - `.pre-commit-config.yaml` — pre-commit hooks (manual install: `pre-commit install`)
   - `scripts/regen_maps.py` — auto-gen MAP.md + MAP_L2.md

5. **Output format — three sections, tables, no fluff:**

```
## Slash commands (N total)
| Command | Description |
|---------|-------------|
| /dev-full | Start backend + frontend dev servers |
...

## Subagents (N total)
| Agent | Description | Tools |
|-------|-------------|-------|
| doc-syncer | ... | Read, Edit, Glob, Grep, Bash |
...

## Rules (N total)
| File | Scope (paths) | First line |
|------|---------------|------------|
| .claude/rules/git-workflow.md | (always-loaded) | ... |
...

## Hook / integration files
- .claude/settings.json — permission allowlist
- .claude/hooks/format-on-edit.py — PostToolUse auto-format on Edit/Write
- .pre-commit-config.yaml — pre-commit hooks (install: `pip install pre-commit && pre-commit install`)
- scripts/regen_maps.py — regenerate docs/MAP.md + MAP_L2.md (slash: /regen-maps)
```

Keep it terse. The point is fast discovery, not exhaustive docs.
