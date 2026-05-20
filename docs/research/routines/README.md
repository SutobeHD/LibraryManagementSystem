# Routine prompts — multi-agent research pipeline

Versioned prompts for the 5 remote routines that run the research pipeline. Each `<name>.md` here holds a routine prompt; everything below its `---` divider is the text to paste into a claude.ai/code routine.

Keeping the prompts in the repo means they are reviewable, diffable, and survive a routine being recreated. **The repo file is the source of truth — edit it here, then re-paste into claude.ai/code.**

## The 5 routines

| File | Routine | Cron (Berlin) | Cron expression | Writes |
|---|---|---|---|---|
| `research-draft.md` | `research-draft` | 05:00 | `0 5 * * *` | docs → `main` |
| `research-explore.md` | `research-explore` | 06:00 + 14:00 | `0 6,14 * * *` | docs → `main` |
| `research-plan.md` | `research-plan` | 13:00 | `0 13 * * *` | docs → `main` |
| `research-implement.md` | `research-implement` | 03:00 + 15:00 | `0 3,15 * * *` | code → `routine/*` branches + PRs |
| `research-triage.md` | `research-triage` | 07:30 | `30 7 * * *` | nothing — read-only, GitHub Issue |

Cron is evaluated in the routine's configured timezone — set it to **Europe/Berlin** on claude.ai/code. Slots are staggered so a doc can flow draft → explore → plan → implement across a day, pausing at each user gate.

## Deploy

For each routine:

1. Open https://claude.ai/code/routines → **New routine**.
2. Name it exactly as the table's "Routine" column (the prompts self-reference these names).
3. Set the schedule to the cron expression above; timezone Europe/Berlin.
4. Point it at the `SutobeHD/LibraryManagementSystem` repo.
5. Paste the prompt — **everything below the `---` divider** in the matching `<name>.md`.
6. Set permissions (next section).
7. Save.

## Permissions per routine

Routines run with their own permission config on claude.ai/code (separate from the local `.claude/settings.json`).

- **research-draft / research-explore / research-plan** — docs only. Need: read/edit files, `git add/commit/mv/push origin main`, `git pull --ff-only`, the Agent tool, WebSearch/WebFetch (explore only). No PR or merge permissions.
- **research-implement** — writes code. Need: all of the above **plus** `git checkout -b`, `git push -u origin routine/*`, `gh pr create`, `gh pr view`. **Must NOT have** `gh pr merge`, `git merge`, `git rebase`, or `git push --force` — merging is GATE D, the user's.
- **research-triage** — read-only. Need: read files, `python`, `gh issue list/view/create/edit/comment`. No write/commit/PR-merge permissions.

## Replace the old routines

This pipeline supersedes the previous 3-routine setup. On claude.ai/code, **delete**:
- `research-exploring-push` — replaced by `research-draft` + `research-explore`.
- `research-draftplan-scout` — replaced by `research-plan`.
- `research-triage-report` — replaced by `research-triage`.

## Updating a prompt

1. Edit the `<name>.md` file here, commit it (normal repo PR flow).
2. Re-paste the section below the `---` into the routine on claude.ai/code.

There is no automatic sync — the repo file and the deployed routine are kept in step by hand. A future enhancement could push prompts via the claude.ai API.

## How the routines fit together

```
idea_ ──draft──▶ ideagate_ ⛔A ──▶ exploring_ ──explore──▶ midgate_ ⛔B
       ──▶ exploring_(w2) ──explore──▶ evaluated_ ──plan──▶ plangate_ ⛔C
       ──▶ accepted_ ──implement──▶ inprogress_ ──▶ PRs ⛔D ──▶ implemented_
```

`research-triage` runs across all of it, read-only, reporting open gates daily. Full state/gate reference: `../README.md`.
