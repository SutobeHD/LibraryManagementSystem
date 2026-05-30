---
description: List every open user gate (A/B/C/D) with the commands to pass/reject each
allowed-tools: Bash
---

Show every user sign-off gate currently waiting on the user.

## Process

1. Run the gates-only pipeline view:
   ```bash
   python scripts/pipeline_status.py --gates
   ```
   This lists every doc in a `*gate_` state with its age + the `/gate-pass` / `/gate-reject` commands.

2. List open GATE D (PR-review) gates as well:
   ```bash
   gh pr list --search "head:routine/" --state open --json number,title,headRefName,statusCheckRollup
   ```
   For each routine/* PR — show number, title, CI status (green/red/pending), and the branch name. CI-green PRs are GATE D ready-to-merge; CI-red PRs are routine-blocked (the routine will fix them on its next run).

3. Reply format — one heading per gate kind, bullet per doc/PR:

   ```
   ## ⛔ GATE A · <count>
   - <slug> · <N days waiting>
     `/gate-pass <slug>` · `/gate-reject <slug> "<reason>"`

   ## ⛔ GATE B · <count>
   - …

   ## ⛔ GATE C · <count>
   - …

   ## ⛔ GATE D · <count> (PRs)
   - #NN <title> · `routine/<slug>-task-N` · CI green · ready to merge
   - #NN <title> · `routine/<slug>-task-N` · CI red · routine will fix on next run
   ```

4. If nothing is open at any gate, reply with one line: "**Pipeline idle — nothing waiting on you.**"

5. Don't editorialise — the output is a checklist, not a status report.

## Don'ts

- Don't run `gh pr merge` automatically — GATE D is the user's. Print the PR list; the user merges.
- Don't include closed gates or merged PRs.
- Don't expand to per-doc detail — that's `/gate-status <slug>`.
