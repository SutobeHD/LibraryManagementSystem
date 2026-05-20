---
description: Reject a research-pipeline gate (A/B/C) — send the doc back with a reason
argument-hint: "<slug> \"<reason>\"  e.g.  metadata-name-fixer \"scope drifted past the original idea\""
allowed-tools: Read, Edit, Bash, Glob
---

Reject a research gate and send the doc back for rework. Slug + reason: $ARGUMENTS

Gates are the user sign-off points of the multi-agent research pipeline (`docs/research/README.md` → "The 4 Gates"). A reject routes the doc back so the routines redo that stage with your feedback.

**A reason is required** — the routines need it to know what to fix. No reason → stop and ask for one.

## Process

1. **Locate the gate doc.** Glob for the slug in the three gate states:
   - `docs/research/research/ideagate_<slug>.md` — GATE A
   - `docs/research/research/midgate_<slug>.md` — GATE B
   - `docs/research/implement/plangate_<slug>.md` — GATE C

   Exactly one must exist. None → stop, report "no gate doc for `<slug>`".

2. **Determine the transition + where the reason goes:**
   | From | Gate | To | Reason written to |
   |------|------|----|----|
   | `ideagate_` | A | `research/drafting_<slug>.md` | `## Idea Verification` — new `### <date> — USER REJECT (GATE A)` entry |
   | `midgate_` | B | `research/exploring_<slug>.md` | `## Mid-Research Checkpoint` → `### Verdict` entry |
   | `plangate_` | C | `implement/rework_<slug>.md` | `## Review` → under "**Rework reasons:**" |

3. **Write the reason** into the section above, before the move:
   - GATE A → append to `## Idea Verification`:
     ```
     ### <today YYYY-MM-DD> — USER REJECT (GATE A)
     - <reason>
     ```
   - GATE B → append to `## Mid-Research Checkpoint`:
     ```
     ### Verdict — <today YYYY-MM-DD> (user)
     - Reject — research these gaps: <reason>
     ```
   - GATE C → add the reason as a bullet under `## Review` → `**Rework reasons:**`.

4. **`git mv`** the file old → new path.

5. **Append a `## Lifecycle` line:**
   ```
   <today YYYY-MM-DD> — <stage>/<new-state>_ — GATE <X> rejected by user: <short reason>
   ```

6. **Update `docs/research/_INDEX.md`:** move the line to the new state's section; fix the link path.

7. **Bump `last_updated`** to today.

8. **Commit + push:**
   ```bash
   git add <old-path> <new-path> docs/research/_INDEX.md
   git commit -m "docs(research): GATE <X> reject <slug> → <new-state>_"
   git push
   ```

9. **Report (2 lines):** transition done; which routine reworks it (`research-draft` for A, `research-explore` for B, `research-plan` for C).

## Don'ts

- Don't reject without a concrete reason — the routine can't act on a blank.
- Don't edit `## Original Idea`.
- Don't delete prior verification/review history — append.
