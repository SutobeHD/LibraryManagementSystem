---
description: Show the research pipeline state + the open approval gate waiting on you
argument-hint: "[--gates]   --gates = only show open gates"
allowed-tools: Bash
---

Show the current state of the multi-agent research pipeline.

## Process

1. Run the status script:
   ```bash
   python scripts/pipeline_status.py $ARGUMENTS
   ```
   It scans `docs/research/{research,implement,archived}/`, groups docs by state, lists open gates, and (unless `--no-pr`) lists open `routine/*` PRs.

2. Print the script output verbatim.

3. If an approval is open, add a one-line nudge below it:
   - "Approve: `/approve <slug>` · Reject: `/reject <slug> \"<reason>\"`"
   - For open `routine/*` PRs: "Test the branch locally, then merge (yourself, or tell me to — `gh pr merge`). The remote routines never merge to `main`."

4. If nothing is open, say so in one line: "Pipeline idle — no approvals, no routine PRs waiting."

Keep it terse. This is a status glance, not a report.
