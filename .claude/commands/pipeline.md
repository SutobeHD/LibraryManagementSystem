---
description: Show the research pipeline state + open gates waiting on you
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

3. If any gate is open, add a one-line nudge below it:
   - "Pass a gate: `/gate-pass <slug>` · Reject: `/gate-reject <slug> \"<reason>\"`"
   - For open `routine/*` PRs (GATE D): "Review the PR, then merge it yourself — routines never merge to `main`."

4. If nothing is open, say so in one line: "Pipeline idle — no gates, no routine PRs waiting."

Keep it terse. This is a status glance, not a report.
