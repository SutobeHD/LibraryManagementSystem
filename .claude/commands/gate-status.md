---
description: Show the current pipeline state of one research doc (state, gate, last activity, next step)
argument-hint: "<slug>   e.g.  metadata-name-fixer"
allowed-tools: Read, Glob, Bash
---

Show the current pipeline state of a single research doc: $ARGUMENTS

## Process

1. **Locate the doc.** Glob for the slug under every stage folder:
   ```
   docs/research/research/*<slug>*.md
   docs/research/implement/*<slug>*.md
   docs/research/archived/*<slug>*.md
   ```
   - Exactly one match → continue.
   - Zero matches → reply "No doc for `<slug>`. Run `/pipeline` to see all docs, or `/research-new <slug>` to scaffold one."
   - Multiple matches (e.g. archived + active with the same slug-stem) → reply with the list and ask which one.

2. **Parse the state** from the filename prefix (`<state>_<slug>.md`).

3. **Read the latest `## Lifecycle` line** — date + state + context.

4. **Build the reply** — fixed table format:

   ```
   ## <slug>

   - **File:** `docs/research/<stage>/<state>_<slug>.md`
   - **State:** `<state>_` (<work-state | APPROVAL GATE | archived-implemented/...>)
   - **Last activity:** YYYY-MM-DD — <one-line context from the Lifecycle entry>
   - **Days in this state:** N (from oldest Lifecycle line with this state)

   ### Next step

   <one of:>
   - Routine `research-draft` will pick this up at next cron (05:00 Berlin)
   - Routine `research-explore` will pick this up at next cron (06:00 + 14:00 Berlin)
   - Routine `research-plan` will pick this up at next cron (13:00 Berlin)
   - Routine `research-implement` will pick this up at next cron (03:00 + 15:00 Berlin)
   - **Awaiting the Approval Gate — your single sign-off.** Read `## Approval Summary` + `## Mockup`, then `/approve <slug>` (→ accepted_) · `/reject <slug> "<reason>"` (→ rework_)
   - Paused (`parked_` / `blocked_`) — routines skip it. Move it back to a work state to resume.
   - Archived — no further action.

   ### Open PRs (test + merge)

   <if any routine/<slug>-task-* PR is open:>
   - PR #NN  CI <status>  <title>  — test locally, then merge
   <else: "None.">
   ```

5. State→next-routine mapping:

   | State | Next |
   |---|---|
   | `idea_` | (user) — fill `## Original Idea` + `git mv` to `drafting_` |
   | `drafting_` | `research-draft` |
   | `exploring_` | `research-explore` |
   | `evaluated_`, `rework_` | `research-plan` |
   | `draftplan_`, `review_` | `research-plan` (still working) |
   | `approvalgate_` | **APPROVAL GATE** — your single sign-off |
   | `accepted_`, `inprogress_` | `research-implement` |
   | `blocked_`, `parked_` | paused |
   | `implemented_`, `superseded_`, `abandoned_` | terminal |

## Don'ts

- Don't run `/approve` automatically — print the command; the user decides.
- Don't include the full doc body — only the Lifecycle summary line.
- Don't guess routine schedules — copy from the table above.
