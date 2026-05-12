---
description: Stage + commit current changes atomically with a Conventional-Commits message. Splits into multiple commits if unrelated changes detected.
argument-hint: "[optional: scope hint or message hint, e.g. 'usb fix' or 'feat(audio): add resampler']"
allowed-tools: Bash, Read, Grep
---

Create one or more atomic commits from the current working state.

User hint: $ARGUMENTS

## Process

1. **Survey:**
   ```bash
   git status -sb
   git diff --stat
   git diff --cached --stat
   ```

2. **Group changes by coherent purpose.** If the working tree contains multiple unrelated changes, split into separate commits. Don't bundle.
   - Same file, same purpose → one commit.
   - Different files, same logical change → one commit.
   - Backend route + frontend client for the same feature → one commit (they belong together).
   - Backend route + unrelated doc cleanup → two commits.
   - Refactor + new feature → two commits, refactor first.

3. **For each group, draft a [Conventional Commits](https://www.conventionalcommits.org/) message:**
   - Format: `<type>(<scope>): <imperative summary under 70 chars>`
   - Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `build`, `ci`, `revert`
   - Scopes: `backend`, `frontend`, `tauri`, `audio`, `usb`, `pdb`, `anlz`, `sc`, `analysis`, `db`, `docs`, `claude`, `deps`
   - Body (optional): explain **why**, not what. Diff shows what.

4. **Sanity-check tree state:**
   - Run a quick syntax/lint check on the staged Python (`python -c "import ast; ast.parse(open('<file>').read())"` for changed app/ files) or Rust (`cargo check --manifest-path src-tauri/Cargo.toml` if Rust changed) so you don't commit broken code.
   - If broken: fix or label commit `chore(wip): ...` with body explaining red state.

5. **Stage by name** (never `git add -A` / `git add .` — risk of grabbing secrets / large files):
   ```bash
   git add <file1> <file2>
   ```

6. **Commit using HEREDOC for multi-line bodies:**
   ```bash
   git commit -m "$(cat <<'EOF'
   <type>(<scope>): <subject>

   <optional body — why this change is needed>

   Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
   EOF
   )"
   ```

7. **Verify:**
   ```bash
   git log -1 --stat
   git status -sb
   ```

8. **Don't push.** Push is always user-confirmed. Mention if drift vs origin requires attention.

## Output (1-3 lines max)

- N commits made: `<sha> <subject>` per commit
- Tree clean? Y/N
- vs origin: `M ahead, K behind` if non-trivial; else skip
