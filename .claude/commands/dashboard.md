---
description: Start the local research-pipeline web dashboard
argument-hint: "[--port N]   default: 8765"
allowed-tools: Bash
---

Start the research pipeline dashboard — a local, auto-refreshing web view of `docs/research/` (docs by state, open gates, routine PRs, blockers).

## Process

1. Start the server as a background process:
   ```bash
   python scripts/pipeline_dashboard.py $ARGUMENTS
   ```
   It serves on `http://127.0.0.1:8765` (or the `--port` passed in `$ARGUMENTS`).

2. Check the process output for the line `Research dashboard running at <url>`.

3. Tell the user: open `<url>` in a browser. The page auto-refreshes every 30 s and is read-only.

4. If the output shows `Cannot bind port ...`, the port is busy — re-run with `/dashboard --port 8766`.

## Notes

- The server keeps running in the background. To stop it, end that background process.
- Read-only: the dashboard never edits files or git. Use `/gate-pass` / `/gate-reject` for actions.
- Equivalent without the slash command: `npm run dashboard`.
