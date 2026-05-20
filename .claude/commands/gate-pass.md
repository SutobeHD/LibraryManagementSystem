---
description: Pass a research-pipeline gate (A/B/C) — advance the doc to the next work state
argument-hint: "<slug> [comment]  e.g.  metadata-name-fixer 'direction looks right'"
allowed-tools: Read, Edit, Bash, Glob
---

Pass a research gate. Slug + optional comment: $ARGUMENTS

Gates are the user sign-off points of the multi-agent research pipeline (`docs/research/README.md` → "The 4 Gates"). This command advances a `*gate_` doc to the next work state so the routines pick it up again.

## Process

1. **Locate the gate doc.** Glob for the slug in the three gate states:
   - `docs/research/research/ideagate_<slug>.md` — GATE A
   - `docs/research/research/midgate_<slug>.md` — GATE B
   - `docs/research/implement/plangate_<slug>.md` — GATE C

   Exactly one must exist. None → stop, report "no gate doc for `<slug>` — run `/pipeline` to see open gates". More than one → stop, report the conflict.

2. **Determine the transition:**
   | From | Gate | To |
   |------|------|----|
   | `ideagate_` | A | `research/exploring_<slug>.md` |
   | `midgate_` | B | `research/exploring_<slug>.md` |
   | `plangate_` | C | `implement/accepted_<slug>.md` |

3. **GATE B only — write the Verdict.** Before the move, edit `## Mid-Research Checkpoint` → add:
   ```
   ### Verdict — <today YYYY-MM-DD> (user)
   - Pass — <comment, or "direction confirmed, proceed to wave 2">
   ```
   This block is what tells `research-explore` to run wave 2. Without it the routine reruns wave 1.

4. **`git mv`** the file old → new path.

5. **Append a `## Lifecycle` line:**
   ```
   <today YYYY-MM-DD> — <stage>/<new-state>_ — GATE <X> passed by user<; comment if given>
   ```

6. **Update `docs/research/_INDEX.md`:** move the doc's line from the gate section to the new state's section; fix the link path if needed.

7. **Bump `last_updated`** in frontmatter to today.

8. **Commit + push:**
   ```bash
   git add <old-path> <new-path> docs/research/_INDEX.md
   git commit -m "docs(research): GATE <X> pass <slug> → <new-state>_"
   git push
   ```
   (The new-path is staged because `git mv` then content edits leave it modified.)

9. **Report (2 lines):** transition done (`<old>` → `<new>`); next routine that will pick it up (`research-explore` for A/B, `research-implement` for C).

## Don'ts

- Don't pass a gate that isn't open — verify the doc exists first.
- Don't edit `## Original Idea`.
- Don't skip the GATE B Verdict block — the pipeline depends on it.
