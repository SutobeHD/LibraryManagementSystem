---
description: Approve the single research-pipeline gate (approvalgate_) — start implementation
argument-hint: "<slug> [comment]  e.g.  metadata-name-fixer 'ship it'"
allowed-tools: Read, Edit, Bash, Glob
---

Approve a research doc for implementation. Slug + optional comment: $ARGUMENTS

The Approval Gate is the **single** user sign-off of the multi-agent research pipeline (`docs/research/README.md` → "The One Gate"). By the time a doc reaches `approvalgate_` it already has a full plan, a `## Approval Summary` (plain-English idea + change list + scope/risk), and a `## Mockup`. Approving advances it to `accepted_`; `research-implement` then builds the Task Queue autonomously — **no new research, no new questions**.

## Process

1. **Locate the gate doc.** Glob `docs/research/implement/approvalgate_<slug>.md`.
   - None → stop, report "no approval waiting for `<slug>` — run `/pipeline` to see open approvals".
   - More than one match → stop, report the conflict.

2. **(Optional) surface the package.** If the user hasn't reviewed it yet, show `## Approval Summary` + `## Mockup` so the yes is informed. For a UI feature, point at `docs/research/mockups/<slug>.html` (open in a browser).

3. **`git mv`** `implement/approvalgate_<slug>.md` → `implement/accepted_<slug>.md`.

4. **Append a `## Lifecycle` line:**
   ```
   <today YYYY-MM-DD> — implement/accepted_ — approved by user<; comment if given>
   ```

5. **Update `docs/research/_INDEX.md`:** move the doc's line from `### approvalgate` to `### accepted`.

6. **Bump `last_updated`** in frontmatter to today.

7. **Commit + push:**
   ```bash
   git add <old-path> <new-path> docs/research/_INDEX.md
   git commit -m "docs(research): approve <slug> → accepted_"
   git push
   ```
   (The new-path is staged because `git mv` then content edits leave it modified.)

8. **Report (2 lines):** transition done (`approvalgate_` → `accepted_`); `research-implement` picks it up at next cron (03:00 + 15:00 Berlin) and opens PRs you test + merge.

## Don'ts

- Don't approve a doc that isn't at `approvalgate_` — verify the file exists first.
- Don't edit `## Original Idea` or `## Approval Summary`.
- Don't merge anything — approval starts the build; the merge is a separate step after you test the finished branch locally.
