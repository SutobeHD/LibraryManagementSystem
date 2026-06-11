# Routine prompts — multi-agent research pipeline

Versioned prompts for the 9 remote routines that run the research pipeline. Each `<name>.md` here holds a routine prompt; everything below its `---` divider is the text to paste into a claude.ai/code routine.

Keeping the prompts in the repo means they are reviewable, diffable, and survive a routine being recreated. **The repo file is the source of truth — edit it here, then re-paste into claude.ai/code.**

## The 9 routines

### Daily work-state routines (advance docs through the pipeline)

| File | Routine | Cron (Berlin) | Cron expression | Writes |
|---|---|---|---|---|
| `research-draft.md` | `research-draft` | 05:00 | `0 5 * * *` | docs → `main` |
| `research-explore.md` | `research-explore` | 06:00 + 14:00 | `0 6,14 * * *` | docs → `main` |
| `research-plan.md` | `research-plan` | 13:00 | `0 13 * * *` | docs → `main` |
| `research-implement.md` | `research-implement` | 03:00 + 15:00 | `0 3,15 * * *` | code → `routine/*` branches + PRs |
| `research-triage.md` | `research-triage` | 07:30 | `30 7 * * *` | nothing — read-only, GitHub Issue |

### Cross-cutting routines (idea generation, re-validation, conflict detection)

| File | Routine | Cron (Berlin) | Cron expression | Writes |
|---|---|---|---|---|
| `research-spawn.md` | `research-spawn` | Sundays 04:00 | `0 4 * * 0` | nothing — read-only, `Idea Backlog` issue |
| `research-watchdog.md` | `research-watchdog` | 1st of month 04:00 | `0 4 1 * *` | `## Lifecycle` lines on `archived/implemented_*` + `Idea Backlog` issue |
| `research-cross-linker.md` | `research-cross-linker` | Tuesdays 04:30 | `30 4 * * 2` | `related:` frontmatter + `## Cross-links` block on active docs |
| `analysis-accuracy-watchdog.md` | `analysis-accuracy-watchdog` | Wednesdays 04:30 | `30 4 * * 3` | nothing — read-only, `Analysis Accuracy Watchdog` issue |

Cron is evaluated in the routine's configured timezone — set it to **Europe/Berlin** on claude.ai/code. Daily slots are staggered so a doc can flow draft → explore → plan across a day and pause only at the single approval gate (then implement once approved). The cross-cutting routines run on lower-frequency schedules so they don't compete with the work routines for `main`-branch commits.

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
- **research-implement** — writes code. Need: all of the above **plus** `git checkout -b`, `git push -u origin routine/*`, `gh pr create`, `gh pr view`. **Must NOT have** `gh pr merge`, `git merge`, `git rebase`, or `git push --force` — merging is the user's, after they test the branch locally.
- **research-triage** — read-only. Need: read files, `python`, `gh issue list/view/create/edit/comment`. No write/commit/PR-merge permissions.
- **research-spawn** — repo read-only, GitHub Issue write. Need: read files, WebSearch/WebFetch, `git log` / `git show`, `gh issue list/view/create/edit/comment`. **No** repo writes, **no** `git commit/push`. Touches only the `Idea Backlog` issue.
- **research-watchdog** — narrow repo write (only `## Lifecycle` lines on `archived/implemented_*`) + GitHub Issue write. Need: read files, WebFetch (for dep CHANGELOGs), `gh api` reads, `git add/commit/push origin main` for the Lifecycle edits, `gh issue edit/comment`. **Must NOT** create new files, `git mv`, or touch non-archived docs.
- **research-cross-linker** — narrow repo write (only `related:` frontmatter and `## Cross-links` blocks on active docs). Need: read files, `git add/commit/push origin main`, `gh issue comment` (for the digest notification). **Must NOT** touch `## Original Idea`, `## Lifecycle`, or content sections.

## Replace the old routines

This pipeline supersedes the previous 3-routine setup. On claude.ai/code, **delete**:
- `research-exploring-push` — replaced by `research-draft` + `research-explore`.
- `research-draftplan-scout` — replaced by `research-plan`.
- `research-triage-report` — replaced by `research-triage`.

## Updating a prompt

1. Edit the `<name>.md` file here, commit it (normal repo PR flow).
2. Run `python scripts/print_routine.py <name>` and pipe to clipboard (`| clip` on Windows, `| pbcopy` on macOS) to grab just the deploy-ready prompt (everything below `---`).
3. Re-paste into the routine on claude.ai/code.
4. `python scripts/print_routine.py --check` is run in CI to ensure every routine file still has a `---` divider — break that, CI fails.

There is no automatic push from the repo into a deployed routine — the repo file and the deployed routine are kept in step by hand. A future enhancement could push prompts via the claude.ai API.

## Commit trailer convention — X-Routine

Every commit-writing routine (draft / explore / plan / implement / watchdog / cross-linker) appends an `X-Routine: <routine-name>` trailer to its commit messages, alongside the standard `Co-Authored-By:` trailer. Example:

```
docs(research): plan downloader-unified → approvalgate_ (mockup + summary)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
X-Routine: research-plan
```

This lets `research-triage` count per-routine activity precisely via `git log --grep="X-Routine: research-plan"` instead of fuzzy subject-prefix matching. The trailer is mandatory — each routine prompt's `## Commit conventions` block enforces it. `research-spawn` and `research-triage` do not commit, so the trailer doesn't apply to them.

## How the routines fit together

```
                  ┌─ research-spawn (Sun 04:00) ──▶ Idea Backlog issue (user picks)
                  │
                  ▼
idea_ ──draft──▶ exploring_ ──explore──▶ evaluated_ ──plan(+mockup)──▶ approvalgate_ ⛔
       ──/approve──▶ accepted_ ──implement──▶ inprogress_ ──▶ PRs ──user test+merge──▶ implemented_
                                                                    │
                                                                    ▼
                  research-watchdog (1st of month) ──▶ Idea Backlog issue (followups)

research-cross-linker (Tue 04:30) — scans all active docs, updates related: + ## Cross-links
research-triage       (daily 07:30) — reports open gates + ready PRs to Pipeline Digest issue
```

**Daily routines** advance docs forward through the pipeline. **Cross-cutting routines** keep the pipeline healthy: `research-spawn` feeds new ideas at the top, `research-watchdog` flags rot on the bottom, `research-cross-linker` finds collisions in the middle, `research-triage` reports state. Full state/gate reference: `../README.md`.
