---
description: List the open approval gate + PRs waiting for you to test & merge
allowed-tools: Bash
---

Show everything in the pipeline currently waiting on you: the single approval gate + ready PRs.

## Process

1. Run the gates-only pipeline view:
   ```bash
   python scripts/pipeline_status.py --gates
   ```
   This lists every doc at `approvalgate_` with its age + the `/approve` / `/reject` commands.

2. List open `routine/*` PRs (the merge step):
   ```bash
   gh pr list --search "head:routine/" --state open --json number,title,headRefName,statusCheckRollup
   ```
   For each — show number, title, CI status (green/red/pending), branch name. CI-green PRs are ready for you to test locally + merge; CI-red PRs are routine-blocked (the routine fixes them on its next run).

3. Reply format — one heading per kind, bullet per doc/PR:

   ```
   ## ⛔ Approval · <count>
   - <slug> · <N days waiting>
     `/approve <slug>` · `/reject <slug> "<reason>"`

   ## 🔀 Ready to test + merge · <count> (PRs)
   - #NN <title> · `routine/<slug>-task-N` · CI green · test locally, then merge
   - #NN <title> · `routine/<slug>-task-N` · CI red · routine will fix on next run
   ```

4. If nothing is open at the gate and no PRs are ready, reply with one line: "**Pipeline idle — nothing waiting on you.**"

5. Don't editorialise — the output is a checklist, not a status report.

## Don'ts

- Don't run `gh pr merge` automatically — you test the branch first, then merge. Print the PR list; you merge.
- Don't include closed approvals or merged PRs.
- Don't expand to per-doc detail — that's `/gate-status <slug>`.
