---
description: Reject the single research-pipeline gate (approvalgate_) — send the plan back with a reason
argument-hint: "<slug> \"<reason>\"  e.g.  metadata-name-fixer \"scope drifted past the original idea\""
allowed-tools: Read, Edit, Bash, Glob
---

Reject a research doc at the Approval Gate and send it back for rework. Slug + reason: $ARGUMENTS

The Approval Gate is the **single** user sign-off of the multi-agent research pipeline (`docs/research/README.md` → "The One Gate"). A reject routes the doc to `rework_`; `research-plan` redoes the plan — and the mockup/summary — with your feedback.

**A reason is required** — the routine needs it to know what to fix. No reason → stop and ask for one.

## Process

1. **Locate the gate doc.** Glob `docs/research/implement/approvalgate_<slug>.md`.
   - None → stop, report "no approval waiting for `<slug>`".
   - More than one match → stop, report the conflict.

2. **Write the reason** into `## Review` → under "**Rework reasons:**" (append a bullet, before the move):
   ```
   - <today YYYY-MM-DD> USER REJECT — <reason>
   ```

3. **`git mv`** `implement/approvalgate_<slug>.md` → `implement/rework_<slug>.md`.

4. **Append a `## Lifecycle` line:**
   ```
   <today YYYY-MM-DD> — implement/rework_ — rejected by user: <short reason>
   ```

5. **Update `docs/research/_INDEX.md`:** move the line from `### approvalgate` to `### rework`.

6. **Bump `last_updated`** to today.

7. **Commit + push:**
   ```bash
   git add <old-path> <new-path> docs/research/_INDEX.md
   git commit -m "docs(research): reject <slug> → rework_"
   git push
   ```

8. **Report (2 lines):** transition done (`approvalgate_` → `rework_`); `research-plan` reworks it at next cron (13:00 Berlin), then it returns to `approvalgate_`.

## Deeper reject — research was wrong

If the problem is the **research itself** (wrong findings, a missing option), not just the plan: say so in the reason, then `git mv` to `research/drafting_<slug>.md` (re-draft) or `research/exploring_<slug>.md` (re-research) instead of `rework_`, and note the reset in the Lifecycle line. Default is `rework_` (plan-level fix — cheapest, most common).

## Don'ts

- Don't reject without a concrete reason — the routine can't act on a blank.
- Don't edit `## Original Idea`.
- Don't delete prior review history — append.
