# Agentic operating mode — what to do without asking

You have broad permission to act locally. The settings allowlist (`.claude/settings.json`) reflects this.

## Just do these

- Run any `npm run …`, `python -m app.main`, `pytest`, `cargo check`, `cargo fmt`, `cargo build` command.
- Read any file, search across the codebase, use Grep/Glob freely.
- Edit / create / delete files in the working tree.
- Run linters and formatters after edits (`ruff format app/`, `cargo fmt`, `prettier --write frontend/src`). Note: a PostToolUse hook (`.claude/hooks/format-on-edit.py`) runs these automatically after `Edit`/`Write` — you usually don't need to invoke them manually.
- `git status`, `git diff`, `git log`, `git branch`, `git add`, `git restore` (staging-area only), `git stash`.
- **`git commit`** — commit atomically and intensely after each logical unit of work. See `commit-and-git.md`.
- `git fetch`, `git pull --ff-only` (fast-forward only — safe).
- `git checkout -b`, `git switch -c` (new branches).
- `gh pr view`, `gh pr list`, `gh issue view`, `gh run list` — read-only GitHub queries.
- Use parallel tool calls aggressively when steps are independent.
- Spawn subagents (`doc-syncer`, `route-architect`, `audio-stack-reviewer`, `test-runner`, `e2e-tester`, plus generic `Explore` / `general-purpose` / `Plan`) for broad searches / multi-step research / verification.

## Confirm first

- `git push`, `git push --force` (always confirm; **never** force-push to `main`).
- `git reset --hard`, `git clean -fd`, branch deletion, history rewrites.
- `gh pr create`, `gh pr merge`, `gh pr close`, `gh issue close`.
- `npm install <new-dep>` / `pip install <new-dep>` / `cargo add` — adding a new dep is a security decision.
- Anything under `requirements.txt`, `Cargo.toml`, `package.json` `dependencies` that bumps versions.
- Touching `.env*` files (read OK, write needs sign-off).
- Deleting files outside `tmp/`, `temp/`, `scratch/`, `work/`, `build/`, `dist/`, `target/`.

## Don't

- Never edit user data: `**/music/`, `**/exports/`, `**/backups/`, USB drive paths, `master.db`, `*.DAT`, `*.ANLZ` files outside `app/templates/`.
- Never disable hooks (`--no-verify`), bypass signing, or skip security audits. The `--no-verify` flag is explicitly in the `deny` list of `.claude/settings.json`.
- Never commit `.env`, `*.db`, audio files, build artefacts (they're in `.gitignore` for a reason).
- Never promote research-pipeline states unilaterally — see `research-pipeline.md`.
