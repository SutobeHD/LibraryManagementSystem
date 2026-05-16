# Agentic operating mode — what to do without asking

Broad permission to act locally. `.claude/settings.json` allowlist reflects this.

## Just do these

- Any `npm run …`, `python -m app.main`, `pytest`, `cargo check/fmt/build`.
- Read/Grep/Glob freely. Edit/create/delete files in working tree.
- `git status/diff/log/branch/add/stash`, `git restore` (staging-area only).
- **`git commit`** — atomically, intensely, per logical unit (see `commit-and-git.md`).
- `git fetch`, `git pull --ff-only`.
- `git checkout -b`, `git switch -c` (new branches).
- `gh pr/issue view`, `gh pr list`, `gh run list` — read-only GitHub queries.

## Confirm first

- `git push --force` (never to `main`). Plain `git push` is auto-fired by hook — see `commit-and-git.md`.
- `git reset --hard`, `git clean -fd`, branch deletion, history rewrites.
- `gh pr create/merge/close`, `gh issue close`.
- `npm/pip/cargo` install of new dep — security decision.
- Version bumps in `requirements.txt`, `Cargo.toml`, `package.json` `dependencies`.
- Write to `.env*` (read OK).
- Delete files outside `tmp/`, `temp/`, `scratch/`, `work/`, `build/`, `dist/`, `target/`.

## Don't

- Edit user data: `**/music/`, `**/exports/`, `**/backups/`, USB drives, `master.db`, `*.DAT`, `*.ANLZ` outside `app/templates/`.
- `--no-verify` / bypass signing / skip security audits. `--no-verify` is in deny list.
- Commit `.env`, `*.db`, audio files, build artefacts (gitignored).
- Promote research-pipeline states unilaterally — see `research-pipeline.md`.
