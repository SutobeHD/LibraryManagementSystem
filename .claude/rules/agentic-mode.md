# Agentic operating mode — what to do without asking

Broad permission to act locally. `.claude/settings.json` allowlist reflects this.

## Just do these

- Any `npm run …`, `python -m app.main`, `pytest`, `cargo check/fmt/build`.
- Read/Grep/Glob freely. Edit/create/delete files in working tree.
- `git status/diff/log/branch/add/stash`, `git restore --staged` (unstage only — worktree-discarding `git restore <file>` prompts).
- **`git commit`** — atomically, intensely, per logical unit (see `commit-and-git.md`).
- `git fetch`, `git pull --ff-only`.
- `git checkout -b`, `git switch -c` (new branches).
- `gh pr/issue view`, `gh pr list`, `gh run list` — read-only GitHub queries.
- **Merge on the user's explicit instruction** — `git merge`, `git rebase main`/`origin/*`, `git cherry-pick`, and `gh pr merge` (incl. `routine/*` PRs) run without a confirm prompt **when the user asked for the merge**. Don't merge proactively or "to be helpful" — only when instructed. Force-push stays denied, so a rebase you can't fast-forward still can't be pushed.
- **Advance research-pipeline docs in a work-state** (draft / explore / plan / implement) — follow the stage logic in `docs/research/routines/`. Stop at every `*gate_` — those are user-only. Run `/pipeline` to see state.

## Branch & scope discipline — confirm at task start

- Confirm the target branch before non-trivial work — feature branch vs directly on `main` is the user's call; don't assume. Don't commit feature code where the user didn't intend.
- **"Scan / review / check first" = produce the review, implement NOTHING** until an explicit go-ahead. Recurring friction: don't jump straight to edits when asked to look.

## Streamlining bias — default ON

Repo culture is **maximum AI autonomy + minimum manual steps**. When you spot a recurring manual ritual (state moves, doc syncs, lifecycle bookkeeping, multi-step PR flow), propose automating it — slash-command, hook, routine, or marker-driven worker. Don't ask "may I automate this?" — show the diff and let the user decline. Defaults favor scripted over hand-typed, marker-driven over per-prompt instruction, idempotent re-runs over one-shot artisan work.

## Confirm first

- `git push --force` (never to `main`). Plain `git push` is auto-fired by hook — see `commit-and-git.md`.
- Plain `git pull` / `git pull origin` (non-ff). `git pull --ff-only` is auto-allowed; a non-ff pull rewrites local history on a drifted base → needs sign-off.
- `git reset --hard`, `git clean -fd`, history rewrites. (Branch deletion: `git branch -d` merged-branch cleanup after a PR merge is autonomous; `-D` force-delete is deny-listed.)
- `gh pr create/close`, `gh issue close`. (`gh pr merge` is autonomous on explicit instruction — see "Just do these".)
- `npm/pip/cargo` install of new dep — security decision.
- Version bumps in `requirements.txt`, `Cargo.toml`, `package.json` `dependencies`.
- Write to `.env.*` variants not covered by the deny list. (`./.env` / `./.env.local` are read- **and** write-denied in settings.json — hand the user a paste-ready block instead, see troubleshooting #13. `.env.example` is freely editable.)
- Delete files outside `tmp/`, `temp/`, `scratch/`, `work/`, `build/`, `dist/`, `target/`.

## Don't

- Edit user data: `**/music/`, `**/exports/`, `**/backups/`, USB drives, `master.db`, `*.DAT`, `*.ANLZ` outside `app/templates/`.
- `--no-verify` / bypass signing / skip security audits. `--no-verify` is in deny list.
- Commit `.env`, `*.db`, audio files, build artefacts (gitignored).
- Pass the research-pipeline approval gate (`approvalgate_` → `accepted_`) — the single sign-off is **user-only**, never auto-advance it. (Merging the finished `routine/*` PR afterwards is NOT user-only: do it on the user's instruction. See `research-pipeline.md` "The one gate".)
